""" Streamlit Google Maps Scraper (Playwright + Python)
---------------------------------------------------
What this app does:
- You can paste a Google Maps search *query* (e.g., "dentists in Karachi") or a full *Maps URL*
- It opens Google Maps, scrolls the results, and clicks each listing card
- It extracts clean business details into a structured table
- It shows results in the UI and lets you download CSV/Excel (no auto-saving to disk)
- It stops exactly at the user-provided Max listings (0 = unlimited)
Important:
- This tool is for demo/educational purposes. Respect terms and local laws.
"""

# ----------------------------
# Standard Python imports
# ----------------------------
import asyncio
import platform
import os
import re
import time
import logging
import urllib.parse
from dataclasses import dataclass, asdict
from typing import List, Optional, Callable
import io
from openpyxl.styles import Font

# ----------------------------
# Third-party libraries
# ----------------------------
import requests
import pandas as pd
import streamlit as st
from playwright.sync_api import sync_playwright, Page

# ----------------------------
# Windows asyncio fix
# ----------------------------
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ----------------------------
# Streamlit page config & CSS
# ----------------------------
st.set_page_config(
    page_title="Google Maps Scraper (Playwright)",
    page_icon="🗺️",
    layout="wide",
)

st.markdown("""
<style>
  .logbox {
    height: 220px; overflow:auto; background:#0b132b; color:#e0e0e0;
    padding:10px; border-radius:12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size:13px;
  }
  .ok {color:#64dfdf}
  .warn {color:#ffd166}
  .err {color:#ef476f}
</style>
""", unsafe_allow_html=True)

# ----------------------------
# Dataclass for Place
# ----------------------------
@dataclass
class Place:
    s_no: int = 0
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    category: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    city: str = ""
    zip_code: str = ""
    country: str = ""
    monday_hours: str = ""
    tuesday_hours: str = ""
    wednesday_hours: str = ""
    thursday_hours: str = ""
    friday_hours: str = ""
    saturday_hours: str = ""
    sunday_hours: str = ""
    instagram_url: str = ""
    facebook_url: str = ""
    linkedin_url: str = ""
    x_url: str = ""
    listing_url: str = ""
    source: str = ""

# ----------------------------
# Logging
# ----------------------------
def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ----------------------------
# Helper functions (sanitize, parse, extract)
# ----------------------------
def sanitize_filename(name: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_\\-]+', '_', name).strip('_')
    return safe or "results"



def parse_address_parts(address: str):

    cleaned = re.sub(r'[^\x00-\x7F]+', '', (address or "")).strip()
    parts = [p.strip() for p in cleaned.split(',') if p.strip()]
    city, zip_code, country = "-", "-", "-"

    if not parts:
        return city, zip_code, country

    # Detect country (if last chunk looks like a country name, not a number/code)
    if len(parts) >= 2 and not re.search(r'\d', parts[-1]):
        country = parts[-1]
        target = parts[-2]
    else:
        target = parts[-1]

    # Extract postal code (UK/EU style or digit ZIP)
    match = re.search(r'\b([A-Z]{1,2}\d[A-Z0-9]?\s?\d[A-Z]{2}|\d{4,6})\b', target, re.IGNORECASE)
    if match:
        zip_code = match.group(1).strip()
        city = re.sub(re.escape(zip_code), '', target).strip(", ").strip()
    else:
        city = target.strip()

    # Normalize empties
    city = city if city else "-"
    zip_code = zip_code if zip_code else "-"
    country = country if country else "-"
    return city, zip_code, country



def extract_text(page: Page, xpath: str) -> str:
    try:
        loc = page.locator(xpath)
        if loc.count() > 0:
            return (loc.inner_text() or "").strip()
    except: return ""
    return ""

def try_click(page: Page, xpath: str) -> bool:
    try:
        loc = page.locator(xpath)
        if loc.count() > 0:
            loc.first.click()
            return True
    except: return False
    return False

