import asyncio
import argparse
import json
import os
import re
import io
import base64
import requests
import pandas as pd
from PIL import Image
from playwright.async_api import async_playwright
import time
import random
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()



async def human_delay(min_sec=1.0, max_sec=3.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def human_mouse_move(page, target_locator):
    try:
        box = await target_locator.bounding_box()
        if box:
            x_target = box["x"] + box["width"] / 2
            y_target = box["y"] + box["height"] / 2
            
            # Generate starting position randomly
            steps = random.randint(6, 12)
            current_x, current_y = random.randint(100, 800), random.randint(100, 600)
            
            for i in range(steps):
                t = (i + 1) / steps
                # Curve calculations: start linear + add some cosine curve deviation
                jitter_x = random.uniform(-4, 4)
                jitter_y = random.uniform(-4, 4)
                step_x = current_x + (x_target - current_x) * t + jitter_x
                step_y = current_y + (y_target - current_y) * t + jitter_y
                await page.mouse.move(step_x, step_y)
                await asyncio.sleep(random.uniform(0.015, 0.035))
            
            # Hover directly on target center
            await page.mouse.move(x_target, y_target)
    except Exception as e:
        # Fallback to direct hover if anything fails
        try:
            await target_locator.hover()
        except Exception:
            pass

async def human_type(page, selector_or_locator, text):
    """
    Simulates a human typing character by character with random delays.
    Clears the target element first.
    """
    if isinstance(selector_or_locator, str):
        locator = page.locator(selector_or_locator)
    else:
        locator = selector_or_locator
        
    await locator.click()
    # Select all and delete to clear existing input
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await human_delay(0.2, 0.4)
    
    for char in text:
        await page.keyboard.type(char)
        # 5% chance of a longer pause mimicking typing mistake or hesitation
        if random.random() < 0.05:
            await human_delay(0.3, 0.7)
        else:
            await asyncio.sleep(random.uniform(0.08, 0.2))
    await human_delay(0.3, 0.6)

async def human_click(page, selector_or_locator):
    """
    Simulates a human clicking an element by hovering using natural mouse paths.
    """
    if isinstance(selector_or_locator, str):
        locator = page.locator(selector_or_locator)
    else:
        locator = selector_or_locator
        
    await human_mouse_move(page, locator)
    await human_delay(0.3, 0.7)
    await locator.click()
    await human_delay(0.5, 1.0)

async def human_scroll(page):
    """
    Simulates a human scrolling down and up slightly to look like a reader.
    """
    try:
        scroll_y = random.randint(150, 350)
        await page.evaluate(f"window.scrollBy(0, {scroll_y})")
        await human_delay(0.5, 1.2)
        await page.evaluate(f"window.scrollBy(0, -{scroll_y})")
        await human_delay(0.3, 0.8)
    except Exception:
        pass

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
]

async def apply_context_stealth(context):
    """
    Applies stealth settings to the browser context to bypass WAF bot checks.
    """
    stealth_js = """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
    window.navigator.chrome = {
        runtime: {},
        loadTimes: () => {},
        csi: () => {}
    };
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });
    """
    await context.add_init_script(stealth_js)


# Load environment variables from local .env file if it exists
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if l and not l.startswith("#") and "=" in l:
                    k, v = l.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass

DEFAULT_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEFAULT_URL = "https://unifiedportal-emp.epfindia.gov.in/publicPortal/no-auth/misReport/home/loadEstSearchHome"



def solve_captcha(image_bytes, api_key=None):
    """
    Solves the captcha using OpenRouter API.
    """
    key_to_use = api_key or DEFAULT_API_KEY
    if not key_to_use:
        print("[!] No OpenRouter API key provided.")
        return ""

    print("[*] Solving captcha using OpenRouter API...")
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {key_to_use}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/epftracker",
            "X-Title": "EPF Tracker Scraper"
        }
        
        models_to_try = [
            "google/gemini-2.5-flash-lite",
            "google/gemini-2.5-flash",
            "google/gemini-flash-1.5"
        ]
        
        for model in models_to_try:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Identify the characters in this CAPTCHA image. Respond with ONLY the alphanumeric characters, nothing else — no punctuation, spaces, or explanation. The answer is 5–6 characters long. Read strictly left to right, even if characters vary in vertical position."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
            }
            try:
                response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
                solution = data['choices'][0]['message']['content'].strip()
                solution = re.sub(r'[^a-zA-Z0-9]', '', solution)
                print(f"[+] OpenRouter ({model}) solved captcha: '{solution}'")
                if solution:
                    return solution
            except Exception as e:
                print(f"[!] OpenRouter ({model}) failed: {e}")
                
    except Exception as outer_e:
        print(f"[!] OpenRouter request setup failed: {outer_e}")

    return ""


def clean_and_deduplicate_csv(input_path, output_path):
    """
    Deduplicates the CSV based on the 'Vendor' (Vendor Code) column.
    """
    print(f"[*] Reading and cleaning CSV file: {input_path}")
    df = pd.read_csv(input_path, dtype=str)
    original_len = len(df)
    
    # Deduplicate based on 'Vendor'
    df_clean = df.drop_duplicates(subset=["Vendor"])
    cleaned_len = len(df_clean)
    
    df_clean.to_csv(output_path, index=False)
    print(f"[+] Deduplicated: {original_len} rows -> {cleaned_len} rows. Saved to: {output_path}")
    return df_clean

