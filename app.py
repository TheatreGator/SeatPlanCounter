import streamlit as st
from playwright.sync_api import sync_playwright
import time
import os
import json

# Install the Chromium browser when the app boots on Streamlit Cloud
os.system("playwright install chromium")

def analyze_seats(url):
    results = {"total": 0, "available": 0, "sold": 0, "error": None}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        captured_jsons = []
        
        # Intercept ALL JSON responses, regardless of what the URL is
        def handle_response(response):
            try:
                if response.ok and "application/json" in response.headers.get("content-type", ""):
                    # Ignore tiny responses to save processing time
                    if int(response.headers.get("content-length", 0)) > 1000 or response.headers.get("content-length") is None:
                        data = response.json()
                        captured_jsons.append(data)
            except:
                pass

        page.on("response", handle_response)
        
        # Intercept and abort media to speed up loading
        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "font", "media", "stylesheet"] 
            else route.continue_())
        
        try:
            # 1. Load the main page
            page.goto(url, wait_until="networkidle", timeout=45000)
            time.sleep(5) # Allow final API calls to resolve
            
            if not captured_jsons:
                page.screenshot(path="debug_error.png")
                results["error"] = "No JSON data was loaded by the page at all. Saved screenshot."
                return results

            # 2. Search through ALL captured JSONs for seat data
            found_seat_data = False
            for data in captured_jsons:
                
                # We need a recursive function to find the seat array, because Spektrix 
                # heavily nests their API responses (e.g. data -> event -> instances -> seats)
                def find_seats_array(obj):
                    if isinstance(obj, list):
                        # Is this a list of seats? Check if the first item has typical seat properties
                        if len(obj) > 0 and isinstance(obj[0], dict):
                            keys = obj[0].keys()
                            if "StatusId" in keys or "IsAvailable" in keys or "SeatId" in keys or "Status" in keys:
                                return obj
                        # If not, check inside the list items
                        for item in obj:
                            res = find_seats_array(item)
                            if res: return res
                            
                    elif isinstance(obj, dict):
                        # Explicitly check for known Spektrix keys first
                        for key in ["Seats", "seats", "Entities", "AvailableSeats"]:
                            if key in obj and isinstance(obj[key], list):
                                return obj[key]
                        # Otherwise search recursively down the dictionary
                        for val in obj.values():
                            res = find_seats_array(val)
                            if res: return res
                    return None

                seats = find_seats_array(data)
                
                if seats:
                    found_seat_data = True
                    for seat in seats:
                        results["total"] += 1
                        
                        # Handle different versions of the Spektrix API
                        is_available = seat.get("IsAvailable", False)
                        status = seat.get("Status", seat.get("StatusId", 1))
                        
                        # Status is usually 0 or "Available" if free
                        if is_available or status == 0 or str(status).lower() == "available":
                            results["available"] += 1
                        else:
                            results["sold"] += 1
                            
                    # Once we found and counted the seats, stop searching
                    break
            
            if not found_seat_data:
                page.screenshot(path="debug_error.png")
                results["error"] = "Intercepted network data, but none of it contained seat availability. The event may not have a seating plan, or it is sold out. Saved screenshot."

        except Exception as e:
            page.screenshot(path="debug_error.png")
            results["error"] = f"{str(e)} (Screenshot saved)"
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
        with st.spinner("Intercepting ticketing API data (this may take up to 20 seconds)..."):
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results = analyze_seats(url_input)
            
            if results.get("error"):
                st.error(f"Failed to scrape: {results['error']}")
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="What the bot saw before failing")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available Seats", results["available"])
                col3.metric("Sold Seats", results["sold"])
    else:
        st.warning("Please enter a valid URL.")
