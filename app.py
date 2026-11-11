import streamlit as st
import os
import time
import json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

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
    time.sleep(15)
    
    try:
        page.locator("button:has-text('Accept')").first.click(timeout=2000)
    except:
        pass

    target_frame = None
    for f in page.frames:
        if "spektrix" in f.url.lower() or "booking" in f.url.lower():
            target_frame = f
            break
            
    if not target_frame and len(page.frames) > 1:
        target_frame = page.frames[1] 
        
    frames_to_scan = [target_frame] if target_frame else page.frames

    found_seats = False
    for frame in frames_to_scan:
        try:
            soup = BeautifulSoup(frame.content(), 'html.parser')
            all_seats = soup.find_all('circle')
            
            if all_seats:
                found_seats = True
                for seat in all_seats:
                    results["total"] += 1
                    classes = seat.get('class', [])
                    fill = seat.get('fill', '').lower()
                    
                    if 'unavailable' in classes or 'locked' in classes or fill in ['#cccccc', 'grey', 'gray', 'none']:
                        results["sold"] += 1
                    else:
                        results["available"] += 1
                break 
        except:
            continue
            
    if not found_seats:
        page.screenshot(path="debug_error.png")
        results["error"] = "No SVG circles found. The event may be sold out, or the iframe structure blocked the scraper. Saved screenshot."
        
    return results, None


# ==========================================
# SCRAPER 2: TRAFALGAR (Hybrid HTML + API Method)
# ==========================================
def analyze_trafalgar(url, page):
    results = {"total": 0, "available": 0, "sold": 0, "error": None}
    intercepted_jsons = []
    
    # 1. Listen for the background array containing SOLD seats
    def handle_response(response):
        try:
            if response.ok and "application/json" in response.headers.get("content-type", ""):
                intercepted_jsons.append(response.json())
        except:
            pass

    page.on("response", handle_response)
    page.goto(url, wait_until="load", timeout=60000)
    time.sleep(15) 
    
    try:
        page.locator("button:has-text('Accept')").first.click(timeout=2000)
    except:
        pass

    # 2. Extract HTML to count AVAILABLE seats (p-1 circles)
    all_html = [page.content()]
    for frame in page.frames:
        try:
            all_html.append(frame.content())
        except:
            pass

    for html in all_html:
        soup = BeautifulSoup(html, 'html.parser')
        seats = soup.find_all(['circle', 'path', 'rect', 'ellipse'])
        
        for seat in seats:
            classes = " ".join(seat.get('class', [])).lower()
            if 'p-1' in classes or 'available' in classes or 'seat' in classes:
                results["available"] += 1
                
        if results["available"] > 0:
            break

    # 3. Find the largest API array to get the SOLD seats
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

    # 4. Combine the logic
    results["sold"] = len(largest_array)
    results["total"] = results["available"] + results["sold"]
    sample = largest_array[:3] if largest_array else None

    if results["total"] == 0:
        page.screenshot(path="debug_error.png")
        results["error"] = "Could not find 'p-1' circles in HTML or intercept a seat array in the API. Saved screenshot."

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
            if "trafalgartickets.com" in url.lower():
                results, sample = analyze_trafalgar(url, page)
                method_used = "Trafalgar Hybrid (API + HTML)"
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
        with st.spinner("Analyzing booking platform (this takes ~20 seconds)..."):
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
                
                if sample:
                    with st.expander("View Diagnostic API Data"):
                        st.code(str(sample), language="json")
    else:
        st.warning("Please enter a valid URL.")