def sanitize_vendor_name(name):
    """
    Removes standard prefixes like M/s, M/S, M/s. to improve search matching.
    """
    if not isinstance(name, str):
        return ""
    name = name.strip()
    name = re.sub(r'^(M/S\.\s*|M/s\.\s*|M/S\s+|M/s\s+|M/S|M/s)\s*', '', name, flags=re.IGNORECASE)
    return name.strip()

def get_state_codes_for_gstn(gstn, statecode_data, district_states):
    """
    Maps the first 2 digits of the GSTN to target EPFO 2-letter state codes.
    """
    if not isinstance(gstn, str) or len(gstn) < 2:
        return []
    gstn_first_2 = gstn[:2]
    try:
        state_key = str(int(gstn_first_2))
    except ValueError:
        return []
        
    state_entry = statecode_data.get(state_key)
    if not state_entry:
        return []
        
    state_name = ""
    state_abbr = ""
    if isinstance(state_entry, dict):
        state_name = state_entry.get("name", "")
        state_abbr = state_entry.get("abbreviation", "")
    else:
        state_name = str(state_entry)
        
    state_name = state_name.upper()
    clean_name = state_name.split("(")[0].strip()
    
    # Custom fix for Delhi
    if "DELHI" in clean_name:
        clean_name = "NATIONAL CAPITAL TERRITORY OF DELHI"
        
    codes = []
    if state_abbr:
        codes.append(state_abbr.upper())
        
    code = district_states.get(clean_name)
    if code:
        codes.append(code)
        
    # Add common alternative/standard EPFO abbreviations
    if "ODISHA" in clean_name or "ORISSA" in clean_name:
        codes.extend(["OR", "OD"])
    elif "UTTAR PRADESH" in clean_name:
        codes.append("UP")
    elif "UTTARAKHAND" in clean_name:
        codes.extend(["UA", "UK"])
    elif "CHATTISGARH" in clean_name or "CHHATTISGARH" in clean_name:
        codes.extend(["CG", "RY"])
        
    return list(set(codes))

def extract_establishment_ids_from_file(file_path):
    """
    Scans an Excel, CSV, or HTML-based export file and extracts all valid EPFO establishment IDs.
    """
    est_ids = set()
    try:
        # Check if the file is HTML (DataTables exports HTML tables with .xls extension sometimes)
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            header = f.read(500)
            
        if "<table" in header.lower() or "<html" in header.lower():
            tables = pd.read_html(file_path)
            for df in tables:
                for col in df.columns:
                    for val in df[col].dropna().astype(str):
                        for match in re.findall(r'\b[A-Z]{5}[0-9]{10}\b', val):
                            est_ids.add(match)
        else:
            # Parse as Excel workbook
            excel_file = pd.ExcelFile(file_path)
            for sheet in excel_file.sheet_names:
                df = excel_file.parse(sheet)
                for col in df.columns:
                    for val in df[col].dropna().astype(str):
                        for match in re.findall(r'\b[A-Z]{5}[0-9]{10}\b', val):
                            est_ids.add(match)
    except Exception as e:
        # Fallback: regex search on raw text
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for match in re.findall(r'\b[A-Z]{5}[0-9]{10}\b', text):
                est_ids.add(match)
        except Exception as e2:
            print(f"[!] Failed to parse {file_path}: {e} / {e2}")
            
    return list(est_ids)

