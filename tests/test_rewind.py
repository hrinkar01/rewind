"""
Unit test suite for Rewind Core SDK.
"""

import unittest
from rewind.diff import serialize_state, compute_state_diff
from rewind.tracer import Tracer, TraceStep


class TestRewindSerialization(unittest.TestCase):
    def test_primitive_serialization(self):
        self.assertEqual(serialize_state(42), 42)
        self.assertEqual(serialize_state("hello"), "hello")
        self.assertEqual(serialize_state(True), True)
        self.assertIsNone(serialize_state(None))

    def test_circular_reference_protection(self):
        a = {}
        b = {"a": a}
        a["b"] = b
        res = serialize_state(a)
        self.assertIn("b", res)
        self.assertIn("<CircularRef", str(res["b"]["a"]))

    def test_set_deterministic_sorting(self):
        s = {"cherry", "apple", "banana"}
        res = serialize_state(s)
        self.assertEqual(res, ["apple", "banana", "cherry"])

    def test_custom_class_serialization(self):
        class User:
            def __init__(self, name, age):
                self.name = name
                self.age = age
                self._secret = "1234"

        u = User("Alice", 30)
        res = serialize_state(u)
        self.assertEqual(res["__class__"], "User")
        self.assertEqual(res["__data__"]["name"], "Alice")
        self.assertEqual(res["__data__"]["age"], 30)
        self.assertNotIn("_secret", res["__data__"])


class TestRewindStateDiff(unittest.TestCase):
    def test_added_keys(self):
        before = {"a": 1}
        after = {"a": 1, "b": 2}
        diffs = compute_state_diff(before, after)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["type"], "added")
        self.assertEqual(diffs[0]["path"], "b")
        self.assertEqual(diffs[0]["value"], 2)

    def test_removed_keys(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1}
        diffs = compute_state_diff(before, after)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["type"], "removed")
        self.assertEqual(diffs[0]["path"], "b")

    def test_mutated_nested_values(self):
        before = {"cart": {"total": 100}}
        after = {"cart": {"total": 200}}
        diffs = compute_state_diff(before, after)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["type"], "mutated")
        self.assertEqual(diffs[0]["path"], "cart.total")
        self.assertEqual(diffs[0]["prev_value"], 100)
        self.assertEqual(diffs[0]["new_value"], 200)


class TestRewindTracer(unittest.TestCase):
    def test_tracer_step_lifecycle(self):
        tracer = Tracer(title="Test Trace")
        with tracer.step("1. Init", meta="test") as state:
            state["counter"] = 10

        self.assertEqual(len(tracer.steps), 1)
        step = tracer.steps[0]
        self.assertEqual(step.name, "1. Init")
        self.assertEqual(step.status, "SUCCESS")
        self.assertEqual(step.state_after["counter"], 10)
        self.assertGreater(step.duration_us, 0)

    def test_tracer_crash_capture(self):
        tracer = Tracer(title="Test Crash")
        with self.assertRaises(ZeroDivisionError):
            with tracer.step("Failing Step") as state:
                x = 1 / 0

        self.assertEqual(len(tracer.steps), 1)
        step = tracer.steps[0]
        self.assertEqual(step.status, "FAILED")
        self.assertIsNotNone(step.error)
        self.assertEqual(step.error["type"], "ZeroDivisionError")


if __name__ == "__main__":
    unittest.main()
