# Direct API Purchase Bot

Runs sequential local Juice Shop purchases using HTTP requests only. No browser,
mouse movements or Playwright. Python 3.10+ standard library only; no pip install.

The bot creates actual orders inside your local test instance and reduces its
inventory. It does not charge a real payment card. It calls Juice Shop's order
endpoint directly with an empty JSON body, which the inspected standard server
accepts. It does not reproduce address, delivery or payment-screen interactions.
If your middleware requires those fields or an additional challenge, a rejection
is a result to record, not a reason to bypass that control.

## Windows instructions

1. Keep Docker Desktop and the `juice-shop` container running.
2. Extract this ZIP into your existing `JuiceShop_Checkout_Abandonment_Bot` folder,
   alongside your existing `.venv`. Do not replace the abandonment script.
3. Open normal PowerShell in that folder.
4. Test one purchase with two products:

```powershell
.\.venv\Scripts\python.exe direct_api_purchase_bot.py --runs 1 --items 2 --delay 5
```

5. Run the repeated test:

```powershell
.\.venv\Scripts\python.exe direct_api_purchase_bot.py --runs 10 --items 2 --delay 5
```

Alternatively use `python direct_api_purchase_bot.py ...` if Python is on PATH.
For a different local port add `--base-url http://127.0.0.1:3001`.

## Product selection

By default the bot chooses distinct products with enough stock for the whole
run, prioritising high-stock products. Each order buys one unit of each selected
product. `--items 2` therefore means two distinct products, one unit each.
The bot checks published per-order quantities and does not modify stock directly.

To target specific product IDs:

```powershell
.\.venv\Scripts\python.exe direct_api_purchase_bot.py --runs 2 --product-ids 20,33 --delay 5
```

These IDs are examples; the bot checks whether each exists and has enough stock.
When `--product-ids` is supplied, the number of IDs determines the items per order.
Reduce the number of runs if stock is insufficient. Avoid running other stock
changing tests at the same time when comparing before and after quantities.
Only local HTTP targets `127.0.0.1` and `localhost` are accepted. Redirects are
not followed. System HTTP proxies are disabled for this local client.

## What happens in each run

- Read the catalogue and inventory and select products.
- Create one new test account per invocation, saving its email and password.
- Log in and obtain that account's basket ID.
- For each attempt: check the basket is empty; read stock; add the selected
  products; verify the basket; submit one checkout request; verify the order's
  exact product IDs and quantities; verify the basket cleared; read stock again.
- Pause between attempts. No simultaneous checkout replay is performed.

## Results and login credentials

Every invocation creates a new subfolder under `api_purchase_results`:

| File | Contents |
| --- | --- |
| `credentials.json` | Test email, password and account-created flag. Use these to log in and inspect order history. |
| `attempts.csv` | One row per purchase attempt, including order ID, result, stock snapshots and timings. |
| `requests.csv` | Method, endpoint, HTTP status, elapsed time and retry index for every API request, including setup and verification. No auth token or password. |
| `summary.json` | Confirmed/verified order totals, units purchased and timing summaries. |
| `orders/*.json` | Order records returned by Juice Shop, checked against the requested products. |
| `checkout_state.json` | Latest checkout state, written before submission and updated on confirmation or an uncertain outcome. |

Successful output: `[1/3] 2 items -> order <ID> verified`.
Successful CSV result: `ORDER_VERIFIED`.

`ORDER_CONFIRMED_VERIFICATION_FAILED` means an order confirmation was received,
but the later verification did not complete. `ORDER_OUTCOME_UNKNOWN` means the
checkout phase did not produce a usable confirmation. The server might still
have changed inventory or created an order. Inspect the account's order history
before repeating. The bot stops on any error; write requests are never retried.
Read-only GET requests may retry network failures twice; HTTP error statuses,
including 429, are not retried. Request logs distinguish individual GET retries.

`checkout_elapsed_ms` measures the checkout HTTP round trip. `elapsed_seconds`
measures the complete attempt including checks and verification. Neither timing
includes the configured inter-attempt delay. Script duration in `summary.json`
includes setup and those delays. Compare like-for-like timings in your report.

The final order tracking API can return an ID-only placeholder for an unknown
order. The bot requires a matching products list, not just an order ID.

## Coursework use

Compare this bot with the browser purchase bot and legitimate users. Record
confirmed orders, detection decisions, request volume and purchase times before
and after your middleware. Missing mouse telemetry alone is not proof of abuse.
To evaluate middleware on another loopback port, point `--base-url` at that port
and ensure the middleware receives every tested API request. Direct requests to
the original Juice Shop port would otherwise measure the unprotected backend.
This bot tests direct order submission, not inventory reservation or expiration.

## Verification and sources

The script is syntax-checked and includes offline regression tests for the HTTP
client, product selection and order verification. It has not been executed
against your laptop's instance. Run `python -m unittest -v test_direct_api_purchase_bot`
for the offline tests; these do not create orders or use a network connection.

API behaviour was checked against the official source:
- https://github.com/juice-shop/juice-shop/blob/master/server.ts
- https://github.com/juice-shop/juice-shop/blob/master/routes/basketItems.ts
- https://github.com/juice-shop/juice-shop/blob/master/routes/order.ts
- https://github.com/juice-shop/juice-shop/blob/master/routes/trackOrder.ts
