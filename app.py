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
            viewport={'width': 1920, 'height': 1080} # Set a desktop viewport
        )
        page = context.new_page()
        
        # 1. Intercept and abort unnecessary resources to prevent timeouts
        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "font", "media", "stylesheet"] 
            else route.continue_())
        
        try:
            # 2. Use domcontentloaded instead of networkidle
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            # 3. Blindly try to click common cookie consent buttons if they exist
            try:
                page.locator("button:has-text('Accept')").first.click(timeout=3000)
            except:
                pass # Ignore if no cookie banner is found
            
            # Wait for the iframe
            page.wait_for_selector("iframe", timeout=15000)
            
            frame = None
            for f in page.frames:
                if "spektrix" in f.url.lower() or "booking" in f.url.lower():
                    frame = f
                    break
            
            if not frame and len(page.frames) > 1:
                frame = page.frames[1] 
                
            if not frame:
                return {"error": "Could not locate the ticketing iframe on this page."}

            frame.wait_for_selector("svg", timeout=15000)
            time.sleep(3) # Ensure dynamic seat classes are applied
            
            html_content = frame.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            all_seats = soup.find_all('circle')
            
            available_seats = 0
            sold_seats = 0
            
            for seat in all_seats:
                classes = seat.get('class', [])
                fill = seat.get('fill', '').lower()
                
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
            return {"error": str(e)}
        finally:
            browser.close()

# Streamlit Interface
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Enter a theatre booking link to calculate how many seats are sold vs. available.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://leedsheritagetheatres.com/whats-on/...")

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner("Loading seating plan and analyzing seats (this may take 10-15 seconds)..."):
            results = analyze_seats(url_input)
            
            if "error" in results:
                st.error(f"Failed to scrape: {results['error']}")
                st.info("Note: If timeouts persist, the ticketing platform is likely detecting and blocking the headless browser.")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available Seats (Colored)", results["available"])
                col3.metric("Sold Seats (Greyed out)", results["sold"])
    else:
        st.warning("Please enter a valid URL.")
