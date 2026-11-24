"""Repeat Add to Basket -> Checkout -> leave address selection on local Juice Shop.

Requires: pip install playwright; python -m playwright install chromium
Run: python checkout_abandonment_bot.py
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError("Use http://localhost:PORT or http://127.0.0.1:PORT")
    try:
        parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value.rstrip("/")


def checked_json(response, operation):
    if not response.ok:
        raise RuntimeError(f"{operation}: HTTP {response.status}. {response.text()[:200]}")
    return response.json()


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    email = f"abandonment-{stamp.lower()}@example.com"
    password = "Test-" + secrets.token_hex(12) + "!"
    log_path = output / f"attempts-{stamp}.csv"
    fields = ["utc", "attempt", "test_account", "cart_quantity", "checkout_url", "result", "elapsed_seconds", "detail"]
    print("Checkout Abandonment Bot v1.4 (banner preferences and basket read retries)")
    print(f"Target: {args.base_url}\nNew test account: {email}\nCSV: {log_path.resolve()}")
    print("Stop at any time with Ctrl+C. No order will be submitted.")

    with sync_playwright() as p, log_path.open("w", newline="", encoding="utf-8") as logfile:
        writer = csv.DictWriter(logfile, fieldnames=fields)
        writer.writeheader()
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(locale="en-US")
        context.set_default_timeout(20000)
        # Seed the same preferences the welcome and cookie banners save on
        # dismissal. Set them before Angular starts so neither banner opens.
        # No locator handlers or banner clicks are needed during login.
        context.add_cookies([
            {"name": name, "value": "dismiss", "url": args.base_url + "/"}
            for name in ("welcomebanner_status", "cookieconsent_status")
        ])
        page = context.new_page()
        blocked = []

        def guard(route):
            request = route.request
            target = urlsplit(request.url)
            # Prevent external requests and any final Juice Shop order submission.
            if target.scheme in {"http", "https"} and target.netloc != urlsplit(args.base_url).netloc:
                route.abort()
            elif re.search(r"/rest/basket/[^/]+/checkout/?$", target.path):
                blocked.append(request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard)
        try:
            # Use a fresh account so cleanup only affects this bot's own cart.
            checked_json(context.request.post(args.base_url + "/api/Users", data={
                "email": email, "password": password, "passwordRepeat": password,
                "securityQuestion": {"id": 1}, "securityAnswer": "local-test"
            }, timeout=20000, max_redirects=0), "Create test account")
            page.goto(args.base_url + "/#/login", wait_until="domcontentloaded")
            page.locator("#email").fill(email)
            page.locator("#password").fill(password)
            with page.expect_response(lambda r: urlsplit(r.url).path == "/rest/user/login"
                                      and r.request.method == "POST") as login:
                page.locator("#loginButton").click()
            auth = checked_json(login.value, "Login")["authentication"]
            basket_id = auth["bid"]
            headers = {"Authorization": "Bearer " + auth["token"]}
            page.wait_for_function("() => !!localStorage.getItem('token')")

            def cart():
                # GET is read-only: retry a connection reset without replaying
                # account creation, basket writes, or any checkout action.
                return checked_json(context.request.get(
                    f"{args.base_url}/rest/basket/{basket_id}", headers=headers,
                    timeout=20000, max_redirects=0, max_retries=2), "Read cart")["data"]["Products"]

            for attempt in range(1, args.runs + 1):
                start = time.monotonic()
                row = dict.fromkeys(fields, "")
                row.update(utc=datetime.now(timezone.utc).isoformat(), attempt=attempt,
                           test_account=email, result="ERROR")
                try:
                    # Independent sessions: clear only our newly created account's basket.
                    for product in cart():
                        response = context.request.delete(
                            f"{args.base_url}/api/BasketItems/{product['BasketItem']['id']}",
                            headers=headers, max_redirects=0)
                        if not response.ok:
                            raise RuntimeError(f"Cart cleanup failed: HTTP {response.status}")
                    if cart():
                        raise RuntimeError("Cart was not empty after cleanup")

                    page.goto(args.base_url + "/#/search", wait_until="domcontentloaded")
                    buttons = page.get_by_role("button", name=re.compile(r"add to basket", re.I))
                    buttons.first.wait_for(state="visible")
                    added = 0
                    for index in range(buttons.count()):
                        button = buttons.nth(index)
                        if not button.is_enabled():
                            continue
                        with page.expect_response(lambda r: urlsplit(r.url).path.startswith("/api/BasketItems")
                                                  and r.request.method in {"POST", "PUT"}) as addition:
                            button.click()
                        if not addition.value.ok:
                            raise RuntimeError(f"Add to basket: HTTP {addition.value.status}")
                        added += 1
                        if added == args.items:
                            break
                    if added != args.items:
                        raise RuntimeError(f"Only {added} available products; requested {args.items}")
                    quantity = sum(int(x["BasketItem"]["quantity"]) for x in cart())
                    row["cart_quantity"] = quantity
                    if quantity != args.items:
                        raise RuntimeError(f"Expected {args.items} cart units, found {quantity}")

                    page.goto(args.base_url + "/#/basket", wait_until="domcontentloaded")
                    page.locator("#checkoutButton").click()
                    page.wait_for_url(re.compile(r"/#/address/select(?:\?.*)?$"))
                    page.locator("app-address-select").wait_for(state="visible")
                    row["checkout_url"] = page.url
                    if blocked:
                        raise RuntimeError("An order submission was blocked; stopping")
                    # Abandon at the first checkout step; no address or payment is supplied.
                    page.wait_for_timeout(args.dwell * 1000)
                    page.goto(args.base_url + "/#/search", wait_until="domcontentloaded")
                    row["result"] = "ABANDONED_AT_ADDRESS_SELECTION"
                    print(f"[{attempt}/{args.runs}] {quantity} items -> Checkout -> abandoned")
                except Exception as exc:
                    row["detail"] = str(exc)
                    raise
                finally:
                    row["elapsed_seconds"] = round(time.monotonic() - start, 3)
                    writer.writerow(row)
                    logfile.flush()
                if attempt < args.runs:
                    page.wait_for_timeout(args.delay * 1000)
        finally:
            browser.close()
    print("Finished. The final abandoned cart remains in the test account.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=local_url, default="http://127.0.0.1:3000")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--items", type=int, default=3)
    parser.add_argument("--delay", type=int, default=5, help="Seconds between attempts")
    parser.add_argument("--dwell", type=int, default=2, help="Seconds at address selection")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output", default="bot_results")
    args = parser.parse_args()
    if not 1 <= args.runs <= 100 or not 1 <= args.items <= 5:
        parser.error("Use 1-100 runs and 1-5 products per cart")
    if args.delay < 1 or args.dwell < 1:
        parser.error("Delay and dwell must each be at least 1 second")
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        parser.exit(1, f"\nBot stopped: {exc}\nCheck Juice Shop is running and inspect the CSV error detail.\n")


if __name__ == "__main__":
    main()
