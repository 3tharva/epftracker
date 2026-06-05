import asyncio
import argparse
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import io
import base64
import requests
import pandas as pd
from PIL import Image
from patchright.async_api import async_playwright
import time
import random
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

import openpyxl.reader.excel
# Bypass stylesheet loading bug in openpyxl for server-generated Excel files
openpyxl.reader.excel.apply_stylesheet = lambda archive, wb: None

def parse_wage_month(month_str):
    if not isinstance(month_str, str):
        return None
    parts = month_str.strip().split('-')
    if len(parts) != 2:
        return None
    month_name, year_str = parts[0].upper(), parts[1]
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    if month_name not in months:
        return None
    month_num = months.index(month_name) + 1
    try:
        if len(year_str) == 2:
            year = 2000 + int(year_str)
        elif len(year_str) == 4:
            year = int(year_str)
        else:
            return None
    except ValueError:
        return None
    return (year, month_num)

def get_latest_payment_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        df = pd.read_excel(file_path)
        cols = {c.strip().lower(): c for c in df.columns}
        wage_month_col = next((cols[c] for c in ['wage month', 'wagemonth', 'month'] if c in cols), None)
        amount_col = next((cols[c] for c in ['amount', 'amt', 'total amount'] if c in cols), None)
        emp_col = next((cols[c] for c in ['no. of employee', 'no. of employees', 'employee count', 'employees', 'no_of_employee', 'no_of_employees'] if c in cols), None)
        
        if not wage_month_col:
            return None
            
        best_row = None
        best_date = None
        
        for idx, row in df.iterrows():
            wm_val = str(row[wage_month_col]).strip()
            parsed = parse_wage_month(wm_val)
            if parsed:
                if not best_date or parsed > best_date:
                    best_date = parsed
                    best_row = row
                    
        if best_row is not None:
            amt_val = best_row[amount_col] if amount_col is not None else None
            emp_val = best_row[emp_col] if emp_col is not None else None
            
            try:
                if pd.isna(amt_val):
                    amt_val = None
                elif isinstance(amt_val, float):
                    amt_val = round(amt_val, 2)
                else:
                    amt_val = int(amt_val)
            except Exception:
                pass
                
            try:
                if pd.isna(emp_val):
                    emp_val = None
                else:
                    emp_val = int(emp_val)
            except Exception:
                pass
                
            return {
                "wage_month": str(best_row[wage_month_col]).strip(),
                "amount": amt_val,
                "employees": emp_val
            }
    except Exception as e:
        print(f"Error parsing payment details {file_path}: {e}")
    return None



async def human_delay(min_sec=8.0, max_sec=10.0):
    await asyncio.sleep(random.uniform(8.0, 10.0))

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
    elif "TELANGANA" in clean_name:
        codes.extend(["TS", "TG", "AP"])
    elif "ANDHRA PRADESH" in clean_name:
        codes.extend(["AP", "TS", "TG"])
        
    return list(set(codes))

custom_office_overrides = {
    "AMBATTUR": "TN",
    "BOMMASANDRA": "KA",
    "K R PURAM (WHITEFIELD)": "KA",
    "KUKATPALLI": "TG",
    "TAMBARAM": "TN",
    "NOIDA": "UP",
    "DELHI (NORTH)": "DL",
    "DELHI (SOUTH)": "DL",
    "BANDRA(MUMBAI-I)": "MH",
    "THANE (MUMBAI-II)": "MH",
    "BARRACKPORE(TITAGARH)": "WB",
    "RAIPUR (CHATTISGARH)": "CG",
    "BHUBANESWAR": "OR",
    "BERHAMPUR": "OR",
    "ROURKELA": "OR",
    "KEONJHAR": "OR",
    "JAMSHEDPUR": "JH",
    "DURGAPUR": "WB",
    "VISHAKAPATNAM": "AP",
    "TRICHY": "TN",
    "NASIK": "MH",
    "BHATINDA": "PB",
    "GURGAON": "HR",
}

def find_state_for_office(office_name, office_state_map):
    office_name = office_name.upper().strip()
    if not office_name:
        return None
        
    # Check manual overrides first
    if office_name in custom_office_overrides:
        return custom_office_overrides[office_name]
        
    # Try exact match
    if office_name in office_state_map:
        return office_state_map[office_name]
        
    # Clean parentheses e.g. "RAIPUR (CHATTISGARH)" -> "RAIPUR"
    cleaned_office = re.sub(r'\(.*\)', '', office_name).strip()
    if cleaned_office in office_state_map:
        return office_state_map[cleaned_office]
        
    if cleaned_office in custom_office_overrides:
        return custom_office_overrides[cleaned_office]
        
    # Try substring match: is district name in office name?
    for dist_name, state_code in office_state_map.items():
        if dist_name in office_name or dist_name in cleaned_office:
            return state_code
            
    # Try substring match: is office name in district name?
    for dist_name, state_code in office_state_map.items():
        if office_name in dist_name or cleaned_office in dist_name:
            return state_code
            
    return None

def extract_establishment_details(file_path):
    """
    Parses the Excel file (as a zip/xml) and extracts dicts with establishment_id, establishment_name, office_name.
    """
    details = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            if 'xl/worksheets/sheet1.xml' not in z.namelist():
                return []
            
            sheet_content = z.read('xl/worksheets/sheet1.xml')
            root = ET.fromstring(sheet_content)
            ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            
            rows = root.findall('.//x:row', ns)
            if not rows:
                return []
            
            est_id_col = None
            est_name_col = None
            office_name_col = None
            
            first_row = rows[0]
            cells = first_row.findall('./x:c', ns)
            for c in cells:
                col_ref = c.get('r')
                col_letter = "".join(filter(str.isalpha, col_ref))
                
                is_t = c.find('.//x:is/x:t', ns)
                val = ""
                if is_t is not None:
                    val = is_t.text or ""
                val_upper = val.strip().upper()
                
                if "ESTABLISHMENT ID" in val_upper or "ESTABLISHMENT CODE" in val_upper:
                    est_id_col = col_letter
                elif "ESTABLISHMENT NAME" in val_upper:
                    est_name_col = col_letter
                elif "OFFICE NAME" in val_upper or "OFFICE" in val_upper:
                    office_name_col = col_letter
            
            if not est_id_col:
                est_id_col = "A"
            if not est_name_col:
                est_name_col = "B"
            if not office_name_col:
                office_name_col = "D"
                
            for r in rows[1:]:
                cells = r.findall('./x:c', ns)
                row_vals = {}
                for c in cells:
                    col_ref = c.get('r')
                    col_letter = "".join(filter(str.isalpha, col_ref))
                    
                    is_t = c.find('.//x:is/x:t', ns)
                    val = ""
                    if is_t is not None:
                        val = is_t.text or ""
                    row_vals[col_letter] = val.strip()
                
                est_id = row_vals.get(est_id_col, "")
                est_name = row_vals.get(est_name_col, "")
                office = row_vals.get(office_name_col, "")
                if re.match(r'^[A-Z]{5}[0-9]{10}$', est_id):
                    details.append({
                        "establishment_id": est_id,
                        "establishment_name": est_name,
                        "office_name": office
                    })
    except Exception as e:
        # Fallback to regex
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for match in re.findall(r'\b[A-Z]{5}[0-9]{10}\b', text):
                details.append({
                    "establishment_id": match,
                    "establishment_name": "",
                    "office_name": ""
                })
        except Exception:
            pass
            
    return details

