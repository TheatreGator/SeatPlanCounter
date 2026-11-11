import streamlit as st
import os
import time
import json
from playwright.sync_api import sync_playwright

os.system("playwright install chromium")

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
"""

def analyze_seats_api(url):
    results = {"total": 0, "available": 0, "sold": 0, "error": None, "sample": None}
    
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
        
        intercepted_jsons = []
        
        # Listen to all network traffic and capture JSON files
        def handle_response(response):
            try:
                if response.ok and "application/json" in response.headers.get("content-type", ""):
                    data = response.json()
                    intercepted_jsons.append(data)
            except:
                pass

        page.on("response", handle_response)
        
        try:
            page.goto(url, wait_until="load", timeout=60000)
            
            # Wait to ensure all background API requests fire and return data
            time.sleep(15) 
            
            if not intercepted_jsons:
                results["error"] = "No JSON network traffic intercepted. The site might be blocking the request."
                return results

            # Recursively search all intercepted files for the largest array
            # A venue seat manifest will almost always be the largest array returned by the API
            largest_array = []
            def find_largest_array(obj):
                nonlocal largest_array
                if isinstance(obj, list):
                    if len(obj) > len(largest_array):
                        largest_array = obj
                    for item in obj:
                        find_largest_array(item)
                elif isinstance(obj, dict):
                    for val in obj.values():
                        find_largest_array(val)

            for data in intercepted_jsons:
                find_largest_array(data)

            if len(largest_array) < 50:
                results["error"] = "Intercepted background data, but couldn't find a list large enough to be a seat manifest."
                return results

            results["total"] = len(largest_array)
            # Save the very first seat in the list as a sample to display on the dashboard
            results["sample"] = largest_array[0] 
            
            for seat in largest_array:
                # Convert the dictionary to a string for broad keyword matching
                seat_str = str(seat).lower()
                
                # Broadly guess common ticketing API flags for "available"
                if ("'status': 0" in seat_str or 
                    "'status': 'available'" in seat_str or 
                    "'isavailable': true" in seat_str or 
                    "'available': true" in seat_str or 
                    "'state': 0" in seat_str or
                    "'statusid': 0" in seat_str):
                    results["available"] += 1
                else:
                    results["sold"] += 1

        except Exception as e:
            results["error"] = f"Crash: {str(e)}"
        finally:
            browser.close()
            
        return results

# Streamlit Interface
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭", layout="wide")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Enter a theatre booking link to calculate how many seats are sold vs. available.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://booking.trafalgartickets.com/...")

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner("Intercepting background API traffic (takes ~20 seconds)..."):
            results = analyze_seats_api(url_input)
            
            if results.get("error"):
                st.error(results['error'])
            else:
                st.success("API Interception Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats (API)", results["total"])
                col2.metric("Available Seats (Estimated)", results["available"])
                col3.metric("Sold Seats (Estimated)", results["sold"])
                
                st.write("---")
                st.subheader("Diagnostic Tool: API Data Sample")
                st.write("To make the counter 100% accurate, look at the background data below. This is what Trafalgar Tickets uses to track a single seat. What property dictates if a seat is sold?")
                st.json(results["sample"])
    else:
        st.warning("Please enter a valid URL.")
