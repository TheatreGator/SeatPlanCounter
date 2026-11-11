import streamlit as st
import os
import time
from playwright.sync_api import sync_playwright

# Install the Chromium browser when the app boots
os.system("playwright install chromium")

# A script to mimic a real browser and bypass Cloudflare/Queue-it
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.navigator.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en-US', 'en'] });
"""

# A recursive JavaScript function that pierces Shadow DOMs to find the SVG seats
JS_SEAT_COUNTER = """
() => {
    // Recursively dig through all elements and their shadow roots
    function getAllElements(root) {
        let elements = Array.from(root.querySelectorAll('*'));
        let result = [...elements];
        elements.forEach(el => {
            if (el.shadowRoot) {
                result.push(...getAllElements(el.shadowRoot));
            }
        });
        return result;
    }
    
    let allNodes = getAllElements(document);
    let shapes = allNodes.filter(el => ['circle', 'path', 'rect', 'ellipse'].includes(el.tagName.toLowerCase()));
    
    let total = 0;
    let available = 0;
    let sold = 0;
    
    shapes.forEach(seat => {
        let className = (seat.getAttribute('class') || '').toLowerCase();
        let fill = (seat.getAttribute('fill') || '').toLowerCase();
        
        // Spektrix uses these generic terms in their classes
        if (className.includes('available') || className.includes('locked') || className.includes('seat') || className.includes('sold')) {
            total++;
            // Check if the seat is marked as taken or greyed out
            if (className.includes('unavailable') || className.includes('locked') || className.includes('sold') || ['#cccccc', '#ccc', 'grey', 'gray', 'none', 'transparent'].includes(fill)) {
                sold++;
            } else {
                available++;
            }
        }
    });
    
    return {total, available, sold};
}
"""

def analyze_seats(url):
    results = {"total": 0, "available": 0, "sold": 0, "error": None}
    
    with sync_playwright() as p:
        # Launch with arguments that disable standard automation flags
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        # Inject the stealth script into every new page
        context.add_init_script(STEALTH_SCRIPT)
        page = context.new_page()
        
        try:
            # Let the page load completely (CSS, JS, and all)
            page.goto(url, wait_until="load", timeout=60000)
            
            # Wait to let iframes, Web Components, and SVG APIs render
            time.sleep(15)
            
            # Blindly try to dismiss any cookie banners blocking the page
            try:
                page.locator("button:has-text('Accept')").first.click(timeout=2000)
                time.sleep(2)
            except:
                pass

            # Run the Shadow DOM parsing script on the main page
            found_seats = False
            main_page_counts = page.evaluate(JS_SEAT_COUNTER)
            if main_page_counts['total'] > 0:
                results.update(main_page_counts)
                found_seats = True
            
            # If not found on the main page, run the script inside every iframe
            if not found_seats:
                for frame in page.frames:
                    try:
                        frame_counts = frame.evaluate(JS_SEAT_COUNTER)
                        if frame_counts['total'] > 0:
                            results.update(frame_counts)
                            found_seats = True
                            break 
                    except:
                        pass
            
            if not found_seats:
                page.screenshot(path="debug_error.png")
                results["error"] = "Bypassed detection, but no SVG seats found. Ensure the event isn't completely sold out/past, or check the screenshot below."
                
        except Exception as e:
            page.screenshot(path="debug_error.png")
            results["error"] = f"Crash: {str(e)}"
        finally:
            browser.close()
            
        return results

# Streamlit Interface
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Enter a theatre booking link to calculate how many seats are sold vs. available.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://leedsheritagetheatres.com/whats-on/...")

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner("Analyzing Web Components and Shadow DOM (this takes ~15-20 seconds)..."):
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results = analyze_seats(url_input)
            
            if results.get("error"):
                st.error(results['error'])
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="Headless Browser Output")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available Seats", results["available"])
                col3.metric("Sold Seats", results["sold"])
    else:
        st.warning("Please enter a valid URL.")