def extract_id_office_pairs(file_path):
    """
    Parses the Excel file (as a zip/xml) and extracts (establishment_id, office_name) pairs.
    """
    pairs = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            if 'xl/worksheets/sheet1.xml' not in z.namelist():
                return []
            
            sheet_content = z.read('xl/worksheets/sheet1.xml')
            root = ET.fromstring(sheet_content)
            ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            
            rows = root.findall('.//x:row', ns)
            if not rows:
                return []
            
            # Find column letters for "Establishment ID" and "Office Name" from header row (row 1)
            est_id_col = None
            office_name_col = None
            
            first_row = rows[0]
            cells = first_row.findall('./x:c', ns)
            for c in cells:
                col_ref = c.get('r')
                col_letter = "".join(filter(str.isalpha, col_ref))
                
                is_t = c.find('.//x:is/x:t', ns)
                val = ""
                if is_t is not None:
                    val = is_t.text or ""
                val_upper = val.strip().upper()
                
                if "ESTABLISHMENT ID" in val_upper or "ESTABLISHMENT CODE" in val_upper:
                    est_id_col = col_letter
                elif "OFFICE NAME" in val_upper or "OFFICE" in val_upper:
                    office_name_col = col_letter
            
            # Default fallbacks if header parsing fails
            if not est_id_col:
                est_id_col = "A"
            if not office_name_col:
                office_name_col = "D"
                
            for r in rows[1:]:
                cells = r.findall('./x:c', ns)
                row_vals = {}
                for c in cells:
                    col_ref = c.get('r')
                    col_letter = "".join(filter(str.isalpha, col_ref))
                    
                    is_t = c.find('.//x:is/x:t', ns)
                    val = ""
                    if is_t is not None:
                        val = is_t.text or ""
                    row_vals[col_letter] = val.strip()
                
                est_id = row_vals.get(est_id_col, "")
                office = row_vals.get(office_name_col, "")
                if re.match(r'^[A-Z]{5}[0-9]{10}$', est_id):
                    pairs.append((est_id, office))
    except Exception as e:
        print(f"[!] XML parsing failed for {file_path}: {e}")
        # Fallback to regex in case of non-standard files, but without office name
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for match in re.findall(r'\b[A-Z]{5}[0-9]{10}\b', text):
                pairs.append((match, ""))
        except Exception as e2:
            print(f"[!] Fallback parsing also failed for {file_path}: {e2}")
            
    return pairs

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

