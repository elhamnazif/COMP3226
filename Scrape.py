
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p['chromium'].launch()
        page = await browser.new_page()

        ##Quantities
        await page.goto('127.0.0.1:3000/api/quantitys', wait_until='networkidle')
        content = await page.content()
        
        fname = f"curl_qtys.txt"

        with open(fname, 'w', encoding="utf-8") as f:
            f.write(content)

        print(f"Written quantities to {fname}")

        ##Item details
        await page.goto('127.0.0.1:3000/rest/products/search', wait_until='networkidle')
        content = await page.content()

        fname = f"curl_items.txt"

        with open(fname, 'w', encoding="utf-8") as f:
            f.write(content)

        print(f"Written items to {fname}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())