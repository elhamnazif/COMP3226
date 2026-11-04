import requests
import threading
import time
import csv
import os
import getpass

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


# ==========================================
# 1. CONFIGURATION
# ==========================================

BASE_URL = "http://localhost:3000"

PRODUCTS = [
    {"ProductId": 20, "quantity": 1},
    {"ProductId": 33, "quantity": 1},
    {"ProductId": 45, "quantity": 1}
]

NUMBER_OF_CHECKOUT_REQUESTS = 3

RESULTS_DIR = "results"

CSV_FILE = os.path.join(
    RESULTS_DIR,
    "same_account_checkout_replay_results.csv"
)

TIMEOUT = 15

os.makedirs(RESULTS_DIR, exist_ok=True)

# Restrict the experiment to the local testbed.
if BASE_URL not in (
    "http://localhost:3000",
    "http://127.0.0.1:3000"
):
    raise ValueError("This script is restricted to local Juice Shop.")


# ==========================================
# 2. AUTHENTICATION
# ==========================================

def login():

    print("\n=== LOGIN ===")

    email = input("Test account email: ")
    password = getpass.getpass("Test account password: ")

    session = requests.Session()

    response = session.post(
        f"{BASE_URL}/rest/user/login",
        json={
            "email": email,
            "password": password
        },
        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    authentication = data.get("authentication", {})

    token = authentication.get("token")
    basket_id = authentication.get("bid")

    if not token or not basket_id:
        raise RuntimeError(
            "Login succeeded but token or basket ID was not returned."
        )

    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    print("[SUCCESS] Login successful.")
    print(f"[INFO] Basket ID: {basket_id}")

    return session, basket_id, token


# ==========================================
# 3. ADD PRODUCTS TO BASKET
# ==========================================

def add_products(session, basket_id):

    print("\n=== ADD PRODUCTS ===")

    for product in PRODUCTS:

        product_id = product["ProductId"]
        quantity = product["quantity"]

        response = session.post(
            f"{BASE_URL}/api/BasketItems",
            json={
                "ProductId": product_id,
                "BasketId": basket_id,
                "quantity": quantity
            },
            timeout=TIMEOUT
        )

        print(
            f"[PRODUCT {product_id}] "
            f"HTTP {response.status_code}"
        )

        if response.status_code not in (200, 201):

            print("[ERROR]", response.text[:1000])

            raise RuntimeError(
                f"Could not add Product ID {product_id}. "
                "Check its stock and basket contents."
            )

    print("[SUCCESS] All products added to basket.")


# ==========================================
# 4. CHECKOUT REQUEST
# ==========================================

barrier = threading.Barrier(
    NUMBER_OF_CHECKOUT_REQUESTS
)


def find_confirmation(value):

    if isinstance(value, dict):

        for key, item in value.items():

            if key == "orderConfirmation" and item:
                return item

            result = find_confirmation(item)

            if result:
                return result

    elif isinstance(value, list):

        for item in value:

            result = find_confirmation(item)

            if result:
                return result

    return None


def checkout_request(request_number, token, basket_id):

    session = requests.Session()

    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    try:

        # Synchronise all checkout requests.
        barrier.wait(timeout=10)

        start_time = time.perf_counter()

        response = session.post(
            f"{BASE_URL}/rest/basket/{basket_id}/checkout",
            json={},
            timeout=TIMEOUT
        )

        elapsed = (
            time.perf_counter() - start_time
        ) * 1000

        try:
            response_data = response.json()

        except ValueError:
            response_data = {}

        order_confirmation = find_confirmation(
            response_data
        )

        result = {
            "request_number": request_number,
            "status_code": response.status_code,
            "response_time_ms": round(elapsed, 2),
            "order_confirmation": str(
                order_confirmation or ""
            ),
            "response_body": response.text[:2000],
            "timestamp": datetime.now().isoformat()
        }

        print(
            f"[CHECKOUT {request_number}] "
            f"HTTP {response.status_code} | "
            f"{elapsed:.2f} ms | "
            f"Order created: {bool(order_confirmation)}"
        )

        return result

    except Exception as error:

        print(
            f"[CHECKOUT {request_number}] ERROR: {error}"
        )

        return {
            "request_number": request_number,
            "status_code": "ERROR",
            "response_time_ms": "",
            "order_confirmation": "",
            "response_body": str(error),
            "timestamp": datetime.now().isoformat()
        }

    finally:

        session.close()


# ==========================================
# 5. SAVE RESULTS
# ==========================================

def save_results(results):

    fieldnames = [
        "request_number",
        "status_code",
        "response_time_ms",
        "order_confirmation",
        "response_body",
        "timestamp"
    ]

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(results)

    print(f"\n[INFO] Results saved to: {CSV_FILE}")


# ==========================================
# 6. MAIN EXPERIMENT
# ==========================================

def main():

    print("=" * 55)

    print(
        " SAME-ACCOUNT CONCURRENT CHECKOUT REPLAY BOT"
    )

    print("=" * 55)

    print(
        f"Products: "
        f"{[p['ProductId'] for p in PRODUCTS]}"
    )

    print(
        f"Product quantities: "
        f"{[p['quantity'] for p in PRODUCTS]}"
    )

    print(
        f"Concurrent checkout requests: "
        f"{NUMBER_OF_CHECKOUT_REQUESTS}"
    )

    print("\nIMPORTANT:")

    print("- Use a dedicated test account.")
    print("- Empty its basket before running.")
    print("- This experiment may create an actual test order.")
    print("- Use only your local Juice Shop instance.")

    confirmation = input(
        "\nType RUN to start the experiment: "
    )

    if confirmation != "RUN":

        print("Experiment cancelled.")
        return

    session = None

    try:

        # Login.
        session, basket_id, token = login()

        # Add all selected products once.
        add_products(session, basket_id)

        print("\n=== CONCURRENT CHECKOUT TEST ===")

        print(
            f"Sending {NUMBER_OF_CHECKOUT_REQUESTS} "
            "checkout requests using the same basket..."
        )

        experiment_start = time.perf_counter()

        with ThreadPoolExecutor(
            max_workers=NUMBER_OF_CHECKOUT_REQUESTS
        ) as executor:

            futures = [

                executor.submit(
                    checkout_request,
                    i + 1,
                    token,
                    basket_id
                )

                for i in range(
                    NUMBER_OF_CHECKOUT_REQUESTS
                )
            ]

            results = [
                future.result()
                for future in futures
            ]

        total_time = (
            time.perf_counter() - experiment_start
        )

        # ==================================
        # 7. ANALYSE RESULTS
        # ==================================

        confirmations = [

            result["order_confirmation"]

            for result in results

            if result["order_confirmation"]
        ]

        unique_confirmations = set(confirmations)

        successful_responses = sum(

            1

            for result in results

            if result["status_code"] == 200
        )

        save_results(results)

        # ==================================
        # 8. EXPERIMENT SUMMARY
        # ==================================

        print("\n" + "=" * 55)

        print(" EXPERIMENT SUMMARY")

        print("=" * 55)

        print(
            f"Checkout requests sent: {len(results)}"
        )

        print(
            f"HTTP 200 responses: {successful_responses}"
        )

        print(
            f"Order confirmations found: "
            f"{len(confirmations)}"
        )

        print(
            f"Distinct order confirmations: "
            f"{len(unique_confirmations)}"
        )

        print(
            f"Total execution time: "
            f"{total_time:.3f} seconds"
        )

        if len(unique_confirmations) > 1:

            print(
                "\n[WARNING] Multiple distinct order confirmations!"
            )

            print(
                "Investigate possible duplicate order processing."
            )

        elif len(unique_confirmations) == 1:

            print(
                "\n[INFO] One distinct order confirmation found."
            )

        else:

            print(
                "\n[INFO] No order confirmation detected."
            )

            print(
                "Inspect CSV response bodies for details."
            )

        print("\nResults file:")

        print(CSV_FILE)

        print("=" * 55)

    except Exception as error:

        print("\n[EXPERIMENT ERROR]", error)

    finally:

        if session:
            session.close()


# ==========================================
# 9. RUN PROGRAM
# ==========================================

if __name__ == "__main__":

    main()
