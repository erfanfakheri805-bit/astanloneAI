"""Prompt 783 - Section 9 web request pipeline (`web.web_request_pipeline`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_dispatcher as wdisp
from web import web_request_executor as we
from web import web_request_output as wo
from web import web_request_pipeline as wp
from web.web_request import create_web_request
from web.web_request_dispatcher import dispatch_web_request
from web.web_request_executor import WebRequestExecutionResult, execute_web_request_plan
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_pipeline import run_web_request_pipeline
from web.web_request_plan import WebRequestPlan, create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_pipeline_prompt783.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_pipeline.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "WEB_REQUEST_PIPELINE_INVALID_PLAN"
DISPATCHER_INVALID = "WEB_REQUEST_DISPATCHER_INVALID_PLAN"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
DEFAULT = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": "page", "timeout_ms": 5000}


def make_plan(**over):
    data = dict(DEFAULT)
    data.update(over)
    req = create_web_request(data)
    assert req.ok, req.failures
    res = create_web_resource({"resource_id": data["resource_type"], "url": "https://example.org/r", "title": "T", "resource_type": "page"})
    assert res.ok, res.failures
    reg = create_web_resource_registry([res.resource])
    assert reg.ok, reg.failures
    plan = create_web_request_plan(validate_web_request(req.request, reg.registry))
    assert plan.ok, plan.codes()
    return plan.plan


class Lookalike:
    request_id, url, method, resource_type, timeout_ms = "req_1", "https://example.org/x", "GET", "page", 5000

    def to_dict(self):
        return dict(DEFAULT)


def live(cls):
    gc.collect()
    return [o for o in gc.get_objects() if type(o) is cls]


class TestValidPipeline(unittest.TestCase):
    def test_1_valid_plan_returns_a_web_request_output(self):
        self.assertIs(type(run_web_request_pipeline(make_plan())), WebRequestOutput)

    def test_2_current_behavior_is_not_implemented(self):
        out = run_web_request_pipeline(make_plan())
        self.assertEqual(out.status, "NOT_IMPLEMENTED")
        self.assertEqual(out.code, NOT_IMPL)
        self.assertEqual(out.metadata, DEFAULT)

    def test_3_status_code_and_metadata_are_preserved_exactly(self):
        plan = make_plan(request_id="r-9", url="https://svc.example/v1?a=1", method="POST", resource_type="api", timeout_ms=250)
        out = run_web_request_pipeline(plan)
        self.assertEqual(out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": plan.to_dict()})
        self.assertEqual(list(out.metadata), list(FIELDS))
        for field in FIELDS:
            self.assertIs(out.metadata[field], getattr(plan, field), field)
        self.assertIs(type(out.metadata["timeout_ms"]), int)

    def test_4_output_equals_the_dispatcher_output_by_value(self):
        plan = make_plan()
        self.assertEqual(run_web_request_pipeline(plan), dispatch_web_request(plan))
        self.assertEqual(hash(run_web_request_pipeline(plan)), hash(dispatch_web_request(plan)))
        self.assertEqual(run_web_request_pipeline(plan), create_web_request_output(execute_web_request_plan(plan)))

    def test_5_unusual_but_valid_values_pass_through_unchanged(self):
        plan = make_plan(request_id="  r 1  ", url="HTTPS://Example.ORG/X ", method="get", timeout_ms=1)
        out = run_web_request_pipeline(plan)
        self.assertEqual(out.metadata, plan.to_dict())
        self.assertEqual(out.code, NOT_IMPL)


class TestDispatcherPropagation(unittest.TestCase):
    def test_6_dispatcher_invoked_exactly_once_with_the_same_plan(self):
        plan = make_plan()
        spy = mock.Mock(wraps=dispatch_web_request)
        with mock.patch.object(wp, "dispatch_web_request", spy):
            out = run_web_request_pipeline(plan)
        spy.assert_called_once()
        self.assertEqual(len(spy.call_args.args), 1)
        self.assertIs(spy.call_args.args[0], plan)
        self.assertEqual(spy.call_args.kwargs, {})
        self.assertEqual(out.code, NOT_IMPL)

    def test_7_dispatcher_result_is_returned_as_the_same_object(self):
        plan = make_plan()
        made = dispatch_web_request(plan)
        with mock.patch.object(wp, "dispatch_web_request", mock.Mock(return_value=made)):
            self.assertIs(run_web_request_pipeline(plan), made)

    def test_8_any_dispatcher_result_propagates_unchanged(self):
        sentinels = (dispatch_web_request(make_plan(request_id="other", method="PUT")), dispatch_web_request(None),
                     create_web_request_output(execute_web_request_plan(None)))
        for sentinel in sentinels:
            with mock.patch.object(wp, "dispatch_web_request", mock.Mock(return_value=sentinel)):
                out = run_web_request_pipeline(make_plan())
            self.assertIs(out, sentinel)
            self.assertEqual(out.to_dict(), sentinel.to_dict())

    def test_9_dispatcher_rejection_is_not_recoded_by_the_pipeline(self):
        rejected = dispatch_web_request(None)
        with mock.patch.object(wp, "dispatch_web_request", mock.Mock(return_value=rejected)):
            out = run_web_request_pipeline(make_plan())
        self.assertEqual(out.code, DISPATCHER_INVALID)
        self.assertNotEqual(out.code, INVALID)

    def test_10_pipeline_uses_the_public_dispatcher_and_adds_no_chain_logic(self):
        self.assertIs(wp.dispatch_web_request, wdisp.dispatch_web_request)
        self.assertIs(wp.WebRequestOutput, wo.WebRequestOutput)
        self.assertIs(wp.WebRequestPlan, WebRequestPlan)
        for name in ("execute_web_request_plan", "create_web_request_output"):
            self.assertNotIn(name, vars(wp))

    def test_11_executor_and_factory_run_only_inside_the_dispatcher(self):
        plan = make_plan()
        ex = mock.Mock(wraps=execute_web_request_plan)
        fac = mock.Mock(wraps=create_web_request_output)
        with mock.patch.object(wdisp, "execute_web_request_plan", ex), mock.patch.object(wdisp, "create_web_request_output", fac):
            out = run_web_request_pipeline(plan)
        ex.assert_called_once()
        fac.assert_called_once()
        self.assertIs(ex.call_args.args[0], plan)
        self.assertEqual(out.code, NOT_IMPL)


class TestInvalidInput(unittest.TestCase):
    INPUTS = (None, {}, DEFAULT, "plan", 1, 1.5, True, [], (), object(), Lookalike(), WebRequestPlan, type(None), b"x", set(), lambda: None)

    def test_12_invalid_input_returns_the_deterministic_rejected_output(self):
        for item in self.INPUTS:
            out = run_web_request_pipeline(item)
            self.assertIs(type(out), WebRequestOutput, item)
            self.assertEqual(out.status, "REJECTED")
            self.assertEqual(out.code, INVALID)
            self.assertIsNone(out.metadata)
            self.assertEqual(out.to_dict(), {"status": "REJECTED", "code": INVALID, "metadata": None})

    def test_13_all_invalid_inputs_give_equal_outputs(self):
        self.assertEqual(len({run_web_request_pipeline(i) for i in self.INPUTS}), 1)

    def test_14_chain_objects_are_not_plans(self):
        plan = make_plan()
        for item in (execute_web_request_plan(plan), dispatch_web_request(plan), run_web_request_pipeline(plan)):
            self.assertEqual(run_web_request_pipeline(item).code, INVALID)

    def test_15_invalid_input_never_reaches_the_dispatcher(self):
        boom = mock.Mock(side_effect=AssertionError("must not be called"))
        with mock.patch.object(wp, "dispatch_web_request", boom):
            for item in self.INPUTS:
                self.assertEqual(run_web_request_pipeline(item).code, INVALID)
        boom.assert_not_called()

    def test_16_invalid_input_is_never_read(self):
        class Spy:
            def __getattribute__(self, name):
                raise AssertionError("input must not be read: " + name)
        self.assertEqual(run_web_request_pipeline(Spy()).code, INVALID)

    def test_17_pipeline_rejection_differs_from_dispatcher_and_factory_rejections(self):
        out = run_web_request_pipeline(None)
        self.assertNotEqual(out, dispatch_web_request(None))
        self.assertNotEqual(out, create_web_request_output(None))
        self.assertEqual((out.status, dispatch_web_request(None).status), ("REJECTED", "REJECTED"))

    def test_18_rejected_output_is_a_real_web_request_output_built_with_the_module_token(self):
        out = run_web_request_pipeline(None)
        self.assertEqual(sorted(type(out).__slots__), ["_code", "_items", "_status"])
        self.assertIsNone(out._items)
        with self.assertRaises(TypeError):
            WebRequestOutput(object(), "REJECTED", INVALID, None)
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestPlan,), {})


class TestNoRetention(unittest.TestCase):
    def test_19_plan_is_not_retained(self):
        plan = make_plan()
        self.assertTrue(any(o is plan for o in live(WebRequestPlan)))   # sanity: the scan sees plans
        out = run_web_request_pipeline(plan)
        self.assertFalse(any(r is plan for r in gc.get_referents(out)))
        self.assertFalse(any(r is plan for r in gc.get_referents(vars(wp))))
        del plan
        self.assertEqual(live(WebRequestPlan), [])
        self.assertEqual(out.metadata, DEFAULT)

    def test_20_execution_result_is_not_retained(self):
        held = execute_web_request_plan(make_plan())
        self.assertEqual(len(live(WebRequestExecutionResult)), 1)       # sanity: the scan sees results
        del held
        self.assertEqual(live(WebRequestExecutionResult), [])
        out = run_web_request_pipeline(make_plan())
        self.assertEqual(live(WebRequestExecutionResult), [])
        self.assertEqual(live(WebRequestPlan), [])
        self.assertEqual(out.code, NOT_IMPL)

    def test_21_dispatcher_result_is_not_retained_by_the_pipeline(self):
        seen = []
        real = dispatch_web_request

        def spy(plan):
            result = real(plan)
            seen.append(id(result))
            return result
        with mock.patch.object(wp, "dispatch_web_request", spy):
            out = run_web_request_pipeline(make_plan())
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], id(out))
        before = len(live(WebRequestOutput))
        del out
        self.assertEqual(len(live(WebRequestOutput)), before - 1)

    def test_22_output_holds_only_plain_values(self):
        out = run_web_request_pipeline(make_plan())
        for item in (out._status, out._code, out._items):
            self.assertNotIsInstance(item, (WebRequestPlan, WebRequestExecutionResult, WebRequestOutput))
        for key, value in out._items:
            self.assertIs(type(key), str)
            self.assertIn(type(value), (str, int))

    def test_23_module_has_no_global_state(self):
        before = dict(vars(wp))
        for item in (make_plan(), None, 1):
            run_web_request_pipeline(item)
        after = vars(wp)
        self.assertEqual(set(after), set(before))
        for name, value in after.items():
            self.assertIs(value, before[name], name)
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, WebRequestPlan, WebRequestExecutionResult, WebRequestOutput), name)

    def test_24_plan_is_not_changed(self):
        plan = make_plan()
        before = (plan.to_dict(), plan, hash(plan))
        run_web_request_pipeline(plan)
        self.assertEqual((plan.to_dict(), plan, hash(plan)), before)


class TestDeterminismAndImmutability(unittest.TestCase):
    def test_25_repeated_calls_are_deterministic(self):
        plan = make_plan()
        outs = [run_web_request_pipeline(plan) for _ in range(5)]
        for o in outs[1:]:
            self.assertEqual(o, outs[0])
            self.assertEqual(hash(o), hash(outs[0]))
            self.assertEqual(o.to_dict(), outs[0].to_dict())
        self.assertEqual(len({run_web_request_pipeline(None) for _ in range(3)}), 1)
        self.assertEqual(run_web_request_pipeline(make_plan()), run_web_request_pipeline(make_plan()))

    def test_26_different_plans_give_different_outputs(self):
        self.assertNotEqual(run_web_request_pipeline(make_plan()), run_web_request_pipeline(make_plan(request_id="other")))
        self.assertNotEqual(run_web_request_pipeline(make_plan()), run_web_request_pipeline(None))

    def test_27_returned_output_is_immutable(self):
        for out in (run_web_request_pipeline(make_plan()), run_web_request_pipeline(None)):
            for attr in ("status", "code", "metadata", "_status", "_code", "_items", "extra"):
                with self.assertRaises(AttributeError, msg=attr):
                    setattr(out, attr, "x")
            for attr in ("status", "_code"):
                with self.assertRaises(AttributeError, msg=attr):
                    delattr(out, attr)
            with self.assertRaises(AttributeError):
                out.__dict__

    def test_28_metadata_and_to_dict_are_fresh_copies(self):
        out = run_web_request_pipeline(make_plan())
        meta = out.metadata
        meta["url"] = "changed"
        meta["extra"] = 1
        d = out.to_dict()
        d["metadata"]["method"] = "DELETE"
        d["status"] = "OK"
        self.assertEqual(out.metadata, DEFAULT)
        self.assertEqual(out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": DEFAULT})
        self.assertIsNot(out.metadata, out.metadata)

    def test_29_copy_deepcopy_and_pickle(self):
        for out in (run_web_request_pipeline(make_plan()), run_web_request_pipeline(None)):
            self.assertIs(copy.copy(out), out)
            self.assertIs(copy.deepcopy(out), out)
            with self.assertRaises(TypeError):
                pickle.dumps(out)
            with self.assertRaises(TypeError):
                type("Sub", (WebRequestOutput,), {})


class TestNoSideEffects(unittest.TestCase):
    def test_30_no_side_effects_filesystem_environment_or_modules(self):
        plan = make_plan()
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (plan, None, 1, Lookalike()):
                run_web_request_pipeline(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_31_no_network_filesystem_subprocess_or_database_access(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        plan = make_plan()
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(run_web_request_pipeline(plan).code, NOT_IMPL)
            self.assertEqual(run_web_request_pipeline(None).code, INVALID)

    def test_32_no_network_module_is_loaded_by_the_pipeline(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl", "sqlite3", "subprocess", "os", "sys", "shutil"):
            self.assertNotIn(name, vars(wp))


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_33_module_imports_only_the_existing_public_web_request_modules(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(sorted(imports), sorted([
            ("web_request_dispatcher", 1, ["dispatch_web_request"]),
            ("web_request_output", 1, ["_CREATE_TOKEN"]),
            ("web_request_output", 1, ["WebRequestOutput"]),
            ("web_request_plan", 1, ["WebRequestPlan"])]))

    def test_34_module_is_pure_and_does_not_duplicate_dispatcher_or_executor_logic(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertEqual(calls, {"type", "WebRequestOutput", "dispatch_web_request"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning", "WebRequestExecutionResult",
                     "WebRequestValidationResult", "WebResourceRegistry", "execute_web_request_plan", "create_web_request_output",
                     "validate_web_request", "create_web_request_plan", "to_dict", "metadata", "request_id", "url", "method", "resource_type", "timeout_ms"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ImportFrom))
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["run_web_request_pipeline"])

    def test_35_earlier_web_modules_are_unaware_of_the_pipeline(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py",
                     "web_request_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_metadata_executor.py",
                     "web_request_dispatcher.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_pipeline", "run_web_request_pipeline"):
                self.assertNotIn(token, text, (name, token))

    def test_36_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_pipeline", "run_web_request_pipeline")
        skip = {"web", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_37_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py",
                          "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py",
                          "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_38_end_to_end_through_public_apis_only(self):
        plan = make_plan(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        out = run_web_request_pipeline(plan)
        self.assertEqual(out, dispatch_web_request(plan))
        self.assertEqual(out.metadata, plan.to_dict())
        self.assertEqual((out.status, out.code), ("NOT_IMPLEMENTED", NOT_IMPL))

    def test_39_documentation_exists_and_names_the_public_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for token in ("Prompt 783", "run_web_request_pipeline", INVALID, "WebRequestOutput", "dispatch_web_request", "NOT_IMPLEMENTED"):
            self.assertIn(token, text, token)


if __name__ == "__main__":
    unittest.main()