# ----------------------------
# Parse weekly hours table into Mon–Sun columns
# ----------------------------
def parse_weekly_hours(page: Page, place: Place):
    try:
        # Open the hours widget (button with item-id containing "oh")
        try_click(page, '//button[contains(@data-item-id,"oh")]')
        time.sleep(0.5)  # tiny wait for table to appear

        # Try a normal table first; fall back to another container variant
        rows = page.locator('//table//tr')
        if rows.count() == 0:
            rows = page.locator('//div[contains(@class,"G8aQO")]//tr')

        # Map short day names to our dataclass fields
        day_map = {
            'mon': 'monday_hours',
            'tue': 'tuesday_hours',
            'wed': 'wednesday_hours',
            'thu': 'thursday_hours',
            'fri': 'friday_hours',
            'sat': 'saturday_hours',
            'sun': 'sunday_hours',
        }

        # Initialize all days to "-" so CSV is consistent
        for fld in day_map.values():
            setattr(place, fld, "-")

        # Iterate each row and place into correct day column
        for i in range(rows.count()):
            try:
                row = rows.nth(i)
                # Day label (e.g., "Monday", "Mon", etc.)
                day_text = (row.locator('td').nth(0).inner_text() or "").strip().lower()
                # Hours text (e.g., "9 AM – 6 PM", "Closed", "Open 24 hours", etc.)
                times_text = (row.locator('td').nth(1).inner_text() or "").strip()

                # Which day key matches this label?
                key = next((d for d in day_map if d in day_text), None)
                if not key:
                    continue

                # Normalize some common cases
                lt = times_text.lower()
                if '24' in lt and 'hour' in lt:
                    final_text = "Open 24 hours"
                elif 'closed' in lt:
                    final_text = "Closed"
                else:
                    # Convert various separators → "X to Y"
                    parts = re.split(r'–|-|to', times_text)
                    open_time = parts[0].strip() if parts else ""
                    close_time = parts[1].strip() if len(parts) > 1 else ""
                    final_text = f"{open_time} to {close_time}" if open_time and close_time else (open_time or "-")

                setattr(place, day_map[key], final_text)
            except Exception:
                continue
    except Exception:
        # If the hours widget is missing, we keep "-" defaults
        pass


def extract_social_links(website_url: str, place: Place):
    try:
        if not website_url: return
        url = website_url
        if url.startswith('//'): url='https:'+url
        if not url.startswith('http'): url='https://'+url.lstrip('/')
        resp = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        if resp.status_code!=200: return
        html=resp.text
        m = re.search(r"https://(?:www\.)?instagram\.com/[A-Za-z0-9_.\-/%?=]+", html); 
        if m: place.instagram_url=m.group(0)
        m = re.search(r"https://(?:www\.)?facebook\.com/[A-Za-z0-9_.\-/%?=]+", html)
        if m: place.facebook_url=m.group(0)
        m = re.search(r"https://(?:www\.)?linkedin\.com/[A-Za-z0-9_.\-/%?=]+", html)
        if m: place.linkedin_url=m.group(0)
        m = re.search(r"https://(?:twitter|x)\.com/[A-Za-z0-9_.\-/%?=]+", html)
        if m: place.x_url=m.group(0)
    except: pass

