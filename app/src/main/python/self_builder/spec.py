"""
Self-Builder - capability specs
===============================
A spec is the complete, JSON-serialisable description of ONE capability
version: what it is, what it takes, what it returns, and the data its
generated module is built from. The code templates (templates.py) turn a
spec into a module; nothing in a spec is ever executed or interpreted as
code.

Three archetypes (policy.SUPPORTED_ARCHETYPES):

  unit_conversion   value * scale + shift between two units
  formula           an arithmetic expression over named numeric variables
  text_tool         a chain (<= 3) of the reviewed text operations in textops

`validate_spec()` re-checks a spec from scratch (it is also run on specs
loaded from the registry), `spec_fingerprint()` hashes only the behaviour of
a spec so "I already have exactly this" can be detected.
"""

import hashlib
import json
import math

from . import expr as expr_mod
from . import fa_text, policy, textops, units
from .errors import SpecError

SPEC_SCHEMA = 1


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _short_hash(text, n=10):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SpecError(f"{name} must be a finite number", code="E_SPEC_NUMBER", field=name)
    return float(value)


def _clean_examples(examples, kind):
    out = []
    for ex in examples or []:
        if not isinstance(ex, dict) or not isinstance(ex.get("inputs"), dict) or "expected" not in ex:
            raise SpecError("bad example", code="E_SPEC_EXAMPLE")
        inputs = {}
        for k, v in ex["inputs"].items():
            if kind == policy.ARCHETYPE_TEXT_TOOL:
                if not isinstance(v, str):
                    raise SpecError("example text input must be text", code="E_SPEC_EXAMPLE")
                inputs[str(k)] = v
            else:
                inputs[str(k)] = _finite_number(v, "example input")
        expected = ex["expected"]
        if isinstance(expected, str):
            if len(expected) > policy.MAX_INVOKE_TEXT_CHARS:
                raise SpecError("example too long", code="E_SPEC_EXAMPLE")
        else:
            expected = _finite_number(expected, "example expected")
        item = {"inputs": inputs, "expected": expected}
        if ex.get("tolerance") is not None:
            item["tolerance"] = _finite_number(ex["tolerance"], "example tolerance")
        if ex.get("positional") is not None:
            item["positional"] = [_finite_number(v, "example input") for v in ex["positional"]]
        out.append(item)
    if len(out) > 12:
        raise SpecError("too many examples", code="E_SPEC_EXAMPLE")
    return out


# ------------------------------------------------------------ unit conversion

def _unit_ref(unit, surface):
    """Reference of one side of a conversion: a table unit or a custom name."""
    if unit is not None:
        keys = units.match_keys(unit.id)
        if surface:
            k = fa_text.key(surface)
            if k and k not in keys:
                keys.append(k)
        return {"id": unit.id, "name": unit.display, "dimension": unit.dimension, "keys": sorted(keys)}
    name = (surface or "").strip()
    key = fa_text.key(name)
    if not key:
        raise SpecError("unit name is empty", code="E_SPEC_UNIT")
    return {"id": "custom_" + _short_hash(key, 6), "name": name, "dimension": None, "keys": [key]}


def unit_conversion_spec(from_unit, to_unit, from_name=None, to_name=None, factor=None,
                         examples=None, title=None):
    """Spec for a conversion `from -> to`.

    `from_unit`/`to_unit`: units.Unit for a table unit, or None for a unit
    the user named himself (then `from_name`/`to_name` carry the text).
    `factor` (units of `to` per 1 `from`): required when either unit is not
    in the table, optional otherwise (it then overrides the table value and
    the deviation is recorded in `reference`)."""
    ref_from = _unit_ref(from_unit, from_name)
    ref_to = _unit_ref(to_unit, to_name)
    if ref_from["keys"] and set(ref_from["keys"]) & set(ref_to["keys"]):
        raise SpecError("both units are the same", code="E_SPEC_SAME_UNIT")
    reference = None
    if from_unit is not None and to_unit is not None:
        if from_unit.dimension == to_unit.dimension:
            table_scale, table_shift = units.conversion_params(from_unit, to_unit)
            reference = {"scale": table_scale, "shift": table_shift}
        elif factor is None:
            units.conversion_params(from_unit, to_unit)  # raises E_SPEC_DIMENSION
    if factor is not None:
        scale = _finite_number(factor, "factor")
        shift = 0.0
        if reference is not None and from_unit.dimension == "temperature":
            raise SpecError("temperature conversions cannot use a plain factor", code="E_SPEC_FACTOR")
        standard = (reference is not None and reference["shift"] == 0.0
                    and abs(scale - reference["scale"]) <= 1e-9 * abs(reference["scale"]))
    elif reference is not None:
        scale, shift, standard = reference["scale"], reference["shift"], True
    else:
        raise SpecError("a conversion factor is required for units that are not in the unit table",
                        code="E_SPEC_FACTOR_REQUIRED")
    if scale == 0.0 or not (1e-12 <= abs(scale) <= 1e12):
        raise SpecError("conversion factor out of range", code="E_SPEC_FACTOR")
    shift = _finite_number(shift, "shift")
    if from_unit is not None and to_unit is not None:
        cid = f"unit_{from_unit.id}_to_{to_unit.id}"
    else:
        cid = "unit_c_" + _short_hash(ref_from["keys"][0] + ">" + ref_to["keys"][0], 10)
    title = title or f"تبدیل {ref_from['name']} به {ref_to['name']}"
    spec = {
        "schema": SPEC_SCHEMA,
        "kind": policy.ARCHETYPE_UNIT_CONVERSION,
        "capability_id": cid,
        "title": title,
        "description": f"تبدیل {ref_from['name']} به {ref_to['name']} (مقدار × {fa_text.format_number(scale, 9)}"
                       + (f" + {fa_text.format_number(shift, 9)}" if shift else "") + ")",
        "from": ref_from,
        "to": ref_to,
        "scale": scale,
        "shift": shift,
        "standard": bool(standard),
        "reference": reference,
        "inputs": [{"name": "value", "type": "number", "label": f"مقدار ({ref_from['name']})"}],
        "outputs": [{"name": "value", "type": "number", "label": f"مقدار ({ref_to['name']})"}],
        "examples": _clean_examples(examples, policy.ARCHETYPE_UNIT_CONVERSION),
        "dependencies": ["helper:_sb_finite", "helper:_sb_number_input"],
        "permissions": [policy.PERMISSION_COMPUTE],
    }
    return spec


