
#!/usr/bin/env python3
"""
COMP3226 - Multi-Session Scalping and Checkout Race Test
OWASP Juice Shop 20.3.0

Three independent accounts simultaneously add and attempt
to purchase one low-stock product in a local test environment.

WARNING:
Checkout creates real orders in the local Juice Shop database
and deducts inventory. Use disposable test accounts and data.
"""

import requests
import time
import csv
import os
import threading

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from getpass import getpass

# CONFIGURATION
TARGET_BASE = "http://localhost:3001"

PRODUCT_ID = 42
EXPECTED_INITIAL_STOCK = 1
NUM_SESSIONS = 3

RESULT_FILE = "results/multi_session_checkout_results.csv"

records = []
records_lock = threading.Lock()


def check_service():
    try:
        response = requests.get(
            f"{TARGET_BASE}/api/Products",
            timeout=3
        )
        response.raise_for_status()
        print("[+] Juice Shop is running.")

    except requests.exceptions.RequestException as error:
        print(f"[!] Cannot connect to Juice Shop:", error)
        raise SystemExit(1)


def get_initial_stock():
    response = requests.get(
        f"{TARGET_BASE}/api/Quantitys/",
        timeout=5
    )
    response.raise_for_status()

    data = response.json().get("data", [])

    for item in data:
        if int(item.get("ProductId", -1)) == PRODUCT_ID:
            return int(item["quantity"])

    raise RuntimeError(
        f"Could not find inventory for Product {PRODUCT_ID}."
    )


def get_test_accounts():
    accounts = []

    print("\nEnter your three independent local test accounts.")

    for i in range(NUM_SESSIONS):
        print(f"\nAccount {i + 1}")

        email = input("Email: ").strip()
        password = getpass("Password: ")

        accounts.append({
            "name": f"Session-{i + 1}",
            "email": email,
            "password": password
        })

    emails = [a["email"].lower() for a in accounts]

    if len(set(emails)) != NUM_SESSIONS:
        raise ValueError(
            "All three accounts must have different email addresses."
        )

    return accounts


def authenticate(session, account):
    response = session.post(
        f"{TARGET_BASE}/rest/user/login",
        json={
            "email": account["email"],
            "password": account["password"]
        },
        timeout=5
    )
    response.raise_for_status()

    auth = response.json().get("authentication", {})

    token = auth.get("token")
    basket_id = auth.get("bid")

    if not token or basket_id is None:
        raise RuntimeError(
            f"Authentication data missing for {account['name']}."
        )

    session.headers.update({
        "Authorization": f"Bearer {token}"
    })

    return basket_id


def record_result(data):
    with records_lock:
        records.append(data)


def make_record(name, basket_id, action,
                status_code, elapsed="", body="",
                order_confirmation=""):

    return {
        "timestamp": datetime.now().isoformat(),
        "session": name,
        "basket_id": basket_id,
        "product_id": PRODUCT_ID,
        "action": action,
        "status_code": status_code,
        "response_ms": elapsed,
        "order_confirmation": order_confirmation,
        "response_body": str(body)[:500]
    }


def simulate_session(account, add_barrier, checkout_barrier):
    session = requests.Session()
    name = account["name"]
    basket_id = ""

    try:
        print(f"[+] Authenticating {name}")

        basket_id = authenticate(session, account)

        print(f"[+] {name} authenticated. Basket ID: {basket_id}")

        # Stage 1: all accounts add the low-stock product.
        add_barrier.wait(timeout=20)

        start = time.perf_counter()

        response = session.post(
            f"{TARGET_BASE}/api/BasketItems",
            json={
                "ProductId": PRODUCT_ID,
                "BasketId": str(basket_id),
                "quantity": 1
            },
            timeout=10
        )

        elapsed = (time.perf_counter() - start) * 1000

        add_success = response.status_code in (200, 201)

        record_result(make_record(
            name,
            basket_id,
            "ADD PRODUCT",
            response.status_code,
            round(elapsed, 2),
            response.text
        ))

        print(
            f"    {name} ADD: HTTP {response.status_code} "
            f"| {elapsed:.2f} ms"
        )

        if not add_success:
            print(f"[!] {name}: Product could not be added.")
            checkout_barrier.abort()
            return

        # Stage 2: only accounts with successful basket additions
        # proceed to the synchronised checkout.
        checkout_barrier.wait(timeout=20)

        start = time.perf_counter()

        response = session.post(
            f"{TARGET_BASE}/rest/basket/{basket_id}/checkout",
            json={},
            timeout=20
        )

        elapsed = (time.perf_counter() - start) * 1000

        try:
            response_data = response.json()
        except ValueError:
            response_data = {}

        order_confirmation = response_data.get(
            "orderConfirmation", ""
        )

        order_success = (
            response.status_code in (200, 201)
            and bool(order_confirmation)
        )

        record_result(make_record(
            name,
            basket_id,
            "CHECKOUT",
            response.status_code,
            round(elapsed, 2),
            response.text,
            order_confirmation
        ))

        print(
            f"    {name} CHECKOUT: HTTP {response.status_code} "
            f"| Order created: {order_success} "
            f"| {elapsed:.2f} ms"
        )

        if order_success:
            print(f"    Order confirmation: {order_confirmation}")

    except threading.BrokenBarrierError:
        print(f"[!] {name}: Synchronisation failed.")

        record_result(make_record(
            name, basket_id, "SYNCHRONISATION",
            "BARRIER_ERROR",
            body="Another session failed before synchronisation."
        ))

    except Exception as error:
        print(f"[!] {name} failed: {error}")

        add_barrier.abort()
        checkout_barrier.abort()

        record_result(make_record(
            name, basket_id, "ERROR",
            "ERROR", body=str(error)
        ))

    finally:
        session.close()


