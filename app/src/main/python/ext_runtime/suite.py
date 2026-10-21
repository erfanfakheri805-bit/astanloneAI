"""
Extension runtime - the acceptance test suite
=============================================
Every extension ships its own test cases (manifest `tests`). `run_suite()` runs each case TWICE in fresh sandboxes
against fixtures (fixed clock, in-memory storage, canned web pages) - never against the real clock, storage or
network - and requires the two runs to agree. An extension whose suite does not pass completely is never activated.
"""

import copy
import json
import re

from . import limits, sandbox
from .errors import ExtError
from .manifest import _json_ok, check_outputs, coerce_inputs, compare_expected

_KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,%d}$" % limits.MAX_KV_KEY_CHARS)


def check_key(key):
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ValueError(f"storage keys are 1-{limits.MAX_KV_KEY_CHARS} characters of letters, digits and _ . : -")
    return key


def check_value(value):
    if not _json_ok(value):
        raise ValueError("storage values must be plain JSON data")
    if len(json.dumps(value, ensure_ascii=False)) > limits.MAX_KV_VALUE_BYTES:
        raise ValueError(f"a stored value may be at most {limits.MAX_KV_VALUE_BYTES} bytes")
    return value


class FixtureCtx:
    """Deterministic stand-in for the host services an extension may be granted."""

    def __init__(self, fixtures=None):
        fixtures = fixtures or {}
        self._clock = float(fixtures.get("clock", 0))
        self._kv = copy.deepcopy(fixtures.get("store", {}))
        self._web = dict(fixtures.get("web", {}))

    def clock(self):
        return self._clock

    def store_get(self, key, default=None):
        return copy.deepcopy(self._kv.get(check_key(key), default))

    def store_put(self, key, value):
        check_key(key)
        if key not in self._kv and len(self._kv) >= limits.MAX_KV_KEYS:
            raise ValueError("too many stored keys")
        self._kv[key] = copy.deepcopy(check_value(value))

    def store_delete(self, key):
        self._kv.pop(check_key(key), None)

    def store_keys(self):
        return sorted(self._kv)

    def web_fetch_text(self, url):
        if url in self._web:
            return self._web[url]
        raise RuntimeError("no network in tests: add the page to fixtures.web")


def _outcome_key(r):
    return (r["ok"], json.dumps(r.get("value"), sort_keys=True, ensure_ascii=False) if r["ok"] else r["error"]["kind"])


def run_suite(manifest, compiled, runs=2):
    """Run the manifest's tests. Returns a JSON-able report; `all_passed` is the activation gate."""
    cases, passed, deterministic = [], 0, True
    granted = frozenset(manifest["permissions"]) - {limits.PERM_COMPUTE}
    max_fuel = 0
    for t in manifest["tests"]:
        inputs, problems = coerce_inputs(manifest, t["inputs"])
        case = {"name": t["name"], "passed": False, "reason": "", "fuel_used": 0}
        cases.append(case)
        if problems:
            case["reason"] = "inputs do not fit the declared inputs: " + "; ".join(f"{p['name']}: {p['message']}" for p in problems)
            continue
        results = [sandbox.run(compiled, inputs, ctx=FixtureCtx(manifest.get("fixtures")), granted=granted) for _ in range(runs)]
        case["fuel_used"] = results[0]["fuel_used"]
        max_fuel = max(max_fuel, case["fuel_used"])
        if len({_outcome_key(r) for r in results}) != 1:
            deterministic = False
            case["reason"] = "two runs with the same inputs gave different results (the extension is not deterministic)"
            continue
        r = results[0]
        if "expect_error" in t:
            if not r["ok"] and r["error"]["code"] == "E_EXT_RUNTIME":
                case["passed"], case["reason"] = True, "raised the expected error"
            elif r["ok"]:
                case["reason"] = "expected an error but the extension returned a result"
            else:
                case["reason"] = f"stopped by {r['error']['code']} ({r['error']['kind']}), not by an error raised by the extension"
            passed += case["passed"]
            continue
        if not r["ok"]:
            case["reason"] = f"{r['error']['kind']}: {r['error']['detail']} (line {r['error']['line']})"
            continue
        try:
            outputs = check_outputs(manifest, r["value"])
        except ExtError as e:
            case["reason"] = str(e)[:200]
            continue
        bad = ""
        for name, want in t["expect"].items():
            ok, why = compare_expected(want, outputs[name], name)
            if not ok:
                bad = why
                break
        case["passed"], case["reason"] = (not bad), (bad or "matched the expected outputs")
        passed += case["passed"]
    return {"total": len(cases), "passed": passed, "all_passed": passed == len(cases) and deterministic and bool(cases),
            "deterministic": deterministic, "runs_per_case": runs, "max_fuel_used": max_fuel, "cases": cases}
