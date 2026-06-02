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
import pytesseract

async def human_delay(min_sec=1.0, max_sec=3.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

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
        await asyncio.sleep(random.uniform(0.08, 0.2))
    await human_delay(0.3, 0.6)

async def human_click(page, selector_or_locator):
    """
    Simulates a human clicking an element by hovering first with a small delay.
    """
    if isinstance(selector_or_locator, str):
        locator = page.locator(selector_or_locator)
    else:
        locator = selector_or_locator
        
    await locator.hover()
    await human_delay(0.3, 0.8)
    await locator.click()
    await human_delay(0.6, 1.2)


# Configure Tesseract path for Windows
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Default values
DEFAULT_API_KEY = "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"
DEFAULT_URL = "https://unifiedportal-emp.epfindia.gov.in/publicPortal/no-auth/misReport/home/loadEstSearchHome"

def preprocess_image(image_bytes):
    """
    Applies image preprocessing to improve OCR accuracy on EPFO captchas.
    """
    img = Image.open(io.BytesIO(image_bytes))
    
    # 1. Convert to grayscale
    img = img.convert('L')
    
    # 2. Resize to 3x for higher resolution text parsing
    img = img.resize((img.width * 3, img.height * 3), Image.Resampling.LANCZOS)
    
    # 3. Threshold to binary (black text on white background)
    threshold = 135
    img = img.point(lambda p: 0 if p < threshold else 255)
    
    return img

def solve_captcha(image_bytes, api_key=None):
    """
    Solves the captcha. If api_key starts with 'sk-or-v1-', uses OpenRouter API.
    Otherwise, falls back to local Tesseract OCR.
    """
    if api_key and api_key.startswith("sk-or-v1-"):
        print("[*] Solving captcha using OpenRouter API...")
        try:
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            
            headers = {
                "Authorization": f"Bearer {api_key}",
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
                    # Clean solution
                    solution = re.sub(r'[^a-zA-Z0-9]', '', solution)
                    print(f"[+] OpenRouter ({model}) solved captcha: '{solution}'")
                    if solution:
                        return solution
                except Exception as e:
                    print(f"[!] OpenRouter ({model}) failed: {e}")
                    
            print("[!] OpenRouter failed to solve captcha. Falling back to local Tesseract OCR...")
        except Exception as outer_e:
            print(f"[!] OpenRouter request setup failed: {outer_e}")

    # Local Tesseract fallback
    try:
        processed_img = preprocess_image(image_bytes)
        custom_config = r'--psm 7 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        solution = pytesseract.image_to_string(processed_img, config=custom_config)
        solution = re.sub(r'[^a-zA-Z0-9]', '', solution)
        print(f"[+] Local Tesseract solved captcha: '{solution.strip()}'")
        return solution.strip()
    except Exception as e:
        print(f"[!] Local Tesseract captcha solver failed: {e}")
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
        await human_click(page, "#searchEmployer")
        
        # Wait for loading overlay (blockUI) to hide
        try:
            await page.locator(".blockUI").wait_for(state="hidden", timeout=15000)
        except Exception:
            pass
            
        # Small wait for UI stabilization
        await human_delay(1.0, 2.0)
        page.remove_listener("dialog", handle_alert)
        
        if captcha_failed:
            print("[!] Incorrect captcha. Retrying...")
            continue
            
        if alert_msg:
            if "no details found" in alert_msg.lower() or "valid establishment name" in alert_msg.lower():
                print(f"[-] Search blocked by 'No Details Found' alert. Skipping query: '{query}'")
                return None, [], None
            print(f"[!] Search blocked by alert: '{alert_msg}'")
            return None, [], None
            
        container_text = await page.locator("#tablecontainer").inner_text()
        if "no records" in container_text.lower():
            print("[-] No records found for this query.")
            return None, [], None
            
        table_locator = page.locator("#tablecontainer table")
        if await table_locator.count() == 0:
            print("[?] Results table not visible. Retrying search...")
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
                    
        return target_est_id, download_paths, disclaimer
        
    print("[!] Failed to solve captcha after maximum search attempts.")
    return None, [], None

async def search_and_download_vendor(page, vendor_name, allowed_state_codes, api_key):
    """
    Performs the search for a vendor, trying both prefix and sanitized formats
    if the name starts with M/S. Solves captcha, downloads details exports.
    """
    original_clean = vendor_name.strip()
    sanitized = sanitize_vendor_name(vendor_name)
    
    queries = []
    if original_clean.upper().startswith("M/S"):
        # Include both: try sanitized (without prefix) first, then original (with prefix)
        if sanitized:
            queries.append(sanitized)
        queries.append(original_clean)
    else:
        if sanitized:
            queries.append(sanitized)
            
    # Try queries sequentially
    for q_idx, query in enumerate(queries):
        if len(queries) > 1:
            print(f"[*] Trying search query variant {q_idx+1}/{len(queries)}: '{query}'")
        target_est_id, download_paths, disclaimer = await execute_search_for_query(
            page, query, allowed_state_codes, api_key
        )
        if target_est_id:
            return target_est_id, download_paths, disclaimer
            
    return None, [], None

async def run_scraper(limit=None, api_key=DEFAULT_API_KEY, headless=True):
    # Setup data files
    if not os.path.exists("VENDORLIST.csv"):
        print("[!] VENDORLIST.csv not found in the current directory.")
        return
        
    # Clean and deduplicate VENDORLIST.csv
    df_vendors = clean_and_deduplicate_csv("VENDORLIST.csv", "VENDORLIST_CLEANED.csv")
    
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
        print("[*] Launching browser in persistent context...")
        user_data_dir = os.path.join(os.getcwd(), "chrome_profile")
        
        # Try launching with Google Chrome channel first, fallback to default Playwright Chromium
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 1024}
            )
            print("[+] Launched persistent context using Google Chrome channel.")
        except Exception as e:
            print(f"[*] Fallback: Could not launch with Google Chrome channel ({e}). Launching default Chromium persistent context...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 1024}
            )
            
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
                            # If matching allowed state codes, or if disclaimer is present and we want to include the mismatched state's IDs as well
                            if prefix in allowed_state_codes or (disclaimer and prefix == target_est_id[:2]):
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
                await asyncio.sleep(5)
                
        await context.close()
        
    print(f"\n[+] Processing complete. Filtered results saved to: {results_file}")

def main():
    parser = argparse.ArgumentParser(description="Deduplicate vendors and run EPFO state filtered search")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Limit the number of vendors to process (default: all)")
    parser.add_argument("-k", "--key", default=DEFAULT_API_KEY, help="Gemini API Key")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    
    args = parser.parse_args()
    
    # Run the async scraper
    asyncio.run(run_scraper(
        limit=args.limit,
        api_key=args.key,
        headless=args.headless
    ))

if __name__ == "__main__":
    main()