async def execute_search_for_query(page, query, allowed_state_codes, api_key, office_state_map, vendor_code="unknown"):
    """
    Executes search for a single query. Returns (target_est_id, downloaded_files, disclaimer).
    Downloads are saved to downloads/{vendor_code}/ so concurrent workers never share a path.
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
        elif "captcha" in msg_lower or "invalid" in msg_lower or "wrong" in msg_lower or "incorrect" in msg_lower or "mismatch" in msg_lower or "does not match" in msg_lower:
            captcha_failed = True
        await dialog.dismiss()
        
    page.on("dialog", handle_alert)
    
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        # Reload the page on every single attempt to guarantee a fresh captcha is loaded and completely rendered
        print(f"[*] Navigating to EPFO Portal to load fresh captcha (Attempt {attempt}/{max_attempts})...")
        await navigate_with_retry(page, DEFAULT_URL)
        await human_delay(1.5, 3.0)
        
        # Enter establishment name
        await human_type(page, "#estName", query)
        
        # Locate captcha image
        captcha_img = page.locator("#capImg")
        await captcha_img.wait_for(state="visible", timeout=15000)
        
        # Wait for captcha to load
        try:
            print(f"[*] Waiting for captcha image to load...")
            await page.wait_for_function(
                "document.querySelector('#capImg') && document.querySelector('#capImg').complete && document.querySelector('#capImg').naturalWidth > 0",
                timeout=8000
            )
        except Exception as e:
            print(f"[!] Warning: Captcha load wait timed out: {e}")
            
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
                return None, [], None, []
            print(f"[!] Search blocked by alert: '{alert_msg}'")
            return None, [], None, []
            
        container_text = await page.locator("#tablecontainer").inner_text()
        container_text_lower = container_text.lower()
        
        if (
            "no records" in container_text_lower 
            or "no details found" in container_text_lower 
            or "no data available" in container_text_lower
        ):
            page.remove_listener("dialog", handle_alert)
            print(f"[-] No details/records found for query: '{query}'. Skipping query.")
            return None, [], None, []
            
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


            
        # Results table is found! Scroll naturally to look like a human reading results
        await human_scroll(page)
        
        # Get rows
        tbody_tr = page.locator("#tablecontainer table tbody tr")
        row_count = await tbody_tr.count()
        if row_count == 0:
            print(f"[-] No search results for query: '{query}'")
            return None, [], None, []

        # Extract headers to know where Office Name is
        headers = []
        thead_ths = page.locator("#tablecontainer table thead th")
        th_count = await thead_ths.count()
        if th_count > 0:
            for h_idx in range(th_count):
                headers.append((await thead_ths.nth(h_idx).inner_text()).strip().upper())
                
        office_name_col_idx = -1
        for h_idx, h_text in enumerate(headers):
            if "OFFICE NAME" in h_text or "OFFICE" in h_text:
                office_name_col_idx = h_idx

        found_matching_row = False
        target_est_id = None
        disclaimer = None
        action_link = None
        search_results_list = []

        # Collect details of all rows from search results HTML table
        for r_idx in range(row_count):
            row = tbody_tr.nth(r_idx)
            tds = row.locator("td")
            td_count = await tds.count()
            
            est_id = ""
            for j in range(td_count):
                cell_text = (await tds.nth(j).inner_text()).strip()
                if re.match(r'^[A-Z]{5}[0-9]{10}$', cell_text):
                    est_id = cell_text
                    break
            
            if est_id:
                # Est Name is usually column index 2
                est_name = ""
                if td_count > 2:
                    est_name = (await tds.nth(2).inner_text()).strip()
                # Office Name column index
                office_name = ""
                if office_name_col_idx != -1 and office_name_col_idx < td_count:
                    office_name = (await tds.nth(office_name_col_idx).inner_text()).strip()
                elif td_count == 5:
                    office_name = (await tds.nth(3).inner_text()).strip()
                elif td_count == 6:
                    office_name = (await tds.nth(4).inner_text()).strip()
                
                search_results_list.append({
                    "establishment_id": est_id,
                    "establishment_name": est_name,
                    "office_name": office_name
                })
                
                prefix = est_id[:2]
                office_state = find_state_for_office(office_name, office_state_map)
                
                is_state_match = (prefix in allowed_state_codes) or (office_state in allowed_state_codes)
                
                # Check for state matching row. Fallback to first row.
                if is_state_match or not found_matching_row:
                    target_est_id = est_id
                    found_matching_row = True
                    
                    if is_state_match:
                        print(f"[+] Found matching establishment ID: '{est_id}' (Office: '{office_name}' -> '{office_state}')")
                        disclaimer = None
                    else:
                        disclaimer = f"State code mismatch ignored (Target: {allowed_state_codes}, Found ID: {prefix}, Office: {office_name} -> {office_state})."
                        print(f"[!] {disclaimer}")
                    
                    action_cell = tds.last
                    action_link = action_cell.locator("a, button, input[type='button']").first
                    
                    # If it's a perfect state match, we can stop searching
                    if is_state_match:
                        break

        if not found_matching_row or not action_link or await action_link.count() == 0:
            print(f"[-] No search result matches for query: '{query}'")
            return None, [], None, []

        print(f"[*] Clicking View Details for best matched ID: {target_est_id}")
        await human_click(page, action_link)

        # Wait for details page load
        print("[*] Waiting for details section/page to load...")
        await human_delay(4.0, 6.0)
        
        # Scroll naturally
        await human_scroll(page)
        
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
                    os.makedirs(f"downloads/{vendor_code}", exist_ok=True)
                    suggested = download.suggested_filename
                    ext = os.path.splitext(suggested)[1] or ".xls"
                    save_path = f"downloads/{vendor_code}/{target_est_id}_export_{i}{ext}"
                    await download.save_as(save_path)
                    print(f"[+] Download saved to: {save_path}")
                    download_paths.append(save_path)
                except Exception as e:
                    print(f"[!] Export download {i+1} failed: {e}")
                    
        # Return success immediately inside the attempt loop!
        if target_est_id:
            page.remove_listener("dialog", handle_alert)
            return target_est_id, download_paths, disclaimer, search_results_list

    page.remove_listener("dialog", handle_alert)
    print("[!] Failed to solve captcha after maximum search attempts.")
    return None, [], None, []

def get_7_digit_code(est_id):
    # Strip any leading non-digits (state + office)
    digits_only = re.sub(r'^[^0-9]+', '', est_id)
    # Strip last 3 characters (extension/zeros)
    if len(digits_only) >= 10:
        digits_only = digits_only[:-3]
    # Ensure it's exactly 7 digits
    if len(digits_only) > 7:
        digits_only = digits_only[:7]
    return digits_only

async def execute_payment_search_and_download(page, target_est_id, api_key, vendor_name, vendor_code):
    est_code_7 = get_7_digit_code(target_est_id)
    print(f"[*] Target full Est ID: {target_est_id} -> 7-digit code: {est_code_7}")
    
    captcha_failed = False
    alert_msg = ""
    
    async def handle_alert(dialog):
        nonlocal captcha_failed, alert_msg
        alert_msg = dialog.message
        msg_lower = alert_msg.lower()
        if "no details found" in msg_lower or "valid establishment name" in msg_lower:
            print(f"[-] Alert: '{alert_msg}'. No details found for this search. Will not retry captcha.")
            captcha_failed = False
        elif "captcha" in msg_lower or "invalid" in msg_lower or "wrong" in msg_lower or "incorrect" in msg_lower or "mismatch" in msg_lower or "does not match" in msg_lower:
            captcha_failed = True
        await dialog.dismiss()
        
    page.on("dialog", handle_alert)
    
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        print(f"[*] Navigating to EPFO Portal for payment details search (Attempt {attempt}/{max_attempts})...")
        await navigate_with_retry(page, DEFAULT_URL)
        await human_delay(1.5, 3.0)
        
        # Enter 7-digit establishment code
        await human_type(page, "#estCode", est_code_7)
        
        # Locate captcha image
        captcha_img = page.locator("#capImg")
        await captcha_img.wait_for(state="visible", timeout=15000)
        
        # Wait for captcha to load
        try:
            await page.wait_for_function(
                "document.querySelector('#capImg') && document.querySelector('#capImg').complete && document.querySelector('#capImg').naturalWidth > 0",
                timeout=8000
            )
        except Exception as e:
            print(f"[!] Warning: Captcha load wait timed out: {e}")
            
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
                print(f"[-] Search blocked by 'No Details Found' alert for query: '{est_code_7}'")
                return None, "No details found for this search"
            print(f"[!] Search blocked by alert: '{alert_msg}'")
            return None, f"Search blocked by alert: {alert_msg}"
            
        container_text = await page.locator("#tablecontainer").inner_text()
        container_text_lower = container_text.lower()
        
        if (
            "no records" in container_text_lower 
            or "no details found" in container_text_lower 
            or "no data available" in container_text_lower
        ):
            page.remove_listener("dialog", handle_alert)
            print(f"[-] No details/records found for code: '{est_code_7}'.")
            return None, "No details/records found on portal search"
            
        table_locator = page.locator("#tablecontainer table")
        if await table_locator.count() == 0:
            print("[*] Results table not visible. Retrying search...")
            continue
            
        # Scroll naturally
        await human_scroll(page)
        
        # Get rows
        tbody_tr = page.locator("#tablecontainer table tbody tr")
        row_count = await tbody_tr.count()
        if row_count == 0:
            print(f"[-] No search results rows found for code: '{est_code_7}'")
            page.remove_listener("dialog", handle_alert)
            return None, "No search result rows found"
            
        # Match the full establishment ID exactly in the table rows
        target_row_index = -1
        for r_idx in range(row_count):
            row = tbody_tr.nth(r_idx)
            tds = row.locator("td")
            td_count = await tds.count()
            
            # Check cell values
            for c_idx in range(td_count):
                cell_text = (await tds.nth(c_idx).inner_text()).strip()
                if cell_text == target_est_id:
                    target_row_index = r_idx
                    break
            if target_row_index != -1:
                break
                
        if target_row_index == -1:
            print(f"[-] Full establishment ID '{target_est_id}' not found in search result rows.")
            page.remove_listener("dialog", handle_alert)
            return None, f"Full establishment ID not found in results rows matching 7-digit code {est_code_7}"
            
        # Click view details on that row
        print(f"[+] Found row matching full Est ID '{target_est_id}' at index {target_row_index}. Clicking View Details...")
        target_row = tbody_tr.nth(target_row_index)
        
        # Click the link (View Details) inside the matched row
        action_cell = target_row.locator("td").last
        action_link = action_cell.locator("a, button, input[type='button']").first
        if await action_link.count() > 0:
            await human_click(page, action_link)
        else:
            # Fallback to selector name GJRAJ1829663000
            fallback_link = target_row.locator(f"a[name='{target_est_id}']")
            if await fallback_link.count() > 0:
                await human_click(page, fallback_link)
            else:
                # Text fallback
                text_link = target_row.locator("a:has-text('View Details')")
                if await text_link.count() > 0:
                    await human_click(page, text_link)
                else:
                    page.remove_listener("dialog", handle_alert)
                    return None, "Could not find 'View Details' link in the matched row"
                    
        # Wait for details section to load
        print("[*] Waiting for details section/page to load...")
        await human_delay(4.0, 6.0)
        await human_scroll(page)
        
        # Locate "View Payment Details" link on the details page
        payment_details_link = page.locator("a:has-text('View Payment Details'), a:has-text('Payment Details')")
        if await payment_details_link.count() == 0:
            payment_details_link = page.locator("a").filter(has_text=re.compile("payment", re.IGNORECASE))
            
        if await payment_details_link.count() == 0:
            page.remove_listener("dialog", handle_alert)
            return None, "Could not locate 'View Payment Details' link on the details page"
            
        # Click the link and wait for the popup window
        print("[*] Clicking 'View Payment Details' to open new window...")
        try:
            async with page.context.expect_page(timeout=25000) as popup_info:
                await human_click(page, payment_details_link.first)
            popup_page = await popup_info.value
            await popup_page.wait_for_load_state()
            print("[+] Payment details popup window opened successfully.")
        except Exception as e:
            page.remove_listener("dialog", handle_alert)
            return None, f"Failed to capture payment details popup window: {e}"
            
        page.remove_listener("dialog", handle_alert)
        
        # --- Handle popup content ---
        try:
            # Wait for content or Datatable to load in popup
            try:
                await popup_page.wait_for_selector("#table_pop_up, body", timeout=15000)
            except Exception:
                pass
                
            popup_text = await popup_page.locator("body").inner_text()
            popup_text_lower = popup_text.lower()
            
            # Check for "No Payment details found for this Establishment" message
            if (
                "no payment details found for this establishment" in popup_text_lower 
                or "no payment details found" in popup_text_lower 
                or "no records found" in popup_text_lower
                or "no details found" in popup_text_lower
            ):
                print(f"[-] Popup says: 'No Payment details found for this Establishment' for Est ID: {target_est_id}")
                await popup_page.close()
                return None, "No Payment details found for this Establishment"
                
            # Wait for Datatable Excel export button
            excel_btn = popup_page.locator("a:has-text('Excel'), button:has-text('Excel'), .buttons-excel").first
            try:
                await excel_btn.wait_for(state="visible", timeout=10000)
            except Exception:
                if "tr" not in popup_text_lower:
                    await popup_page.close()
                    return None, "No Payment details found for this Establishment"
                await popup_page.close()
                return None, "Could not locate Excel export button in payment details popup"
                
            # Perform download
            print("[*] Excel button found. Initializing download...")
            async with popup_page.expect_download(timeout=15000) as download_info:
                await human_click(popup_page, excel_btn)
            download = await download_info.value
            
            # Save download
            os.makedirs(f"downloads/{vendor_code}", exist_ok=True)
            suggested = download.suggested_filename
            ext = os.path.splitext(suggested)[1] or ".xlsx"
            clean_vendor_name = re.sub(r'[^a-zA-Z0-9_-]', '_', vendor_name)
            save_path = f"downloads/{vendor_code}/{clean_vendor_name}_{target_est_id}_payment_details{ext}"
            await download.save_as(save_path)
            print(f"[+] Payment details Excel saved to: {save_path}")
            
            await popup_page.close()
            return save_path, None
            
        except Exception as pop_err:
            try:
                await popup_page.close()
            except Exception:
                pass
            return None, f"Error while parsing popup details: {pop_err}"
            
    print("[!] Failed to solve captcha after maximum attempts for payment search.")
    return None, "Failed to solve captcha after maximum attempts"

def save_results(results_file, results):
    temp_file = results_file + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, results_file)
    except Exception as e:
        print(f"[!] Warning: Failed to save results atomically: {e}. Attempting direct save.")
        try:
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        except Exception as save_err:
            print(f"[!] Critical: Failed to save results: {save_err}")

def load_suffixes(file_path="suffixes.txt"):
    default_suffixes = ["PVT", "LTD", "LT", "LIMITED", "LIM", "PRIVATE", "CO", "COMPANY"]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_paths = [file_path, os.path.join(script_dir, file_path)]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    suffixes = [line.strip().upper() for line in f if line.strip() and not line.strip().startswith("#")]
                if suffixes:
                    return suffixes
            except Exception as e:
                print(f"[!] Error loading {path}: {e}")
    return default_suffixes

SUFFIXES = load_suffixes()

def remove_pvt_ltd(name):
    """
    Removes company suffixes (case-insensitive) from a vendor name.
    """
    if not isinstance(name, str):
        return ""
    escaped_suffixes = [re.escape(s) for s in SUFFIXES]
    pattern = re.compile(r'\b(' + '|'.join(escaped_suffixes) + r')\b\.?', re.IGNORECASE)
    cleaned = pattern.sub("", name)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip(" ,.-/")

def remove_symbols(name):
    """
    Removes all non-alphanumeric characters (except spaces and dots) and collapses multiple spaces.
    """
    if not isinstance(name, str):
        return ""
    # Replace non-alphanumeric characters (except spaces and dots) with nothing
    cleaned = re.sub(r'[^a-zA-Z0-9\s\.]', '', name)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()

async def search_and_download_vendor(page, vendor_name, allowed_state_codes, api_key, office_state_map, vendor_code="unknown"):
    """
    Performs the search for a vendor. If M/s is present, it generates:
    1) Sanitized (without prefix, e.g. "Power Pioneers")
    2) Without slash (MS prefix, e.g. "MS Power Pioneers")
    Downloads are namespaced under downloads/{vendor_code}/ to prevent concurrent collisions.
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
            
    # Generate dot-to-space variants
    dot_space_queries = []
    for q in queries:
        if '.' in q:
            dot_replaced = q.replace('.', ' ')
            dot_replaced = re.sub(r'\s+', ' ', dot_replaced).strip()
            if dot_replaced and dot_replaced not in queries and dot_replaced not in dot_space_queries:
                dot_space_queries.append(dot_replaced)
    queries.extend(dot_space_queries)
    
    # Ensure initial_queries are unique and order preserved
    initial_queries = []
    for q in queries:
        if q not in initial_queries:
            initial_queries.append(q)
            
    escaped_suffixes = [re.escape(s) for s in SUFFIXES]
    pvt_ltd_pattern = re.compile(r'\b(' + '|'.join(escaped_suffixes) + r')\b', re.IGNORECASE)
    symbol_pattern = re.compile(r'[^a-zA-Z0-9\s\.]')
    
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
        target_est_id, download_paths, disclaimer, search_results_list = await execute_search_for_query(
            page, query, allowed_state_codes, api_key, office_state_map, vendor_code=vendor_code
        )
        if target_est_id:
            return target_est_id, download_paths, disclaimer, search_results_list
            
    return None, [], None, []

