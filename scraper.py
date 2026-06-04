import asyncio
import argparse
import json
import os
import re
import io
import base64
import random
import requests
from PIL import Image
from patchright.async_api import async_playwright
from dotenv import load_dotenv

# Helpers for human-like behavior
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

# Load environment variables from .env
load_dotenv()

# Default OpenRouter API key loaded from environment
DEFAULT_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEFAULT_URL = "https://unifiedportal-emp.epfindia.gov.in/publicPortal/no-auth/misReport/home/loadEstSearchHome"


def solve_captcha(image_bytes, api_key):
    """
    Sends the captcha image bytes to OpenRouter API to solve.
    """
    if not api_key:
        print("[!] No OpenRouter API key provided.")
        return ""
    
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/epftracker",
            "X-Title": "EPF Tracker Scraper"
        }
        
        models_to_try = [
            "google/gemini-2.5-flash",
            "google/gemini-2.5-flash-lite",
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

async def extract_table_data(page):
    """
    Extracts rows and headers from the results table.
    """
    table_selector = "#tablecontainer table"
    if await page.locator(table_selector).count() == 0:
        return [], []

    table = page.locator(table_selector)
    
    # Extract headers
    headers = []
    header_elements = table.locator("thead th")
    header_count = await header_elements.count()
    if header_count > 0:
        for i in range(header_count):
            headers.append((await header_elements.nth(i).inner_text()).strip())
    else:
        # Fallback if there is no official thead structure
        first_row = table.locator("tr").first
        th_td_elements = first_row.locator("th, td")
        for i in range(await th_td_elements.count()):
            headers.append((await th_td_elements.nth(i).inner_text()).strip())

    # If headers are still empty, create default column names
    if not headers:
        headers = ["Col_" + str(i) for i in range(10)]

    rows = []
    # Extract all rows from tbody
    tbody_tr = table.locator("tbody tr")
    row_count = await tbody_tr.count()
    
    # If no tbody trs, look for all trs except the first (header)
    if row_count == 0:
        all_tr = table.locator("tr")
        all_tr_count = await all_tr.count()
        for i in range(1, all_tr_count):
            tds = all_tr.nth(i).locator("td")
            td_count = await tds.count()
            row_vals = []
            for j in range(td_count):
                row_vals.append((await tds.nth(j).inner_text()).strip())
            if row_vals:
                rows.append(row_vals)
    else:
        for i in range(row_count):
            tds = tbody_tr.nth(i).locator("td")
            td_count = await tds.count()
            row_vals = []
            for j in range(td_count):
                row_vals.append((await tds.nth(j).inner_text()).strip())
            if row_vals:
                rows.append(row_vals)
                
    # Map row lists to dictionary using headers
    mapped_rows = []
    for r in rows:
        if len(r) == len(headers):
            mapped_rows.append(dict(zip(headers, r)))
        else:
            mapped_rows.append({"raw_cells": r})
            
    return headers, mapped_rows


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
    Removes company suffixes (case-insensitive) from a vendor/establishment name.
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

async def run_scraper(establishment_name, api_key, headless=True):
    queries = [establishment_name]
    
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

    async with async_playwright() as p:
        import platform
        if platform.system() == "Windows":
            user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")
        else:
            user_data_dir = os.path.expanduser("~/.config/microsoft-edge")
        print(f"[*] Launching browser in persistent context using system Edge profile: '{user_data_dir}'...")

        # ── PATCH: User-Agent Spoofing ────────────────────────────────────────
        # The default headless UA contains the word 'HeadlessChrome', which is
        # trivially detected. We replace it with a real desktop Chrome UA.
        # This UA must NOT contain 'Headless' to pass UA-based bot filters.
        # ──────────────────────────────────────────────────────────────────────
        selected_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        assert "Headless" not in selected_ua, "User-Agent must not contain 'Headless'!"

        # ── PATCH: Stealth Launch Args ────────────────────────────────────────
        # --headless=new:              Uses the new headless mode (less detectable).
        # --disable-blink-features:    Removes the AutomationControlled flag from
        #                              navigator.webdriver and blink internals.
        # --window-size:               Forces a realistic viewport size; headless
        #                              defaults to very small or 0-sized windows.
        # --no-sandbox / --disable-gpu: Common stability args for server environments.
        # ──────────────────────────────────────────────────────────────────────
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
            # ── PROXY CONFIGURATION ──────────────────────────────────────────
            # If you need to route traffic through a proxy to avoid IP bans,
            # uncomment and fill in the line below:
            # "--proxy-server=http://USER:PASS@PROXY_HOST:PORT",
            # ────────────────────────────────────────────────────────────────
        ]

        # ── PATCH: excludeSwitches / useAutomationExtension ──────────────────
        # Playwright does not expose CDP-level prefs directly at launch, but
        # `ignore_default_args` removes Playwright's own `--enable-automation`
        # flag. Combined with AutomationControlled disable above, this removes
        # the banner and the navigator.webdriver=true default.
        # ──────────────────────────────────────────────────────────────────────
        ignore_automation_args = [
            "--enable-automation",
            "--no-sandbox",
        ]

        # Try launching with Microsoft Edge channel first, fallback to default Playwright Chromium
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=headless,
                args=stealth_args,
                ignore_default_args=ignore_automation_args,
                user_agent=selected_ua,
                viewport={"width": 1920, "height": 1080},
                screen={"width": 1920, "height": 1080},
                ignore_https_errors=True
            )
            print("[+] Launched persistent context using Microsoft Edge channel.")
        except Exception as e:
            if "already in use" in str(e).lower() or "existing browser session" in str(e).lower():
                print(f"[!] Warning: The Edge profile at '{user_data_dir}' is already in use by a running Edge browser.")
                fallback_dir = os.path.join(os.getcwd(), "edge_profile_fallback")
                print(f"[!] Falling back to a separate user data directory: '{fallback_dir}'...")
                try:
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=fallback_dir,
                        channel="msedge",
                        headless=headless,
                        args=stealth_args,
                        ignore_default_args=ignore_automation_args,
                        user_agent=selected_ua,
                        viewport={"width": 1920, "height": 1080},
                        screen={"width": 1920, "height": 1080},
                        ignore_https_errors=True
                    )
                    print("[+] Launched persistent context using Microsoft Edge channel with fallback profile.")
                except Exception as fallback_e:
                    print(f"[*] Fallback with Edge channel failed ({fallback_e}). Launching default Chromium persistent context...")
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=fallback_dir,
                        headless=headless,
                        args=stealth_args,
                        ignore_default_args=ignore_automation_args,
                        user_agent=selected_ua,
                        viewport={"width": 1920, "height": 1080},
                        screen={"width": 1920, "height": 1080},
                        ignore_https_errors=True
                    )
            else:
                print(f"[*] Fallback: Could not launch with Microsoft Edge channel ({e}). Launching default Chromium persistent context...")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    args=stealth_args,
                    ignore_default_args=ignore_automation_args,
                    user_agent=selected_ua,
                    viewport={"width": 1920, "height": 1080},
                    screen={"width": 1920, "height": 1080},
                    ignore_https_errors=True
                )
            
        page = context.pages[0] if context.pages else await context.new_page()

        
        captcha_failed = False
        alert_triggered = False
        alert_msg = ""

        # Set up dialog listener to handle invalid captcha alerts or server errors
        async def on_dialog(dialog):
            nonlocal captcha_failed, alert_triggered, alert_msg
            alert_triggered = True
            alert_msg = dialog.message
            print(f"[!] Alert popup detected: {alert_msg}")
            
            # Check if this alert is captcha related
            if "captcha" in alert_msg.lower() or "invalid" in alert_msg.lower() or "wrong" in alert_msg.lower() or "incorrect" in alert_msg.lower() or "mismatch" in alert_msg.lower() or "does not match" in alert_msg.lower():
                captcha_failed = True
            await dialog.dismiss()

        page.on("dialog", on_dialog)

        results_rows = []
        found_records = False

        idx_no_symbols = len(initial_queries)
        idx_no_pvt = idx_no_symbols + len(no_symbol_queries)
        idx_both = idx_no_pvt + len(no_pvt_ltd_queries)

        for q_idx, current_name in enumerate(queries):
            if len(queries) > 1:
                if q_idx == idx_no_symbols:
                    print("\n[*] Initial search queries returned no matches. Trying fallback: symbols removed...")
                elif q_idx == idx_no_pvt:
                    print("\n[*] No-symbol fallback queries returned no matches. Trying fallback: PVT LTD / CO removed...")
                elif q_idx == idx_both:
                    print("\n[*] No-suffix fallback queries returned no matches. Trying fallback: both symbols and PVT LTD / CO removed...")
                print(f"\n[*] Trying search query variant {q_idx+1}/{len(queries)}: '{current_name}'")

            print(f"[*] Navigating to EPFO Portal: {DEFAULT_URL}")
            await page.goto(DEFAULT_URL, wait_until="load", timeout=60000)
            
            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                print(f"\n--- Scraping Attempt {attempt}/{max_attempts} ---")
                
                print(f"[*] Navigating to EPFO Portal to load fresh captcha (Attempt {attempt}/{max_attempts})...")
                await page.goto(DEFAULT_URL, wait_until="load", timeout=60000)
                await human_delay(1.5, 3.0)
                
                # Fill establishment name
                print(f"[*] Entering establishment name: '{current_name}'")
                await human_type(page, "#estName", current_name)
                
                # Locate captcha image and take a screenshot of the image element
                print("[*] Locating captcha image...")
                captcha_img = page.locator("#capImg")
                await captcha_img.wait_for(state="visible", timeout=15000)
                
                try:
                    print(f"[*] Waiting for captcha image to load...")
                    await page.wait_for_function(
                        "document.querySelector('#capImg') && document.querySelector('#capImg').complete && document.querySelector('#capImg').naturalWidth > 0",
                        timeout=8000
                    )
                except Exception as e:
                    print(f"[!] Warning: Captcha load wait timed out: {e}")
                
                # Give it a tiny bit of time to fully render the image
                await page.wait_for_timeout(1000)
                
                # Take element screenshot
                image_bytes = await captcha_img.screenshot()
                
                # Solve using Gemini
                try:
                    print("[*] Requesting captcha solution from Gemini API...")
                    captcha_solution = solve_captcha(image_bytes, api_key)
                    print(f"[+] Gemini solved captcha: '{captcha_solution}'")
                except Exception as e:
                    print(f"[!] Gemini solver failed: {e}. Retrying with a new captcha image...")
                    # Click reset button instead of reload page to get a new captcha
                    reset_btn = page.locator("input[value='Reset']")
                    if await reset_btn.count() > 0 and await reset_btn.is_visible():
                        try:
                            print("[*] Clicking Reset button to get new captcha...")
                            await human_click(page, reset_btn)
                            await page.wait_for_timeout(2000)
                        except Exception:
                            await page.reload()
                            await page.wait_for_timeout(2000)
                    else:
                        await page.reload()
                        await page.wait_for_timeout(2000)
                    continue
                    
                # Fill solved captcha
                await human_type(page, "#captcha", captcha_solution)
                
                # Reset states before search click
                captcha_failed = False
                alert_triggered = False
                alert_msg = ""
                
                # Click search
                print("[*] Clicking Search...")
                # We click the button and wait for responses
                await human_click(page, "#searchEmployer")
                
                # Wait for either alert to trigger or search results loading to finish
                # Data is fetched asynchronously via jQuery AJAX
                # Wait a few seconds to let AJAX run or dialog to trigger
                await page.wait_for_timeout(4000)
                
                if captcha_failed or (alert_triggered and "captcha" in alert_msg.lower()):
                    print("[!] Captcha verification failed. Trying again...")
                    # The page automatically updates the captcha image on failure, we can just proceed to next loop
                    continue
                
                if alert_triggered:
                    print(f"[!] Search halted due to unexpected alert: {alert_msg}")
                    # Check if it was an error or notification
                    # If it's a validation error, let's break or retry
                    # If we get "Something get wrong", let's reload/retry
                    if "wrong" in alert_msg.lower() or "error" in alert_msg.lower():
                        reset_btn = page.locator("input[value='Reset']")
                        if await reset_btn.count() > 0 and await reset_btn.is_visible():
                            try:
                                print("[*] Clicking Reset button due to error...")
                                await human_click(page, reset_btn)
                                await page.wait_for_timeout(2000)
                            except Exception:
                                await page.reload()
                                await page.wait_for_timeout(2000)
                        else:
                            await page.reload()
                            await page.wait_for_timeout(2000)
                        continue
                    break
                    
                # Check tablecontainer for results
                container_locator = page.locator("#tablecontainer")
                container_text = await container_locator.inner_text()
                
                if "no records" in container_text.lower():
                    print(f"[-] Search completed. No records found for query: '{current_name}'")
                    break
                
                # If the search was successful, the table should be visible
                table_locator = page.locator("#tablecontainer table")
                if await table_locator.count() > 0:
                    print("[+] Search successful! Extracting results...")
                    found_records = True
                    
                    # Scroll naturally
                    await human_scroll(page)
                    
                    # We will handle pagination if DataTables is used
                    # Let's extract pages of data
                    while True:
                        headers, page_rows = await extract_table_data(page)
                        results_rows.extend(page_rows)
                        print(f"[+] Extracted {len(page_rows)} rows from current page. Total: {len(results_rows)}")
                        
                        # Look for Next button in pagination
                        # jQuery DataTable format: <li class="paginate_button next" id="example_next"><a ...>Next</a></li>
                        # If it has class "disabled", it means we're on the last page.
                        next_btn = page.locator("li.paginate_button.next, a.paginate_button.next, #example_next, [id$='_next']").first
                        if await next_btn.count() > 0:
                            class_attr = await next_btn.get_attribute("class") or ""
                            aria_disabled = await next_btn.get_attribute("aria-disabled") or ""
                            if "disabled" in class_attr.lower() or aria_disabled.lower() == "true":
                                print("[*] Reached the last page of results.")
                                break
                            
                            if await next_btn.evaluate("el => el.tagName.toLowerCase()") == "a":
                                next_link = next_btn
                            else:
                                next_link = next_btn.locator("a").first
                                if await next_link.count() == 0:
                                    print("[*] No link inside Next button, assuming last page.")
                                    break
                            
                            # Check visibility
                            if not await next_link.is_visible():
                                print("[*] Next link is not visible, assuming last page.")
                                break
                            
                            try:
                                print("[*] Clicking Next page button...")
                                await human_click(page, next_link)
                                # Wait for table to update
                                await page.wait_for_timeout(2000)
                            except Exception as e:
                                print(f"[*] Next page click failed or timed out: {e}. Assuming last page.")
                                break
                        else:
                            break
                    break
                else:
                    print("[?] Results table not found yet. Content inside container:")
                    print(container_text[:200])
                    print("[*] Retrying...")
                    
            if found_records:
                break
                
        await context.close()

        return results_rows

def main():
    parser = argparse.ArgumentParser(description="EPFO Establishment Search Scraper")
    parser.add_argument("-n", "--name", required=True, help="Name of the establishment to search for")
    parser.add_argument("-k", "--key", default=DEFAULT_API_KEY, help="Gemini API Key")
    parser.add_argument("-o", "--output", default="results.json", help="Path to output JSON file")
    parser.add_argument("--no-headless", action="store_true", help="Run browser in non-headless mode (visible UI)")
    
    args = parser.parse_args()
    
    establishment_name = args.name
    api_key = args.key
    headless = not args.no_headless
    
    print(f"[*] Starting EPFO scraper for: '{establishment_name}'")
    
    # Run the async scraper
    results = asyncio.run(run_scraper(establishment_name, api_key, headless))
    
    if results is not None and len(results) > 0:
        print(f"\n[+] Successfully scraped {len(results)} establishments:")
        print(json.dumps(results[:5], indent=2))
        if len(results) > 5:
            print(f"... and {len(results) - 5} more entries.")
            
        # Write to JSON file
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"[+] Results saved to: {args.output}")
    else:
        print("\n[-] No results found or scraper failed to extract data.")

if __name__ == "__main__":
    main()
