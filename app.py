import streamlit as st
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import os

# Install the Chromium browser when the app boots on Streamlit Cloud
os.system("playwright install chromium")

def analyze_seats(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        # Intercept and abort unnecessary resources, but ALLOW Javascript and API calls
        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "font", "media"] 
            else route.continue_())
        
        try:
            # 1. Load the main page
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            # Dismiss cookies if present
            try:
                page.locator("button:has-text('Accept')").first.click(timeout=3000)
            except:
                pass 
            
            # 2. Wait for the iframe container to exist in the DOM
            page.wait_for_selector("iframe", timeout=15000)
            
            # Identify the correct frame
            target_frame = None
            for f in page.frames:
                if "spektrix" in f.url.lower() or "booking" in f.url.lower():
                    target_frame = f
                    break
            
            if not target_frame and len(page.frames) > 1:
                target_frame = page.frames[1] 
                
            if not target_frame:
                return {"error": "Could not locate the ticketing iframe on this page."}

            # 3. Wait for the iframe itself to finish loading its internal content
            # Instead of waiting for 'svg', we give the frame time to execute its javascript
            try:
                target_frame.page.wait_for_load_state("networkidle", timeout=15000)
            except:
                # If networkidle times out, just pause for 5 seconds and proceed anyway
                time.sleep(5) 
            
            # 4. Extract the HTML
            html_content = target_frame.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            all_seats = soup.find_all('circle')
            
            # If no circles were found, the SVG might be named differently or the bot is blocked
            if not all_seats:
                # Take a debug screenshot
                page.screenshot(path="debug_error.png")
                return {"error": f"Iframe loaded, but no SVG seats found. The ticketing site may be blocking the bot. Saved screenshot."}
            
            available_seats = 0
            sold_seats = 0
            
            for seat in all_seats:
                classes = seat.get('class', [])
                fill = seat.get('fill', '').lower()
                
                # Check locked/unavailable markers
                if 'unavailable' in classes or 'locked' in classes or fill in ['#cccccc', 'grey', 'gray', 'none']:
                    sold_seats += 1
                else:
                    available_seats += 1
                    
            return {
                "total": len(all_seats),
                "available": available_seats,
                "sold": sold_seats
            }
            
        except Exception as e:
            # Take a screenshot if any other exception occurs
            page.screenshot(path="debug_error.png")
            return {"error": f"{str(e)} (Screenshot saved)"}
        finally:
            browser.close()

# Streamlit Interface
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Enter a theatre booking link to calculate how many seats are sold vs. available.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://leedsheritagetheatres.com/whats-on/...")

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner("Loading seating plan and analyzing seats (this may take up to 30 seconds)..."):
            # Clear previous debug images
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results = analyze_seats(url_input)
            
            if "error" in results:
                st.error(f"Failed to scrape: {results['error']}")
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="What the bot saw before failing")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available Seats (Colored)", results["available"])
                col3.metric("Sold Seats (Greyed out)", results["sold"])
    else:
        st.warning("Please enter a valid URL.")