async def _launch_worker_context(p, worker_id, headless, stealth_args, ignore_automation_args):
    """
    Launches an isolated Patchright browser context for a single concurrent worker.
    Each worker gets its own temporary profile directory so sessions never collide.
    Tries Edge channel first, falls back to bundled Patchright Chromium.
    """
    import platform
    import tempfile

    # Each worker uses its own throwaway profile dir — no session sharing between workers.
    worker_profile = os.path.join(tempfile.gettempdir(), f"epf_worker_{worker_id}_{os.getpid()}")
    os.makedirs(worker_profile, exist_ok=True)

    selected_ua = random.choice(USER_AGENTS)
    assert "Headless" not in selected_ua, "User-Agent must not contain 'Headless'!"

    launch_kwargs = dict(
        headless=headless,
        args=stealth_args,
        ignore_default_args=ignore_automation_args,
        user_agent=selected_ua,
        viewport={"width": 1920, "height": 1080},
        screen={"width": 1920, "height": 1080},
        ignore_https_errors=True,
    )

    for attempt_channel in ["msedge", None]:
        try:
            if attempt_channel:
                ctx = await p.chromium.launch_persistent_context(
                    user_data_dir=worker_profile,
                    channel=attempt_channel,
                    **launch_kwargs
                )
            else:
                ctx = await p.chromium.launch_persistent_context(
                    user_data_dir=worker_profile,
                    **launch_kwargs
                )
            label = f"Edge ({attempt_channel})" if attempt_channel else "Patchright Chromium"
            print(f"[W{worker_id}] Launched browser context via {label} (profile: {worker_profile})")
            return ctx, worker_profile
        except Exception as e:
            print(f"[W{worker_id}] Channel '{attempt_channel}' failed: {e}. Trying next...")

    raise RuntimeError(f"[W{worker_id}] Could not launch any browser context.")