# --------------------------------------------------------------------- formula

def formula_spec(title, expression, variable_labels=None, examples=None, result_label=None,
                 variable_order=None):
    """Spec for a formula.

    `expression`: STRICT ASCII expression text (see expr.py); the caller
    (repair.py) is responsible for turning user wording into it.
    `variable_labels`: {variable name: Persian label} (display/matching only).
    `variable_order`: order of the inputs (a permutation of the expression's
    variables; default = order of first appearance). An example may give its
    values as `positional` (in input order) instead of by name."""
    title = (title or "").strip()
    if not fa_text.key(title):
        raise SpecError("a formula needs a name", code="E_SPEC_TITLE")
    if len(title) > 60:
        raise SpecError("formula name too long", code="E_SPEC_TITLE")
    tree = expr_mod.parse(expression)
    names = expr_mod.variables(tree)
    if not names:
        raise SpecError("a formula needs at least one variable", code="E_SPEC_NO_VARIABLES")
    if len(names) > policy.MAX_VARIABLES:
        raise SpecError("too many variables", code="E_SPEC_TOO_MANY_VARIABLES", limit=policy.MAX_VARIABLES)
    if variable_order is not None:
        if sorted(variable_order) != sorted(names):
            raise SpecError("variable order must be a permutation of the formula's variables",
                            code="E_SPEC_VARIABLES")
        names = list(variable_order)
    prepared = []
    for ex in examples or []:
        ex = dict(ex)
        if ex.get("positional") is not None:
            if len(ex["positional"]) != len(names):
                raise SpecError("example has the wrong number of values", code="E_SPEC_EXAMPLE")
            ex["inputs"] = {n: v for n, v in zip(names, ex["positional"])}
        prepared.append(ex)
    examples = prepared
    labels = dict(variable_labels or {})
    variables = []
    for name in names:
        label = (labels.get(name) or name).strip()
        aliases = sorted({k for k in (fa_text.key(label), fa_text.key(name)) if k})
        variables.append({"name": name, "label": label, "aliases": aliases})
    cid = "formula_" + _short_hash(fa_text.key(title), 10)
    result_label = (result_label or title).strip()
    spec = {
        "schema": SPEC_SCHEMA,
        "kind": policy.ARCHETYPE_FORMULA,
        "capability_id": cid,
        "title": title,
        "description": f"محاسبهٔ «{title}» با فرمول {expression}",
        "expression": expression.strip(),
        "tree": tree,
        "variables": variables,
        "result_label": result_label,
        "title_key": fa_text.key(title),
        "inputs": [{"name": v["name"], "type": "number", "label": v["label"]} for v in variables],
        "outputs": [{"name": "value", "type": "number", "label": result_label}],
        "examples": _clean_examples(examples, policy.ARCHETYPE_FORMULA),
        "dependencies": ["helper:" + h for h in expr_mod.helper_names_used(tree)]
                        + ["helper:_sb_finite", "helper:_sb_number_input"],
        "permissions": [policy.PERMISSION_COMPUTE],
    }
    spec["dependencies"] = sorted(set(spec["dependencies"]))
    return spec


# ------------------------------------------------------------------- text tool