async def navigate_with_retry(page, url, retries=3):
    for i in range(retries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            # Check for WAF block page
            content = await page.content()
            if "web page blocked" in content.lower() or "attack id" in content.lower() or "message id" in content.lower():
                print("[!] EPFO WAF Block Page detected! Your IP address is temporarily blocked by the EPFO firewall.")
                raise Exception("EPFO WAF IP block detected.")
                
            return True
        except Exception as e:
            if "EPFO WAF IP block detected" in str(e):
                raise e
            print(f"[!] Navigation attempt {i+1} failed: {e}")
            if i == retries - 1:
                raise
            await asyncio.sleep(5)
    return False

async def execute_search_for_query(page, query, allowed_state_codes, api_key):
    """
    Executes search for a single query. Returns (target_est_id, downloaded_files, disclaimer).
    """
    captcha_failed = False
    alert_msg = ""
    
    async def handle_alert(dialog):
        nonlocal captcha_failed, alert_msg
        alert_msg = dialog.message
        msg_lower = alert_msg.lower()
        if "no details found" in msg_lower or "valid establishment name" in msg_lower:
            print(f"[-] Alert: '{alert_msg}'. No details found for this search. Will not retry captcha.")
            captcha_failed = False
        elif "captcha" in msg_lower or "invalid" in msg_lower or "wrong" in msg_lower:
            captcha_failed = True
        await dialog.dismiss()
        
    page.on("dialog", handle_alert)
    
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        # Go to home/reset page if we are not there
        await navigate_with_retry(page, DEFAULT_URL)
        await human_delay(1.5, 3.0)
        
        # Enter establishment name
        await human_type(page, "#estName", query)
        
        # Capture Captcha
        captcha_img = page.locator("#capImg")
        await captcha_img.wait_for(state="visible", timeout=15000)
        await human_delay(1.0, 2.0)
        image_bytes = await captcha_img.screenshot()
        
        # Solve Captcha
        try:
            captcha_solution = solve_captcha(image_bytes, api_key)
            print(f"[*] Attempt {attempt}: Captcha solved as '{captcha_solution}'")
        except Exception as e:
            print(f"[!] Captcha solver failed: {e}")
            await asyncio.sleep(2)
            continue
            
        await human_type(page, "#captcha", captcha_solution)
        
        # Reset states before click to ensure fresh capture
        captcha_failed = False
        alert_msg = ""
        
        await human_click(page, "#searchEmployer")
        
        # Wait for loading overlay (blockUI) to hide
        try:
            await page.locator(".blockUI").wait_for(state="hidden", timeout=15000)
        except Exception:
            pass
            
        # Small wait for UI stabilization
        await human_delay(1.0, 2.0)
        
        if captcha_failed:
            print("[!] Incorrect captcha. Retrying...")
            continue
            
        if alert_msg:
            page.remove_listener("dialog", handle_alert)
            if "no details found" in alert_msg.lower() or "valid establishment name" in alert_msg.lower():
                print(f"[-] Search blocked by 'No Details Found' alert. Skipping query: '{query}'")
                return None, [], None
            print(f"[!] Search blocked by alert: '{alert_msg}'")
            return None, [], None
            
        container_text = await page.locator("#tablecontainer").inner_text()
        container_text_lower = container_text.lower()
        body_text_lower = (await page.locator("body").inner_text()).lower()
        
        if (
            "no records" in container_text_lower 
            or "no details found" in container_text_lower 
            or "no details found" in body_text_lower
            or "valid establishment" in container_text_lower 
            or "valid establishment" in body_text_lower
        ):
            page.remove_listener("dialog", handle_alert)
            print(f"[-] No details/records found for query: '{query}'. Skipping query.")
            return None, [], None
            
        table_locator = page.locator("#tablecontainer table")
        if await table_locator.count() == 0:
            print("[?] Results table not visible. Extracting page content for terminal debug...")
            try:
                title = await page.title()
                body_text = await page.locator("body").inner_text()
                container_html = await page.locator("#tablecontainer").inner_html()
                
                print(f"\n--- [DEBUG] PAGE TITLE: '{title}' ---")
                print("--- [DEBUG] FIRST 500 CHARACTERS OF BODY TEXT ---")
                print(body_text.strip()[:500])
                print("-------------------------------------------------")
                print(f"DEBUG: #tablecontainer innerHTML: {container_html.strip()[:200]}")
                
                # Save HTML dump
                with open("error_search_table.html", "w", encoding="utf-8") as f:
                    f.write(await page.content())
                print("[*] Page HTML source saved to 'error_search_table.html'")
            except Exception as e:
                print(f"[!] Failed to dump debug info: {e}")
            print("[*] Retrying search...")
            continue


            
        # Get rows
        tbody_tr = page.locator("#tablecontainer table tbody tr")
        row_count = await tbody_tr.count()
        
        # Check if there is pagination
        next_li = page.locator("li.paginate_button.next, #example_next").first
        has_next_page = False
        if await next_li.count() > 0:
            class_attr = await next_li.get_attribute("class") or ""
            if "disabled" not in class_attr:
                has_next_page = True
                
        # If there is exactly 1 row on the first page, and no next page exists
        is_single_entry = (row_count == 1) and (not has_next_page)
        
        found_matching_row = False
        target_est_id = None
        disclaimer = None
        
        if is_single_entry:
            tds = tbody_tr.nth(0).locator("td")
            td_count = await tds.count()
            est_id = ""
            for j in range(td_count):
                cell_text = (await tds.nth(j).inner_text()).strip()
                if re.match(r'^[A-Z]{5}[0-9]{10}$', cell_text):
                    est_id = cell_text
                    break
            
            if est_id:
                prefix = est_id[:2]
                target_est_id = est_id
                found_matching_row = True
                if prefix not in allowed_state_codes:
                    disclaimer = f"Single search result found. State code mismatch ignored (Target: {allowed_state_codes}, Found: {prefix})."
                    print(f"[!] {disclaimer}")
                else:
                    print(f"[+] Found single matching establishment ID: '{est_id}'")
                
                action_cell = tds.last
                action_link = action_cell.locator("a, button, input[type='button']").first
                if await action_link.count() > 0:
                    await human_click(page, action_link)
        else:
            current_page = 1
            first_row_est_id = None
            first_row_tds = None
            while True:
                tbody_tr = page.locator("#tablecontainer table tbody tr")
                row_count = await tbody_tr.count()
                
                for i in range(row_count):
                    tds = tbody_tr.nth(i).locator("td")
                    td_count = await tds.count()
                    est_id = ""
                    for j in range(td_count):
                        cell_text = (await tds.nth(j).inner_text()).strip()
                        if re.match(r'^[A-Z]{5}[0-9]{10}$', cell_text):
                            est_id = cell_text
                            break
                    
                    if est_id:
                        if first_row_est_id is None:
                            first_row_est_id = est_id
                            first_row_tds = tds
                            
                        prefix = est_id[:2]
                        if prefix in allowed_state_codes:
                            print(f"[+] Found matching establishment ID: '{est_id}' on page {current_page}")
                            action_cell = tds.last
                            action_link = action_cell.locator("a, button, input[type='button']").first
                            if await action_link.count() > 0:
                                await human_click(page, action_link)
                                found_matching_row = True
                                target_est_id = est_id
                                break
                
                if found_matching_row:
                    break
                    
                next_li = page.locator("li.paginate_button.next, #example_next").first
                if await next_li.count() > 0:
                    class_attr = await next_li.get_attribute("class") or ""
                    if "disabled" in class_attr:
                        break
                    next_link = next_li.locator("a")
                    if await next_link.count() == 0 or not await next_link.is_visible():
                        break
                    print(f"[*] Match not found on page {current_page}. Going to next results page...")
                    await human_click(page, next_link)
                    await human_delay(1.5, 3.0)
                    current_page += 1
                else:
                    break
                    
            if not found_matching_row and first_row_est_id is not None:
                if current_page > 1:
                    print("[*] State-matching row not found. Navigating back to page 1 to select first result...")
                    first_page_btn = page.locator("li.paginate_button a:has-text('1'), #example a:has-text('1')").first
                    if await first_page_btn.count() > 0:
                        await human_click(page, first_page_btn)
                        await human_delay(1.5, 3.0)
                    tbody_tr = page.locator("#tablecontainer table tbody tr")
                    first_row_tds = tbody_tr.nth(0).locator("td")
                
                prefix = first_row_est_id[:2]
                disclaimer = f"State code mismatch ignored (Target: {allowed_state_codes}, Found: {prefix})."
                print(f"[!] {disclaimer}")
                action_cell = first_row_tds.last
                action_link = action_cell.locator("a, button, input[type='button']").first
                if await action_link.count() > 0:
                    await human_click(page, action_link)
                    found_matching_row = True
                    target_est_id = first_row_est_id
                    
        if not found_matching_row:
            print(f"[-] No search result matches state codes for query: '{query}'")
            return None, [], None
            
        # Wait for details page load
        print("[*] Waiting for details section/page to load...")
        await human_delay(4.0, 6.0)
        
        # Locate export buttons
        excel_locators = page.locator("a:has-text('Excel'), button:has-text('Excel'), input[value='Excel'], .buttons-excel, a:has-text('CSV'), button:has-text('CSV'), .buttons-csv")
        excel_count = await excel_locators.count()
        print(f"[+] Found {excel_count} Excel/CSV export button(s) in details page.")
        
        download_paths = []
        for i in range(excel_count):
            btn = excel_locators.nth(i)
            if await btn.is_visible():
                try:
                    print(f"[*] Downloading file {i+1}/{excel_count}...")
                    async with page.expect_download(timeout=15000) as download_info:
                        await human_click(page, btn)
                    download = await download_info.value
                    os.makedirs("downloads", exist_ok=True)
                    suggested = download.suggested_filename
                    ext = os.path.splitext(suggested)[1] or ".xls"
                    save_path = f"downloads/{target_est_id}_export_{i}{ext}"
                    await download.save_as(save_path)
                    print(f"[+] Download saved to: {save_path}")
                    download_paths.append(save_path)
                except Exception as e:
                    print(f"[!] Export download {i+1} failed: {e}")
                    
        page.remove_listener("dialog", handle_alert)
        return target_est_id, download_paths, disclaimer
        
    page.remove_listener("dialog", handle_alert)
    print("[!] Failed to solve captcha after maximum search attempts.")
    return None, [], None

def remove_pvt_ltd(name):
    """
    Removes 'PVT LTD', 'CO', 'COMPANY', and similar suffixes (case-insensitive) from a vendor name.
    """
    if not isinstance(name, str):
        return ""
    # Matches PVT LTD, PVT. LTD., PVT.LTD, PVT LTD., PVT LT, PVT. LT., PRIVATE LIMITED, CO, CO., COMPANY, etc.
    pattern = re.compile(r'\b(PVT\.?\s*(LTD|LT|LIMITED|L)|PRIVATE\s+LIMITED|CO|COMPANY)\b\.?', re.IGNORECASE)
    cleaned = pattern.sub("", name)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip(" ,.-/")

def remove_symbols(name):
    """
    Removes all non-alphanumeric characters (except spaces) and collapses multiple spaces.
    """
    if not isinstance(name, str):
        return ""
    # Replace non-alphanumeric characters with nothing
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()

async def search_and_download_vendor(page, vendor_name, allowed_state_codes, api_key):
    """
    Performs the search for a vendor. If M/s is present, it generates:
    1) Sanitized (without prefix, e.g. "Power Pioneers")
    2) Without slash (MS prefix, e.g. "MS Power Pioneers")
    """
    original_clean = vendor_name.strip()
    sanitized = sanitize_vendor_name(vendor_name)
    
    queries = []
    m_s_pattern = re.compile(r'\bM/S\.?\b', re.IGNORECASE)
    
    if m_s_pattern.search(original_clean):
        # 1) Try completely sanitized
        if sanitized and sanitized not in queries:
            queries.append(sanitized)
            
        # 2) Try replacing M/s with MS (no slash)
        no_slash_variant = m_s_pattern.sub("MS", original_clean)
        no_slash_variant = re.sub(r'\s+', ' ', no_slash_variant).strip()
        if no_slash_variant and no_slash_variant not in queries:
            queries.append(no_slash_variant)

    else:
        # Standard fallback
        if sanitized and sanitized not in queries:
            queries.append(sanitized)
        if original_clean not in queries:
            queries.append(original_clean)
            
    # Ensure initial_queries are unique and order preserved
    initial_queries = []
    for q in queries:
        if q not in initial_queries:
            initial_queries.append(q)
            
    pvt_ltd_pattern = re.compile(r'\b(PVT\.?\s*(LTD|LT|LIMITED|L)|PRIVATE\s+LIMITED|CO|COMPANY)\b', re.IGNORECASE)
    symbol_pattern = re.compile(r'[^a-zA-Z0-9\s]')
    
    # 1. Generate no-symbol queries (keeping PVT LTD CO suffix)
    no_symbol_queries = []
    for q in initial_queries:
        if symbol_pattern.search(q):
            w_sym = remove_symbols(q)
            if w_sym and w_sym not in initial_queries and w_sym not in no_symbol_queries:
                no_symbol_queries.append(w_sym)
                
    # 2. Generate no-suffix queries (keeping symbols)
    no_pvt_ltd_queries = []
    for q in initial_queries:
        if pvt_ltd_pattern.search(q):
            w_pvt = remove_pvt_ltd(q)
            if (w_pvt and 
                w_pvt not in initial_queries and 
                w_pvt not in no_symbol_queries and 
                w_pvt not in no_pvt_ltd_queries):
                no_pvt_ltd_queries.append(w_pvt)
                
    # 3. Generate queries with both symbols and suffixes removed
    both_removed_queries = []
    for q in initial_queries:
        if pvt_ltd_pattern.search(q) or symbol_pattern.search(q):
            w_both = remove_symbols(remove_pvt_ltd(q))
            if (w_both and 
                w_both not in initial_queries and 
                w_both not in no_symbol_queries and 
                w_both not in no_pvt_ltd_queries and 
                w_both not in both_removed_queries):
                both_removed_queries.append(w_both)
                
    queries = initial_queries + no_symbol_queries + no_pvt_ltd_queries + both_removed_queries

    # Try queries sequentially
    idx_no_symbols = len(initial_queries)
    idx_no_pvt = idx_no_symbols + len(no_symbol_queries)
    idx_both = idx_no_pvt + len(no_pvt_ltd_queries)

    for q_idx, query in enumerate(queries):
        if len(queries) > 1:
            if q_idx == idx_no_symbols:
                print("\n[*] Initial search queries returned no matches. Trying fallback: symbols removed...")
            elif q_idx == idx_no_pvt:
                print("\n[*] No-symbol fallback queries returned no matches. Trying fallback: PVT LTD / CO removed...")
            elif q_idx == idx_both:
                print("\n[*] No-suffix fallback queries returned no matches. Trying fallback: both symbols and PVT LTD / CO removed...")
                
            print(f"[*] Trying search query variant {q_idx+1}/{len(queries)}: '{query}'")
        target_est_id, download_paths, disclaimer = await execute_search_for_query(
            page, query, allowed_state_codes, api_key
        )
        if target_est_id:
            return target_est_id, download_paths, disclaimer
            
    return None, [], None

async def run_scraper(limit=None, api_key=DEFAULT_API_KEY, headless=True, input_file="vendorList.csv", profile_dir="chrome_profile"):
    # Setup data files
    base_name, _ = os.path.splitext(input_file)
    cleaned_file = f"{base_name}_cleaned.csv"
    
    if os.path.exists(input_file):
        # Clean and deduplicate input file
        df_vendors = clean_and_deduplicate_csv(input_file, cleaned_file)
    elif os.path.exists(cleaned_file):
        print(f"[*] {input_file} not found, but {cleaned_file} exists. Loading cleaned vendor list...")
        df_vendors = pd.read_csv(cleaned_file, dtype=str)
    else:
        print(f"[!] Neither {input_file} nor {cleaned_file} found in the current directory.")
        return
    
    # Load state codes mapping
    if not os.path.exists("STATECODE.JSON"):
        print("[!] STATECODE.JSON not found.")
        return
    with open("STATECODE.JSON", "r", encoding="utf-8") as f:
        statecode_data = json.load(f)
        
    # Load district details for state codes
    if not os.path.exists("districts.json"):
        print("[!] districts.json not found.")
        return
    with open("districts.json", "r", encoding="utf-8") as f:
        districts_data = json.load(f)
    district_states = {d["state"].upper(): d["stateCode"].upper() for d in districts_data["districts"]}
    
    # Load existing results for resume capability
    results_file = "vendor_est_matches.json"
    results = {}
    if os.path.exists(results_file):
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            print(f"[+] Resuming scraping. Loaded {len(results)} already processed vendors.")
        except Exception as e:
            print(f"[!] Failed to parse existing results file: {e}. Starting fresh.")
            
    # Process vendors
    count = 0
    
    async with async_playwright() as p:
        import platform
        if profile_dir == "chrome_profile":
            if platform.system() == "Windows":
                user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
            else:
                user_data_dir = os.path.expanduser("~/.config/google-chrome")
            print(f"[*] Launching browser in persistent context using system standard Chrome profile: '{user_data_dir}'...")
        else:
            user_data_dir = os.path.join(os.getcwd(), profile_dir)
            print(f"[*] Launching browser in persistent context using custom profile: '{user_data_dir}'...")
        selected_ua = random.choice(USER_AGENTS)


        # Try launching with Google Chrome channel first, fallback to default Playwright Chromium
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=selected_ua,
                viewport={"width": 1280, "height": 1024},
                ignore_https_errors=True
            )
            print("[+] Launched persistent context using Google Chrome channel.")
        except Exception as e:
            print(f"[*] Fallback: Could not launch with Google Chrome channel ({e}). Launching default Chromium persistent context...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=selected_ua,
                viewport={"width": 1280, "height": 1024},
                ignore_https_errors=True
            )


            
        await apply_context_stealth(context)
        page = context.pages[0] if context.pages else await context.new_page()
        
        for idx, row in df_vendors.iterrows():
            vendor_code = str(row["Vendor"])
            vendor_name = str(row["Vendor Name"])
            vendor_gstn = str(row["Vendor GSTN"])
            
            # Skip if already processed
            if vendor_code in results:
                continue
                
            if limit and count >= limit:
                print(f"[*] Reached limit of {limit} vendors. Halting.")
                break
                
            allowed_state_codes = get_state_codes_for_gstn(vendor_gstn, statecode_data, district_states)
            if not allowed_state_codes:
                print(f"[-] Skipped Vendor {vendor_code}: Could not determine state codes from GSTN '{vendor_gstn}'")
                results[vendor_code] = {
                    "vendor_name": vendor_name,
                    "vendor_gstn": vendor_gstn,
                    "status": "skipped_no_state_code",
                    "matched_establishment_ids": []
                }
                # Write intermediate progress
                with open(results_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                continue
                
            print(f"\n========== Processing Vendor {count+1} (Code: {vendor_code}) ==========")
            print(f"Vendor Name: {vendor_name} | GSTN: {vendor_gstn}")
            
            try:
                target_est_id, downloaded_files, disclaimer = await search_and_download_vendor(
                    page, vendor_name, allowed_state_codes, api_key
                )
                
                matched_est_ids = set()
                status = "no_match_found"
                
                if target_est_id and downloaded_files:
                    status = "success"
                    # Scan downloaded Excel files for establishment IDs
                    for f_path in downloaded_files:
                        all_ids = extract_establishment_ids_from_file(f_path)
                        # Filter by state codes
                        for eid in all_ids:
                            prefix = eid[:2]
                            # If matching allowed state codes, or if disclaimer is present (state code mismatch was bypassed), collect all of them
                            if prefix in allowed_state_codes or disclaimer:
                                matched_est_ids.add(eid)
                                
                    print(f"[+] Found {len(matched_est_ids)} state-matching establishment IDs inside downloaded files.")
                elif target_est_id:
                    status = "no_downloads"
                    print("[-] Clicked view details but no export downloads succeeded.")
                else:
                    print("[-] Search returned no matching results for vendor state.")
                    
                results[vendor_code] = {
                    "vendor_name": vendor_name,
                    "vendor_gstn": vendor_gstn,
                    "status": status,
                    "allowed_state_codes": allowed_state_codes,
                    "target_establishment_id": target_est_id,
                    "matched_establishment_ids": list(matched_est_ids)
                }
                if disclaimer:
                    results[vendor_code]["disclaimer"] = disclaimer
                
                # Save progress after every vendor
                with open(results_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                
                count += 1
                print("[*] Waiting 10 seconds before next vendor...")
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"[!] Error processing vendor {vendor_code}: {e}")
                # Save failure status to resume later
                results[vendor_code] = {
                    "vendor_name": vendor_name,
                    "vendor_gstn": vendor_gstn,
                    "status": f"failed_error: {str(e)}",
                    "matched_establishment_ids": []
                }
                with open(results_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                # Small wait before trying next
                print("[*] Waiting 10 seconds after failure before next vendor...")
                await asyncio.sleep(10)
                
        await context.close()
        
    print(f"\n[+] Processing complete. Filtered results saved to: {results_file}")

async def scrape_details_page_tables(page):
    """
    Scrapes all visible tables in the details section of the page and returns them as a dict.
    """
    tables_data = {}
    
    sections = {
        "validity_status": "#tablecontainer3",
        "establishment_status": "#tablecontainer4",
        "establishment_details": "#tablecontainer5",
        "units_subcode": "#tablecontainer8",
        "other_codes": "#tablecontainer9",
        "branches_without_code": "#tablecontainer10",
        "same_pan_establishments": "#tablecontainer11",
        "additional_information": "#tablecontainer12"
    }
    
    for section_name, selector in sections.items():
        try:
            container = page.locator(selector)
            if await container.count() > 0 and await container.is_visible():
                # Check if there is a table inside
                table = container.locator("table")
                if await table.count() > 0:
                    # Extract headers
                    headers = []
                    thead_ths = table.locator("thead th, thead td")
                    th_count = await thead_ths.count()
                    if th_count > 0:
                        for h_idx in range(th_count):
                            headers.append((await thead_ths.nth(h_idx).inner_text()).strip())
                    else:
                        # Fallback to first tr ths
                        first_tr_ths = table.locator("tr").first.locator("th, td")
                        for h_idx in range(await first_tr_ths.count()):
                            headers.append((await first_tr_ths.nth(h_idx).inner_text()).strip())
                            
                    # Extract rows
                    rows = []
                    tbody_trs = table.locator("tbody tr")
                    tr_count = await tbody_trs.count()
                    start_idx = 0
                    if tr_count == 0:
                        # Fallback to all trs except first if no tbody
                        tbody_trs = table.locator("tr")
                        tr_count = await tbody_trs.count()
                        start_idx = 1 if len(headers) > 0 else 0
                        
                    for r_idx in range(start_idx, tr_count):
                        row_cells = tbody_trs.nth(r_idx).locator("td, th")
                        cell_count = await row_cells.count()
                        row_data = {}
                        for c_idx in range(cell_count):
                            cell_val = (await row_cells.nth(c_idx).inner_text()).strip()
                            header_name = headers[c_idx] if c_idx < len(headers) else f"column_{c_idx}"
                            row_data[header_name] = cell_val
                        if row_data:
                            rows.append(row_data)
                            
                    tables_data[section_name] = rows
        except Exception as e:
            print(f"[!] Error scraping table {section_name}: {e}")
            
    return tables_data


async def scrape_establishment_by_code(page, matched_id, api_key):
    """
    Searches EPFO by the 7-digit establishment code, solves captcha, clicks view report,
    scrapes all visible tables and downloads export files.
    """
    if len(matched_id) < 12:
        print(f"[!] Matched ID '{matched_id}' is invalid or too short.")
        return None, []
        
    code_7 = matched_id[5:12]
    print(f"[*] Searching for matched ID: '{matched_id}' using 7-digit code: '{code_7}'")
    
    captcha_failed = False
    alert_msg = ""
    
    async def handle_alert(dialog):
        nonlocal captcha_failed, alert_msg
        alert_msg = dialog.message
        msg_lower = alert_msg.lower()
        if "no details found" in msg_lower or "valid establishment name" in msg_lower:
            print(f"[-] Alert: '{alert_msg}'. No details found for this search. Will not retry captcha.")
            captcha_failed = False
        elif "captcha" in msg_lower or "invalid" in msg_lower or "wrong" in msg_lower:
            captcha_failed = True
        await dialog.dismiss()
        
    page.on("dialog", handle_alert)
    
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        await navigate_with_retry(page, DEFAULT_URL)
        await human_delay(1.5, 3.0)
        
        # Clear estName to ensure we only search by code
        await page.locator("#estName").clear()
        
        # Enter 7-digit code
        await human_type(page, "#estCode", code_7)
        
        # Capture Captcha
        captcha_img = page.locator("#capImg")
        await captcha_img.wait_for(state="visible", timeout=15000)
        await human_delay(1.0, 2.0)
        image_bytes = await captcha_img.screenshot()
        
        # Solve Captcha
        try:
            captcha_solution = solve_captcha(image_bytes, api_key)
            print(f"[*] Attempt {attempt}: Captcha solved as '{captcha_solution}'")
        except Exception as e:
            print(f"[!] Captcha solver failed: {e}")
            await asyncio.sleep(2)
            continue
            
        await human_type(page, "#captcha", captcha_solution)
        
        # Reset states before click to ensure fresh capture
        captcha_failed = False
        alert_msg = ""
        
        await human_click(page, "#searchEmployer")
        
        # Wait for loading overlay (blockUI) to hide
        try:
            await page.locator(".blockUI").wait_for(state="hidden", timeout=15000)
        except Exception:
            pass
            
        # Small wait for UI stabilization
        await human_delay(1.0, 2.0)
        
        if captcha_failed:
            print("[!] Incorrect captcha. Retrying...")
            continue
            
        if alert_msg:
            page.remove_listener("dialog", handle_alert)
            if "no details found" in alert_msg.lower() or "valid establishment name" in alert_msg.lower():
                print(f"[-] Search blocked by 'No Details Found' alert. Skipping matched ID: '{matched_id}'")
                return None, []
            print(f"[!] Search blocked by alert: '{alert_msg}'")
            return None, []
            
        container_text = await page.locator("#tablecontainer").inner_text()
        container_text_lower = container_text.lower()
        body_text_lower = (await page.locator("body").inner_text()).lower()
        
        if (
            "no records" in container_text_lower 
            or "no details found" in container_text_lower 
            or "no details found" in body_text_lower
            or "valid establishment" in container_text_lower 
            or "valid establishment" in body_text_lower
        ):
            page.remove_listener("dialog", handle_alert)
            print(f"[-] No details/records found for matched ID: '{matched_id}'")
            return None, []
            
        table_locator = page.locator("#tablecontainer table")
        if await table_locator.count() == 0:
            print("[?] Results table not visible. Retrying search...")
            continue
            
        # Get first row
        tbody_tr = page.locator("#tablecontainer table tbody tr")
        row_count = await tbody_tr.count()
        if row_count == 0:
            page.remove_listener("dialog", handle_alert)
            print("[-] Results table is empty.")
            return None, []
            
        tds = tbody_tr.nth(0).locator("td")
        action_cell = tds.last
        action_link = action_cell.locator("a, button, input[type='button']").first
        if await action_link.count() == 0:
            page.remove_listener("dialog", handle_alert)
            print("[-] View Report action button not found.")
            return None, []
            
        # Click View Report/Details
        await human_click(page, action_link)
        
        # Wait for details page load
        print("[*] Waiting for details section/page to load...")
        await human_delay(5.0, 7.0)
        
        # Scrape all HTML tables
        print("[*] Scraping HTML tables from details page...")
        tables_data = await scrape_details_page_tables(page)
        
        # Download files
        excel_locators = page.locator("a:has-text('Excel'), button:has-text('Excel'), input[value='Excel'], .buttons-excel, a:has-text('CSV'), button:has-text('CSV'), .buttons-csv")
        excel_count = await excel_locators.count()
        print(f"[+] Found {excel_count} Excel/CSV export button(s) in details page.")
        
        download_paths = []
        for i in range(excel_count):
            btn = excel_locators.nth(i)
            if await btn.is_visible():
                try:
                    print(f"[*] Downloading file {i+1}/{excel_count}...")
                    async with page.expect_download(timeout=15000) as download_info:
                        await human_click(page, btn)
                    download = await download_info.value
                    os.makedirs("downloads", exist_ok=True)
                    suggested = download.suggested_filename
                    ext = os.path.splitext(suggested)[1] or ".xls"
                    save_path = f"downloads/{matched_id}_details_export_{i}{ext}"
                    await download.save_as(save_path)
                    print(f"[+] Download saved to: {save_path}")
                    download_paths.append(save_path)
                except Exception as e:
                    print(f"[!] Export download {i+1} failed: {e}")
                    
        page.remove_listener("dialog", handle_alert)
        return tables_data, download_paths
        
    page.remove_listener("dialog", handle_alert)
    print("[!] Failed to solve captcha after maximum attempts.")
    return None, []


async def run_details_scraper(api_key=DEFAULT_API_KEY, headless=True):
    results_file = "vendor_est_matches.json"
    if not os.path.exists(results_file):
        print(f"[!] Results file '{results_file}' not found. Run the primary scraper first.")
        return
        
    with open(results_file, "r", encoding="utf-8") as f:
        results = json.load(f)
        
    async with async_playwright() as p:
        import platform
        if platform.system() == "Windows":
            user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        else:
            user_data_dir = os.path.expanduser("~/.config/google-chrome")
        print(f"[*] Launching browser in persistent context for details scraping using system Chrome profile: '{user_data_dir}'...")
        selected_ua = random.choice(USER_AGENTS)

        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=selected_ua,
                viewport={"width": 1280, "height": 1024},
                ignore_https_errors=True
            )
            print("[+] Launched persistent context using Google Chrome channel.")
        except Exception as e:
            print(f"[*] Fallback: Could not launch with Google Chrome channel ({e}). Launching default Chromium persistent context...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=selected_ua,
                viewport={"width": 1280, "height": 1024},
                ignore_https_errors=True
            )

            
        await apply_context_stealth(context)
        page = context.pages[0] if context.pages else await context.new_page()
        
        for vendor_code, vendor_data in results.items():
            if vendor_data.get("status") != "success":
                continue
                
            matched_ids = vendor_data.get("matched_establishment_ids", [])
            if not matched_ids:
                continue
                
            if "scraped_details" not in vendor_data:
                vendor_data["scraped_details"] = {}
                
            for mid in matched_ids:
                # Skip if already scraped successfully
                if mid in vendor_data["scraped_details"] and vendor_data["scraped_details"][mid].get("status") == "success":
                    continue
                    
                print(f"\n--- Scraping details for Matched ID: {mid} (Vendor: {vendor_data['vendor_name']}) ---")
                try:
                    tables, downloads = await scrape_establishment_by_code(page, mid, api_key)
                    if tables is not None:
                        vendor_data["scraped_details"][mid] = {
                            "status": "success",
                            "tables": tables,
                            "downloaded_files": downloads
                        }
                    else:
                        vendor_data["scraped_details"][mid] = {
                            "status": "failed_or_skipped",
                            "tables": {},
                            "downloaded_files": []
                        }
                except Exception as ex:
                    print(f"[!] Error scraping details for {mid}: {ex}")
                    vendor_data["scraped_details"][mid] = {
                        "status": f"failed_error: {str(ex)}",
                        "tables": {},
                        "downloaded_files": []
                    }
                    await asyncio.sleep(5)
                    
                # Save progress after every matched ID
                with open(results_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                    
        await context.close()
    print("[+] Details scraping completed.")


def main():
    parser = argparse.ArgumentParser(description="Deduplicate vendors and run EPFO state filtered search")
    parser.add_argument("-i", "--input", default="vendorList.csv", help="Path to input vendor CSV file (default: vendorList.csv)")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Limit the number of vendors to process (default: all)")
    parser.add_argument("-k", "--key", default=DEFAULT_API_KEY, help="Gemini API Key")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--scrape-details", action="store_true", help="Scrape details only for already matched IDs")
    parser.add_argument("--profile", default="chrome_profile", help="Path to Chrome user data directory (default: chrome_profile)")
    
    args = parser.parse_args()
    
    if args.scrape_details:
        # Run stage 2 only
        asyncio.run(run_details_scraper(
            api_key=args.key,
            headless=args.headless
        ))
    else:
        # Run stage 1 (primary search)
        asyncio.run(run_scraper(
            limit=args.limit,
            api_key=args.key,
            headless=args.headless,
            input_file=args.input,
            profile_dir=args.profile
        ))
        # Automatically trigger stage 2 for newly matched IDs
        print("\n[*] Starting stage 2: Scraping details for matched establishment IDs...")
        asyncio.run(run_details_scraper(
            api_key=args.key,
            headless=args.headless
        ))



if __name__ == "__main__":
    main()
