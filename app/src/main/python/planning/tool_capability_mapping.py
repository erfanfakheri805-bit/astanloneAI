"""
Explicit Capability Mapping Contract (Prompt 710, Section 6) - decision F2
============================================================================
A small, PURE translation table between two vocabularies that are deliberately different:

    Section 4  `PlanStep.required_capabilities`   free-form strings (any non-empty text)
    Section 5  tool capability grants             names matching ^[a-z][a-z0-9_]{0,63}\\Z  (`ToolRequest.granted_capabilities`)

    map_required_capabilities(required_capabilities, mapping) -> CapabilityMappingResult
    find_ungranted_capabilities(mapping_result, granted_capabilities) -> tuple of Section 5 names the caller did not grant

MAPPING IS TRANSLATION, NOT AUTHORIZATION
- The caller supplies BOTH inputs: the Section 4 names it wants translated and the mapping. Nothing is inferred, guessed,
  discovered, learned, defaulted, normalized, trimmed, lower-cased or read from a plan, a registry or a tool. The module has no
  state, imports nothing (not even `tools`), reads no plan and calls no registry.
- A mapping can never create a grant. It only says "Section 4 name X means Section 5 grant name(s) Y". Whether Y was actually
  granted is decided by the caller's `ToolRequest`, and whether Y is enough for the tool is decided by Section 5 alone
  (`registry.preflight()` / `_evaluate()`), which is untouched.
- Input structures are never mutated; results hold tuples and `to_dict()` returns fresh copies.

MAPPING STRUCTURE (explicit; a list/tuple of entries)
    [{"capability": "<Section 4 name>", "grants": ["<Section 5 name>", ...]}, ...]
  - `capability`: a non-empty (not whitespace-only) `str`, compared exactly (Section 4 names are free-form, so no case folding).
  - `grants`: a NON-EMPTY list/tuple of valid Section 5 names, order significant (a set has no order and is refused). One
    requirement may need several grants (one-to-many).
  - exactly those two keys; anything else is an invalid entry. A `dict` shortcut is deliberately not accepted, because a dict
    cannot represent a duplicate or conflicting entry and so could hide one.
  - the same `capability` twice is `DUPLICATE_MAPPING_ENTRY` (identical grants) or `CONFLICTING_MAPPING_ENTRY` (different grants);
    the same grant twice inside one entry is `DUPLICATE_MAPPING_GRANT`. Nothing is merged or "last wins".
  An empty mapping (`[]`) is a valid structure (it simply maps nothing).

RESULT STATUS (`CapabilityMappingResult.status`), checked in this order
    `invalid_input`    `required_capabilities` is not a list/tuple of non-empty strings.
    `invalid_mapping`  the mapping structure or any entry is invalid (`invalid_entries` lists every problem; no translation is attempted).
    `unmapped`         the mapping is valid but at least one required name has no entry (`missing`, in required order); the
                       mapped part is still reported in `resolved` / `grant_names`, nothing is silently dropped.
    `satisfied`        every required name is mapped; `grant_names` is the resulting Section 5 grant list.
  `ok` is True only for `satisfied`.

DETERMINISM
  `required` keeps the caller's order (an exact repeat of a name is collapsed once - it is the same requirement, not a dropped one).
  `resolved` follows `required`; `grant_names` is the concatenation of the resolved grants in that order, first occurrence wins
  (a grant shared by two requirements appears once). Mapping entries not needed by `required` are ignored, never granted.
"""

import re

# The Section 5 capability-name rule (the registry's own name pattern), restated because planning modules other than the bridge must
# not import `tools`. A test asserts that the two patterns are identical, so the rule cannot silently drift.
_GRANT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")

STATUS_SATISFIED = "satisfied"
STATUS_UNMAPPED = "unmapped"
STATUS_INVALID_MAPPING = "invalid_mapping"
STATUS_INVALID_INPUT = "invalid_input"

