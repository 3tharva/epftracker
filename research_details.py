import asyncio
import io
import re
import os
import base64
import requests
from PIL import Image
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY", "")
URL = "https://unifiedportal-emp.epfindia.gov.in/publicPortal/no-auth/misReport/home/loadEstSearchHome"


def solve_captcha(image_bytes):
    if not API_KEY:
        print("[!] No OpenRouter API key provided.")
        return ""
    
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {API_KEY}",
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
                                "text": "Identify the characters in this CAPTCHA image. Respond with ONLY the alphanumeric characters, nothing else."
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
                if solution:
                    return solution
            except Exception as e:
                print(f"[!] OpenRouter ({model}) failed: {e}")
                
    except Exception as outer_e:
        print(f"[!] OpenRouter request setup failed: {outer_e}")

    return ""

async def main():
    async with async_playwright() as p:
        import platform
        if platform.system() == "Windows":
            user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")
        else:
            user_data_dir = os.path.expanduser("~/.config/microsoft-edge")
        print(f"[*] Launching browser in persistent context using system Edge profile: '{user_data_dir}'...")
        selected_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

        
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--no-sandbox"],
                user_agent=selected_ua,
                viewport={"width": 1280, "height": 1024},
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
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_default_args=["--no-sandbox"],
                        user_agent=selected_ua,
                        viewport={"width": 1280, "height": 1024},
                        ignore_https_errors=True
                    )
                    print("[+] Launched persistent context using Microsoft Edge channel with fallback profile.")
                except Exception as fallback_e:
                    print(f"[*] Fallback with Edge channel failed ({fallback_e}). Launching default Chromium persistent context...")
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=fallback_dir,
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_default_args=["--no-sandbox"],
                        user_agent=selected_ua,
                        viewport={"width": 1280, "height": 1024},
                        ignore_https_errors=True
                    )
            else:
                print(f"[*] Fallback: Could not launch with Microsoft Edge channel ({e}). Launching default Chromium persistent context...")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--no-sandbox"],
                    user_agent=selected_ua,
                    viewport={"width": 1280, "height": 1024},
                    ignore_https_errors=True
                )



        page = await context.new_page()
        
        captcha_failed = False
        async def on_dialog(dialog):
            nonlocal captcha_failed
            print(f"[!] Alert: {dialog.message}")
            captcha_failed = True
            await dialog.dismiss()
        page.on("dialog", on_dialog)

        print("[*] Going to EPFO...")
        # Use commit for faster, more reliable load on slow government servers
        await page.goto(URL, wait_until="commit", timeout=60000)
        
        await page.fill("#estName", "VGR INFRA")
        
        captcha_img = page.locator("#capImg")
        await captcha_img.wait_for(state="visible")
        await page.wait_for_timeout(1000)
        img_bytes = await captcha_img.screenshot()
        
        code = solve_captcha(img_bytes)
        print(f"[+] Captcha: {code}")
        await page.fill("#captcha", code)
        
        await page.click("#searchEmployer")
        await page.wait_for_timeout(4000)
        
        if captcha_failed:
            print("[-] Captcha failed.")
            await context.close()
            return

            
        # Click the link under Action column.
        # Let's locate the table rows and find the link/button
        table_rows = page.locator("#tablecontainer table tbody tr")
        row_count = await table_rows.count()
        print(f"[+] Found {row_count} rows in table")
        if row_count > 0:
            # Let's look for "View Details" link in the first row
            first_row = table_rows.nth(0)
            # Find all links/buttons in the first row
            links = first_row.locator("a, button, input[type='button']")
            link_count = await links.count()
            print(f"[+] Found {link_count} links/buttons in first row")
            for i in range(link_count):
                text = await links.nth(i).inner_text()
                val = await links.nth(i).get_attribute("value") or ""
                onclick = await links.nth(i).get_attribute("onclick") or ""
                print(f"Link {i}: text='{text}', value='{val}', onclick='{onclick}'")
            
            # Click the link
            print("[*] Clicking first action link...")
            # Usually the action cell has an 'a' tag or button
            # Let's target the link with text containing "View Details"
            view_details_link = first_row.locator("a:has-text('View Details')").first
            if await view_details_link.count() > 0:
                await view_details_link.click()
            else:
                await links.first.click()
                
            # Wait for details to load
            print("[*] Waiting for details page/section to load...")
            await page.wait_for_timeout(6000)
            
            # Let's dump the page HTML to see what's loaded
            html = await page.content()
            with open("details_source.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("[+] Details HTML saved to details_source.html")
            
            # Let's also check if there is an excel download button in the page content
            excel_elements = page.locator("a:has-text('Excel'), button:has-text('Excel'), input[value='Excel'], :has-text('excel')")
            print(f"[+] Found {await excel_elements.count()} elements containing 'Excel'")
            
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
