"""
Self-Builder - sandbox
======================
Loads ONE validated generated module under restrictions and runs test suites
or capability calls against it, in-process (Android has no usable Python
subprocess, and the generated code is far too small to need one).

What makes this a sandbox rather than "just importing a file"
-------------------------------------------------------------
1. The file path must pass Policy.resolve() (allowed directory, name pattern,
   no symlinks, inside the Self-Builder root).
2. The bytes are read ONCE, size-limited, hash-checked against the registry
   (when a hash is known), decoded as ASCII and run through the AST allowlist
   (validator.py). The very same bytes are then compiled - the loader never
   re-reads the file, never reads or writes bytecode caches, so what was
   validated is exactly what runs.
3. The module namespace gets `__builtins__ = {}` (no builtins at all - not
   even `len`, `open`, `__import__`) plus the pre-bound helper functions of
   helpers.py and nothing else. The module is never put in `sys.modules`.
4. The validated shape (no loops, recursion, imports, attributes) means a call
   cannot run unboundedly; a soft wall-clock budget per call is still
   enforced and results are type- and size-checked.

There is no eval()/exec()/compile() call anywhere in the Self-Builder: the
standard import machinery (a `SourceFileLoader` subclass fed the verified
bytes) executes the module body, exactly as it would for any imported file -
but only for a file that passed steps 1-3.
"""

import hashlib
import importlib.machinery
import importlib.util
import math
import time

from . import helpers, mathcore, policy, templates, validator
from .errors import SandboxError, ValidationError


class _VerifiedSourceLoader(importlib.machinery.SourceFileLoader):
    """A source loader that compiles exactly the bytes it was constructed
    with: no file re-read, no bytecode cache read or write."""

    def __init__(self, fullname, path, source_bytes):
        super().__init__(fullname, path)
        self._source_bytes = source_bytes

    def get_data(self, path):
        if path == self.path:
            return self._source_bytes
        return super().get_data(path)

    def get_code(self, fullname):
        return self.source_to_code(self._source_bytes, self.path)

    def set_data(self, path, data, *, _mode=0o666):
        return None


class LoadedModule:
    """A loaded, validated capability module. `run()` never raises: it returns
    {"ok": True, "value": ...} or {"ok": False, "error": code, "detail": text}."""

    def __init__(self, module, capability_id, version, kind, sha256, source):
        self._module = module
        self.capability_id = capability_id
        self.version = version
        self.kind = kind
        self.sha256 = sha256
        self.source = source
        self._run = module.run

    def run(self, inputs):
        started = time.perf_counter()
        try:
            out = self._run(inputs)
        except mathcore.MathFailure as e:
            return {"ok": False, "error": e.code, "detail": e.detail}
        except Exception as e:  # generated code is not trusted to behave
            return {"ok": False, "error": "exception", "detail": type(e).__name__}
        elapsed = time.perf_counter() - started
        if elapsed > policy.MAX_CALL_SECONDS:
            return {"ok": False, "error": "timeout", "detail": f"call took {elapsed:.3f}s"}
        if not isinstance(out, dict) or set(out) != {"value"}:
            return {"ok": False, "error": "bad_output", "detail": "result must be {'value': ...}"}
        value = out["value"]
        if isinstance(value, bool):
            return {"ok": False, "error": "bad_output", "detail": "boolean result"}
        if isinstance(value, (int, float)):
            if not math.isfinite(value) or abs(value) > policy.MAX_RESULT_ABS:
                return {"ok": False, "error": "overflow", "detail": "result is not a finite number"}
            return {"ok": True, "value": float(value)}
        if isinstance(value, str):
            if len(value) > policy.MAX_INVOKE_TEXT_CHARS:
                return {"ok": False, "error": "bad_output", "detail": "result text too long"}
            return {"ok": True, "value": value}
        return {"ok": False, "error": "bad_output", "detail": f"result type {type(value).__name__}"}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_verified(path, expected_sha256=None):
    """Read a module file once (size-limited) and verify its hash."""
    try:
        with open(path, "rb") as f:
            data = f.read(policy.MAX_SOURCE_BYTES + 1)
    except OSError as e:
        raise SandboxError(f"module file unreadable: {type(e).__name__}", code="E_SANDBOX_READ") from None
    if len(data) > policy.MAX_SOURCE_BYTES:
        raise ValidationError("module file too large", code="E_VALIDATION", violations=[
            {"code": "V_SIZE", "message": "source too large", "line": None}])
    digest = sha256_bytes(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise SandboxError("module file hash differs from the registry", code="E_SANDBOX_HASH",
                           expected=expected_sha256, actual=digest)
    return data, digest


def load_module(root, subdir, filename, kind, capability_id, version, expected_sha256=None):
    """Load one generated module file under the sandbox rules above."""
    policy.Policy.check_operation(policy.OP_LOAD_MODULE)
    if subdir not in (policy.SUBDIR_STAGING, policy.SUBDIR_MODULES):
        raise SandboxError("modules are only loaded from staging/ or modules/", code="E_SANDBOX_DIR")
    path = policy.Policy.resolve(root, subdir, filename)
    data, digest = read_verified(path, expected_sha256)
    try:
        source = data.decode("ascii")
    except UnicodeDecodeError:
        raise ValidationError("module is not ASCII", code="E_VALIDATION", violations=[
            {"code": "V_ASCII", "message": "source must be ASCII", "line": None}]) from None
    validator.require_valid(source, kind, expected_id=capability_id, expected_version=version)

    module_name = f"sb_cap_{capability_id}_v{int(version)}"
    loader = _VerifiedSourceLoader(module_name, path, data)
    spec = importlib.util.spec_from_loader(module_name, loader, origin=path)
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__builtins__"] = {}
    module.__dict__.update(helpers.HELPERS)
    try:
        loader.exec_module(module)
    except Exception as e:
        raise SandboxError(f"module body failed: {type(e).__name__}", code="E_SANDBOX_EXEC") from None
    if not callable(getattr(module, "run", None)):
        raise SandboxError("module has no run()", code="E_SANDBOX_SHAPE")
    return LoadedModule(module, capability_id, int(version), kind, digest, source)


def run_suite(loaded, suite):
    """Run a generated/stored test suite against a loaded module.

    Returns {"total", "passed", "failed": [...], "ok", "duration_ms"}. Each
    case runs twice - a differing second result is a determinism failure."""
    started = time.perf_counter()
    failed = []
    cases = suite.get("cases", [])
    for case in cases:
        out = loaded.run(case["inputs"])
        ok, reason = templates.check_expectation(case["expect"], out.get("value"), out.get("error"))
        if ok:
            again = loaded.run(case["inputs"])
            if again != out:
                ok, reason = False, "result differs between two identical calls"
        if not ok:
            failed.append({"name": case["name"], "reason": reason, "inputs": case["inputs"],
                           "expect": case["expect"], "actual": out, "source": case.get("source", "auto")})
    total = len(cases)
    return {
        "total": total,
        "passed": total - len(failed),
        "failed": failed,
        "ok": total > 0 and not failed,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }
