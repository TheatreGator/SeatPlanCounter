import streamlit as st
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time

def analyze_seats(url):
    with sync_playwright() as p:
        # Launch Chromium headless
        browser = p.chromium.launch(headless=True)
        # Create a new context to mimic a real user
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            # Navigate to the booking URL
            page.goto(url, wait_until="networkidle")
            
            # Wait for the iframe holding the Spektrix/ticketing portal
            page.wait_for_selector("iframe", timeout=15000)
            
            # Get the ticketing frame (often the first iframe, or specifically the spektrix one)
            frame = None
            for f in page.frames:
                if "spektrix" in f.url.lower() or "booking" in f.url.lower():
                    frame = f
                    break
            
            # Fallback to the first child frame if a specific name wasn't matched
            if not frame and len(page.frames) > 1:
                frame = page.frames[1] 
                
            if not frame:
                return {"error": "Could not locate the ticketing iframe on this page."}

            # Wait for the SVG seating plan to render inside the iframe
            frame.wait_for_selector("svg", timeout=15000)
            
            # Give it a short pause to ensure dynamic classes (colors) are fully applied
            time.sleep(2) 
            
            # Extract the raw HTML/SVG content from the frame
            html_content = frame.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Parse the SVG circles (seats)
            all_seats = soup.find_all('circle')
            
            available_seats = 0
            sold_seats = 0
            
            for seat in all_seats:
                # Different ticketing systems use different markers for "sold". 
                # Common patterns: a specific class like 'unavailable', 'locked', or a grey 'fill' color.
                # Example assumes 'available' vs 'unavailable' classes, or looking at the fill attribute:
                classes = seat.get('class', [])
                fill = seat.get('fill', '').lower()
                
                # Check if it has a class indicating it is unavailable, or a greyed-out fill color
                if 'unavailable' in classes or 'locked' in classes or fill in ['#cccccc', 'grey', 'gray', 'none']:
                    sold_seats += 1
                else:
                    # If it has a color and isn't marked unavailable
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
                st.info("Note: The site might be blocking headless browsers, or the seating plan structure may have changed.")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available Seats (Colored)", results["available"])
                col3.metric("Sold Seats (Greyed out)", results["sold"])
    else:
        st.warning("Please enter a valid URL.")