def extract_place(page: Page, user_input: str, index: int, listing_url: str) -> Place:
    place=Place()
    place.s_no=index
    place.source=user_input
    place.listing_url=listing_url
    name_xpath='//div[@class="TIHn2 "]//h1[contains(@class,"DUwDvf")]'
    address_xpath='//button[@data-item-id="address"]//div[contains(@class,"fontBodyMedium")]'
    phone_xpath='//button[contains(@data-item-id,"phone:tel:")]//div[contains(@class,"fontBodyMedium")]'
    category_xpath='//button[contains(@class,"DkEaL")]'
    place.name=extract_text(page,name_xpath)
    place.address=extract_text(page,address_xpath)
    place.phone_number=extract_text(page,phone_xpath)
    place.category=extract_text(page,category_xpath)
    try:
        rating_elem=page.locator('//div[@role="img" and contains(@aria-label,"stars")]')
        if rating_elem.count()>0:
            rating_text=rating_elem.first.get_attribute("aria-label") or ""
            nums=re.findall(r"[0-9.]+",rating_text)
            if nums: place.reviews_average=float(nums[0])
    except: place.reviews_average=None
    try:
        review_elem=page.locator('//span[@aria-label and contains(@aria-label,"reviews")]')
        if review_elem.count()>0:
            count_text=review_elem.first.get_attribute("aria-label") or ""
            digits=re.findall(r"[0-9,]+",count_text)
            if digits: place.reviews_count=int(digits[0].replace(",",""))
    except: place.reviews_count=None
    try:
        auth=page.locator('//a[@data-item-id="authority"]')
        if auth.count():
            website_url=auth.first.get_attribute("href") or ""
            if website_url and not website_url.startswith("http"): website_url="https://"+website_url.lstrip("/")
            place.website=website_url.strip()
    except: place.website=""
    # Extract latitude and longitude from listing_url instead of page.url
    try:
        m = re.search(r'@([0-9\.-]+),([0-9\.-]+)', listing_url)
        if m:
            place.latitude = float(m.group(1))
            place.longitude = float(m.group(2))
        
        else:
            m = re.search(r'!3d([-0-9\.]+)!4d([-0-9\.]+)', listing_url)
            if m:
                place.latitude = float(m.group(1))
                place.longitude = float(m.group(2))
            else:
                place.latitude = 0.0
                place.longitude = 0.0
    except:
        place.latitude = 0.0
        place.longitude = 0.0
    # Split address into City / ZIP / Country using our parser
    if place.address:
        city, zip_code, country = parse_address_parts(place.address)
    else:
        city, zip_code, country = "-", "-", "-"
    place.city, place.zip_code, place.country = city, zip_code, country
    # Try to parse weekly hours (keeps "-" if widget not present)
    parse_weekly_hours(page,place)
    # If a website exists, try to sniff social links (best-effort)
    if place.website: 
        extract_social_links(place.website,place)
    # Final normalization: replace empty strings with "-" so CSV columns are consistent.
    for k,v in asdict(place).items():
        if isinstance(v,str) and v.strip()=="": setattr(place,k,"-")
    return place

def go_to_next_results_page(page: Page, log: Callable[[str,str],None]) -> bool:
    selectors=['//button[@aria-label=" Next page " or @aria-label="Next page"]',
               '//button[contains(@aria-label,"Next") and contains(@class,"HlvSq")]',
               '//div[contains(@jsaction,"pane.paginationSection.nextPage")]//button',
               '//button[contains(@data-id,"pagination-button-next")]']
    for xp in selectors:
        try:
            btn=page.locator(xp)
            if btn.count()>0 and btn.first.is_enabled():
                btn.first.click()
                log("Clicked Next page…","ok")
                page.wait_for_timeout(1500)
                page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]',timeout=30000)
                return True
        except: continue
    return False

