"""
Understanding - extensible NLU pipeline / registry (Prompt 825)
================================================================
Persian NLU v1 (persian_nlu.py) was one fixed list of patterns. This
module turns it into a small, deterministic pipeline whose parts are
registered by name, so later stages can add broader Persian
understanding by registering a component - not by editing this file or
the v1 patterns.

    text -> prepare (normalize, body, "?" flag)
         -> INTENT stage      components tried in priority order;
                              the first one that returns a result
                              decides the primary intent
         -> ANNOTATION stage  every component runs in priority order and
                              may add one structured block (question,
                              request, negation, correction, context)
         -> NLUAnalysis       primary PersianNLUResult + structure

Two kinds of component (`NLUComponent`):

  * INTENT components   `analyze(inp) -> PersianNLUResult | None`
    None means "not mine". The default registry holds the seven v1
    rules, one component each, in the original order, so the primary
    result is identical to `analyze_persian` (a test compares them).
  * ANNOTATOR components `analyze(inp) -> dict | None`
    The dict is stored in `analysis.structure[component.name]`; None
    means "nothing to report". Annotators never change the primary
    intent, so Core's existing routing and replies cannot be affected by
    them.

Built-in annotators: question, request, negation, correction, context.

Guarantees
  * Deterministic: no randomness, clock, network or I/O; stdlib only.
  * Never raises: a component that raises, or returns the wrong type, is
    skipped and listed in `analysis.errors`.
  * `pipeline.analyze(text, context)` is pure. Only
    `NLUConversationContext.record()` stores anything, and only in
    process RAM (bounded). Nothing is persisted: facts still reach
    Memory only through Core's existing LearningSystem path.
  * Persian only: components flagged `persian_only` (all built-ins) are
    skipped for input with no Arabic-script letters.

Known limits (fixed word lists, not parsing)
  * "نه" is also the number nine; "کی" is both "who" and "when".
  * A leading "نه، ..." is only treated as a correction when the
    previous turn was not a question (otherwise it is an answer).
  * Corrections are detected and linked to the turn they refer to; they
    are not applied to Memory in this stage.
"""

import copy
import re

from .persian_nlu import (
    PersianNLUResult, prepare_persian, V1_RULES, _result,
    INTENT_UNKNOWN, INTENT_REQUEST, INTENT_QUESTION, INTENT_ASK_USER_NAME,
    INTENT_DISLIKE, _QUESTION_WORDS, _REQUEST_PREFIXES, _REQUEST_ENDINGS,
)

KIND_INTENT = "intent"
KIND_ANNOTATOR = "annotator"
_KINDS = (KIND_INTENT, KIND_ANNOTATOR)

DEFAULT_PRIORITY = 1000
DEFAULT_MAX_TURNS = 8


# --- conversational context -------------------------------------------

class TurnRecord:
    """One remembered turn. Read-only by convention."""

    __slots__ = ("index", "normalized_text", "intent", "entities", "structure_keys")

    def __init__(self, index, normalized_text, intent, entities, structure_keys):
        self.index = index
        self.normalized_text = normalized_text
        self.intent = intent
        self.entities = entities
        self.structure_keys = structure_keys

    def to_dict(self):
        return {
            "index": self.index,
            "normalized_text": self.normalized_text,
            "intent": self.intent,
            "entities": dict(self.entities),
            "structure_keys": list(self.structure_keys),
        }

    def __repr__(self):
        return f"TurnRecord({self.to_dict()!r})"


