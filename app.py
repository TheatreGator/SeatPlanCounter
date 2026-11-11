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
        
        # We will store the intercepted JSON data here
        captured_seat_data = []
        
        # --- THE MAGIC ---
        # Listen to all network responses. 
        # When Spektrix requests the seat status data, we intercept the JSON response.
        def handle_response(response):
            # Spektrix seat data endpoints typically contain these keywords
            if "api" in response.url.lower() and ("seats" in response.url.lower() or "availability" in response.url.lower() or "status" in response.url.lower()):
                try:
                    # Only try to parse if it's a successful JSON response
                    if response.ok and "application/json" in response.headers.get("content-type", ""):
                        data = response.json()
                        captured_seat_data.append(data)
                except:
                    pass

        page.on("response", handle_response)
        
        # Intercept and abort media to speed up loading, but ALLOW all API/fetch requests
        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "font", "media"] 
            else route.continue_())
        
        try:
            # 1. Load the main page and wait for the network to settle
            page.goto(url, wait_until="networkidle", timeout=45000)
            
            # Wait a few extra seconds to ensure the async API calls finish
            time.sleep(5)
            
            # 2. Check if we captured the API data
            if not captured_seat_data:
                # Fallback: take a screenshot if we didn't get the data
                page.screenshot(path="debug_error.png")
                results["error"] = "Could not intercept the Spektrix seat API request. The URL might be incorrect or the event is sold out/past. Saved screenshot."
                return results

            # 3. Parse the JSON Data
            # Note: The exact JSON structure varies slightly depending on whether they use 
            # Spektrix API v3 or the newer Web Components, but generally looks like a list of seats.
            
            # We loop through all captured JSONs (usually there's only 1 relevant one)
            for data_payload in captured_seat_data:
                # Case A: Data is a direct list of seats
                if isinstance(data_payload, list):
                    seats = data_payload
                # Case B: Data is wrapped in a dictionary (e.g., {"Seats": [...]})
                elif isinstance(data_payload, dict):
                    # Guess the key holding the seats
                    seats = data_payload.get("Seats", data_payload.get("seats", data_payload.get("Entities", [])))
                else:
                    continue

                if not seats:
                    continue
                
                # Count the status
                for seat in seats:
                    results["total"] += 1
                    
                    # Spektrix typically uses a 'StatusId', 'IsAvailable', or 'Status' field
                    # 0 usually means available, integers > 0 mean sold/locked/held
                    is_available = seat.get("IsAvailable", False)
                    status_id = seat.get("StatusId", seat.get("Status", 1))
                    
                    if is_available or status_id == 0 or status_id == "Available":
                        results["available"] += 1
                    else:
                        results["sold"] += 1
                
                # If we found and counted seats, break out of the loop
                if results["total"] > 0:
                    break
            
            if results["total"] == 0:
                results["error"] = "Intercepted API data, but couldn't parse the seat status format."

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
