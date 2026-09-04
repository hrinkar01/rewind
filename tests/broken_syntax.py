"""
Sample Multi-Step Script with a Dynamic Syntax Error for Testing Rewind.

Run this with:
    rewind run tests/broken_syntax.py
"""

def load_system_config():
    print("[Step 1] Loading system configuration and feature flags...")
    return {
        "env": "production",
        "version": "2.4.0",
        "features": ["dynamic_pricing", "instant_checkout"],
    }


def authenticate_user(config):
    print("[Step 2] Authenticating service account and permissions...")
    return {
        "user_id": "usr_7749",
        "role": "admin",
        "tier": "enterprise",
    }


def evaluate_custom_formula(user):
    print("[Step 3] Evaluating user-defined pricing calculation formula...")
    # Dynamic formula with invalid syntax (unclosed parenthesis)
    formula_code = "print(f'Tier calculation for: ' + user['role']"
    
    # Crash occurs here: parsing the malformed formula raises SyntaxError!
    compiled = compile(formula_code, "<dynamic_formula>", "eval")
    return eval(compiled, {"user": user})


def main():
    config = load_system_config()
    user = authenticate_user(config)
    result = evaluate_custom_formula(user)
    print(f"[Step 4] Completed: {result}")


if __name__ == "__main__":
    main()
