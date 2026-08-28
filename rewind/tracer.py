"""
Core execution tracer and timeline recording engine for Rewind.
"""

import inspect
import json
import os
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from .diff import compute_state_diff, serialize_state


class TraceStep:
    def __init__(
        self,
        step_id: int,
        name: str,
        caller_file: str,
        caller_line: int,
        inputs: Optional[Dict[str, Any]] = None,
    ):
        self.step_id = step_id
        self.name = name
        self.caller_file = caller_file
        self.caller_line = caller_line
        self.inputs = inputs or {}
        self.output: Any = None
        self.state_before: Dict[str, Any] = {}
        self.state_after: Dict[str, Any] = {}
        self.diff: List[Dict[str, Any]] = []
        self.duration_us: float = 0.0
        self.timestamp: float = time.time()
        self.status: str = "PENDING"
        self.error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts this step into a JSON-serializable dictionary."""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "caller_file": self.caller_file,
            "caller_line": self.caller_line,
            "inputs": self.inputs,
            "output": self.output,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "diff": self.diff,
            "duration_us": self.duration_us,
            "timestamp": self.timestamp,
            "status": self.status,
            "error": self.error,
        }


class Tracer:
    def __init__(self, title: str = "Rewind Execution Trace"):
        self.title = title
        self.lock = threading.RLock()
        self.steps: List[TraceStep] = []
        self.state: Dict[str, Any] = {}
        self._step_counter = 0
        self.start_time = time.time()

    def record_step_data(
        self,
        name: str,
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        state_updates: Optional[Dict[str, Any]] = None,
    ) -> TraceStep:
        """Manually records a single atomic step data record."""
        with self.lock:
            self._step_counter += 1
            step_obj = TraceStep(
                step_id=self._step_counter,
                name=name,
                caller_file="cli_runner",
                caller_line=0,
                inputs=serialize_state(inputs or {}),
            )
            step_obj.state_before = serialize_state(self.state)
            if state_updates:
                self.state.update(state_updates)
            step_obj.state_after = serialize_state(self.state)
            step_obj.diff = compute_state_diff(step_obj.state_before, step_obj.state_after)
            step_obj.status = "SUCCESS"
            self.steps.append(step_obj)
            return step_obj

    @contextmanager
    def step(self, name: str, **metadata):
        with self.lock:
            self._step_counter += 1
            curr_id = self._step_counter

            frame = inspect.currentframe()
            caller_frame = frame.f_back.f_back if frame and frame.f_back else None
            caller_file = os.path.basename(caller_frame.f_code.co_filename) if caller_frame else "unknown"
            caller_line = caller_frame.f_lineno if caller_frame else 0

            step_obj = TraceStep(
                step_id=curr_id,
                name=name,
                caller_file=caller_file,
                caller_line=caller_line,
                inputs=serialize_state(metadata),
            )
            step_obj.state_before = serialize_state(self.state)

        start_t = time.perf_counter()
        try:
            yield self.state
            step_obj.status = "SUCCESS"
        except BaseException as e:
            if isinstance(e, SystemExit) and (e.code == 0 or e.code is None):
                step_obj.status = "SUCCESS"
            else:
                step_obj.status = "FAILED"
                step_obj.error = {
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }
            raise
        finally:
            end_t = time.perf_counter()
            step_obj.duration_us = round((end_t - start_t) * 1_000_000, 2)
            with self.lock:
                step_obj.state_after = serialize_state(self.state)
                step_obj.diff = compute_state_diff(step_obj.state_before, step_obj.state_after)
                self.steps.append(step_obj)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the entire timeline into a portable dictionary."""
        with self.lock:
            has_error = any(s.status == "FAILED" for s in self.steps)
            total_duration_ms = (time.time() - self.start_time) * 1000

            return {
                "schema_version": "1.0.0",
                "title": self.title,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "has_crash": has_error,
                "total_steps": len(self.steps),
                "total_duration_ms": round(total_duration_ms, 2),
                "final_state": serialize_state(self.state),
                "steps": [s.to_dict() for s in self.steps],
            }

    def export(self, filepath: str = "rewind_trace.json") -> str:
        """Saves the timeline trace to a JSON file (creating parent directories automatically)."""
        data = self.to_dict()
        dir_name = os.path.dirname(filepath)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return filepath


# Global Singleton
_GLOBAL_TRACER = Tracer()


def get_global_tracer() -> Tracer:
    return _GLOBAL_TRACER


def step(name: str, **metadata):
    return _GLOBAL_TRACER.step(name=name, **metadata)
