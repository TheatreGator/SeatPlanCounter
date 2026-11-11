import streamlit as st
import os
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

os.system("playwright install chromium")

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
"""

def analyze_seats(url):
    # We can no longer calculate 'sold' just by looking at the HTML
    results = {"available": 0, "error": None}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        context.add_init_script(STEALTH_SCRIPT)
        page = context.new_page()
        
        try:
            page.goto(url, wait_until="load", timeout=60000)
            
            # Wait for SVG and anti-bot scripts to settle
            time.sleep(15)
            
            try:
                page.locator("button:has-text('Accept')").first.click(timeout=2000)
                time.sleep(2)
            except:
                pass

            all_html = [page.content()]
            for frame in page.frames:
                try:
                    all_html.append(frame.content())
                except:
                    pass
            
            found_seats = False
            for html in all_html:
                soup = BeautifulSoup(html, 'html.parser')
                
                # Look specifically for Trafalgar's seat class and Spektrix fallbacks
                seats = soup.find_all(['circle', 'path', 'rect', 'ellipse'])
                
                for seat in seats:
                    classes = " ".join(seat.get('class', [])).lower()
                    
                    # 'p-1' is Trafalgar's available seat identifier
                    if 'p-1' in classes or 'available' in classes or 'seat' in classes:
                        found_seats = True
                        results["available"] += 1
                            
                if found_seats:
                    break 
            
            if not found_seats:
                page.screenshot(path="debug_error.png")
                results["error"] = "Could not find any available seats. The event is either sold out, or the platform blocked the scraper. See screenshot below."
                
        except Exception as e:
            page.screenshot(path="debug_error.png")
            results["error"] = f"Crash: {str(e)}"
        finally:
            browser.close()
            
        return results

# Streamlit Interface
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Enter a theatre booking link to calculate how many seats are available.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://booking.trafalgartickets.com/...")

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner("Bypassing bot detection and parsing seating plan (takes ~20 seconds)..."):
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results = analyze_seats(url_input)
            
            if results.get("error"):
                st.error(results['error'])
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="Headless Browser Output")
            else:
                st.success("Analysis Complete!")
                # Since sold seats aren't rendered, we can only display available seats accurately
                st.metric("Available Seats (Rendered as p-1 circles)", results["available"])
                st.info("Note: Trafalgar Tickets does not render sold seats in the HTML, so we cannot accurately provide a 'Total' or 'Sold' count via visual scraping.")
    else:
        st.warning("Please enter a valid URL.")
