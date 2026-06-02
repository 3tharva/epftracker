import asyncio
import argparse
import json
import os
import re
import io
from PIL import Image
from playwright.async_api import async_playwright
import google.generativeai as genai

# Default Gemini API key provided by the user
DEFAULT_API_KEY = "AQ.Ab8RN6IDVNTxAAb1aRQZReNPVvmoB6t4Jw9sdJwuVpxzHK5yng"
DEFAULT_URL = "https://unifiedportal-emp.epfindia.gov.in/publicPortal/no-auth/misReport/home/loadEstSearchHome"

def solve_captcha(image_bytes, api_key):
    """
    Sends the captcha image bytes to Gemini API to solve.
    """
    genai.configure(api_key=api_key)
    
    # We will use gemini-2.5-flash as it is available and extremely fast for image tasks
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    image = Image.open(io.BytesIO(image_bytes))
    
    prompt = (
        "Solve this captcha image. Output ONLY the alphanumeric captcha code exactly as shown, "
        "with absolutely no other text, spaces, or explanation."
    )
    
    response = model.generate_content([prompt, image])
    solution = response.text.strip()
    
    # Sanitize solution to keep only alphanumeric characters
    solution = re.sub(r'[^a-zA-Z0-9]', '', solution)
    return solution

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

async def run_scraper(establishment_name, api_key, headless=True):
    async with async_playwright() as p:
        print("[*] Launching browser...")
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        # Configure context with standard headers and resolution
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1024}
        )
        
        page = await context.new_page()
        
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
            if "captcha" in alert_msg.lower() or "invalid" in alert_msg.lower() or "wrong" in alert_msg.lower():
                captcha_failed = True
            await dialog.dismiss()

        page.on("dialog", on_dialog)

        print(f"[*] Navigating to EPFO Portal: {DEFAULT_URL}")
        await page.goto(DEFAULT_URL, wait_until="load", timeout=60000)
        
        max_attempts = 5
        results_headers = []
        results_rows = []
        
        for attempt in range(1, max_attempts + 1):
            print(f"\n--- Scraping Attempt {attempt}/{max_attempts} ---")
            
            # Fill establishment name
            print(f"[*] Entering establishment name: '{establishment_name}'")
            await page.fill("#estName", establishment_name)
            
            # Locate captcha image and take a screenshot of the image element
            print("[*] Locating captcha image...")
            captcha_img = page.locator("#capImg")
            await captcha_img.wait_for(state="visible", timeout=15000)
            
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
                # Click reset or reload page to get a new captcha
                await page.reload()
                await page.wait_for_timeout(2000)
                continue
                
            # Fill solved captcha
            await page.fill("#captcha", captcha_solution)
            
            # Reset states before search click
            captcha_failed = False
            alert_triggered = False
            alert_msg = ""
            
            # Click search
            print("[*] Clicking Search...")
            # We click the button and wait for responses
            await page.click("#searchEmployer")
            
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
                    await page.reload()
                    await page.wait_for_timeout(2000)
                    continue
                break
                
            # Check tablecontainer for results
            container_locator = page.locator("#tablecontainer")
            container_text = await container_locator.inner_text()
            
            if "no records" in container_text.lower():
                print("[-] Search completed. No records found for this establishment.")
                break
            
            # If the search was successful, the table should be visible
            table_locator = page.locator("#tablecontainer table")
            if await table_locator.count() > 0:
                print("[+] Search successful! Extracting results...")
                
                # We will handle pagination if DataTables is used
                # Let's extract pages of data
                while True:
                    headers, page_rows = await extract_table_data(page)
                    results_headers = headers
                    results_rows.extend(page_rows)
                    print(f"[+] Extracted {len(page_rows)} rows from current page. Total: {len(results_rows)}")
                    
                    # Look for Next button in pagination
                    # jQuery DataTable format: <li class="paginate_button next" id="example_next"><a ...>Next</a></li>
                    # If it has class "disabled", it means we're on the last page.
                    next_li = page.locator("li.paginate_button.next, #example_next").first
                    if await next_li.count() > 0:
                        class_attr = await next_li.get_attribute("class") or ""
                        if "disabled" in class_attr:
                            print("[*] Reached the last page of results.")
                            break
                        
                        next_link = next_li.locator("a")
                        if await next_link.count() == 0:
                            print("[*] No link inside Next button, assuming last page.")
                            break
                        
                        # Check visibility
                        if not await next_link.is_visible():
                            print("[*] Next link is not visible, assuming last page.")
                            break
                            
                        # Check aria-disabled
                        aria_disabled = await next_link.get_attribute("aria-disabled")
                        if aria_disabled == "true":
                            print("[*] Next link is aria-disabled, assuming last page.")
                            break
                            
                        try:
                            print("[*] Clicking Next page button...")
                            await next_link.click(timeout=3000)
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
                
        await browser.close()
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