class NLUConversationContext:
    """Bounded, process-RAM-only record of recent analyzed turns. Owned
    by the caller (Core holds one); the pipeline only reads it. Never
    touches Memory or any store."""

    def __init__(self, max_turns=DEFAULT_MAX_TURNS):
        if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1:
            raise ValueError("max_turns must be an integer >= 1")
        self.max_turns = max_turns
        self._turns = []
        self._count = 0

    @property
    def turn_count(self):
        """Total turns recorded since creation / last reset (not capped)."""
        return self._count

    @property
    def previous(self):
        return self._turns[-1] if self._turns else None

    def turns(self):
        return tuple(self._turns)

    # Prompt 826: read-only access helpers for future NLU features. They
    # never modify the context and never raise on an empty context.

    @property
    def size(self):
        """Number of turns currently retained (always <= max_turns)."""
        return len(self._turns)

    @property
    def is_empty(self):
        return not self._turns

    def recent(self, n=None):
        """The last `n` retained turns, oldest first, as a tuple. `n=None`
        means every retained turn; `n=0` gives (). `n` larger than what is
        retained simply returns what is retained."""
        if n is None:
            return tuple(self._turns)
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("n must be None or an integer >= 0")
        return tuple(self._turns[len(self._turns) - n:]) if n else ()

    def turn_at(self, index):
        """The retained turn whose absolute `index` (as in TurnRecord.index,
        counted since creation / last reset) is `index`, else None (never
        recorded, or already dropped by the max_turns bound)."""
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("index must be an integer")
        if not self._turns:
            return None
        pos = index - self._turns[0].index
        return self._turns[pos] if 0 <= pos < len(self._turns) else None

    def snapshot(self):
        """Plain-data copy of the whole context (JSON-safe, deterministic).
        Mutating the result cannot affect the context."""
        return {
            "max_turns": self.max_turns,
            "turn_count": self._count,
            "turns": [t.to_dict() for t in self._turns],
        }

    def record(self, analysis):
        turn = TurnRecord(
            self._count,
            analysis.result.normalized_text,
            analysis.result.intent,
            dict(analysis.result.entities),
            tuple(sorted(analysis.structure)),
        )
        self._turns.append(turn)
        if len(self._turns) > self.max_turns:
            del self._turns[0:len(self._turns) - self.max_turns]
        self._count += 1
        return turn

    def reset(self):
        """Forget every turn and restart the turn counter. Keeps max_turns.
        Safe to call repeatedly."""
        self._turns = []
        self._count = 0


# --- pipeline input / output -----------------------------------------

class NLUInput:
    """What a component receives. `primary` and `structure` are filled in
    as the stages run (`primary` is None during the intent stage;
    annotators see the primary result and the blocks added before them).
    Components must treat it as read-only."""

    __slots__ = ("raw_text", "text", "body", "asks", "has_persian_script",
                 "tokens", "context", "primary", "structure")

    def __init__(self, raw_text, context):
        text, body, asks, has_script = prepare_persian(raw_text)
        self.raw_text = raw_text
        self.text = text
        self.body = body
        self.asks = asks
        self.has_persian_script = has_script
        self.tokens = tuple(body.split(" ")) if body else ()
        self.context = context
        self.primary = None
        self.structure = {}


class NLUAnalysis:
    """Primary result + structured blocks + diagnostics."""

    __slots__ = ("result", "structure", "component", "errors")

    def __init__(self, result, structure, component, errors):
        self.result = result
        self.structure = structure
        self.component = component  # name of the intent component that decided, or None
        self.errors = errors        # tuple of (component name, problem)

    @property
    def intent(self):
        return self.result.intent

    @property
    def is_question(self):
        return "question" in self.structure

    @property
    def is_request(self):
        return "request" in self.structure

    @property
    def is_negated(self):
        return "negation" in self.structure

    @property
    def is_correction(self):
        return "correction" in self.structure

    def to_dict(self):
        return {
            "result": self.result.to_dict(),
            "structure": copy.deepcopy(self.structure),
            "component": self.component,
            "errors": [list(e) for e in self.errors],
        }

    def normalized(self):
        """Prompt 828: the same analysis as a fixed-shape plain dict (see
        understanding/nlu_structured_output.py). Pure; changes nothing."""
        from .nlu_structured_output import normalize_nlu_analysis
        return normalize_nlu_analysis(self)

    def semantic_view(self):
        """Prompt 831: compact read-only semantic view (intent, context
        reference, slots, relations; see understanding/nlu_semantic_view.py).
        Pure; changes nothing."""
        from .nlu_semantic_view import build_semantic_view
        return build_semantic_view(self)

    def resolve_references(self, context=None):
        """Prompt 832: the explicit references of this analysis resolved
        against the (optional, read-only) context; see
        understanding/nlu_meaning_bridge.py. Pure; changes nothing."""
        from .nlu_meaning_bridge import resolve_references
        return resolve_references(self, context)

    def reasoning_input(self, context=None):
        """Prompt 833: compact reasoning-ready representation built from the
        semantic view and the meaning bridge; see
        understanding/nlu_reasoning_input.py. Pure; changes nothing."""
        from .nlu_reasoning_input import build_reasoning_input
        return build_reasoning_input(self, context)

    def __eq__(self, other):
        return isinstance(other, NLUAnalysis) and self.to_dict() == other.to_dict()

    def __repr__(self):
        return f"NLUAnalysis({self.to_dict()!r})"


