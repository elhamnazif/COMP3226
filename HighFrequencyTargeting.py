import asyncio
from playwright.async_api import async_playwright
from playwright.async_api import expect

import pandas as pd
import re
import time as t

async def main():
    pageTimes = []
    totalStart = t.perf_counter()

    async with async_playwright() as p:
        #Page traversal & loading
        browser = await p['chromium'].launch()
        page = await browser.new_page()

        await page.goto('127.0.0.1:3000', wait_until='networkidle')

        #Clear pop-ups
        await page.get_by_role('button', name="Close Welcome Banner").click()
        await page.get_by_role('button', name="dismiss cookie message").click()

        ##Setup

        nextButton = page.get_by_role('button', name="Next page")
        pageRange = page.locator('.mat-mdc-paginator-range-label').first
        curRange = await pageRange.inner_text()
        basket = page.locator('.fa-layers-counter').first
        basketTotal = await basket.inner_text()

        basketButton = page.get_by_role('button', name="Show the shopping cart")

        ##Adding to cart

        canNext = True
        pNames = [] #Final list that will hold all products
        nPages = 0 #For logging only

        while(canNext):
            pageStart = t.perf_counter()

            #Go to next page
            if(nPages > 0):
                await nextButton.click()
                await expect(pageRange).not_to_have_text(curRange, use_inner_text=True) #Check that we are on the next page

            products = await page.locator('app-product').all() #All product panes have the tag <app-product> so scrape by that

            #For each scraped <app-product>
            for item in products:
                itemStart = t.perf_counter()
                res = {} #Dict to store relevant data
                ordered = 0

                #Extract item name
                #Default: "Missing"
                nameProb = item.locator('.name')
                res['name'] =  (
                    await nameProb.inner_text() if nameProb else "Missing"
                )

                #Extract price
                #Default: -1
                priceProb = item.locator('.price')
                res['price'] = (
                    await priceProb.inner_text() if priceProb else -1
                )

                #Format later as doing any operation in await causes concurrency issues
                try:
                    res['price'] = float(res['price'][:-1])
                except ValueError as e:
                    res['price'] = -1

                #Extract limit (if it exists)
                #Default: -1 IF does not exist
                #          0 IF sold out
                isLimitProb = item.locator('.ribbon')
                ribbonCount = await isLimitProb.count()
                #Need to check if ribbon exists
                if(ribbonCount > 0):
                    ribbonText = await isLimitProb.inner_text()

                    #Typically written as "Only <n> remaining" or "Sold Out"
                    ribbonText = ribbonText.split()

                    #So if there is 3 or more words, must be "Only <n> remaining" so take the 2nd word
                    if len(ribbonText) > 2:
                        limit = int(ribbonText[1])
                    else:
                        limit = 0 #Otherwise is "Sold Out" so set 0
                else:
                    #Ribbon does not exist at all
                    limit = -1
                res['limit'] = limit

                if(limit > 0):
                    print(f"Buying {res['name']} with limit {res['limit']}")

                #Add to cart while permuting
                while(limit > 0):
                    #Add to cart
                    await item.get_by_role('button', name="Add to Basket").click()

                    #Check if have hit limit
                    banner = page.locator('.mdc-snackbar__label').last
                    await expect(banner).to_be_attached() #Ensure the banner exists (it should always pass)
                    bannerTxt = await banner.inner_text()
                    limitTxt = re.search(r"up to \d items",bannerTxt) #Looks for specific format once limit is reached
                    if(limitTxt):
                        print("Hit limit")
                        await banner.wait_for(state='detached')
                        break

                    #Validation check that item was added
                    await expect(basket).not_to_have_text(basketTotal, use_inner_text=True)
                    basketTotal = await basket.inner_text()
                    
                    ordered = ordered + 1
                    limit = limit - 1

                    print(f'Bought {ordered}')

                res['time'] = t.perf_counter() - itemStart
                res['ordered'] = ordered
                res['pageNum'] = nPages
    
                #Add current item to dataframe
                pNames.append(res)

            #Check that there exists a next page
            canNext = not await nextButton.is_disabled()
            nPages = nPages + 1

            pageTotal = t.perf_counter() - pageStart

            print(f"Done page {nPages} after {pageTotal} s")

            pageTimes.append(pageTotal)            

        #Convert to dataframe
        df = pd.DataFrame(pNames)
        print(df)

        #"Make" purchase
        await basketButton.click()

        checkoutBtn = page.locator('#checkoutButton').first

        if(checkoutBtn and len(df) > 0):
            await expect(checkoutBtn).not_to_be_disabled()

            await page.screenshot(path='proof.png')

            await checkoutBtn.click()

            print("Done!")
        else:
            await page.screenshot(path='failed.png')

            print('Failed final checkout!')

        await browser.close()

    ##Do smtg for statistics or smtg
    totalEnd = t.perf_counter()
    totalTime = totalEnd - totalStart

    print(f"Took {totalTime} to order {df['ordered'].sum()} items")

if __name__ == "__main__":
    asyncio.run(main())