import copy 
# pyrefly: ignore [missing-import]
from typing import Dict, Any, List, Optional, Set

def serialize_state(obj, max_depth=6, seen=None):
    if seen is None:
        seen=set()
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    # 2. Prevent infinite loops on circular references
    obj_id = id(obj)
    if obj_id in seen:
        return f"<CircularRef: {type(obj).__name__}>"

    # Stop if object nesting is too deep (e.g. > 6 levels)
    if max_depth <= 0:
        return f"<MaxDepthReached: {type(obj).__name__}>"

    seen.add(obj_id)

    # 3. Handle Dictionaries
    if isinstance(obj, dict):
        return {str(k): serialize_state(v, max_depth - 1, set(seen)) for k, v in obj.items()}
    
    # 4. Handle Lists & Tuples
    if isinstance(obj, (list, tuple)):
        return [serialize_state(item, max_depth - 1, set(seen)) for item in obj]
   
    # 5. Handle Sets
    if isinstance(obj, set):
        return [serialize_state(item, max_depth - 1, set(seen)) for item in sorted(list(obj), key=str)]
    
    # 6. Handle Custom Objects / Classes
    if hasattr(obj, "__dict__"):
        clean_vars = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        return {
            "__class__": obj.__class__.__name__,
            "__data__": serialize_state(clean_vars, max_depth - 1, set(seen))
        }
    # 7. Fallback to string representation for anything else
    return repr(obj)

def compute_state_diff(prev_state, curr_state, path="root"):
    diffs = []

    # Case 1: Both are Dictionaries
    if isinstance(prev_state, dict) and isinstance(curr_state, dict):
        prev_keys = set(prev_state.keys())
        curr_keys = set(curr_state.keys())

        # 1. Added Keys (in curr, but NOT in prev)
        for k in curr_keys - prev_keys:
            key_path = f"{path}.{k}" if path != "root" else str(k)
            diffs.append({
                "type": "added",
                "path": key_path,
                "value": serialize_state(curr_state[k])
            })

        # 2. Removed Keys (in prev, but NOT in curr)
        for k in prev_keys - curr_keys:
            key_path = f"{path}.{k}" if path != "root" else str(k)
            diffs.append({
                "type": "removed",
                "path": key_path,
                "prev_value": serialize_state(prev_state[k])
            })

        # 3. Common Keys (in BOTH prev and curr)
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
                        "new_value": serialize_state(v_curr)
                    })

        return diffs

    # Case 2: Primitive Value Comparison (e.g. comparing 10 to 20)
    if prev_state != curr_state:
        diffs.append({
            "type": "mutated",
            "path": path,
            "prev_value": serialize_state(prev_state),
            "new_value": serialize_state(curr_state)
        })

    return diffs
