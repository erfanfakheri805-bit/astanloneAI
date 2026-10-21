"""
Extension runtime - compile and run
===================================
`compile_source()` = validate + instrument + compile (one code object, nothing is executed). `run()` executes it:
a FRESH module per call (so one call can never influence the next except through the declared `storage`
permission), with `__builtins__ = {}` and exactly the namespace guards.make_runtime() builds, under a work/time
budget. The code object is run through importlib's own loader machinery (`exec_module`) - the same technique as the
Self-Builder sandbox - so this package contains no explicit dynamic-execution call.
"""

import importlib.machinery
import importlib.util
import json
import math
import re
import sys

from . import guards, limits
from .errors import LimitExceeded, SourceRejected
from .instrument import instrument
from .srcvalidate import validate_source

_PATH_RE = re.compile(r"[^A-Za-z0-9_.:<>-]")


class _CodeLoader(importlib.machinery.SourceFileLoader):
    """Hands the already-compiled, already-verified code object to importlib; never reads a file."""

    def __init__(self, fullname, path, code):
        super().__init__(fullname, path)
        self._ext_code = code

    def get_code(self, fullname):
        return self._ext_code

    def get_data(self, path):
        raise OSError("extension code is never read from disk at run time")


class CompiledExtension:
    __slots__ = ("capability_id", "entry", "code", "math_imports", "helpers_used", "functions", "path", "nodes")

    def __init__(self, capability_id, entry, code, report, path):
        self.capability_id = capability_id
        self.entry = entry
        self.code = code
        self.math_imports = tuple(report.math_imports)
        self.helpers_used = frozenset(report.helpers_used)
        self.functions = dict(report.functions)
        self.path = path
        self.nodes = report.nodes


def compile_source(source, input_names, capability_id="ext", entry="run"):
    """Validate, instrument and compile. Raises SourceRejected (with .issues) when the source is not acceptable."""
    report, tree = validate_source(source, input_names, entry)
    if tree is None:
        raise SourceRejected(f"{len(report.issues)} problem(s) in the extension source", issues=report.issues)
    path = "<ext:" + _PATH_RE.sub("_", str(capability_id))[:60] + ">"
    loader = _CodeLoader("ext_" + _PATH_RE.sub("_", str(capability_id))[:40], path, None)
    try:
        code = loader.source_to_code(instrument(tree), path)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise SourceRejected("the extension source cannot be compiled",
                             issues=[{"code": "compile", "line": int(getattr(e, "lineno", 0) or 0), "message": f"{type(e).__name__}: {e}"[:200]}]) from None
    return CompiledExtension(capability_id, entry, code, report, path)


# ------------------------------------------------------------------------------------------------ outputs
def to_json_value(value, depth=0):
    """A result value, checked and converted to plain JSON data (or ValueError)."""
    if depth > limits.MAX_OUTPUT_DEPTH:
        raise ValueError("result is nested too deeply")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value.bit_length() > limits.MAX_INT_BITS:
            raise ValueError("integer result too large")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("result contains a non-finite number")
        return value
    if isinstance(value, str):
        if len(value) > limits.MAX_OUTPUT_TEXT:
            raise ValueError("text result too long")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > limits.MAX_OUTPUT_LIST:
            raise ValueError("list result too long")
        return [to_json_value(v, depth + 1) for v in value]
    if isinstance(value, dict):
        if len(value) > 200:
            raise ValueError("object result has too many keys")
        out = {}
        for k, v in value.items():
            if not isinstance(k, str) or len(k) > 64:
                raise ValueError("result object keys must be short text")
            out[k] = to_json_value(v, depth + 1)
        return out
    raise ValueError(f"result of type {type(value).__name__} is not allowed")


def _error_line(exc, path):
    tb = exc.__traceback__
    line = 0
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == path:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _fail(code, kind, detail="", line=0, used=0):
    return {"ok": False, "error": {"code": code, "kind": kind, "detail": str(detail)[:limits.MAX_ERROR_DETAIL], "line": line},
            "fuel_used": int(used)}


def run(compiled, inputs, ctx=None, granted=frozenset(), fuel=limits.MAX_FUEL, seconds=limits.MAX_SECONDS, clock=None):
    """Run the extension once. Returns {"ok": True, "value": <json data>, "fuel_used": n} or {"ok": False, "error": {...}}."""
    budget = guards.Budget(fuel, seconds) if clock is None else guards.Budget(fuel, seconds, clock)
    start = int(fuel)

    def used():
        return start - budget.fuel
    hooks, ns = guards.make_runtime(budget, ctx, frozenset(granted))
    loader = _CodeLoader("ext_run", compiled.path, compiled.code)
    spec = importlib.util.spec_from_loader("ext_run", loader)
    module = importlib.util.module_from_spec(spec)
    d = module.__dict__
    d["__builtins__"] = {}
    d.update(ns)
    d.update(hooks)
    for name in compiled.math_imports:
        d[name] = vars(ns["math"])[name]
    try:
        loader.exec_module(module)
        fn = d.get(compiled.entry)
        if not callable(fn):
            return _fail("E_EXT_RUNTIME", "no_entry", f"{compiled.entry}() was not defined", used=used())
        result = fn(**inputs)
    except LimitExceeded as e:
        return _fail("E_EXT_LIMIT", e.kind, e, used=used())
    except RecursionError:
        return _fail("E_EXT_LIMIT", "recursion", "recursion too deep", used=used())
    except MemoryError:
        return _fail("E_EXT_LIMIT", "memory", "out of memory", used=used())
    except Exception as e:                                                       # the extension's own error
        return _fail("E_EXT_RUNTIME", type(e).__name__, e, _error_line(e, compiled.path), used())
    try:
        value = to_json_value(result)
        if len(json.dumps(value, ensure_ascii=False)) > limits.MAX_OUTPUT_BYTES:
            raise ValueError("result too large")
    except (ValueError, RecursionError) as e:
        return _fail("E_EXT_OUTPUT", "output", e, used=used())
    return {"ok": True, "value": value, "fuel_used": used()}
