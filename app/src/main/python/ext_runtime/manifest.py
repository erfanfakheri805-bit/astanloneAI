"""
Extension runtime - the `ext.v1` manifest
=========================================
A package is ONE JSON object: metadata + declared inputs/outputs + dependencies + permissions + the Python source +
trigger phrases + tests. This module validates and normalizes it (strictly: unknown keys are errors, so a typo such
as "permission" can never silently drop a requested permission), fingerprints it, checks call inputs and results
against the declared types, renders the Persian answer and compares test expectations. It never runs any code.
"""

import hashlib
import json
import math
import re

from self_builder import fa_text

from . import limits, patterns
from .errors import ExtError, ManifestError

API_LEVEL = 1
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
_TOP_KEYS = ("schema", "api", "id", "title", "description", "version_label", "inputs", "outputs", "dependencies", "permissions",
             "entry", "source", "triggers", "answer", "examples", "tests", "fixtures", "provenance")
_INPUT_KEYS = ("name", "type", "label", "required", "default", "min", "max", "max_items")
_OUTPUT_KEYS = ("name", "type", "label")
_TEST_KEYS = ("name", "inputs", "expect", "expect_error")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _text(x, lo, hi):
    return isinstance(x, str) and lo <= len(x.strip()) and len(x) <= hi


class _Issues:
    def __init__(self):
        self.items = []

    def add(self, code, path, message):
        if len(self.items) < 40:
            self.items.append({"code": code, "path": path, "message": message})

    def raise_if_any(self):
        if self.items:
            raise ManifestError(f"{len(self.items)} problem(s) in the extension manifest", issues=self.items)


def _json_ok(value, depth=0):
    if depth > 6:
        return False
    if value is None or isinstance(value, (bool, str)) or _num(value):
        return True
    if isinstance(value, list):
        return len(value) <= 200 and all(_json_ok(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return len(value) <= 100 and all(isinstance(k, str) and len(k) <= 64 and _json_ok(v, depth + 1) for k, v in value.items())
    return False


def _check_value_type(value, typ, spec=None):
    """None when `value` fits the declared input type, else a short reason."""
    if typ == limits.TYPE_NUMBER:
        return None if _num(value) else "must be a finite number"
    if typ == limits.TYPE_INTEGER:
        return None if (isinstance(value, int) and not isinstance(value, bool)) else "must be an integer"
    if typ == limits.TYPE_TEXT:
        return None if isinstance(value, str) and len(value) <= limits.MAX_TEXT_INPUT_CHARS else "must be text"
    if typ == limits.TYPE_BOOLEAN:
        return None if isinstance(value, bool) else "must be true or false"
    cap = min(int((spec or {}).get("max_items", limits.MAX_LIST_INPUT_ITEMS)), limits.MAX_LIST_INPUT_ITEMS)
    if typ == limits.TYPE_LIST_NUMBER:
        return None if isinstance(value, list) and len(value) <= cap and all(_num(v) for v in value) else f"must be a list of at most {cap} numbers"
    if typ == limits.TYPE_LIST_TEXT:
        return None if isinstance(value, list) and len(value) <= cap and all(isinstance(v, str) and len(v) <= 2000 for v in value) \
            else f"must be a list of at most {cap} texts"
    return "unknown type"


def validate_manifest(obj, source=None):
    """Return the NORMALIZED manifest (a new dict) or raise ManifestError listing every problem found.
    `source` (optional) replaces/provides the "source" field, for packages that ship the code as a separate file."""
    iss = _Issues()
    if not isinstance(obj, dict):
        raise ManifestError("an extension package must be a JSON object", issues=[{"code": "type", "path": "", "message": "not an object"}])
    obj = dict(obj)
    if source is not None:
        obj["source"] = source
    for k in obj:
        if k not in _TOP_KEYS:
            iss.add("unknown_key", k, f"unknown key {k!r} (allowed: {', '.join(_TOP_KEYS)})")
    if obj.get("schema") != limits.EXT_SCHEMA:
        iss.add("schema", "schema", f"schema must be {limits.EXT_SCHEMA!r}")
    api = obj.get("api", API_LEVEL)
    if not isinstance(api, int) or isinstance(api, bool) or api < 1:
        iss.add("api", "api", "api must be a positive integer")
    elif api > API_LEVEL:
        iss.add("incompatible", "api", f"this package needs extension API level {api}, this app supports {API_LEVEL}")
    cid = obj.get("id")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        iss.add("id", "id", "id must be 3-40 characters: lowercase ASCII letters, digits, underscore; starting with a letter")
    title = obj.get("title")
    if not _text(title, 2, limits.MAX_TITLE_CHARS):
        iss.add("title", "title", f"title must be 2-{limits.MAX_TITLE_CHARS} characters")
    desc = obj.get("description")
    if not _text(desc, 5, limits.MAX_DESCRIPTION_CHARS):
        iss.add("description", "description", f"description must be 5-{limits.MAX_DESCRIPTION_CHARS} characters")
    label = obj.get("version_label", "")
    if not isinstance(label, str) or len(label) > 20:
        iss.add("version_label", "version_label", "version_label must be text of at most 20 characters")
    if obj.get("entry", "run") != "run":
        iss.add("entry", "entry", "the entry point must be 'run'")
    src = obj.get("source")
    if not isinstance(src, str) or not src.strip():
        iss.add("source", "source", "source (the Python code) is required")
    elif len(src.encode("utf-8", "replace")) > limits.MAX_SOURCE_BYTES:
        iss.add("source", "source", f"source is larger than {limits.MAX_SOURCE_BYTES} bytes")

    inputs, outputs = [], []
    raw_in = obj.get("inputs", [])
    if not isinstance(raw_in, list) or len(raw_in) > limits.MAX_INPUTS:
        iss.add("inputs", "inputs", f"inputs must be a list of at most {limits.MAX_INPUTS} entries")
        raw_in = []
    for i, it in enumerate(raw_in):
        path = f"inputs[{i}]"
        if not isinstance(it, dict):
            iss.add("inputs", path, "must be an object")
            continue
        for k in it:
            if k not in _INPUT_KEYS:
                iss.add("unknown_key", f"{path}.{k}", f"unknown key {k!r}")
        name, typ = it.get("name"), it.get("type")
        if not isinstance(name, str) or not NAME_RE.match(name):
            iss.add("name", path + ".name", "input names are lowercase ASCII snake_case (they are Python parameter names)")
            continue
        if any(x["name"] == name for x in inputs):
            iss.add("name", path + ".name", f"duplicate input {name!r}")
        if typ not in limits.INPUT_TYPES:
            iss.add("type", path + ".type", f"type must be one of {', '.join(limits.INPUT_TYPES)}")
            continue
        ent = {"name": name, "type": typ, "label": str(it.get("label", name))[:limits.MAX_LABEL_CHARS],
               "required": it.get("required", True)}
        if not isinstance(ent["required"], bool):
            iss.add("required", path + ".required", "required must be true or false")
        for bound in ("min", "max"):
            if bound in it:
                if typ not in (limits.TYPE_NUMBER, limits.TYPE_INTEGER) or not _num(it[bound]):
                    iss.add("bound", f"{path}.{bound}", f"{bound} is only valid on number/integer inputs and must be a number")
                else:
                    ent[bound] = it[bound]
        if "max_items" in it:
            if typ not in (limits.TYPE_LIST_NUMBER, limits.TYPE_LIST_TEXT) or not isinstance(it["max_items"], int) \
                    or isinstance(it["max_items"], bool) or not 1 <= it["max_items"] <= limits.MAX_LIST_INPUT_ITEMS:
                iss.add("bound", path + ".max_items", f"max_items is only valid on list inputs, 1..{limits.MAX_LIST_INPUT_ITEMS}")
            else:
                ent["max_items"] = it["max_items"]
        if "default" in it:
            if it["default"] is not None and _check_value_type(it["default"], typ, ent):
                iss.add("default", path + ".default", "the default does not fit the input type")
            else:
                ent["default"] = it["default"]
        elif ent["required"] is False:
            ent["default"] = None
        inputs.append(ent)
    raw_out = obj.get("outputs")
    if not isinstance(raw_out, list) or not 1 <= len(raw_out) <= limits.MAX_OUTPUTS:
        iss.add("outputs", "outputs", f"outputs must list 1-{limits.MAX_OUTPUTS} entries")
        raw_out = []
    for i, it in enumerate(raw_out):
        path = f"outputs[{i}]"
        if not isinstance(it, dict):
            iss.add("outputs", path, "must be an object")
            continue
        for k in it:
            if k not in _OUTPUT_KEYS:
                iss.add("unknown_key", f"{path}.{k}", f"unknown key {k!r}")
        name, typ = it.get("name"), it.get("type")
        if not isinstance(name, str) or not NAME_RE.match(name):
            iss.add("name", path + ".name", "output names are lowercase ASCII snake_case")
            continue
        if any(x["name"] == name for x in outputs) or any(x["name"] == name for x in inputs):
            iss.add("name", path + ".name", f"{name!r} is already used by another input/output")
        if typ not in limits.OUTPUT_TYPES:
            iss.add("type", path + ".type", f"type must be one of {', '.join(limits.OUTPUT_TYPES)}")
            continue
        outputs.append({"name": name, "type": typ, "label": str(it.get("label", name))[:limits.MAX_LABEL_CHARS]})

    deps = obj.get("dependencies", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        iss.add("dependencies", "dependencies", "dependencies must be a list of names")
        deps = []
    for d in deps:
        if d not in limits.ALLOWED_DEPENDENCIES:
            iss.add("dependency", "dependencies", f"dependency {d!r} is not available inside the app "
                                                  f"(available: {', '.join(limits.ALLOWED_DEPENDENCIES)}); packages cannot be installed from the internet")
    perms = obj.get("permissions", [limits.PERM_COMPUTE])
    if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
        iss.add("permissions", "permissions", "permissions must be a list of names")
        perms = []
    for p in perms:
        if p not in limits.ALL_PERMISSIONS:
            iss.add("permission", "permissions", f"permission {p!r} is unknown (allowed: {', '.join(limits.ALL_PERMISSIONS)})")

    types = {x["name"]: x["type"] for x in inputs}
    trig_in = obj.get("triggers")
    triggers = []
    if not isinstance(trig_in, list) or not 1 <= len(trig_in) <= limits.MAX_TRIGGERS:
        iss.add("triggers", "triggers", f"triggers must list 1-{limits.MAX_TRIGGERS} trigger phrases")
    else:
        for i, t in enumerate(trig_in):
            try:
                patterns.compile_trigger(t, types)
                triggers.append(t.strip())
            except patterns.PatternError as e:
                iss.add("trigger", f"triggers[{i}]", str(e))
    examples = obj.get("examples", [])
    if not isinstance(examples, list) or len(examples) > 5 or not all(isinstance(e, str) and len(e) <= 200 for e in examples):
        iss.add("examples", "examples", "examples must be a list of at most 5 short texts")
        examples = []

    names = {x["name"] for x in inputs} | {x["name"] for x in outputs}
    answer = obj.get("answer")
    if answer is None and outputs:
        answer = "نتیجه: {%s}" % outputs[0]["name"] if len(outputs) == 1 else "؛ ".join("%s: {%s}" % (o["label"], o["name"]) for o in outputs)
    if not isinstance(answer, str) or not 1 <= len(answer) <= 300:
        iss.add("answer", "answer", "answer must be a template of at most 300 characters")
    else:
        for ph in _PLACEHOLDER_RE.findall(answer):
            if ph not in names:
                iss.add("answer", "answer", f"placeholder {{{ph}}} is not a declared input or output")
        if re.sub(_PLACEHOLDER_RE, "", answer).count("{") or re.sub(_PLACEHOLDER_RE, "", answer).count("}"):
            iss.add("answer", "answer", "unbalanced braces in the answer template")

    tests = []
    raw_tests = obj.get("tests")
    if not isinstance(raw_tests, list) or not 1 <= len(raw_tests) <= limits.MAX_TESTS:
        iss.add("tests", "tests", f"tests must list 1-{limits.MAX_TESTS} test cases (an extension without tests is never activated)")
        raw_tests = []
    skeleton = {"inputs": inputs}
    for i, t in enumerate(raw_tests):
        path = f"tests[{i}]"
        if not isinstance(t, dict):
            iss.add("tests", path, "must be an object")
            continue
        for k in t:
            if k not in _TEST_KEYS:
                iss.add("unknown_key", f"{path}.{k}", f"unknown key {k!r}")
        given = t.get("inputs", {})
        if not isinstance(given, dict):
            iss.add("tests", path + ".inputs", "must be an object")
            continue
        _, problems = coerce_inputs(skeleton, given)
        for p in problems:
            iss.add("test_input", f"{path}.inputs.{p['name']}", p["message"])
        has_expect, has_err = "expect" in t, "expect_error" in t
        if has_expect == has_err:
            iss.add("tests", path, "give exactly one of expect / expect_error")
            continue
        case = {"name": str(t.get("name", f"test {i + 1}"))[:60], "inputs": given}
        if has_expect:
            exp = t["expect"]
            if not isinstance(exp, dict) or not exp or any(k not in {o["name"] for o in outputs} for k in exp) or not _json_ok(exp):
                iss.add("tests", path + ".expect", "expect must be an object whose keys are declared outputs")
                continue
            case["expect"] = exp
        else:
            if t["expect_error"] is not True:
                iss.add("tests", path + ".expect_error", "expect_error must be true")
                continue
            case["expect_error"] = True
        tests.append(case)
    if raw_tests and not any("expect" in t for t in tests):
        iss.add("tests", "tests", "at least one test must check a successful result")

    fixtures = obj.get("fixtures")
    if fixtures is not None:
        ok = isinstance(fixtures, dict) and set(fixtures) <= {"clock", "store", "web"} and _json_ok(fixtures)
        if ok and "clock" in fixtures and not _num(fixtures["clock"]):
            ok = False
        if ok and "store" in fixtures and not isinstance(fixtures["store"], dict):
            ok = False
        if ok and "web" in fixtures and not (isinstance(fixtures["web"], dict) and len(fixtures["web"]) <= 10
                                            and all(isinstance(v, str) and len(v) <= limits.MAX_FETCH_TEXT for v in fixtures["web"].values())):
            ok = False
        if not ok:
            iss.add("fixtures", "fixtures", "fixtures: {clock: number, store: {...}, web: {url: text}} (at most 10 pages)")
            fixtures = None
    prov = obj.get("provenance", {})
    if not isinstance(prov, dict) or set(prov) - {"author", "source", "note"} or \
            not all(isinstance(v, str) and len(v) <= limits.MAX_PROVENANCE_CHARS for v in prov.values()):
        iss.add("provenance", "provenance", "provenance: {author, source, note} as short texts")
        prov = {}
    iss.raise_if_any()
    out = {"schema": limits.EXT_SCHEMA, "api": api, "id": cid, "title": title.strip(), "description": desc.strip(),
           "version_label": label, "inputs": inputs, "outputs": outputs, "dependencies": sorted(set(deps)),
           "permissions": sorted(set(perms) | {limits.PERM_COMPUTE}), "entry": "run", "source": src, "triggers": triggers,
           "answer": answer, "examples": examples, "tests": tests}
    if fixtures is not None:
        out["fixtures"] = fixtures
    if prov:
        out["provenance"] = prov
    return out


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(manifest):
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def check_source_consistency(manifest, compiled):
    """Declared permissions/dependencies versus what the validated source actually uses. Returns a list of issues."""
    problems = []
    needed = {limits.HELPER_TO_PERMISSION[h] for h in compiled.helpers_used}
    declared = set(manifest["permissions"]) - {limits.PERM_COMPUTE}
    for p in sorted(needed - declared):
        problems.append({"code": "permission_undeclared", "path": "permissions",
                         "message": f"the code uses a {p!r} helper but the manifest does not declare the {p!r} permission"})
    for p in sorted(declared - needed):
        problems.append({"code": "permission_unused", "path": "permissions",
                         "message": f"the manifest asks for the {p!r} permission but the code never uses it (least privilege)"})
    uses_math = "import math" in manifest["source"] or bool(compiled.math_imports) or "math." in manifest["source"]
    if uses_math and "math" not in manifest["dependencies"]:
        problems.append({"code": "dependency_undeclared", "path": "dependencies", "message": "the code uses math but dependencies does not list 'math'"})
    return problems


# ------------------------------------------------------------------------------------------------ run-time inputs/outputs
def coerce_inputs(manifest, given):
    """(inputs, problems): declared inputs filled from `given` (defaults for optional ones), each checked. Never raises."""
    given = given if isinstance(given, dict) else {}
    result, problems = {}, []
    declared = {x["name"] for x in manifest["inputs"]}
    for k in given:
        if k not in declared:
            problems.append({"name": str(k)[:30], "code": "unknown_input", "message": "this input is not declared"})
    for spec in manifest["inputs"]:
        name, typ = spec["name"], spec["type"]
        if name not in given or given[name] is None:
            if spec.get("required", True):
                problems.append({"name": name, "code": "missing", "message": "this input is required"})
            else:
                result[name] = spec.get("default")
            continue
        value = given[name]
        if typ == limits.TYPE_INTEGER and isinstance(value, float) and value.is_integer():
            value = int(value)
        reason = _check_value_type(value, typ, spec)
        if reason:
            problems.append({"name": name, "code": "type", "message": reason})
            continue
        if "min" in spec and value < spec["min"]:
            problems.append({"name": name, "code": "range", "message": f"must be at least {spec['min']}"})
            continue
        if "max" in spec and value > spec["max"]:
            problems.append({"name": name, "code": "range", "message": f"must be at most {spec['max']}"})
            continue
        result[name] = value
    return result, problems


def check_outputs(manifest, value):
    """The result of run() as {output_name: value}; raises ExtError(E_EXT_OUTPUT) when it does not match the declaration."""
    outs = manifest["outputs"]
    if not isinstance(value, dict):
        if len(outs) != 1:
            raise ExtError("run() must return an object with the declared output names", code="E_EXT_OUTPUT")
        value = {outs[0]["name"]: value}
    declared = {o["name"]: o["type"] for o in outs}
    if set(value) != set(declared):
        raise ExtError(f"run() returned keys {sorted(value)} but the manifest declares {sorted(declared)}", code="E_EXT_OUTPUT")
    for name, typ in declared.items():
        v = value[name]
        ok = (typ == limits.TYPE_NUMBER and _num(v)) or (typ == limits.TYPE_INTEGER and isinstance(v, int) and not isinstance(v, bool)) \
            or (typ == limits.TYPE_TEXT and isinstance(v, str)) or (typ == limits.TYPE_BOOLEAN and isinstance(v, bool)) \
            or (typ == "list" and isinstance(v, list)) or typ == "json"
        if not ok:
            raise ExtError(f"output {name!r} should be {typ}, got {type(v).__name__}", code="E_EXT_OUTPUT")
    return value


def _fmt(v):
    if isinstance(v, bool):
        return "بله" if v else "خیر"
    if isinstance(v, (int, float)):
        return fa_text.fa_number(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "، ".join(_fmt(x) for x in v)
    return json.dumps(v, ensure_ascii=False)


def render_answer(manifest, inputs, outputs):
    values = {**inputs, **outputs}
    return _PLACEHOLDER_RE.sub(lambda m: _fmt(values.get(m.group(1), "")), manifest["answer"])[:2000]


def compare_expected(expected, actual, path="value"):
    """(ok, reason). Numbers match within 1e-9 relative/absolute, or `{"approx": x, "tol": t}`."""
    if isinstance(expected, dict) and set(expected) <= {"approx", "tol"} and "approx" in expected:
        tol = float(expected.get("tol", 1e-9))
        ok = _num(actual) and abs(actual - expected["approx"]) <= tol
        return ok, "" if ok else f"{path}: expected about {expected['approx']} (+-{tol}), got {actual!r}"
    if isinstance(expected, bool) or isinstance(actual, bool) or expected is None or actual is None:
        return expected == actual and type(expected) is type(actual), "" if expected == actual and type(expected) is type(actual) \
            else f"{path}: expected {expected!r}, got {actual!r}"
    if _num(expected) and _num(actual):
        ok = abs(expected - actual) <= 1e-9 * max(1.0, abs(expected))
        return ok, "" if ok else f"{path}: expected {expected!r}, got {actual!r}"
    if isinstance(expected, str) and isinstance(actual, str):
        return expected == actual, "" if expected == actual else f"{path}: expected {expected!r}, got {actual!r}"
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False, f"{path}: expected {len(expected)} items, got {len(actual)}"
        for i, (e, a) in enumerate(zip(expected, actual)):
            ok, why = compare_expected(e, a, f"{path}[{i}]")
            if not ok:
                return False, why
        return True, ""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            return False, f"{path}: expected keys {sorted(expected)}, got {sorted(actual)}"
        for k in expected:
            ok, why = compare_expected(expected[k], actual[k], f"{path}.{k}")
            if not ok:
                return False, why
        return True, ""
    return False, f"{path}: expected {expected!r}, got {actual!r}"
