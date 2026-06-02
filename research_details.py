import asyncio
import io
import re
from PIL import Image
from playwright.async_api import async_playwright
import google.generativeai as genai

API_KEY = "AQ.Ab8RN6IDVNTxAAb1aRQZReNPVvmoB6t4Jw9sdJwuVpxzHK5yng"
URL = "https://unifiedportal-emp.epfindia.gov.in/publicPortal/no-auth/misReport/home/loadEstSearchHome"

def solve_captcha(image_bytes):
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    image = Image.open(io.BytesIO(image_bytes))
    prompt = "Solve this captcha image. Output ONLY the alphanumeric captcha code."
    response = model.generate_content([prompt, image])
    return re.sub(r'[^a-zA-Z0-9]', '', response.text.strip())

async def main():
    async with async_playwright() as p:
        print("[*] Launching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1024}
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
            await browser.close()
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
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