def save_results():
    os.makedirs("results", exist_ok=True)

    with records_lock:
        results = list(records)

    fields = [
        "timestamp",
        "session",
        "basket_id",
        "product_id",
        "action",
        "status_code",
        "response_ms",
        "order_confirmation",
        "response_body"
    ]

    with open(
        RESULT_FILE, "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    print(f"[+] CSV saved: {RESULT_FILE}")


def check_final_stock():
    try:
        stock = get_initial_stock()
        print(f"[+] Product {PRODUCT_ID} remaining stock: {stock}")
        return stock

    except Exception as error:
        print(f"[!] Could not verify final stock: {error}")
        return None


def main():
    check_service()

    print("=" * 65)
    print(" MULTI-SESSION SIMULTANEOUS CHECKOUT TEST")
    print("=" * 65)

    try:
        initial_stock = get_initial_stock()

        print(f"[*] Product ID: {PRODUCT_ID}")
        print(f"[*] Initial inventory: {initial_stock}")

        if initial_stock != EXPECTED_INITIAL_STOCK:
            print(
                "[!] Test stopped: Product 42 must have exactly "
                f"{EXPECTED_INITIAL_STOCK} unit before this experiment."
            )
            return

        accounts = get_test_accounts()

        add_barrier = threading.Barrier(NUM_SESSIONS)
        checkout_barrier = threading.Barrier(NUM_SESSIONS)

        start = time.perf_counter()

        with ThreadPoolExecutor(
            max_workers=NUM_SESSIONS
        ) as executor:

            futures = [
                executor.submit(
                    simulate_session,
                    account,
                    add_barrier,
                    checkout_barrier
                )
                for account in accounts
            ]

            for future in futures:
                future.result()

        elapsed = time.perf_counter() - start

        with records_lock:
            results = list(records)

        add_records = [
            r for r in results if r["action"] == "ADD PRODUCT"
        ]

        checkout_records = [
            r for r in results if r["action"] == "CHECKOUT"
        ]

        successful_adds = sum(
            1 for r in add_records
            if r["status_code"] in (200, 201)
        )

        successful_orders = sum(
            1 for r in checkout_records
            if r["order_confirmation"]
        )

        print("\n" + "=" * 65)
        print(" EXECUTION SUMMARY")
        print("=" * 65)

        print(f"Independent accounts: {NUM_SESSIONS}")
        print(f"Initial stock: {initial_stock}")
        print(f"Successful basket additions: {successful_adds}")
        print(f"Checkout attempts: {len(checkout_records)}")
        print(f"Confirmed orders: {successful_orders}")
        print(f"Execution time: {elapsed:.3f} seconds")

        final_stock = check_final_stock()

        if final_stock is not None:
            print(f"Initial stock: {initial_stock}")
            print(f"Final stock: {final_stock}")

            if final_stock < 0:
                print(
                    "[!] WARNING: Inventory became negative. "
                    "Investigate concurrent stock handling."
                )

            elif successful_orders > initial_stock:
                print(
                    "[!] More orders were confirmed than the "
                    "initial stock quantity."
                )

        save_results()

    except ValueError as error:
        print(f"[!] {error}")

    except RuntimeError as error:
        print(f"[!] {error}")

    except KeyboardInterrupt:
        print("\n[!] Experiment cancelled.")

    finally:
        print("[+] Multi-session experiment finished.")


if __name__ == "__main__":
    main()
