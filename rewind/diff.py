"""
High-performance structural diffing and circular-safe object serializer.
"""

from typing import Any, Dict, List, Optional, Set


def serialize_state(obj: Any, max_depth: int = 6, seen: Optional[Set[int]] = None) -> Any:
    """Recursively serializes any Python data structure or object into a JSON-serializable structure."""
    if seen is None:
        seen = set()

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    # 1. Prevent infinite loops on circular references
    try:
        obj_id = id(obj)
        if obj_id in seen:
            return f"<CircularRef: {type(obj).__name__}>"

        if max_depth <= 0:
            return f"<MaxDepthReached: {type(obj).__name__}>"

        seen.add(obj_id)

        # 2. Dictionaries
        if isinstance(obj, dict):
            return {str(k): serialize_state(v, max_depth - 1, set(seen)) for k, v in obj.items()}

        # 3. Lists & Tuples
        if isinstance(obj, (list, tuple)):
            return [serialize_state(item, max_depth - 1, set(seen)) for item in obj]

        # 4. Sets
        if isinstance(obj, set):
            try:
                sorted_items = sorted(list(obj), key=lambda x: str(x))
            except Exception:
                sorted_items = list(obj)
            return [serialize_state(item, max_depth - 1, set(seen)) for item in sorted_items]

        # 5. Custom Objects / Classes
        if hasattr(obj, "__dict__"):
            try:
                clean_vars = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
                return {
                    "__class__": obj.__class__.__name__,
                    "__data__": serialize_state(clean_vars, max_depth - 1, set(seen)),
                }
            except Exception:
                pass

        # 6. Safe String Fallback
        return repr(obj)
    except Exception as e:
        return f"<Unserializable: {type(obj).__name__} ({str(e)})>"


def compute_state_diff(prev_state: Any, curr_state: Any, path: str = "root") -> List[Dict[str, Any]]:
    """Recursively compares two states and computes added (+), removed (-), and mutated (~) diffs."""
    diffs = []

    # Case 1: Both are Dictionaries
    if isinstance(prev_state, dict) and isinstance(curr_state, dict):
        prev_keys = set(prev_state.keys())
        curr_keys = set(curr_state.keys())

        # Added Keys
        for k in curr_keys - prev_keys:
            key_path = f"{path}.{k}" if path != "root" else str(k)
            diffs.append({
                "type": "added",
                "path": key_path,
                "value": serialize_state(curr_state[k]),
            })

        # Removed Keys
        for k in prev_keys - curr_keys:
            key_path = f"{path}.{k}" if path != "root" else str(k)
            diffs.append({
                "type": "removed",
                "path": key_path,
                "prev_value": serialize_state(prev_state[k]),
            })

        # Common Keys
        for k in prev_keys & curr_keys:
            key_path = f"{path}.{k}" if path != "root" else str(k)
            v_prev = prev_state[k]
            v_curr = curr_state[k]

            if v_prev != v_curr:
                if isinstance(v_prev, dict) and isinstance(v_curr, dict):
                    diffs.extend(compute_state_diff(v_prev, v_curr, key_path))
                else:
                    diffs.append({
                        "type": "mutated",
                        "path": key_path,
                        "prev_value": serialize_state(v_prev),
                        "new_value": serialize_state(v_curr),
                    })

        return diffs

    # Case 2: Primitive or Non-Dict Value Comparison
    if prev_state != curr_state:
        diffs.append({
            "type": "mutated",
            "path": path,
            "prev_value": serialize_state(prev_state),
            "new_value": serialize_state(curr_state),
        })

    return diffs
