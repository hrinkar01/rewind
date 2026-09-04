"""
Sample Multi-Step Script with a Runtime Bug for Testing Rewind.

Run this with:
    rewind run tests/broken_pipeline.py
"""

def initialize_session(user_name):
    print(f"[Step 1] Initializing order checkout session for {user_name}...")
    return {
        "order_id": "ORD-94821",
        "customer": user_name,
        "items": ["Mechanical Keyboard", "USB-C Cable"],
        "subtotal": 120.00,
        "discount": 20.00,
        "tax": None,  # Bug: tax was initialized to None instead of a numeric value!
        "status": "INITIALIZED",
    }


def apply_discount(order):
    print("[Step 2] Applying promotional coupon discount...")
    order["discounted_subtotal"] = order["subtotal"] - order["discount"]
    order["status"] = "DISCOUNT_APPLIED"
    return order


def calculate_shipping(order):
    print("[Step 3] Calculating express shipping fee...")
    order["shipping_fee"] = 15.00
    order["status"] = "SHIPPING_CALCULATED"
    return order


def finalize_invoice(order):
    print("[Step 4] Finalizing total ledger invoice including tax...")
    # Crash occurs here: Adding float and NoneType raises TypeError!
    final_total = order["discounted_subtotal"] + order["shipping_fee"] + order["tax"]
    order["final_total"] = final_total
    order["status"] = "COMPLETED"
    print(f"[Step 5] Order finalized successfully! Total: ${final_total:.2f}")
    return order


def main():
    order = initialize_session("Alice")
    order = apply_discount(order)
    order = calculate_shipping(order)
    order = finalize_invoice(order)
    return order


if __name__ == "__main__":
    main()
