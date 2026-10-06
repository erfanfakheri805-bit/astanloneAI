"""
Tests for Prompt 939 - Runtime Growth Request.

`create_runtime_growth_request(data)` is a pure, deterministic constructor and
normalizer for the first growth-pipeline object. It records a request only.

Run directly:
    python -m unittest tests.test_runtime_growth_request_prompt939 -v
"""

import ast
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_growth import runtime_growth_request as rgr

create = rgr.create_runtime_growth_request
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_request.py")
FIELDS = ["version", "request_id", "kind", "goal", "target", "reason", "source", "status"]
INVALID = {"version": "1", "request_id": None, "kind": None, "goal": None, "target": None,
           "reason": None, "source": None, "status": "invalid"}


def data(**over):
    base = {"kind": "IMPROVE_CAPABILITY", "goal": "Answer questions faster",
            "target": "code_analysis", "reason": "Users wait too long", "source": "runtime"}
    base.update(over)
    return base


def tree_state(root):
    out = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return out


class TestValidRequests(unittest.TestCase):
    def check(self, kind):
        result = create(data(kind=kind))
        self.assertEqual(list(result), FIELDS)
        self.assertEqual(result["version"], "1")
        self.assertEqual(result["kind"], kind)
        self.assertEqual(result["status"], "requested")
        self.assertEqual(result["goal"], "Answer questions faster")
        self.assertEqual(result["target"], "code_analysis")
        self.assertEqual(result["reason"], "Users wait too long")
        self.assertEqual(result["source"], "runtime")
        self.assertTrue(result["request_id"].startswith("growth_req_"))
        self.assertEqual(len(result["request_id"]), len("growth_req_") + 16)
        json.dumps(result)
        return result

    def test_create_capability(self):
        self.check("CREATE_CAPABILITY")

    def test_improve_capability(self):
        self.check("IMPROVE_CAPABILITY")

    def test_improve_runtime(self):
        self.check("IMPROVE_RUNTIME")

    def test_supported_kinds_are_limited_and_explicit(self):
        self.assertEqual(rgr.REQUEST_KINDS,
                         ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME"))

    def test_reason_and_source_are_optional_with_safe_defaults(self):
        result = create({"kind": "IMPROVE_RUNTIME", "goal": "g", "target": "t"})
        self.assertEqual((result["reason"], result["source"], result["status"]),
                         ("", "runtime", "requested"))

    def test_text_is_normalized(self):
        result = create(data(goal="  Answer \t questions\n faster  ", target=" code_analysis "))
        self.assertEqual(result["goal"], "Answer questions faster")
        self.assertEqual(result["target"], "code_analysis")

    def test_no_execution_approval_or_code_fields(self):
        result = create(data())
        for name in ("execution_allowed", "executed", "approved", "approval", "code", "patch",
                     "command", "execute"):
            self.assertNotIn(name, result)

    def test_persian_text_is_supported(self):
        result = create(data(goal="پاسخ سریع‌تر", target="تحلیل_کد"))
        self.assertEqual(result["status"], "requested")
        self.assertEqual(result["goal"], "پاسخ سریع‌تر")


class TestInvalidRequests(unittest.TestCase):
    def test_unknown_kind(self):
        for kind in ("DELETE_EVERYTHING", "create_capability", "", "  ", None, 1, [], "EXECUTE"):
            self.assertEqual(create(data(kind=kind)), INVALID, repr(kind))

    def test_missing_goal(self):
        d = data()
        del d["goal"]
        self.assertEqual(create(d), INVALID)
        for bad in ("", "   \n", None, 5):
            self.assertEqual(create(data(goal=bad)), INVALID, repr(bad))

    def test_missing_target(self):
        d = data()
        del d["target"]
        self.assertEqual(create(d), INVALID)
        for bad in ("", "  ", None, 5):
            self.assertEqual(create(data(target=bad)), INVALID, repr(bad))

    def test_missing_kind(self):
        d = data()
        del d["kind"]
        self.assertEqual(create(d), INVALID)

    def test_malformed_input(self):
        for bad in (None, "x", 1, 1.5, True, [], (), set(), object(), [data()], ("a",)):
            self.assertEqual(create(bad), INVALID, repr(bad))
        for key, value in (("reason", 5), ("reason", None), ("source", None), ("source", ""),
                           ("source", 7), ("goal", ["x"]), ("target", {"a": 1}),
                           ("goal", "x" * 501)):
            self.assertEqual(create(data(**{key: value})), INVALID, (key, value))

    def test_unexpected_keys_are_rejected(self):
        for extra in ("execute", "approved", "code", "id", "request_id", "status"):
            self.assertEqual(create(data(**{extra: "x"})), INVALID, extra)

    def test_input_that_raises_when_read(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def get(self, *a, **k):
                raise RuntimeError("boom")

        self.assertEqual(create(Boom(data())), INVALID)

    def test_invalid_result_is_fresh_each_time(self):
        first = create(None)
        first["status"] = "requested"
        self.assertEqual(create(None), INVALID)


class TestDeterministicIds(unittest.TestCase):
    def test_request_id_is_deterministic(self):
        first = create(data())["request_id"]
        for _ in range(5):
            self.assertEqual(create(data())["request_id"], first)

    def test_expected_derivation(self):
        r = create(data())
        text = json.dumps({"version": "1", "kind": r["kind"], "goal": r["goal"],
                           "target": r["target"], "reason": r["reason"], "source": r["source"]},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(r["request_id"],
                         "growth_req_" + hashlib.sha256(text.encode("ascii")).hexdigest()[:16])

    def test_equivalent_inputs_produce_equivalent_results(self):
        a = create(data())
        b = create(data(goal="  Answer   questions\tfaster ", target="code_analysis  ",
                        reason=" Users wait   too long"))
        c = create(dict(reversed(list(data().items()))))
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(a["request_id"], b["request_id"])
        d = data()
        del d["source"]
        self.assertEqual(create(d)["request_id"], create(data(source="runtime"))["request_id"])

    def test_different_meaningful_inputs_produce_different_ids(self):
        base = create(data())["request_id"]
        variants = [data(kind="CREATE_CAPABILITY"), data(kind="IMPROVE_RUNTIME"),
                    data(goal="Answer slower"), data(target="memory"),
                    data(reason="Other reason"), data(source="user_feedback")]
        ids = [create(v)["request_id"] for v in variants]
        self.assertNotIn(base, ids)
        self.assertEqual(len(set(ids)), len(ids))

    def test_id_depends_only_on_content_not_environment(self):
        first = create(data())["request_id"]
        with mock.patch.dict(os.environ, {"X_GROWTH": "1", "TZ": "Pacific/Kiritimati"}):
            self.assertEqual(create(data())["request_id"], first)
        with mock.patch("time.time", side_effect=AssertionError("clock")), \
                mock.patch("random.random", side_effect=AssertionError("random")), \
                mock.patch("uuid.uuid4", side_effect=AssertionError("uuid")):
            self.assertEqual(create(data())["request_id"], first)


class TestPurity(unittest.TestCase):
    def test_no_input_mutation(self):
        for d in (data(), data(goal="  spaced   out "), data(kind="nope"), {"x": 1}):
            before = copy.deepcopy(d)
            create(d)
            self.assertEqual(d, before)

    def test_repeated_calls_are_deterministic_and_fresh(self):
        d = data()
        first = create(d)
        self.assertEqual(json.dumps(create(d)), json.dumps(first))
        first["goal"] = "tampered"
        self.assertEqual(create(d)["goal"], "Answer questions faster")
        self.assertIsNot(create(d), create(d))

    def test_no_filesystem_or_memory_modification(self):
        db = os.path.join(PY_ROOT, "data", "memory.db")
        with open(db, "rb") as handle:
            db_before = hashlib.sha256(handle.read()).hexdigest()
        tree_before = tree_state(PY_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                for d in (data(), data(kind="x"), None, data(goal="y" * 900)):
                    create(d)
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(old)
        with open(db, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), db_before)
        self.assertEqual(tree_state(PY_ROOT), tree_before)

    def test_no_io_database_network_or_execution_is_attempted(self):
        trap = AssertionError("must not be called")
        with mock.patch("builtins.open", side_effect=trap), \
                mock.patch("sqlite3.connect", side_effect=trap), \
                mock.patch("socket.socket", side_effect=trap), \
                mock.patch("subprocess.Popen", side_effect=trap), \
                mock.patch("os.system", side_effect=trap), \
                mock.patch("os.remove", side_effect=trap), \
                mock.patch("builtins.exec", side_effect=trap), \
                mock.patch("builtins.eval", side_effect=trap):
            self.assertEqual(create(data())["status"], "requested")
            self.assertEqual(create("bad"), INVALID)

    def test_callables_in_the_input_are_never_called(self):
        trap = mock.Mock(side_effect=AssertionError("must not be called"))
        for bad in (data(goal=trap), data(reason=trap), data(execute=trap)):
            self.assertEqual(create(bad), INVALID)
        trap.assert_not_called()

    def test_module_source_is_pure(self):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"hashlib", "json"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__",
                                                "input", "print", "setattr", "delattr", "getattr"})

    def test_not_wired_into_core(self):
        for rel in ("core/core.py",
                    "runtime_integration/bridge.py", "ael/interpreter.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