async def _process_single_vendor(
    worker_id, p, vendor_code, vendor_name, vendor_gstn,
    allowed_state_codes, api_key, office_state_map,
    results, results_lock, results_file,
    headless, stealth_args, ignore_automation_args,
    vendor_number, payment_mode=False
):
    """
    Full lifecycle for one vendor: launch isolated context → search → download → save → close.
    Runs entirely independently; shares nothing except the guarded results dict.
    """
    context = None
    worker_profile = None
    try:
        print(f"\n[W{worker_id}] ========== Processing Vendor {vendor_number} (Code: {vendor_code}) ==========")
        print(f"[W{worker_id}] Vendor Name: {vendor_name} | GSTN: {vendor_gstn}")

        context, worker_profile = await _launch_worker_context(
            p, worker_id, headless, stealth_args, ignore_automation_args
        )
        page = context.pages[0] if context.pages else await context.new_page()

        if payment_mode:
            # ── Payment mode execution ──
            async with results_lock:
                record = results.get(vendor_code) or results.get(vendor_code.lstrip('0'))
            
            if not record:
                print(f"[W{worker_id}] No matching record found in results for {vendor_code}. Skipping.")
                record = {
                    "vendor_name": vendor_name,
                    "vendor_gstn": vendor_gstn,
                    "status": "no_match_found_skipped",
                    "list_establishment_ids": [],
                    "matched_establishment_ids": []
                }
            else:
                matched_list = record.get("matched_establishment_ids", [])
                if not matched_list:
                    print(f"[W{worker_id}] No matched_establishment_ids found in results for {vendor_code}. Skipping payment details download.")
                else:
                    # Loop and download payment details for all matched establishment IDs
                    for item in matched_list:
                        est_id = item.get("establishment id")
                        est_name = item.get("establishment Name") or vendor_name
                        if not est_id:
                            continue

                        # Check if already processed
                        if item.get("payment_details_status") in ["success", "No Payment details found for this Establishment"] and item.get("payment_details_file"):
                            print(f"[W{worker_id}] Payment details already downloaded for {est_id}. Skipping.")
                            if item.get("payment_details_status") == "success" and "latest_payment" not in item:
                                latest_info = get_latest_payment_info(item.get("payment_details_file"))
                                if latest_info:
                                    item["latest_payment"] = latest_info
                            continue
                        if item.get("payment_details_status") == "No Payment details found for this Establishment":
                            print(f"[W{worker_id}] No payments exist for {est_id}. Skipping.")
                            continue

                        print(f"[W{worker_id}] Running payment details download for Est ID: {est_id} ({est_name})")
                        save_path, err = await execute_payment_search_and_download(
                            page, est_id, api_key, est_name, vendor_code
                        )

                        if save_path:
                            item["payment_details_status"] = "success"
                            item["payment_details_file"] = save_path
                            if "payment_details_error" in item:
                                del item["payment_details_error"]
                            print(f"[W{worker_id}] Successfully downloaded payment details for {est_id} to {save_path}")
                            latest_info = get_latest_payment_info(save_path)
                            if latest_info:
                                item["latest_payment"] = latest_info
                        else:
                            if err == "No Payment details found for this Establishment":
                                item["payment_details_status"] = "No Payment details found for this Establishment"
                                item["payment_details_file"] = ""
                                if "payment_details_error" in item:
                                    del item["payment_details_error"]
                            else:
                                item["payment_details_status"] = "failed"
                                item["payment_details_error"] = err
                                print(f"[W{worker_id}] Payment details download failed for {est_id}: {err}")

                        # Intermediate save
                        async with results_lock:
                            actual_key = vendor_code
                            if vendor_code.lstrip('0') in results:
                                actual_key = vendor_code.lstrip('0')
                            results[actual_key] = record
                            save_results(results_file, results)

                    # Aggregate statuses for top-level keys (backwards compatibility)
                    successful_downloads = [it.get("payment_details_file") for it in matched_list if it.get("payment_details_status") == "success" and it.get("payment_details_file")]
                    no_payment_msgs = [it for it in matched_list if it.get("payment_details_status") == "No Payment details found for this Establishment"]
                    errors = [it.get("payment_details_error") for it in matched_list if it.get("payment_details_error")]

                    if successful_downloads:
                        record["payment_details_status"] = "success"
                        record["payment_details_file"] = successful_downloads[0]
                        if "payment_details_error" in record:
                            del record["payment_details_error"]
                        for it in matched_list:
                            if it.get("payment_details_status") == "success" and it.get("latest_payment"):
                                record["latest_payment"] = it["latest_payment"]
                                break
                    elif no_payment_msgs and len(no_payment_msgs) == len(matched_list):
                        record["payment_details_status"] = "No Payment details found for this Establishment"
                        record["payment_details_file"] = ""
                        if "payment_details_error" in record:
                            del record["payment_details_error"]
                    elif errors:
                        record["payment_details_status"] = "failed"
                        record["payment_details_error"] = "; ".join(errors)

        else:
            # ── Standard matching mode execution ──
            target_est_id, downloaded_files, disclaimer, search_results_list = await search_and_download_vendor(
                page, vendor_name, allowed_state_codes, api_key, office_state_map, vendor_code=vendor_code
            )

            list_est_ids = []
            matched_est_ids = []
            status = "no_match_found"

            # Combine candidates from search_results_list and downloaded details Excel
            candidates = []
            seen_cand_ids = set()

            def add_candidate(eid, name, office):
                if not eid or eid in seen_cand_ids:
                    return
                seen_cand_ids.add(eid)
                candidates.append({
                    "establishment_id": eid,
                    "establishment_name": name,
                    "office_name": office
                })

            if target_est_id and downloaded_files:
                status = "success"
                all_details = []
                for f_path in downloaded_files:
                    details = extract_establishment_details(f_path)
                    all_details.extend(details)
                for d in all_details:
                    add_candidate(d["establishment_id"], d["establishment_name"], d["office_name"])

            if search_results_list:
                for r in search_results_list:
                    add_candidate(r["establishment_id"], r["establishment_name"], r["office_name"])

            if candidates:
                for c in candidates:
                    list_est_ids.append({
                        "establishment Name": c["establishment_name"],
                        "establishment id": c["establishment_id"]
                    })

                prefix_matches = []
                office_matches = []
                for c in candidates:
                    eid = c["establishment_id"]
                    name = c["establishment_name"]
                    office = c["office_name"]
                    prefix = eid[:2].upper()
                    office_state = find_state_for_office(office, office_state_map)
                    
                    item = {
                        "establishment Name": name,
                        "establishment id": eid
                    }
                    if prefix in allowed_state_codes:
                        prefix_matches.append((eid, item))
                    elif office_state in allowed_state_codes:
                        office_matches.append((eid, item))

                if prefix_matches:
                    target_est_id = prefix_matches[0][0]
                    disclaimer = None
                    matched_est_ids = [item for _, item in prefix_matches] + [item for _, item in office_matches]
                elif office_matches:
                    target_est_id = office_matches[0][0]
                    disclaimer = None
                    matched_est_ids = [item for _, item in office_matches]
                else:
                    # If no state match, fallback to the primary target clicked
                    if target_est_id:
                        fallback_item = None
                        for c in candidates:
                            if c["establishment_id"] == target_est_id:
                                fallback_item = {
                                    "establishment Name": c["establishment_name"],
                                    "establishment id": c["establishment_id"]
                                }
                                break
                        if not fallback_item:
                            fallback_item = {
                                "establishment Name": vendor_name,
                                "establishment id": target_est_id
                            }
                        matched_est_ids = [fallback_item]
                    else:
                        matched_est_ids = []

                print(f"[W{worker_id}] Found {len(matched_est_ids)} state-matching establishment IDs.")
            elif target_est_id:
                status = "no_downloads"
                print(f"[W{worker_id}] Clicked view details but no export downloads succeeded.")
            else:
                print(f"[W{worker_id}] Search returned no matching results for vendor state.")

            record = {
                "vendor_name": vendor_name,
                "vendor_gstn": vendor_gstn,
                "status": status,
                "allowed_state_codes": allowed_state_codes,
                "target_establishment_id": target_est_id,
                "list_establishment_ids": list_est_ids,
                "matched_establishment_ids": matched_est_ids
            }
            if disclaimer:
                record["disclaimer"] = disclaimer

    except Exception as e:
        print(f"[W{worker_id}] Error processing vendor {vendor_code}: {e}")
        if payment_mode:
            async with results_lock:
                record = results.get(vendor_code) or results.get(vendor_code.lstrip('0')) or {
                    "vendor_name": vendor_name,
                    "vendor_gstn": vendor_gstn,
                    "status": "success",
                    "target_establishment_id": None
                }
            record["payment_details_error"] = f"Runtime error: {str(e)}"
        else:
            record = {
                "vendor_name": vendor_name,
                "vendor_gstn": vendor_gstn,
                "status": f"failed_error: {str(e)}",
                "list_establishment_ids": [],
                "matched_establishment_ids": []
            }
    finally:
        # Always close the context so the browser process is released
        if context:
            try:
                await context.close()
            except Exception:
                pass

        # ── Cleanup: delete vendor's download directory (ONLY in matching mode) ───────
        if not payment_mode:
            import shutil
            vendor_dl_dir = os.path.join("downloads", vendor_code)
            if os.path.isdir(vendor_dl_dir):
                try:
                    shutil.rmtree(vendor_dl_dir)
                    print(f"[W{worker_id}] Cleaned up download dir: {vendor_dl_dir}")
                except Exception as cleanup_err:
                    print(f"[W{worker_id}] Warning: could not remove {vendor_dl_dir}: {cleanup_err}")

    # ── Thread-safe results write ─────────────────────────────────────────────
    async with results_lock:
        actual_key = vendor_code
        if vendor_code.lstrip('0') in results:
            actual_key = vendor_code.lstrip('0')
        results[actual_key] = record
        save_results(results_file, results)

    print(f"[W{worker_id}] Finished vendor {vendor_code} -> status: {record['status']}")


