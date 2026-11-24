"""Direct API Purchase Bot v1.0 for local OWASP Juice Shop. Python 3.10+, no packages.

Creates local test orders and reduces local inventory. No browser or real payment.
Example: python direct_api_purchase_bot.py --runs 3 --items 2 --delay 5
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import re
import secrets
import statistics
import sys
import time
from urllib import error, parse, request

VERSION = "1.0"


def utc():
    return datetime.now(timezone.utc).isoformat()


def local_url(value):
    try:
        u = parse.urlsplit(value)
        port = u.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if (u.scheme != "http" or u.hostname not in {"127.0.0.1", "localhost"}
            or u.username or u.password or u.path not in {"", "/"}
            or u.query or u.fragment or (port is not None and port < 1)):
        raise argparse.ArgumentTypeError("Use http://127.0.0.1:PORT or http://localhost:PORT")
    return value.rstrip("/")


class BotError(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, base, log, timeout=20):
        self.base, self.log, self.timeout = base, log, timeout
        self.token = None
        self.attempt = 0
        # Loopback requests should not be routed through a system HTTP proxy.
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def call(self, method, path, data=None):
        if not path.startswith("/") or path.startswith("//"):
            raise BotError("Invalid API path")
        body = None if data is None else json.dumps(data).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": "LocalJuiceShopAPIBot/" + VERSION}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        # Only GET may be retried. Never automatically replay a POST.
        for retry in range(3 if method == "GET" else 1):
            start = time.perf_counter()
            status, outcome = "", "NETWORK_ERROR"
            try:
                req = request.Request(self.base + path, body, headers, method=method)
                with self.opener.open(req, timeout=self.timeout) as response:
                    status = response.status
                    raw = response.read()
                outcome = "HTTP_RESPONSE"
                if not 200 <= status < 300:
                    raise BotError(f"{method} {path}: HTTP {status}")
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise BotError(f"{method} {path}: response was not JSON") from exc
                return result, status, (time.perf_counter() - start) * 1000
            except error.HTTPError as exc:
                status, outcome = exc.code, "HTTP_ERROR"
                exc.close()
                raise BotError(f"{method} {path}: HTTP {status}") from None
            except (error.URLError, OSError, http.client.HTTPException) as exc:
                if method == "GET" and retry < 2:
                    outcome = "NETWORK_ERROR_RETRYING"
                else:
                    raise BotError(f"{method} {path}: {type(exc).__name__}; connection failed. "
                                   "Write requests are not retried.") from None
            finally:
                self.log({"utc": utc(), "attempt": self.attempt, "method": method,
                          "path": path, "status_code": status, "retry": retry,
                          "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                          "outcome": outcome})
            time.sleep(0.5 * (retry + 1))

    def get(self, path):
        return self.call("GET", path)[0]


def data_list(payload, name):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise BotError(name + ": unexpected API response")
    return data


def read_stock(api):
    return {int(r["ProductId"]): r for r in data_list(
        api.get("/api/Quantitys?limit=1000"), "Stock lookup")}


def choose_products(products, stock, args):
    available = {int(p["id"]): p for p in products}
    if args.product_ids:
        try:
            ids = [int(x.strip()) for x in args.product_ids.split(",")]
        except ValueError:
            raise BotError("--product-ids must be comma-separated positive integers") from None
        if len(set(ids)) != len(ids) or not 1 <= len(ids) <= 5:
            raise BotError("Choose 1-5 distinct product IDs")
    else:
        # Prefer well-stocked products for a repeatable baseline test.
        ids = sorted((pid for pid in available if pid in stock
                      and int(stock[pid]["quantity"]) >= args.runs
                      and (stock[pid].get("limitPerUser") is None
                           or int(stock[pid]["limitPerUser"]) >= 1)),
                     key=lambda pid: (-int(stock[pid]["quantity"]), pid))[:args.items]
        if len(ids) != args.items:
            raise BotError("Not enough stocked products for this test. Reduce --runs/--items.")
    for pid in ids:
        if pid not in available or pid not in stock:
            raise BotError(f"Product {pid} is not available in the catalogue")
        if int(stock[pid]["quantity"]) < args.runs:
            raise BotError(f"Product {pid} has {stock[pid]['quantity']} units; {args.runs} required. "
                           "Reduce --runs or select another product.")
        limit = stock[pid].get("limitPerUser")
        if limit is not None and int(limit) < 1:
            raise BotError(f"Product {pid} does not allow a quantity of one")
    return ids, available


def basket_quantities(api, basket_id):
    data = api.get(f"/rest/basket/{basket_id}").get("data")
    if not isinstance(data, dict) or not isinstance(data.get("Products"), list):
        raise BotError("Unexpected basket response")
    result = Counter()
    for p in data["Products"]:
        result[int(p["id"])] += int(p["BasketItem"]["quantity"])
    return result


def check_order(api, order_id, expected):
    records = data_list(api.get("/rest/track-order/" + parse.quote(order_id, safe="")), "Order lookup")
    for record in records:
        if record.get("orderId") == order_id and isinstance(record.get("products"), list):
            actual = Counter()
            for product in record["products"]:
                actual[int(product["id"])] += int(product["quantity"])
            if actual == expected:
                return record
    # Juice Shop can return an ID-only placeholder for a nonexistent order.
    raise BotError("Order lookup did not contain the expected products and quantities")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run(args):
    folder = Path(args.output) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                + "-" + secrets.token_hex(3))
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "orders").mkdir()
    credentials = {"base_url": args.base_url,
                   "email": f"api-buyer-{secrets.token_hex(8)}@example.com",
                   "password": "Test-" + secrets.token_hex(12) + "!",
                   "account_created": False}
    credentials_file = folder / "credentials.json"
    write_json(credentials_file, credentials)
    attempts = []
    confirmed_ids = []
    started = time.perf_counter()
    print(f"Direct API Purchase Bot v{VERSION}\nTarget: {args.base_url}")
    print("This run creates local test orders and reduces local stock.")
    print(f"Account: {credentials['email']}\nCredentials: {credentials_file.resolve()}")
    print(f"Results: {folder.resolve()}", flush=True)
    request_fields = ["utc", "attempt", "method", "path", "status_code", "retry", "elapsed_ms", "outcome"]
    fields = ["utc", "attempt", "test_account", "basket_id", "product_ids", "cart_quantity",
              "checkout_http_status", "checkout_elapsed_ms", "order_confirmation", "result",
              "basket_empty_after", "stock_before", "stock_after", "elapsed_seconds", "detail"]
    with (folder / "requests.csv").open("w", newline="", encoding="utf-8") as rf, \
            (folder / "attempts.csv").open("w", newline="", encoding="utf-8") as af:
        request_writer = csv.DictWriter(rf, fieldnames=request_fields)
        request_writer.writeheader()
        writer = csv.DictWriter(af, fieldnames=fields)
        writer.writeheader()

        def log_request(row):
            request_writer.writerow(row)
            rf.flush()

        api = API(args.base_url, log_request, args.timeout)
        try:
            # Check connectivity before creating an account.
            products = data_list(api.get("/rest/products/search?q="), "Catalogue")
            stock = read_stock(api)
            ids, catalogue = choose_products(products, stock, args)
            print("Products: " + ", ".join(f"{pid}: {catalogue[pid]['name']}" for pid in ids))
            api.call("POST", "/api/Users", {"email": credentials["email"],
                     "password": credentials["password"], "passwordRepeat": credentials["password"],
                     "securityQuestion": {"id": 1}, "securityAnswer": "local-test"})
            credentials["account_created"] = True
            write_json(credentials_file, credentials)
            auth = api.call("POST", "/rest/user/login", {"email": credentials["email"],
                            "password": credentials["password"]})[0]["authentication"]
            api.token = auth["token"]
            basket_id = int(auth["bid"])
            expected = Counter({pid: 1 for pid in ids})

            for attempt in range(1, args.runs + 1):
                api.attempt = attempt
                begin = time.perf_counter()
                row = dict.fromkeys(fields, "")
                row.update(utc=utc(), attempt=attempt, test_account=credentials["email"],
                           basket_id=basket_id, product_ids=",".join(map(str, ids)), result="ERROR")
                phase = "prepare"
                try:
                    if basket_quantities(api, basket_id):
                        raise BotError("Basket is not empty. Stop and inspect it before another order.")
                    before = read_stock(api)
                    row["stock_before"] = json.dumps({pid: int(before[pid]["quantity"]) for pid in ids})
                    if any(int(before[pid]["quantity"]) < 1 for pid in ids):
                        row["result"] = "OUT_OF_STOCK"
                        raise BotError("A selected product is now out of stock")
                    for pid in ids:
                        api.call("POST", "/api/BasketItems", {
                            "ProductId": pid, "BasketId": basket_id, "quantity": 1})
                    if basket_quantities(api, basket_id) != expected:
                        raise BotError("Basket contents do not match the requested products")
                    row["cart_quantity"] = sum(expected.values())
                    phase = "submit_order"
                    # Persist intent first. A lost response does not prove the order failed.
                    write_json(folder / "checkout_state.json", {
                        "utc": utc(), "attempt": attempt, "state": "SUBMITTING",
                        "basket_id": basket_id, "products": dict(expected)})
                    payload, status, ms = api.call("POST", f"/rest/basket/{basket_id}/checkout", {})
                    row["checkout_http_status"] = status
                    row["checkout_elapsed_ms"] = round(ms, 3)
                    order_id = payload.get("orderConfirmation")
                    if not isinstance(order_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", order_id):
                        raise BotError("Checkout did not return a valid order confirmation")
                    row["order_confirmation"] = order_id
                    confirmed_ids.append(order_id)
                    write_json(folder / "checkout_state.json", {
                        "utc": utc(), "attempt": attempt, "state": "CONFIRMED", "order_id": order_id})
                    phase = "verify_order"
                    record = check_order(api, order_id, expected)
                    write_json(folder / "orders" / (order_id + ".json"), record)
                    row["basket_empty_after"] = not bool(basket_quantities(api, basket_id))
                    if not row["basket_empty_after"]:
                        raise BotError("Order exists but basket was not cleared; stopping")
                    after = read_stock(api)
                    row["stock_after"] = json.dumps({pid: int(after[pid]["quantity"]) for pid in ids})
                    row["result"] = "ORDER_VERIFIED"
                    print(f"[{attempt}/{args.runs}] {len(ids)} items -> order {order_id} verified", flush=True)
                except BaseException as exc:
                    if phase == "submit_order":
                        row["result"] = "ORDER_OUTCOME_UNKNOWN"
                        write_json(folder / "checkout_state.json", {
                            "utc": utc(), "attempt": attempt, "state": "OUTCOME_UNKNOWN",
                            "note": "Do not replay automatically. Inspect this account's order history."})
                    elif phase == "verify_order":
                        row["result"] = "ORDER_CONFIRMED_VERIFICATION_FAILED"
                    row["detail"] = str(exc) or type(exc).__name__
                    raise
                finally:
                    row["elapsed_seconds"] = round(time.perf_counter() - begin, 3)
                    writer.writerow(row)
                    af.flush()
                    attempts.append(row)
                if attempt < args.runs:
                    time.sleep(args.delay)
        finally:
            verified = [r for r in attempts if r["result"] == "ORDER_VERIFIED"]
            summary = {"bot_version": VERSION, "base_url": args.base_url, "configured_runs": args.runs,
                       "attempts_recorded": len(attempts), "confirmed_orders": len(confirmed_ids),
                       "verified_orders": len(verified), "order_ids": confirmed_ids,
                       "verified_units": sum(int(r["cart_quantity"]) for r in verified),
                       "script_elapsed_seconds": round(time.perf_counter() - started, 3),
                       "mean_verified_attempt_seconds": round(statistics.mean(
                           r["elapsed_seconds"] for r in verified), 3) if verified else None,
                       "mean_checkout_response_ms": round(statistics.mean(
                           r["checkout_elapsed_ms"] for r in verified), 3) if verified else None}
            write_json(folder / "summary.json", summary)
            print(f"Verified orders: {len(verified)}/{args.runs}. Results: {folder.resolve()}", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=local_url, default="http://127.0.0.1:3000")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--items", type=int, default=2, help="Distinct products per order; one unit each")
    parser.add_argument("--product-ids", help="Comma-separated IDs; replaces automatic --items selection")
    parser.add_argument("--delay", type=float, default=5, help="Pause between sequential orders in seconds")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output", default="api_purchase_results")
    args = parser.parse_args()
    if not 1 <= args.runs <= 100 or not 1 <= args.items <= 5:
        parser.error("Use 1-100 runs and 1-5 items")
    if not 0 <= args.delay <= 3600 or not 1 <= args.timeout <= 120:
        parser.error("Use a delay of 0-3600 seconds and timeout of 1-120 seconds")
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nStopped. Inspect saved results and checkout_state.json before repeating.")
        return 130
    except Exception as exc:
        print(f"\nBot stopped: {exc}", file=sys.stderr)
        print("Inspect requests.csv, attempts.csv and checkout_state.json if present. "
              "A checkout error can occur after server-side changes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