# ----------------------------
# Main scraping function
# ----------------------------
def scrape_places_streamlit(user_input:str, headless:bool, show_system_chrome:bool, max_listings:int, scroll_delay:float, should_stop:Callable, log:Callable[[str,str],None]):
    places=[]
    if user_input.startswith("http"):
        parsed = urllib.parse.urlparse(user_input)
        qs = urllib.parse.parse_qs(parsed.query)
        if "q" in qs:
            search_title = qs["q"][0]
        else:
            # /search/... pattern se extract
            match = re.search(r"/maps/search/([^/?]+)", user_input)
            search_title = urllib.parse.unquote(match.group(1)) if match else "google_maps_results"
    else:
        search_title = user_input

    output_filename = sanitize_filename(search_title) + ".csv"
    with sync_playwright() as p:
        # if show_system_chrome:
        #     try:
        #         browser = p.chromium.launch(channel="chrome", headless=headless)
        #     except:
        #         # Fallback: Playwright ka bundled Chromium
        #         browser = p.chromium.launch(headless=headless)
        # else:
        #     browser = p.chromium.launch(headless=headless)
        # ----------------------------
        # Browser launch (Cloud-safe)
        # ----------------------------
        if platform.system() == "Windows":
            # Local testing: show browser if desired
            browser = p.chromium.launch(headless=not show_system_chrome)
        else:
            # Streamlit Cloud / Linux: always headless, use bundled Chromium
            browser = p.chromium.launch(headless=True)

        context=browser.new_context()
        page=context.new_page()
        if "http" not in user_input: url=f"https://www.google.com/maps/search/{urllib.parse.quote(user_input)}"
        else: url=user_input
        page.goto(url)
        page.wait_for_timeout(1500)
        # Gather listing URLs
        # Gather listing URLs dynamically (handle 0 = unlimited and N limit)
        # Gather listing URLs
        listing_urls = []
        no_new_rounds = 0
        MAX_NO_NEW_ROUNDS = 5   # tolerate 5 empty scrolls before giving up

        while True:
            if should_stop():
                log("⏹️ User pressed Stop while collecting URLs. Proceeding to scrape collected listings...", "warn")
                break

            # Scroll results panel
            try:
                results_panel = page.locator('//div[contains(@aria-label,"Results for") or @role="feed"]')
                if results_panel.count() > 0:
                    for _ in range(3):
                        results_panel.first.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                        page.wait_for_timeout(1000)
                else:
                    for _ in range(3):
                        page.evaluate("() => window.scrollBy(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1000)
            except:
                pass

            # Collect listing cards
            cards = page.locator('//a[contains(@href,"/maps/place/")]')
            added = 0
            for i in range(cards.count()):
                href = cards.nth(i).get_attribute("href")
                if href and href not in listing_urls:
                    listing_urls.append(href)
                    added += 1

                    # ✅ Fixed limit
                    if max_listings > 0 and len(listing_urls) >= max_listings:
                        break

            # ✅ Stop condition for fixed N
            if max_listings > 0 and len(listing_urls) >= max_listings:
                log(f"Collected {len(listing_urls)} / {max_listings} listings. Stopping URL collection.", "ok")
                break

            # ✅ Infinite/unlimited mode
            if max_listings == 0:
                if added == 0:
                    no_new_rounds += 1
                    log(f"No new cards (round {no_new_rounds})", "warn")

                    if no_new_rounds >= MAX_NO_NEW_ROUNDS:
                        moved = go_to_next_results_page(page, log)
                        if not moved:
                            log("No more pages found. Ending unlimited scraping.", "warn")
                            break
                        else:
                            no_new_rounds = 0
                else:
                    no_new_rounds = 0
                continue

            # ✅ For fixed N also: try to move next page if no new cards
            if added == 0:
                no_new_rounds += 1
                log(f"No new cards (round {no_new_rounds})", "warn")

                if no_new_rounds >= MAX_NO_NEW_ROUNDS:
                    moved = go_to_next_results_page(page, log)
                    if not moved:
                        log("No more pages, stopping.", "warn")
                        break
                    else:
                        no_new_rounds = 0
            else:
                no_new_rounds = 0



        log("Start Data Scraping", "ok")
        if st.session_state.get("stop", False):
            st.session_state.stop = False
            log("Stopped collecting URLs. Now scraping collected listings...", "warn")
        results_container = st.empty()  # container for table & download

        places = []

        # Scrape each listing
        for idx, link in enumerate(listing_urls, 1):
            if max_listings > 0 and idx > max_listings:
                break

            page.goto(link)
            page.wait_for_timeout(scroll_delay*1000)
            place = extract_place(page, user_input, idx, link)
            places.append(place)
            ui_log(f"Scraped {idx}: {place.name}", "ok")

            # ✅ Update partial results in session
            df_partial = pd.DataFrame([asdict(p) for p in places])
            st.session_state["last_results"] = (df_partial, output_filename)

            # ✅ Agar stop dabaya gaya hai
            if should_stop():
                ui_log("⏹️ User pressed Stop.", "warn")
                break


            # # ✅ Render partial results immediately
            # df = pd.DataFrame([asdict(p) for p in places])
            # if not df.empty:
            #     if 's_no' in df.columns:
            #         cols = df.columns.tolist()
            #         cols.insert(0, cols.pop(cols.index('s_no')))
            #         df = df[cols]

            #     results_container.dataframe(df, use_container_width=True, height=420)
            #     # Optional: render download button too
            #     csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                

            # ✅ Stop check
            if should_stop():
                ui_log("⏹️ User pressed Stop.", "warn")
                break


        browser.close()
        return places, output_filename




# ----------------------------
# Streamlit UI elements
# ----------------------------
st.title("🗺️ Google Maps Scraper")
st.sidebar.header("Settings")
user_input = st.sidebar.text_input(
    "Enter Google Maps search query or full URL", 
    placeholder="e.g. dentists in Karachi OR https://www.google.com/maps/..."
)
headless=st.sidebar.checkbox("Run headless",value=True)
use_system_chrome=st.sidebar.checkbox("Use system Chrome",value=True)
max_listings=st.sidebar.number_input("Max listings (0=unlimited)",min_value=0,value=10,step=1)
scroll_delay=st.sidebar.number_input("Scroll delay per listing (seconds)",min_value=0.1,value=1.0,step=0.1)
# Sidebar mai 2 columns banate hain
col_btn = st.sidebar.columns(2) 
start= col_btn[0].button("▶️ Start")
stop= col_btn[1].button("🛑 Stop", type="secondary")
st.session_state.setdefault("stop",False)

def should_stop(): 
    return st.session_state.stop

log_box=st.empty()
progress = st.empty()
status = st.empty()
def ui_log(msg: str, level: str = "ok"):
    # Append to a session log list and render
    if "_logs" not in st.session_state:
        st.session_state._logs = []
    st.session_state._logs.append((level, msg))
    # Keep last 400 lines
    st.session_state._logs = st.session_state._logs[-400:]

    # Build HTML
    html = ["<div class='logbox'>"]
    for lvl, m in st.session_state._logs:
        cls = {"ok":"ok", "warn":"warn", "err":"err"}.get(lvl, "ok")
        html.append(f"<div class='{cls}'>» {m}</div>")
    html.append("</div>")
    log_box.markdown("\n".join(html), unsafe_allow_html=True)



def show_results(df, output_filename):
    if not df.empty:
        # Reorder columns
        if 's_no' in df.columns:
            cols = df.columns.tolist()
            cols.insert(0, cols.pop(cols.index('s_no')))
            df = df[cols]

        if st.session_state.stop:
            st.success(f"⏹️ Scraped {len(df)} listings (stopped early).")
        else:
            st.success(f"✅ Scraped {len(df)} listings.")

        st.dataframe(df, use_container_width=True, height=420)
    else:
        st.warning("No data scraped before Stop.")


    # Render download button even if empty
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
            worksheet = writer.sheets['Sheet1']
            for cell in worksheet[1]:
                cell.font = Font(bold=True)
        output.seek(0)
        st.download_button(
            label="⬇️ Download Excel with bold headers",
            data=output,
            file_name=output_filename.replace(".csv", ".xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception:
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label="⬇️ Download CSV",
            data=csv_bytes,
            file_name=output_filename,
            mime="text/csv",
            use_container_width=True,
        )


# ----------------------------
# Start scraping logic
# ----------------------------

if start:
    st.session_state.stop = False
    st.session_state._logs = []
    if not user_input.strip():
        st.warning("Please enter a Google Maps search query or URL.")
    else:
        ui_log("Launching browser…", "ok")
        try:
            places, output_filename = scrape_places_streamlit(
                user_input=user_input.strip(),
                headless=headless,
                show_system_chrome=use_system_chrome,
                max_listings=max_listings,
                scroll_delay=scroll_delay,
                should_stop=should_stop,
                log=ui_log,
            )

            df = pd.DataFrame([asdict(p) for p in places])
            show_results(df, output_filename)   # 👈 calling result show Function

            # ✅ Save last results for Stop button
            st.session_state["last_results"] = (df, output_filename)

        except Exception as e:
            ui_log(f"Fatal error: {e}", "err")
            st.error(f"❌ Scraping failed: {e}")

# ✅ Stop button should ONLY set stop flag
if stop:
    st.session_state.stop = True
    ui_log("⏹️ Stop pressed. Finishing current listing then halting...", "warn")

    if "last_results" in st.session_state:
        df, output_filename = st.session_state["last_results"]
        show_results(df, output_filename)   # 👈 ab stop pe bhi table & download milega

# ----------------------------
# Helpful tips
# ----------------------------
# with st.expander("Tips & Troubleshooting"):
#     st.markdown(
#         """
# - If nothing loads, **disable headless** so the browser is visible.
# - Google Maps in headless mode can be inconsistent; visible mode is often better.
# - Use a specific query like *restaurants in Lahore* or paste a full Maps search URL.
# - **Duplicates blocked** via name+address and listing URL.
# - On Windows, try **Use system Chrome path** for better stability.
# - If Playwright errors about browsers, run: `playwright install chromium` in your terminal.
# - This tool is for educational/demo use. Respect websites’ terms and local laws.
#         """
#     )

