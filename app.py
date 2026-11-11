import streamlit as st
import os
import time
import json
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

os.system("playwright install chromium")

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
"""

# Helper function to aggressively hunt down the fill/stroke color
def extract_color(element, css_color_map):
    if not element:
        return None
        
    # 1. Check direct 'fill' or 'stroke' attributes
    for attr in ['fill', 'stroke']:
        val = element.get(attr, '').lower().strip()
        if val and val not in ['none', 'transparent', '']:
            return val
        
    # 2. Check inline 'style' attribute (e.g., style="stroke: #ff0000;")
    style = element.get('style', '').lower()
    for attr in ['fill:', 'stroke:']:
        if attr in style:
            try:
                val = style.split(attr)[1].split(';')[0].strip()
                if val and val not in ['none', 'transparent', '']:
                    return val
            except:
                pass
                
    # 3. Check CSS Class map (This catches Trafalgar's `<style>` block method)
    classes = element.get('class', [])
    for cls in classes:
        if cls.lower() in css_color_map:
            return css_color_map[cls.lower()]
            
    return None


# ==========================================
# SCRAPER 1: SPEKTRIX (Visual HTML Method)
# ==========================================
def analyze_spektrix(url, page):
    results = {"total": 0, "available": 0, "sold": 0, "colors": {}, "error": None}
    
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
            
            # Map all CSS classes to their colors from the <style> blocks
            css_text = " ".join([s.string for s in soup.find_all('style') if s.string])
            css_color_map = {}
            for m in re.finditer(r'\.([a-zA-Z0-9_-]+)[^{]*\{[^}]*(?:fill|stroke)\s*:\s*(#[a-fA-F0-9]{3,8}|rgba?\([^)]+\))', css_text, re.IGNORECASE):
                css_color_map[m.group(1).lower()] = m.group(2).lower().strip()

            all_seats = soup.find_all('circle')
            
            if all_seats:
                found_seats = True
                for seat in all_seats:
                    results["total"] += 1
                    classes = " ".join(seat.get('class', [])).lower()
                    
                    # Aggressive color hunt
                    color = extract_color(seat, css_color_map)
                    if not color:
                        color = extract_color(seat.find_parent('g'), css_color_map)
                        
                    if 'unavailable' in classes or 'locked' in classes or color in ['#cccccc', '#ccc', '#e0e0e0', 'grey', 'gray', 'none']:
                        results["sold"] += 1
                    else:
                        results["available"] += 1
                        if color:
                            results["colors"][color] = results["colors"].get(color, 0) + 1
                        else:
                            results["colors"]["Unknown Color"] = results["colors"].get("Unknown Color", 0) + 1
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
    results = {"total": 0, "available": 0, "sold": 0, "colors": {}, "error": None}
    intercepted_jsons = []
    
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

    all_html = [page.content()]
    for frame in page.frames:
        try:
            all_html.append(frame.content())
        except:
            pass

    for html in all_html:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Build CSS color map by reading all <style> blocks
        css_text = " ".join([s.string for s in soup.find_all('style') if s.string])
        css_color_map = {}
        # This Regex finds strings like:  .s-s circle.p-1 { stroke: #0072b3; } 
        for m in re.finditer(r'\.([a-zA-Z0-9_-]+)[^{]*\{[^}]*(?:fill|stroke)\s*:\s*(#[a-fA-F0-9]{3,8}|rgba?\([^)]+\))', css_text, re.IGNORECASE):
            css_color_map[m.group(1).lower()] = m.group(2).lower().strip()
            
        seats = soup.find_all(['circle', 'path', 'rect', 'ellipse'])
        
        for seat in seats:
            classes = " ".join(seat.get('class', [])).lower()
            if 'p-1' in classes or 'available' in classes or 'seat' in classes:
                results["available"] += 1
                
                # Use our new map to check the seat and its parent <g> for colors
                color = extract_color(seat, css_color_map)
                if not color:
                    color = extract_color(seat.find_parent('g'), css_color_map)
                
                if color:
                    results["colors"][color] = results["colors"].get(color, 0) + 1
                else:
                    results["colors"]["Unknown Color"] = results["colors"].get("Unknown Color", 0) + 1
                
        if results["available"] > 0:
            break

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
def analyze_seats(url, platform):
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
            if platform == "Trafalgar Tickets":
                results, sample = analyze_trafalgar(url, page)
            else:
                results, sample = analyze_spektrix(url, page)
                
        except Exception as e:
            page.screenshot(path="debug_error.png")
            results = {"error": f"Crash: {str(e)}"}
            sample = None
        finally:
            browser.close()
            
        return results, sample


# ==========================================
# STREAMLIT UI
# ==========================================
st.set_page_config(page_title="Theatre Seat Counter", page_icon="🎭", layout="wide")
st.title("🎭 Theatre Seat Availability Checker")
st.markdown("Calculate seat availability and forecast remaining gross profit.")

url_input = st.text_input("Enter Booking URL:", placeholder="https://...")
platform_choice = st.selectbox("Select Booking Platform:", ["Spektrix", "Trafalgar Tickets"])

if st.button("Check Seats", type="primary"):
    if url_input:
        with st.spinner(f"Bypassing bot detection and analyzing {platform_choice} (takes ~20 seconds)..."):
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results, sample = analyze_seats(url_input, platform_choice)
            
            if results.get("error"):
                st.error(results['error'])
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="Headless Browser Output")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available", results["available"])
                col3.metric("Sold", results["sold"])
                
                st.divider()
                
                st.subheader("Available Gross Profit Calculator")
                if not results.get("colors"):
                    st.warning("Could not detect distinct colors for the available seats.")
                else:
                    st.write("Assign a ticket price to each color band to calculate potential remaining revenue.")
                    
                    total_potential_revenue = 0.0
                    cols = st.columns(3)
                    col_index = 0
                    
                    for color, count in results["colors"].items():
                        with cols[col_index % 3]:
                            if color.startswith("#") or color.startswith("rgb") or color.isalpha():
                                st.markdown(
                                    f'<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">'
                                    f'<div style="background-color: {color}; width: 20px; height: 20px; border-radius: 50%; border: 1px solid #ccc;"></div>'
                                    f'<strong>{count} seats</strong>'
                                    f'</div>', 
                                    unsafe_allow_html=True
                                )
                            else:
                                st.markdown(f"**{count} seats ({color})**")
                                
                            price = st.number_input(f"Price (£)", key=f"price_{color}", value=0.0, step=1.0)
                            total_potential_revenue += price * count
                        
                        col_index += 1
                        
                    st.write("")
                    st.metric("Total Available GP Left", f"£{total_potential_revenue:,.2f}")
                
                if sample:
                    with st.expander("View Diagnostic API Data (Trafalgar)"):
                        st.code(str(sample), language="json")
    else:
        st.warning("Please enter a valid URL.")