# --- components and registry -----------------------------------------

class NLUComponent:
    """Base class. Subclass and set `name`/`kind`/`priority`, implement
    `analyze(inp)`. Lower priority runs first; ties keep registration
    order."""

    name = ""
    kind = KIND_ANNOTATOR
    priority = DEFAULT_PRIORITY
    persian_only = False

    def analyze(self, inp):  # pragma: no cover - interface
        raise NotImplementedError


class FunctionComponent(NLUComponent):
    """Wraps a plain function `fn(inp)` as a component."""

    def __init__(self, name, kind, fn, priority=DEFAULT_PRIORITY, persian_only=False):
        self.name = name
        self.kind = kind
        self.priority = priority
        self.persian_only = persian_only
        self._fn = fn

    def analyze(self, inp):
        return self._fn(inp)


class NLURegistry:
    """Named collection of components. Names are unique across kinds."""

    def __init__(self):
        self._items = {}   # name -> (seq, component)
        self._seq = 0

    @staticmethod
    def _validate(component):
        name = getattr(component, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("component.name must be a non-empty string")
        if getattr(component, "kind", None) not in _KINDS:
            raise ValueError(f"component.kind must be one of {_KINDS}")
        priority = getattr(component, "priority", None)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("component.priority must be an integer")
        if not callable(getattr(component, "analyze", None)):
            raise ValueError("component.analyze must be callable")

    def register(self, component, replace=False):
        self._validate(component)
        if component.name in self._items and not replace:
            raise ValueError(f"component already registered: {component.name}")
        self._seq += 1
        self._items[component.name] = (self._seq, component)
        return component

    def unregister(self, name):
        return self._items.pop(name, None) is not None

    def get(self, name):
        item = self._items.get(name)
        return item[1] if item else None

    def __contains__(self, name):
        return name in self._items

    def __len__(self):
        return len(self._items)

    def components(self, kind=None):
        items = [(c.priority, seq, c) for seq, c in self._items.values()
                 if kind is None or c.kind == kind]
        items.sort(key=lambda t: (t[0], t[1]))
        return [c for _p, _s, c in items]

    def names(self, kind=None):
        return [c.name for c in self.components(kind)]

    def copy(self):
        other = NLURegistry()
        for _p, seq, c in sorted(((c.priority, s, c) for s, c in self._items.values()),
                                 key=lambda t: t[1]):
            other.register(c)
        return other


# --- pipeline ---------------------------------------------------------

class NLUPipeline:
    def __init__(self, registry=None):
        self.registry = registry if registry is not None else NLURegistry()

    @staticmethod
    def _skipped(component, inp):
        return bool(getattr(component, "persian_only", False)) and (
            not inp.has_persian_script or not inp.body)

    def _intent_stage(self, inp, errors):
        for component in self.registry.components(KIND_INTENT):
            if self._skipped(component, inp):
                continue
            try:
                got = component.analyze(inp)
            except Exception as exc:  # a broken component must not break NLU
                errors.append((component.name, type(exc).__name__))
                continue
            if got is None:
                continue
            if not isinstance(got, PersianNLUResult):
                errors.append((component.name, "invalid result type"))
                continue
            return got, component.name
        return _result(INTENT_UNKNOWN, inp.text, None), None

    def analyze_intent(self, raw_text):
        """Intent stage only -> PersianNLUResult (the v1 contract)."""
        inp = NLUInput(raw_text, None)
        result, _name = self._intent_stage(inp, [])
        return result

    def analyze(self, raw_text, context=None):
        """Full analysis. Pure: `context` is read, never modified."""
        inp = NLUInput(raw_text, context)
        errors = []
        result, decided_by = self._intent_stage(inp, errors)
        inp.primary = result
        structure = {}
        inp.structure = structure
        for component in self.registry.components(KIND_ANNOTATOR):
            if self._skipped(component, inp):
                continue
            try:
                block = component.analyze(inp)
            except Exception as exc:
                errors.append((component.name, type(exc).__name__))
                continue
            if block is None:
                continue
            if not isinstance(block, dict):
                errors.append((component.name, "invalid result type"))
                continue
            structure[component.name] = copy.deepcopy(block)
        return NLUAnalysis(result, structure, decided_by, tuple(errors))


# --- built-in intent components (the v1 rules) ------------------------

class V1RuleComponent(NLUComponent):
    kind = KIND_INTENT
    persian_only = True

    def __init__(self, rule_name, rule, priority):
        self.name = "v1." + rule_name
        self.priority = priority
        self._rule = rule

    def analyze(self, inp):
        return self._rule(inp.text, inp.body, inp.asks)


# --- built-in annotators ----------------------------------------------

_QUESTION_TYPES = {
    "چی": "what", "چیه": "what", "چیست": "what", "چه": "what",
    "چرا": "why",
    "چطور": "how", "چگونه": "how", "چجوری": "how", "چطوری": "how",
    "کی": "who_or_when", "کیه": "who", "کیست": "who",
    "کجا": "where", "کجاست": "where",
    "کدام": "which", "کدوم": "which",
    "چند": "quantity", "چقدر": "quantity",
    "آیا": "yes_no",
}

_MODAL_PREFIXES = frozenset((
    "میشه", "می شه", "میتونی", "می تونی", "میتوانی", "می توانی",
    "ممکنه", "ممکن است", "بتونی",
))

# Longest first so "نشون بده" wins over "بده"; ties keep v1 order.
_ACTIONS_LONGEST_FIRST = tuple(sorted(
    _REQUEST_ENDINGS, key=lambda e: -len(e)))

_NEG_PARTICLES = frozenset(("نه", "نخیر", "هرگز", "هیچ", "هیچوقت"))
_NEG_COPULA = frozenset((
    "نیست", "نیستم", "نیستی", "نیستیم", "نیستید", "نیستند", "نیستن",
    "نبود", "نبودم", "نبودی", "نبودیم", "نبودند", "نبودن",
))
_NEG_HAVE = frozenset((
    "ندارم", "نداری", "ندارد", "نداره", "نداریم", "ندارید", "ندارند", "ندارن",
    "نداشت", "نداشتم",
))
_NEG_FUTURE = frozenset((
    "نخواهم", "نخواهی", "نخواهد", "نخواهیم", "نخواهید", "نخواهند",
))
_NEG_PROHIBITION = frozenset((
    "نکن", "نکنید", "نکنین", "نگو", "نگید", "نگویید", "نرو", "نزن",
    "نذار", "نباش", "نباشید",
))


def _negation_markers(tokens):
    """[(token, kind)] in token order."""
    found = []
    for t in tokens:
        if t in _NEG_PARTICLES:
            found.append((t, "particle"))
        elif t in _NEG_COPULA:
            found.append((t, "copula"))
        elif t in _NEG_HAVE:
            found.append((t, "have"))
        elif t in _NEG_FUTURE:
            found.append((t, "future"))
        elif t in _NEG_PROHIBITION:
            found.append((t, "prohibition"))
        elif t == "نمی" or (t.startswith("نمی") and len(t) > 3):
            found.append((t, "verb"))
    return found


class QuestionAnnotator(NLUComponent):
    name = "question"
    kind = KIND_ANNOTATOR
    priority = 100
    persian_only = True

    def analyze(self, inp):
        primary = inp.primary
        if primary.intent not in (INTENT_QUESTION, INTENT_ASK_USER_NAME):
            return None
        marker = primary.entities.get("marker")
        if primary.intent == INTENT_ASK_USER_NAME:
            qtype, topic = "what", "user_name"
        elif marker:
            qtype, topic = _QUESTION_TYPES.get(marker, "unspecified"), None
        else:
            qtype, topic = "yes_no", None  # question mark only
        return {
            "type": qtype,
            "marker": marker,
            "has_question_mark": bool(inp.asks),
            "topic": topic,
        }


class RequestAnnotator(NLUComponent):
    name = "request"
    kind = KIND_ANNOTATOR
    priority = 110
    persian_only = True

    def analyze(self, inp):
        primary = inp.primary
        if primary.intent != INTENT_REQUEST:
            return None
        marker = primary.entities.get("marker")
        prefix = marker if primary.matched_rule == "request_prefix" else None
        rest = inp.body[len(prefix):].strip() if prefix else inp.body
        action = next((e for e in _ACTIONS_LONGEST_FIRST
                       if rest == e or rest.endswith(" " + e)), None)
        argument = rest[:len(rest) - len(action)].strip() if action else rest
        if prefix is None:
            form = "imperative"
        elif prefix in _MODAL_PREFIXES:
            form = "modal"
        else:
            form = "polite"
        prohibition = any(k == "prohibition" for _t, k in _negation_markers(inp.tokens))
        return {
            "form": form,
            "marker": marker,
            "action": action,
            "argument": argument or None,
            "prohibition": prohibition,
        }


class NegationAnnotator(NLUComponent):
    name = "negation"
    kind = KIND_ANNOTATOR
    priority = 120
    persian_only = True

    def analyze(self, inp):
        found = _negation_markers(inp.tokens)
        if not found:
            return None
        return {
            "markers": [t for t, _k in found],
            "kinds": sorted({k for _t, k in found}),
            "count": len(found),
            # "دوست ندارم" is already carried by the dislike intent itself.
            "folded_into_intent": inp.primary.intent == INTENT_DISLIKE,
        }


_CORR_REPLACE_RE = re.compile(r"^(?:نه[ ,]+)*منظور(?:م| من) (.+?) (?:بود|بوده)$")
_CORR_RETRACT_RE = re.compile(
    r"^(?:(?:نه|ببخشید)[ ,]+)*(?:من )?(?:اشتباه|غلط) "
    r"(?:گفتم|کردم|شد|نوشتم|فهمیدم|بود)(?:[ ,]+(.+))?$")
_CORR_REJECT_PHRASES = frozenset((
    "اشتباهه", "اشتباه است", "غلطه", "غلط است", "درست نیست",
    "این اشتباهه", "این غلطه", "این درست نیست",
))
_CORR_LEADING_NO_RE = re.compile(r"^(?:(?:نه|نخیر)[ ,]+)+(.+)$")


class CorrectionAnnotator(NLUComponent):
    name = "correction"
    kind = KIND_ANNOTATOR
    priority = 130
    persian_only = True

    @staticmethod
    def _refers_to(context):
        prev = context.previous if context is not None else None
        if prev is None:
            return None
        return {"turn_index": prev.index, "intent": prev.intent,
                "normalized_text": prev.normalized_text}

    def analyze(self, inp):
        body = inp.body
        refers = self._refers_to(inp.context)

        m = _CORR_REPLACE_RE.match(body)
        if m:
            return {"kind": "replacement", "marker": "منظورم", "explicit": True,
                    "corrected_text": m.group(1).strip(), "refers_to": refers}

        m = _CORR_RETRACT_RE.match(body)
        if m:
            text = (m.group(1) or "").strip() or None
            return {"kind": "replacement" if text else "retraction",
                    "marker": "اشتباه", "explicit": True,
                    "corrected_text": text, "refers_to": refers}

        if body in _CORR_REJECT_PHRASES:
            return {"kind": "rejection", "marker": body, "explicit": True,
                    "corrected_text": None, "refers_to": refers}

        # Leading "نه، ..." is ambiguous (it also answers questions), so it
        # needs a previous turn that was not a question.
        m = _CORR_LEADING_NO_RE.match(body)
        if m and refers is not None and refers["intent"] not in (
                INTENT_QUESTION, INTENT_ASK_USER_NAME):
            remainder = m.group(1).strip()
            if remainder:
                return {"kind": "replacement", "marker": "نه", "explicit": False,
                        "corrected_text": remainder, "refers_to": refers}
        return None


_CONTINUATION_MARKERS = frozenset((
    "و", "پس", "ولی", "اما", "یعنی", "همچنین", "بعدش", "اونوقت",
))

# Prompt 827: basic reference cues. Fixed word lists, not parsing - a cue
# only says "this turn points back"; it never says what it means.
_AGAIN_TOKENS = frozenset((
    "دوباره", "مجددا", "مجدد", "باز", "دوبار", "دوباره‌ای",
))
_AGAIN_PHRASES = (
    " یه بار دیگه ", " یک بار دیگه ", " یکبار دیگه ", " یه دفعه دیگه ",
    " یک دفعه دیگه ", " یه بار دیگر ", " یک بار دیگر ",
)
_REFERENCE_TOKENS = frozenset((
    "همون", "همونو", "همین", "همینو", "اونو", "اینو", "قبلی", "بالایی",
    "همان", "آنرا", "آن",
))
_REFERENCE_PHRASES = (" مثل قبل ", " مثل بالا ", " مثل همون ", " مثل قبلی ")


def _context_reference(inp, ctx, prev):
    """The Prompt 827 `reference` sub-block of the context annotation.
    Reads only `ctx`'s retained turns (bounded by its max_turns); pure."""
    text = inp.text
    same = [t for t in ctx.turns() if t.normalized_text == text] if text else []
    padded = " " + inp.body + " " if inp.body else ""
    tokens = inp.tokens
    again = bool(tokens) and (
        any(t in _AGAIN_TOKENS for t in tokens)
        or any(ph in padded for ph in _AGAIN_PHRASES))
    refers = bool(tokens) and (
        any(t in _REFERENCE_TOKENS for t in tokens)
        or any(ph in padded for ph in _REFERENCE_PHRASES))
    first = tokens[0] if tokens else None
    continuation = bool(prev and first in _CONTINUATION_MARKERS)
    points_back = bool(prev and (continuation or again or refers))
    primary = inp.primary.intent if inp.primary is not None else INTENT_UNKNOWN
    inherited = None
    if points_back and primary == INTENT_UNKNOWN and prev.intent != INTENT_UNKNOWN:
        inherited = prev.intent
    return {
        "repeat_count": len(same),
        "repeat_of": same[-1].index if same else None,
        "again": again,
        "refers_to_previous": refers,
        "referenced_turn": prev.index if points_back else None,
        "inherited_intent": inherited,
        "effective_intent": inherited if inherited is not None else primary,
    }


class ContextAnnotator(NLUComponent):
    name = "context"
    kind = KIND_ANNOTATOR
    priority = 140
    persian_only = True

    def analyze(self, inp):
        ctx = inp.context
        if ctx is None:
            return None
        prev = ctx.previous
        first = inp.tokens[0] if inp.tokens else None
        return {
            "turn_index": ctx.turn_count,
            "previous_intent": prev.intent if prev else None,
            "previous_text": prev.normalized_text if prev else None,
            "same_intent_as_previous": bool(prev and prev.intent == inp.primary.intent
                                            and inp.primary.intent != INTENT_UNKNOWN),
            "is_repeat": bool(prev and prev.normalized_text == inp.text),
            "follows_question": bool(prev and prev.intent in (
                INTENT_QUESTION, INTENT_ASK_USER_NAME)),
            "continuation": first if (prev and first in _CONTINUATION_MARKERS) else None,
            # Prompt 827: additive; every key above is unchanged.
            "reference": _context_reference(inp, ctx, prev),
        }


# --- default wiring ---------------------------------------------------

def build_default_registry():
    """A fresh registry holding the v1 rules (priorities 100, 110, ...)
    and the five built-in annotators. Priorities are spaced so a future
    component can slot in between without renumbering."""
    registry = NLURegistry()
    for i, (rule_name, rule) in enumerate(V1_RULES):
        registry.register(V1RuleComponent(rule_name, rule, 100 + 10 * i))
    for annotator in (QuestionAnnotator(), RequestAnnotator(), NegationAnnotator(),
                      CorrectionAnnotator(), ContextAnnotator()):
        registry.register(annotator)
    return registry


def default_pipeline():
    return NLUPipeline(build_default_registry())
