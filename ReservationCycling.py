import asyncio
from playwright.async_api import async_playwright
from playwright.async_api import expect
import random as r
import string
import pandas as pd
from COMP3226.ParseQty import QuantityParser, ItemParser
import COMP3226.JuiceShopFunctions as js

import time as t

EMAIL_DOMAINS = ['gmail','yahoo','hotmail','mac']
NHOLDS = 10
ACC_LOG = "accounts.txt"

async def Hoard(limited):
    roundTimes = []
    totalSupBuy = limited['quantity'].sum()
    totalStart = t.perf_counter()

    async with async_playwright() as p:

        #Load website
        browser = await p['chromium'].launch()
        page = await browser.new_page()

        nRounds = 1 #Number of rounds / accounts made

        #Handles each account iteration, i.e. each new iteration has a new account
        try:
            while(len(limited) > 0):
                roundStart = t.perf_counter()
                print(f"On round {nRounds} with {len(limited)} rows left")
                limited, bought = await burnHold(limited,page)
                #clear 0 qtys left
                limited = limited[limited['quantity'] > 0]

                print(limited)

                nRounds = nRounds + 1

                roundTimes.append({"time":t.perf_counter() - roundStart,"bought":bought})
        except Exception as e:
            #Take a screenshot if anything fails
            await page.screenshot(path="fail.png")
            raise e

        print("Done!")

        await browser.close()

    totalEnd = t.perf_counter()
    totalTime = totalEnd - totalStart

    print(f"Took {totalTime}s to order {sum([i['bought'] for i in roundTimes])}/{totalSupBuy} items over {nRounds - 1}")
    print(roundTimes)

#toBuy: Pandas DataFrame with cols [id, name, limitPerUser, quantity]
#page: website page
async def burnHold(toBuy, page):

    ##Create new account

    await page.goto('127.0.0.1:3000/#/register', wait_until='networkidle')

    #Clear pop-ups (if they exist)
    if((await page.get_by_role('button', name="Close Welcome Banner").count()) > 0):
        await page.get_by_role('button', name="Close Welcome Banner").click()
        await page.get_by_role('button', name="dismiss cookie message").click()

    #Create and save account details
    email = RandomString((1,10), {
        string.ascii_letters: 0.6,
        string.digits: 0.4,
    }) + "@" + r.choice(EMAIL_DOMAINS) + ".com"
    pwd = RandomString((5,10), {
        string.ascii_letters: 0.5,
        string.digits: 0.4,
        string.punctuation: 0.1
    })
    secQIndex = r.randint(0,13)
    secQAns = RandomString((5,7), None)

    accData = js.Account(email, pwd, secQIndex, secQAns)
    print("Making a new account")
    print(accData)
    accData.writeOut()

    ##Register new account

    await js.RegisterFromAcc(accData,page)

    ##Login

    await js.Login(accData.email, accData.pwd, page)

    ##Buy stuff

    #Setup

    basket = page.locator('.fa-layers-counter').first
    basketTotal = await basket.inner_text()

    async def HoldIfInLimit(item, page):
        nonlocal basket, basketTotal

        itm = await item.locator('.name').inner_text() #Item name
        
        if (itm in toBuy['name'].values): #IF we need to buy this...
            total = toBuy.loc[toBuy['name'] == itm, 'limitPerUser'].iloc[0]
            for i in range(total):
                await item.get_by_role('button', name="Add to Basket").click()

                #Validation check that item was added AND allow next purchase to go through
                await expect(basket).not_to_have_text(basketTotal, use_inner_text=True)
                basketTotal = await basket.inner_text()

    await js.TraverseItems(HoldIfInLimit,page)

    #Update totals

    await page.get_by_role('button', name="Show the shopping cart").click()

    await expect(page.locator('.cell-initial-font').first).to_be_visible()

    cells = await page.locator('.cell-initial-font').all()

    totalBought = 0

    for i in range(0,len(cells),3):
        name = await cells[i].inner_text()
        ttl = int(await cells[i+1].inner_text())
        totalBought = totalBought + ttl

        itmID = (toBuy['name'] == name).idxmax()

        toBuy.at[itmID, 'quantity'] = toBuy.at[itmID, 'quantity'] - ttl

    return toBuy, totalBought

    #Don't need to logout as going to /register and logging in again clears previous account


def RandomString(length, dist = {}):
    DEFAULT = {
        string.ascii_letters: 0.34,
        string.digits: 0.33,
        string.punctuation: 0.33
    }

    if(dist):
        if(sum(dist.values()) != 1):
            print(f"Invalid probability distribution given! (Sums to {sum(dist.values())}) Resorting to default")
    
            dist = DEFAULT
    else:
        dist = DEFAULT

    if(length[0] > 0 and length[1] > 0):
        x = length[0]
        y = length[1]

        length = (min(x,y),max(x,y))
    else:
        raise ValueError(f"Invalid lengths in ({length[0]},{length[1]}). Positive numbers only!")

    return RandomStringMain(length, dist)

def RandomStringMain(length, dist):
    chosenLen = r.randint(length[0], length[1])
    out = ""

    cumProb = 0
    for group in dist:
        dist[group] = dist[group] + cumProb
        cumProb = dist[group]

    while(chosenLen > 0):
        groupRand = r.random()

        for group in dist:
            if dist[group] >= groupRand:
                out = out + r.choice(group)
                chosenLen = chosenLen - 1
                break

    return out

if __name__ == "__main__":
    ##Setting up the dataframe

    qtyP = QuantityParser()
    itmP = ItemParser()

    #Reading from curls
    with open('curl_qtys.txt', 'r', encoding="utf-8") as f:
        qtyP.feed(f.read())

    with open('curl_items.txt', 'r', encoding="utf-8") as f:
        itmP.feed(f.read())

    if(len(qtyP.df) > 0):
        #Preprocess curls
        df = qtyP.df

        #Only keep limited items
        df = df[df['quantity'] > 0]
        df = df[df['quantity'] <= NHOLDS]

        #Add names to quantities
        df = pd.merge(df, itmP.df, on="id", how="inner")
        df = df[['id','quantity','limitPerUser','name']]

        #Format limit to be int instead of default float
        df['limitPerUser'] = df['limitPerUser'].astype(int)

        print("Holding out these items:")
        print(df)

        asyncio.run(Hoard(df))
    else:
        print("Could not read DataFrame to confirm purchases!")