def _text_tool_id(op_list):
    cid = "text_" + "_".join(op_list)
    if len(cid) > 48:
        cid = "text_" + _short_hash("|".join(op_list), 12)
    return cid


def text_tool_spec(op_list, title=None, examples=None):
    ops = list(op_list or [])
    if not 1 <= len(ops) <= textops.MAX_CHAIN:
        raise SpecError("a text tool chains 1 to 3 operations", code="E_SPEC_OPS")
    for i, op in enumerate(ops):
        if op not in textops.OPS:
            raise SpecError(f"unknown text operation {op!r}", code="E_SPEC_OPS", op=str(op))
        if textops.op_kind(op) == "number" and i != len(ops) - 1:
            raise SpecError("a numeric operation must be the last step", code="E_SPEC_OPS", op=op)
    output_kind = textops.op_kind(ops[-1])
    labels = [textops.op_label(o) for o in ops]
    title = (title or " و ".join(labels)).strip()
    spec = {
        "schema": SPEC_SCHEMA,
        "kind": policy.ARCHETYPE_TEXT_TOOL,
        "capability_id": _text_tool_id(ops),
        "title": title,
        "description": "ابزار متنی: " + " ← ".join(labels),
        "ops": ops,
        "output_kind": output_kind,
        "triggers": sorted({fa_text.key(p) for o in ops for p in textops.OPS[o][3] if fa_text.key(p)}),
        "inputs": [{"name": "text", "type": "text", "label": "متن"}],
        "outputs": [{"name": "value", "type": "number" if output_kind == "number" else "text",
                     "label": "نتیجه"}],
        "examples": _clean_examples(examples, policy.ARCHETYPE_TEXT_TOOL),
        "dependencies": sorted({"helper:" + textops.HELPER_PREFIX + o for o in ops} | {"helper:_sb_text_input"}),
        "permissions": [policy.PERMISSION_COMPUTE],
    }
    return spec


# ------------------------------------------------------------------ validation

_REQUIRED_COMMON = ("schema", "kind", "capability_id", "title", "description", "inputs", "outputs",
                    "dependencies", "permissions")


def validate_spec(spec):
    """Full re-validation of a spec (also run on specs read back from the
    registry). Returns the spec; raises SpecError / PolicyViolation."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be an object", code="E_SPEC")
    for key in _REQUIRED_COMMON:
        if key not in spec:
            raise SpecError(f"spec field missing: {key}", code="E_SPEC_FIELD", field=key)
    if spec["schema"] != SPEC_SCHEMA:
        raise SpecError("unsupported spec schema", code="E_SPEC_SCHEMA")
    policy.Policy.check_archetype(spec["kind"])
    policy.Policy.check_capability_id(spec["capability_id"])
    policy.Policy.check_permissions(spec["permissions"])
    kind = spec["kind"]
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        for key in ("from", "to", "scale", "shift"):
            if key not in spec:
                raise SpecError(f"spec field missing: {key}", code="E_SPEC_FIELD", field=key)
        scale = _finite_number(spec["scale"], "scale")
        _finite_number(spec["shift"], "shift")
        if scale == 0.0 or not (1e-12 <= abs(scale) <= 1e12):
            raise SpecError("conversion factor out of range", code="E_SPEC_FACTOR")
    elif kind == policy.ARCHETYPE_FORMULA:
        tree = expr_mod.parse(spec.get("expression", ""))
        names = expr_mod.variables(tree)
        declared = [v.get("name") for v in spec.get("variables", [])]
        if sorted(names) != sorted(declared) or len(set(declared)) != len(declared):
            raise SpecError("formula variables do not match the expression", code="E_SPEC_VARIABLES")
        if not names or len(names) > policy.MAX_VARIABLES:
            raise SpecError("bad number of variables", code="E_SPEC_VARIABLES")
        if spec.get("tree") != tree:
            raise SpecError("stored expression tree does not match the expression", code="E_SPEC_TREE")
    else:
        ops = spec.get("ops")
        text_tool_spec(ops)  # re-runs the structural checks
    if len(spec["capability_id"]) > 48:
        raise SpecError("capability id too long", code="E_SPEC_ID")
    _clean_examples(spec.get("examples"), kind)
    return spec


def spec_fingerprint(spec):
    """SHA-256 of the *behaviour* of a spec (not its title/examples)."""
    kind = spec["kind"]
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        core = {"kind": kind, "from": spec["from"]["id"], "to": spec["to"]["id"],
                "scale": repr(float(spec["scale"])), "shift": repr(float(spec["shift"]))}
    elif kind == policy.ARCHETYPE_FORMULA:
        core = {"kind": kind, "tree": spec["tree"], "variables": [v["name"] for v in spec["variables"]]}
    else:
        core = {"kind": kind, "ops": list(spec["ops"])}
    return sha256_text(canonical_json(core))


def input_names(spec):
    return [i["name"] for i in spec["inputs"]]