def needs_payment_download(record):
    if not record:
        return False
    matched_list = record.get("matched_establishment_ids", [])
    if not matched_list:
        return False
        
    for item in matched_list:
        est_id = item.get("establishment id")
        if not est_id:
            continue
        status = item.get("payment_details_status")
        file_path = item.get("payment_details_file")
        if status == "success" and file_path:
            continue
        if status == "No Payment details found for this Establishment":
            continue
        return True
    return False


async def run_scraper(
    limit=None,
    api_key=DEFAULT_API_KEY,
    headless=True,
    input_file="vendorList.csv",
    profile_dir="chrome_profile",
    sleep_delay=10,
    workers=2,
    payment_mode=False,
):
    """
    Concurrent EPFO vendor scraper.

    workers : int
        Number of parallel browser contexts (2–3 recommended).
        Each worker gets its own isolated Patchright context and profile dir.
        A batch delay of 3–8 s fires after every `workers` vendors complete
        to space out bursts and reduce WAF surface.
    """
    # ── Clamp concurrency to safe range ──────────────────────────────────────
    CONCURRENCY = max(1, min(workers, 3))  # hard cap at 3
    print(f"[*] Starting concurrent scraper — {CONCURRENCY} parallel worker(s).")

    # ── Load reference data ───────────────────────────────────────────────────
    for fname in ["STATECODE.JSON", "districts.json"]:
        if not os.path.exists(fname):
            print(f"[!] {fname} not found.")
            return

    with open("STATECODE.JSON", "r", encoding="utf-8") as f:
        statecode_data = json.load(f)
    with open("districts.json", "r", encoding="utf-8") as f:
        districts_data = json.load(f)

    district_states = {d["state"].upper(): d["stateCode"].upper() for d in districts_data["districts"]}
    office_state_map = {
        d.get("district", "").strip().upper(): d.get("stateCode", "").strip().upper()
        for d in districts_data.get("districts", [])
        if d.get("district", "").strip()
    }

    # ── Resume from existing results ──────────────────────────────────────────
    input_base = os.path.splitext(os.path.basename(input_file))[0]
    if input_base.endswith("_cleaned"):
        input_base = input_base[:-8]
    results_file = f"{input_base}.json"
    results = {}
    if os.path.exists(results_file):
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            successful_runs = sum(1 for v in results.values() if v.get("status") == "success")
            print(f"[+] Loaded matching database — {len(results)} vendors found ({successful_runs} successfully matched).")
        except Exception as e:
            print(f"[!] Could not load existing results ({e}). Starting fresh.")

    # ── Load vendor list ──────────────────────────────────────────────────────
    df_vendors = None
    if os.path.exists(input_file):
        base_name, _ = os.path.splitext(input_file)
        cleaned_file = f"{base_name}_cleaned.csv"
        df_vendors = clean_and_deduplicate_csv(input_file, cleaned_file)
    elif os.path.exists(f"{os.path.splitext(input_file)[0]}_cleaned.csv"):
        cleaned_file = f"{os.path.splitext(input_file)[0]}_cleaned.csv"
        print(f"[*] {input_file} not found, using {cleaned_file}.")
        df_vendors = pd.read_csv(cleaned_file, dtype=str)

    # ── Shared concurrency primitives ─────────────────────────────────────────
    semaphore = asyncio.Semaphore(CONCURRENCY)
    results_lock = asyncio.Lock()

    # ── Stealth browser args ──────────────────────────────────────────────────
    stealth_args = [
        "--disable-blink-features=AutomationControlled",
        "--window-size=1920,1080",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-infobars",
        "--disable-extensions",
        "--start-maximized",
        "--lang=en-US,en",
    ]
    ignore_automation_args = ["--enable-automation", "--no-sandbox"]

    # ── PHASE 1: ESTABLISHMENT MATCHING ──────────────────────────────────────
    # We run matching phase ONLY if NOT explicitly requested to run payment details only
    run_phase1 = not payment_mode
    
    if run_phase1:
        if df_vendors is None:
            print("[!] CSV vendor list is required for Establishment Matching mode.")
            return

        pending_match = []
        for _, row in df_vendors.iterrows():
            vc = str(row["Vendor"])
            if results.get(vc, {}).get("status") == "success":
                continue
            pending_match.append(row)
            if limit and len(pending_match) >= limit:
                break

        if pending_match:
            print(f"\n[*] ==========================================")
            print(f"[*] Starting Phase 1: Establishment Matching")
            print(f"[*] {len(pending_match)} vendor(s) to process matching")
            print(f"[*] ==========================================\n")

            async def worker_match(p, worker_id, row, vendor_number):
                vendor_code = str(row["Vendor"])
                vendor_name = str(row["Vendor Name"])
                vendor_gstn = str(row["Vendor GSTN"])

                allowed_state_codes = get_state_codes_for_gstn(vendor_gstn, statecode_data, district_states)
                if not allowed_state_codes:
                    print(f"[W{worker_id}] Skipped {vendor_code}: no state codes for GSTN '{vendor_gstn}'")
                    async with results_lock:
                        results[vendor_code] = {
                            "vendor_name": vendor_name,
                            "vendor_gstn": vendor_gstn,
                            "status": "skipped_no_state_code",
                            "list_establishment_ids": [],
                            "matched_establishment_ids": []
                        }
                        save_results(results_file, results)
                    return

                async with semaphore:
                    await _process_single_vendor(
                        worker_id=worker_id,
                        p=p,
                        vendor_code=vendor_code,
                        vendor_name=vendor_name,
                        vendor_gstn=vendor_gstn,
                        allowed_state_codes=allowed_state_codes,
                        api_key=api_key,
                        office_state_map=office_state_map,
                        results=results,
                        results_lock=results_lock,
                        results_file=results_file,
                        headless=headless,
                        stealth_args=stealth_args,
                        ignore_automation_args=ignore_automation_args,
                        vendor_number=vendor_number,
                        payment_mode=False,
                    )

            async with async_playwright() as p:
                vendor_number = 0
                for batch_start in range(0, len(pending_match), CONCURRENCY):
                    batch = pending_match[batch_start: batch_start + CONCURRENCY]
                    tasks = []
                    for i, row in enumerate(batch):
                        vendor_number += 1
                        wid = (batch_start + i) % CONCURRENCY + 1
                        tasks.append(asyncio.create_task(worker_match(p, wid, row, vendor_number)))

                    await asyncio.gather(*tasks)

                    # Batch delay
                    if batch_start + CONCURRENCY < len(pending_match):
                        batch_delay = random.uniform(3, 8)
                        print(f"\n[*] Batch complete. Waiting {batch_delay:.1f}s before next batch...\n")
                        await asyncio.sleep(batch_delay)
            
            print("\n[+] Phase 1 (Establishment Matching) completed successfully!")
        else:
            print("[*] Phase 1 (Establishment Matching) already complete. Skipping.")

    # ── PHASE 2: PAYMENT DETAILS DOWNLOADING ──────────────────────────────────
    # Run automatically after matching phase, or if payment_mode flag was explicitly set
    pending_payment = []
    
    # Reload results from results file to get fresh updates from Phase 1
    if os.path.exists(results_file):
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                results = json.load(f)
        except Exception:
            pass

    if df_vendors is not None and not df_vendors.empty:
        for _, row in df_vendors.iterrows():
            vc = str(row["Vendor"])
            record = results.get(vc) or results.get(vc.lstrip('0'))
            if needs_payment_download(record):
                pending_payment.append(row)
    else:
        print("[*] No vendor list CSV active, generating queue directly from matched results in JSON.")
        for vc, record in results.items():
            if needs_payment_download(record):
                row_dict = {
                    "Vendor": vc,
                    "Vendor Name": record.get("vendor_name", ""),
                    "Vendor GSTN": record.get("vendor_gstn", "")
                }
                pending_payment.append(row_dict)

    if limit:
        pending_payment = pending_payment[:limit]

    if pending_payment:
        print(f"\n[*] ==========================================")
        print(f"[*] Starting Phase 2: Payment Details Downloading")
        print(f"[*] {len(pending_payment)} vendor(s) to process downloads")
        print(f"[*] ==========================================\n")

        async def worker_payment(p, worker_id, row, vendor_number):
            vendor_code = str(row["Vendor"])
            vendor_name = str(row["Vendor Name"])
            vendor_gstn = str(row["Vendor GSTN"])

            async with semaphore:
                await _process_single_vendor(
                    worker_id=worker_id,
                    p=p,
                    vendor_code=vendor_code,
                    vendor_name=vendor_name,
                    vendor_gstn=vendor_gstn,
                    allowed_state_codes=[],
                    api_key=api_key,
                    office_state_map=office_state_map,
                    results=results,
                    results_lock=results_lock,
                    results_file=results_file,
                    headless=headless,
                    stealth_args=stealth_args,
                    ignore_automation_args=ignore_automation_args,
                    vendor_number=vendor_number,
                    payment_mode=True,
                )

        async with async_playwright() as p:
            vendor_number = 0
            for batch_start in range(0, len(pending_payment), CONCURRENCY):
                batch = pending_payment[batch_start: batch_start + CONCURRENCY]
                tasks = []
                for i, row in enumerate(batch):
                    vendor_number += 1
                    wid = (batch_start + i) % CONCURRENCY + 1
                    tasks.append(asyncio.create_task(worker_payment(p, wid, row, vendor_number)))

                await asyncio.gather(*tasks)

                # Batch delay
                if batch_start + CONCURRENCY < len(pending_payment):
                    batch_delay = random.uniform(3, 8)
                    print(f"\n[*] Batch complete. Waiting {batch_delay:.1f}s before next batch...\n")
                    await asyncio.sleep(batch_delay)
        
        print("\n[+] Phase 2 (Payment Details Downloading) completed successfully!")
    else:
        print("[*] Phase 2 (Payment Details Downloading) already complete. Skipping.")

    print(f"\n[+] Pipeline execution completed. All results saved to: {results_file}")


def main():
    parser = argparse.ArgumentParser(description="Concurrent EPFO vendor EPFO state-filtered search")
    parser.add_argument("-i", "--input", default="vendorList.csv", help="Path to input vendor CSV file (default: vendorList.csv)")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Limit the number of vendors to process (default: all)")
    parser.add_argument("-k", "--key", default=DEFAULT_API_KEY, help="OpenRouter API Key for captcha solving")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile", default="edge_profile", help="Base profile dir name (default: edge_profile)")
    parser.add_argument("--sleep", type=int, default=10, help="(Unused in concurrent mode — kept for dashboard compatibility)")
    parser.add_argument("--workers", type=int, default=2, help="Number of concurrent browser workers (1–3, default: 2)")
    parser.add_argument("--payment", action="store_true", help="Run in payment details downloading mode using matched JSON")

    args = parser.parse_args()

    asyncio.run(run_scraper(
        limit=args.limit,
        api_key=args.key,
        headless=args.headless,
        input_file=args.input,
        profile_dir=args.profile,
        sleep_delay=args.sleep,
        workers=args.workers,
        payment_mode=args.payment,
    ))


if __name__ == "__main__":
    main()