MAPPING_INVALID_REQUIRED = "INVALID_REQUIRED_CAPABILITIES"
MAPPING_INVALID_STRUCTURE = "INVALID_MAPPING_STRUCTURE"
MAPPING_INVALID_ENTRY = "INVALID_MAPPING_ENTRY"
MAPPING_EMPTY_CAPABILITY = "EMPTY_MAPPING_CAPABILITY_NAME"
MAPPING_INVALID_GRANTS = "INVALID_MAPPING_GRANTS"
MAPPING_EMPTY_GRANTS = "EMPTY_MAPPING_GRANTS"
MAPPING_INVALID_GRANT_NAME = "INVALID_SECTION5_CAPABILITY_NAME"
MAPPING_DUPLICATE_GRANT = "DUPLICATE_MAPPING_GRANT"
MAPPING_DUPLICATE_ENTRY = "DUPLICATE_MAPPING_ENTRY"
MAPPING_CONFLICTING_ENTRY = "CONFLICTING_MAPPING_ENTRY"
MAPPING_UNMAPPED = "UNMAPPED_REQUIRED_CAPABILITY"

_ENTRY_KEYS = frozenset({"capability", "grants"})


def _issue(code, message, **details):
    item = {"code": code, "message": message}
    item.update(details)
    return item


def _plain_items(value):
    """Items of an exact list/tuple read with the base types' own iterators (no caller-supplied `__iter__`), else None."""
    if isinstance(value, list):
        return list(list.__iter__(value))
    if isinstance(value, tuple):
        return list(tuple.__iter__(value))
    return None


def _is_name(value):
    return isinstance(value, str) and bool(str.strip(value))


