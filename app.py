import streamlit as st
import os
import time
import json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Install the Chromium browser when the app boots
os.system("playwright install chromium")

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
"""

# ==========================================
# SCRAPER 1: SPEKTRIX (Visual HTML Method)
# ==========================================
def analyze_spektrix(url, page):
    results = {"total": 0, "available": 0, "sold": 0, "error": None}
    
    page.goto(url, wait_until="load", timeout=60000)
    time.sleep(15)  # Wait for iframes and SVG to settle
    
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
        seats = soup.find_all(['circle', 'path', 'rect', 'ellipse'])
        
        for seat in seats:
            classes = " ".join(seat.get('class', [])).lower()
            fill = seat.get('fill', '').lower()
            
            parent = seat.find_parent('g')
            parent_classes = " ".join(parent.get('class', [])).lower() if parent else ""
            parent_fill = (parent.get('fill', '') if parent else '').lower()
            
            combined_classes = classes + " " + parent_classes
            combined_fill = fill or parent_fill
            
            if 'available' in combined_classes or 'locked' in combined_classes or 'seat' in combined_classes:
                found_seats = True
                results["total"] += 1
                
                if 'unavailable' in combined_classes or 'locked' in combined_classes or 'sold' in combined_classes or combined_fill in ['#cccccc', '#ccc', '#e0e0e0', '#eeeeee', 'grey', 'gray', 'none']:
                    results["sold"] += 1
                else:
                    results["available"] += 1
                    
        if found_seats:
            break 
    
    if not found_seats:
        page.screenshot(path="debug_error.png")
        results["error"] = "No SVG seats found. Ensure the event isn't sold out/past. Saved screenshot."
        
    return results, None  # Spektrix doesn't need to return a JSON sample


# ==========================================
# SCRAPER 2: TRAFALGAR (API Network Method)
# ==========================================
def analyze_trafalgar(url, page):
    results = {"total": 0, "available": 0, "sold": 0, "error": None}
    intercepted_jsons = []
    
    def handle_response(response):
        try:
            if response.ok and "application/json" in response.headers.get("content-type", ""):
                data = response.json()
                intercepted_jsons.append(data)
        except:
            pass

    page.on("response", handle_response)
    page.goto(url, wait_until="load", timeout=60000)
    time.sleep(15) 
    
    if not intercepted_jsons:
        results["error"] = "No JSON network traffic intercepted. The site might be blocking the request."
        return results, None

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
        return results, None

    results["total"] = len(largest_array)
    sample = largest_array[0] 
    
    for seat in largest_array:
        seat_str = str(seat).lower()
        if ("'status': 0" in seat_str or 
            "'status': 'available'" in seat_str or 
            "'isavailable': true" in seat_str or 
            "'available': true" in seat_str or 
            "'state': 0" in seat_str or
            "'statusid': 0" in seat_str):
            results["available"] += 1
        else:
            results["sold"] += 1

    return results, sample


# ==========================================
# MAIN BROWSER ROUTER
# ==========================================
def analyze_seats(url):
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
            # Smart Routing: Check URL and send to the correct scraper
            if "trafalgartickets.com" in url.lower():
                results, sample = analyze_trafalgar(url, page)
                method_used = "Trafalgar API"
            else:
                results, sample = analyze_spektrix(url, page)
                method_used = "Spektrix HTML"
                
        except Exception as e:
            page.screenshot(path="debug_error.png")
            results = {"error": f"Crash: {str(e)}"}
            sample = None
            method_used = "Error"
        finally:
            browser.close()
            
        return results, sample, method_used


# ==========================================
# STREAMLIT UI
# ==========================================
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭", layout="wide")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Enter a theatre booking link to calculate how many seats are sold vs. available.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://...")

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner("Analyzing booking platform (this takes ~15-20 seconds)..."):
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results, sample, method_used = analyze_seats(url_input)
            
            if results.get("error"):
                st.error(results['error'])
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="Headless Browser Output")
            else:
                st.success(f"Analysis Complete! (Used {method_used} Method)")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available", results["available"])
                col3.metric("Sold", results["sold"])
                
                # Only show the diagnostic data if it was a Trafalgar scan
                if sample:
                    st.write("---")
                    st.subheader("Diagnostic Tool: API Data Sample")
                    st.write("To make the counter 100% accurate, look at the background data below. This is what Trafalgar Tickets uses to track a single seat. What property dictates if a seat is sold?")
                    st.json(sample)
    else:
        st.warning("Please enter a valid URL.")
