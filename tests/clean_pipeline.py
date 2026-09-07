"""
Clean multi-step execution pipeline for testing Rewind CI passed status
"""

def fetch_data():
    return {"users": ["Alice", "Bob", "Charlie"], "count": 3}

def transform_data(payload):
    payload["processed"] = True
    payload["total_active"] = len(payload["users"])
    return payload

def save_summary(payload):
    print(f"Processed {payload['total_active']} users successfully.")
    return {"status": "OK", "saved": True}

def main():
    raw = fetch_data()
    processed = transform_data(raw)
    result = save_summary(processed)
    return result

if __name__ == "__main__":
    main()
