# Local Juice Shop checkout abandonment bot

The Python Playwright script creates a dedicated test account, opens a visible
Chromium browser, logs in, adds three products with browser clicks, opens the
basket, clicks Checkout, waits at address selection, and returns to the catalogue.
It repeats five times by default. It supplies no address, payment or order.
It blocks Juice Shop's final `/rest/basket/:id/checkout` order endpoint.

## Windows setup

1. Keep Docker Desktop and your local Juice Shop container running.
2. Extract this ZIP into a folder, for example `C:\JuiceShopBot`.
3. Open normal PowerShell in that folder (administrator access is unnecessary).
4. Run these commands individually:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe checkout_abandonment_bot.py
```

If `python` is unavailable but `py` works, use `py -3 -m venv .venv` for the first
command. Otherwise install Python 3.10 or later first.

No virtual environment activation or PowerShell execution-policy change is needed.
The script downloads no products and makes no real purchases.

## Options

```powershell
.\.venv\Scripts\python.exe checkout_abandonment_bot.py --runs 10 --items 2 --delay 10
```

If Juice Shop uses port 3001:

```powershell
.\.venv\Scripts\python.exe checkout_abandonment_bot.py --base-url http://localhost:3001
```

Use `--headless` to hide Chromium. Press Ctrl+C to stop.
Only localhost and 127.0.0.1 HTTP targets are accepted.

## Results and interpretation

Each run writes `bot_results/attempts-TIMESTAMP.csv`. Rows include attempt number,
UTC time, test account, verified cart quantity, checkout URL, elapsed time and
result or error. A successful attempt reads `ABANDONED_AT_ADDRESS_SELECTION`.
It confirms the checkout page was entered, rather than an order being placed.
The script stops on an error and records the failing attempt when inside the loop.
Setup failures are printed before any attempt row exists.

The bot clears its own test basket before each attempt and leaves the final cart
abandoned. It reuses one account per invocation; it does not create a new cart ID
for each iteration. Each invocation creates one new account with a generated
password, not stored on disk. This avoids touching personal accounts.

This is early checkout abandonment, before entering delivery or payment details.
It does not demonstrate inventory reservation or stock exhaustion: assess those
separately rather than claiming that adding to a basket reserves inventory.
The CSV is client-side evidence; corroborate with server logs for coursework.
The browser performs shopping actions; setup and between-attempt cart cleanup
use the application's API, so exclude those requests from shopping-behaviour
measurements if needed. This bot does not simulate human mouse movements.

## Compatibility and validation

Selectors and API paths were checked against official Juice Shop source. The
Python file was syntax-checked. It has not been run against your laptop's
instance; its selectors may need adjustment if your image differs.
Keep the UI in English. The script uses the normal email/password login and
the `#checkoutButton` control, then verifies `/#/address/select` is rendered.

Official source references:
- https://github.com/juice-shop/juice-shop/blob/master/frontend/src/app/basket/basket.component.ts
- https://github.com/juice-shop/juice-shop/blob/master/frontend/src/app/basket/basket.component.html
- https://github.com/juice-shop/juice-shop/blob/master/frontend/src/app/Services/basket.service.ts
- https://github.com/juice-shop/juice-shop/blob/master/frontend/src/app/product/product.component.html
- https://github.com/juice-shop/juice-shop/blob/master/frontend/src/app/login/login.component.html