class CapabilityMappingResult:
    """Outcome of one `map_required_capabilities()` call. Plain read-only data (tuples); holds no plan, request or registry."""

    __slots__ = ("_status", "_required", "_resolved", "_grant_names", "_missing", "_invalid_entries", "_failures")

    def __init__(self, status, required, resolved, grant_names, missing, invalid_entries, failures):
        for key, value in (("status", status), ("required", tuple(required)), ("resolved", tuple(resolved)),
                           ("grant_names", tuple(grant_names)), ("missing", tuple(missing)),
                           ("invalid_entries", tuple(invalid_entries)), ("failures", tuple(failures))):
            object.__setattr__(self, "_" + key, value)

    def __setattr__(self, key, value):
        raise AttributeError("CapabilityMappingResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("CapabilityMappingResult is immutable.")

    @property
    def status(self):
        return self._status

    @property
    def ok(self):
        """True only when EVERY required Section 4 name is mapped by a valid mapping."""
        return self._status == STATUS_SATISFIED

    @property
    def required(self):
        """The Section 4 names that were asked for (caller order, exact repeats collapsed)."""
        return self._required

    @property
    def resolved(self):
        """Tuple of `(section4_name, (section5_grant, ...))`, in `required` order, for the names that are mapped."""
        return self._resolved

    @property
    def grant_names(self):
        """The resulting Section 5 grant names (deterministic, de-duplicated). TRANSLATION ONLY - none of these is granted."""
        return self._grant_names

    @property
    def missing(self):
        """Required Section 4 names that have no mapping entry, in `required` order."""
        return self._missing

    @property
    def invalid_entries(self):
        """Every problem found in the mapping (or its structure), as `{"code", "message", ...}` dicts (fresh copies)."""
        return [dict(i) for i in self._invalid_entries]

    @property
    def failures(self):
        """All failure entries: invalid input, invalid mapping problems, or one `UNMAPPED_REQUIRED_CAPABILITY` per missing name."""
        return [dict(f) for f in self._failures]

    def codes(self):
        return [f["code"] for f in self._failures]

    def to_dict(self):
        """Fresh plain-JSON view with a fixed key set."""
        return {"ok": self.ok, "status": self._status, "required": list(self._required),
                "resolved": [{"capability": c, "grants": list(g)} for c, g in self._resolved],
                "grant_names": list(self._grant_names), "missing": list(self._missing),
                "invalid_entries": self.invalid_entries, "failures": self.failures}

    def __repr__(self):
        return f"CapabilityMappingResult(status={self._status!r}, grant_names={self._grant_names!r})"


def _parse_mapping(mapping):
    """Returns (table, problems): `table` maps a Section 4 name to its tuple of grants (valid entries only)."""
    entries = _plain_items(mapping)
    if entries is None:
        return {}, [_issue(MAPPING_INVALID_STRUCTURE, "The mapping must be a list or tuple of entries.")]
    table, problems, bad_names = {}, [], set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(dict.keys(entry)) != _ENTRY_KEYS:
            problems.append(_issue(MAPPING_INVALID_ENTRY,
                                   'Each mapping entry must be a dict with exactly the keys "capability" and "grants".',
                                   index=index))
            continue
        name, grants = dict.__getitem__(entry, "capability"), dict.__getitem__(entry, "grants")
        entry_ok = True
        if not _is_name(name):
            problems.append(_issue(MAPPING_EMPTY_CAPABILITY, "The Section 4 capability name must be a non-empty string.",
                                   index=index))
            entry_ok = False
        items = _plain_items(grants)
        if items is None:
            problems.append(_issue(MAPPING_INVALID_GRANTS, "grants must be a list or tuple of Section 5 capability names.",
                                   index=index))
            entry_ok = False
        elif not items:
            problems.append(_issue(MAPPING_EMPTY_GRANTS, "An entry must map to at least one Section 5 grant name.", index=index))
            entry_ok = False
        else:
            seen = set()
            for grant in items:
                if not (isinstance(grant, str) and _GRANT_NAME_RE.fullmatch(grant)):
                    problems.append(_issue(MAPPING_INVALID_GRANT_NAME,
                                           "Not a valid Section 5 capability name (^[a-z][a-z0-9_]{0,63}$).", index=index))
                    entry_ok = False
                elif str.__str__(grant) in seen:
                    problems.append(_issue(MAPPING_DUPLICATE_GRANT, "A grant name is repeated inside one entry.",
                                           index=index, grant=str.__str__(grant)))
                    entry_ok = False
                else:
                    seen.add(str.__str__(grant))
        if not entry_ok:
            if _is_name(name):
                bad_names.add(str.__str__(name))
            continue
        key, value = str.__str__(name), tuple(str.__str__(g) for g in items)
        if key in table:
            code = MAPPING_DUPLICATE_ENTRY if table[key] == value else MAPPING_CONFLICTING_ENTRY
            problems.append(_issue(code, "The same Section 4 capability name is mapped more than once.",
                                   index=index, capability=key))
            bad_names.add(key)
        else:
            table[key] = value
    for key in bad_names:
        table.pop(key, None)        # a name with any invalid/duplicate/conflicting entry is never translated
    return table, problems


def map_required_capabilities(required_capabilities, mapping):
    """Translate the caller's Section 4 `required_capabilities` into Section 5 grant NAMES using the caller's `mapping`
    (see the module docstring). Pure and deterministic; never raises for bad data; never mutates its arguments; never grants."""
    items = _plain_items(required_capabilities)
    if items is None or not all(_is_name(i) for i in items):
        return CapabilityMappingResult(
            STATUS_INVALID_INPUT, (), (), (), (), (),
            [_issue(MAPPING_INVALID_REQUIRED, "required_capabilities must be a list or tuple of non-empty strings.")])
    required = []
    for item in items:
        item = str.__str__(item)
        if item not in required:
            required.append(item)

    table, problems = _parse_mapping(mapping)
    if problems:
        return CapabilityMappingResult(STATUS_INVALID_MAPPING, required, (), (), (), problems, problems)

    resolved, missing, grant_names = [], [], []
    for name in required:
        if name not in table:
            missing.append(name)
            continue
        resolved.append((name, table[name]))
        for grant in table[name]:
            if grant not in grant_names:
                grant_names.append(grant)
    if missing:
        failures = [_issue(MAPPING_UNMAPPED, f"Required capability {name!r} has no explicit mapping.", capability=name)
                    for name in missing]
        return CapabilityMappingResult(STATUS_UNMAPPED, required, resolved, grant_names, missing, (), failures)
    return CapabilityMappingResult(STATUS_SATISFIED, required, resolved, grant_names, (), (), ())


def find_ungranted_capabilities(mapping_result, granted_capabilities):
    """The resulting Section 5 grant names (in mapping order) that are NOT present in the caller's `granted_capabilities`
    (any iterable of names, read-only). Extra grants are irrelevant here and never removed. Returns a tuple; grants nothing."""
    granted = set(granted_capabilities)
    return tuple(g for g in mapping_result.grant_names if g not in granted)
