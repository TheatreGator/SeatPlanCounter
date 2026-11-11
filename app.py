import streamlit as st
import os

os.system("pip install playwright-stealth")

from playwright.sync_api import sync_playwright
# The correct import path for version 2.x
from playwright_stealth.stealth import stealth_sync 
from bs4 import BeautifulSoup
import time

os.system("playwright install chromium")

def analyze_seats(url):
    results = {"total": 0, "available": 0, "sold": 0, "error": None}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        stealth_sync(page)
        
        try:
            page.goto(url, wait_until="load", timeout=60000)
            
            time.sleep(12)
            
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
                    
                    if 'available' in classes or 'locked' in classes or 'seat' in classes:
                        found_seats = True
                        results["total"] += 1
                        
                        if 'unavailable' in classes or 'locked' in classes or fill in ['#cccccc', '#ccc', 'grey', 'gray', 'none']:
                            results["sold"] += 1
                        else:
                            results["available"] += 1
                            
                if found_seats:
                    break 
            
            if not found_seats:
                page.screenshot(path="debug_error.png")
                results["error"] = "Bypassed basic bot detection, but still couldn't find SVG seats. Look at the screenshot below to see exactly what the bot is seeing."
                
        except Exception as e:
            page.screenshot(path="debug_error.png")
            results["error"] = f"Crash: {str(e)}"
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
        with st.spinner("Bypassing bot detection and parsing iframes (this takes ~15 seconds)..."):
            if os.path.exists("debug_error.png"):
                os.remove("debug_error.png")
                
            results = analyze_seats(url_input)
            
            if results.get("error"):
                st.error(results['error'])
                if os.path.exists("debug_error.png"):
                    st.image("debug_error.png", caption="Headless Browser Output")
            else:
                st.success("Analysis Complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Seats", results["total"])
                col2.metric("Available Seats", results["available"])
                col3.metric("Sold Seats", results["sold"])
    else:
        st.warning("Please enter a valid URL.")
