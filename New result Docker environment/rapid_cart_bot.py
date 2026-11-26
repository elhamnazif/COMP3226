
#!/usr/bin/env python3
"""
COMP3226 - Rapid Cart Manipulation Bot
OWASP Juice Shop 20.3.0

One authenticated account repeatedly adds different products,
updates quantities where permitted, and removes basket items.
"""

import requests
import time
import csv
import os
import sys

from datetime import datetime
from getpass import getpass

# CONFIGURATION
TARGET_BASE = "http://localhost:3001"

# Previously inspected products:
# 20: stock 5, per-user limit 5
# 33: stock 3, per-user limit 1
# 45: stock 3, per-user limit 1
PRODUCT_IDS = [20, 33, 45]

NUM_ROUNDS = 5
DELAY_SECONDS = 0.10

RESULT_FILE = "results/rapid_cart_results_updated.csv"


def check_service():
    try:
        response = requests.get(
            f"{TARGET_BASE}/api/Products",
            timeout=3
        )
        response.raise_for_status()
        print("[+] Juice Shop is running.")

    except requests.exceptions.RequestException as error:
        print(f"[!] Cannot connect to Juice Shop: {error}")
        sys.exit(1)


def login_client(session):
    print("\nEnter your local Juice Shop test account.")

    email = input("Email: ").strip()
    password = getpass("Password: ")

    response = session.post(
        f"{TARGET_BASE}/rest/user/login",
        json={"email": email, "password": password},
        timeout=5
    )
    response.raise_for_status()

    auth = response.json().get("authentication", {})
    token = auth.get("token")
    basket_id = auth.get("bid")

    if not token or basket_id is None:
        raise RuntimeError("Authentication data missing.")

    session.headers.update({
        "Authorization": f"Bearer {token}"
    })

    print("[+] Login successful.")
    print(f"[+] Basket ID: {basket_id}")

    return basket_id


def send_request(session, method, endpoint,
                 payload=None, action="", product_id=""):

    start = time.perf_counter()

    try:
        response = session.request(
            method,
            f"{TARGET_BASE}{endpoint}",
            json=payload,
            timeout=5
        )

        elapsed = (time.perf_counter() - start) * 1000

        record = {
            "timestamp": datetime.now().isoformat(),
            "product_id": product_id,
            "action": action,
            "status_code": response.status_code,
            "response_ms": round(elapsed, 2),
            "response_body": response.text[:500]
        }

        print(
            f"    Product {str(product_id):<4} "
            f"{action:<20} Status: {response.status_code} | "
            f"{elapsed:.2f} ms"
        )

        return response, record

    except requests.exceptions.RequestException as error:
        print(f"[!] {action} failed: {error}")

        record = {
            "timestamp": datetime.now().isoformat(),
            "product_id": product_id,
            "action": action,
            "status_code": "ERROR",
            "response_ms": "",
            "response_body": str(error)[:500]
        }

        return None, record


def add_product(session, basket_id, product_id, records):
    response, record = send_request(
        session,
        "POST",
        "/api/BasketItems",
        {
            "ProductId": product_id,
            "BasketId": str(basket_id),
            "quantity": 1
        },
        "ADD PRODUCT",
        product_id
    )

    records.append(record)

    if response is None or response.status_code not in (200, 201):
        return None

    try:
        return response.json()["data"]["id"]
    except (ValueError, KeyError, TypeError):
        print("[!] Could not obtain basket item ID.")
        return None


def perform_action(session, method, endpoint,
                   payload, action, product_id, records):

    _, record = send_request(
        session,
        method,
        endpoint,
        payload,
        action,
        product_id
    )
    records.append(record)


def simulate_rapid_cart_bot(session, basket_id, records):
    print("\n[*] Rapid Cart Manipulation Started")
    print(f"[*] Products: {PRODUCT_IDS}")
    print(f"[*] Rounds: {NUM_ROUNDS}")
    print(f"[*] Delay: {DELAY_SECONDS} seconds")

    start_time = time.perf_counter()

    for round_number in range(1, NUM_ROUNDS + 1):
        print(f"\n[Round {round_number}]")

        basket_items = {}

        # Add three different products.
        for product_id in PRODUCT_IDS:
            item_id = add_product(
                session, basket_id, product_id, records
            )

            if item_id is not None:
                basket_items[product_id] = item_id

            time.sleep(DELAY_SECONDS)

        # Product 20 permits a quantity of two.
        # Products 33 and 45 have a per-user limit of one.
        item_id = basket_items.get(20)

        if item_id is not None:
            endpoint = f"/api/BasketItems/{item_id}"

            perform_action(
                session, "PUT", endpoint,
                {"quantity": 2},
                "INCREASE QUANTITY", 20, records
            )
            time.sleep(DELAY_SECONDS)

            perform_action(
                session, "PUT", endpoint,
                {"quantity": 1},
                "DECREASE QUANTITY", 20, records
            )
            time.sleep(DELAY_SECONDS)

        # Remove all successfully added items.
        for product_id, item_id in basket_items.items():
            perform_action(
                session,
                "DELETE",
                f"/api/BasketItems/{item_id}",
                None,
                "REMOVE PRODUCT",
                product_id,
                records
            )
            time.sleep(DELAY_SECONDS)

    return time.perf_counter() - start_time


def save_results(records):
    os.makedirs("results", exist_ok=True)

    fields = [
        "timestamp",
        "product_id",
        "action",
        "status_code",
        "response_ms",
        "response_body"
    ]

    with open(
        RESULT_FILE, "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    print(f"[+] CSV saved: {RESULT_FILE}")


def main():
    check_service()

    print("=" * 65)
    print(" RAPID CART MANIPULATION BOT")
    print("=" * 65)

    session = requests.Session()
    records = []

    try:
        basket_id = login_client(session)

        elapsed = simulate_rapid_cart_bot(
            session, basket_id, records
        )

        successful = sum(
            1 for item in records
            if item["status_code"] in (200, 201)
        )

        total = len(records)

        print("\n" + "=" * 65)
        print(" EXECUTION SUMMARY")
        print("=" * 65)
        print(f"Products targeted: {len(PRODUCT_IDS)}")
        print(f"Recorded requests: {total}")
        print(f"Successful requests: {successful}")
        print(f"Failed requests: {total - successful}")
        print(f"Execution time: {elapsed:.3f} seconds")

        if elapsed > 0:
            print(
                f"Average request frequency: "
                f"{total / elapsed:.2f} requests/sec"
            )

        save_results(records)

    except requests.exceptions.RequestException as error:
        print(f"[!] Request error: {error}")

    except RuntimeError as error:
        print(f"[!] Error: {error}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
