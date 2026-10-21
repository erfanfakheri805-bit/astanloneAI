"""
brain_hub.graph - the capability graph: one honest list of everything the app has, can do, or cannot do yet
==========================================================================================================
Every node says exactly ONE of these things about itself (`state`), and which of them count as "usable":

  active               registered, enabled, permissions satisfied AND verified with evidence (tests passed, a
                       self-check or a real use in this process)           -> usable
  available            implemented and its pre-conditions hold, but it has no acceptance evidence of its own yet
                       (for example a web read that was never tried)         -> usable
  registered           known to a registry but not (yet) usable or verified
  permission_blocked   implemented, but a permission the user has not granted is missing
  dependency_blocked   needs something that is not here: a model file, an engine, a native piece, a connection
  pending_approval     prepared and tested, waiting for the user's explicit yes
  scaffold_only        a contract / planner / validator exists in the code, nothing executes it
  not_implemented      no implementation exists yet
  policy_blocked       Android or the app's safety policy forbids it
  broken               was registered but failed its verification
  disabled             switched off by the user

`tested` is separate: it says whether the node carries its own passing test evidence. `active` requires it.
`blockers` lists, for every non-usable node, the exact missing thing (permission / model / native code / new APK /
hardware / policy / consequential / external service ...). Nothing here executes anything; `invoker.execute` does.
"""

from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

__all__ = ["STATES", "USABLE_STATES", "NODE_KINDS", "BLOCKER_KINDS", "STATE_TEXT", "Blocker", "CapabilityNode",
           "CapabilityGraph", "state_label"]

STATES = ("active", "available", "registered", "permission_blocked", "dependency_blocked", "pending_approval",
          "scaffold_only", "not_implemented", "policy_blocked", "broken", "disabled")
USABLE_STATES = frozenset({"active", "available"})
NODE_KINDS = ("brain", "extension", "self_builder", "tool", "model", "android", "infra", "gap")
BLOCKER_KINDS = ("permission", "dependency", "model", "native_code", "new_apk", "hardware", "policy", "consequential",
                 "external_service", "design", "approval", "network", "test", "user_input")

STATE_TEXT: Dict[str, Tuple[str, str]] = {
    "active": ("فعال و آزمایش‌شده", "active and verified"),
    "available": ("آماده (هنوز آزمون عملی خودش را ندارد)", "available (no acceptance evidence of its own yet)"),
    "registered": ("ثبت‌شده ولی هنوز قابل استفاده نیست", "registered but not usable yet"),
    "permission_blocked": ("منتظر مجوز", "waiting for a permission"),
    "dependency_blocked": ("نیازمند چیزی که اینجا نیست", "needs something that is not here"),
    "pending_approval": ("منتظر تأیید تو", "waiting for your approval"),
    "scaffold_only": ("فقط طرح و قرارداد؛ چیزی اجرا نمی‌کند", "design/contract only; nothing executes it"),
    "not_implemented": ("پیاده‌سازی نشده", "not implemented"),
    "policy_blocked": ("به‌خاطر سیاست امنیتی/اندروید ممنوع یا محدود", "blocked or limited by policy"),
    "broken": ("خراب؛ تأیید ناموفق بود", "broken; verification failed"),
    "disabled": ("غیرفعال", "disabled"),
}


def state_label(state, lang="fa"):
    pair = STATE_TEXT.get(state, (str(state), str(state)))
    return pair[0] if lang == "fa" else pair[1]


@dataclass(frozen=True)
class Blocker:
    kind: str
    text_fa: str
    text_en: str

    def __post_init__(self):
        if self.kind not in BLOCKER_KINDS:
            raise ValueError("unknown blocker kind %r" % (self.kind,))


@dataclass(frozen=True)
class CapabilityNode:
    node_id: str
    kind: str
    title_fa: str
    title_en: str
    state: str
    summary_fa: str = ""
    summary_en: str = ""
    tested: bool = False
    entry: str = ""                      # how a request reaches it (a plain-language call path)
    version: Optional[int] = None
    blockers: Tuple[Blocker, ...] = ()
    examples_fa: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()       # short, real facts: "tests 5/5", "smoke test passed", "served 3 messages"
    actions: Tuple[str, ...] = ()        # what `execute` accepts for this node

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError("unknown node state %r" % (self.state,))
        if self.kind not in NODE_KINDS:
            raise ValueError("unknown node kind %r" % (self.kind,))
        if self.state == "active" and not self.tested:
            raise ValueError("a node is 'active' only with test evidence")
        if not isinstance(self.node_id, str) or not self.node_id or len(self.node_id) > 100:
            raise ValueError("bad node id")

    @property
    def usable(self):
        return self.state in USABLE_STATES

    def to_dict(self):
        data = asdict(self)
        data["usable"] = self.usable
        data["state_label_fa"], data["state_label_en"] = STATE_TEXT[self.state]
        return data


@dataclass
class CapabilityGraph:
    _nodes: Dict[str, CapabilityNode] = field(default_factory=dict)

    def __init__(self, nodes: Iterable[CapabilityNode] = ()):
        self._nodes = {}
        for node in nodes:
            if not isinstance(node, CapabilityNode):
                raise ValueError("a graph holds CapabilityNode objects only")
            if node.node_id in self._nodes:
                raise ValueError("duplicate node id %r" % node.node_id)
            self._nodes[node.node_id] = node

    def __len__(self):
        return len(self._nodes)

    def __contains__(self, node_id):
        return node_id in self._nodes

    def get(self, node_id) -> Optional[CapabilityNode]:
        return self._nodes.get(node_id) if isinstance(node_id, str) else None

    def nodes(self, kind=None, state=None) -> List[CapabilityNode]:
        return [n for n in self._nodes.values() if (kind is None or n.kind == kind) and (state is None or n.state == state)]

    def usable(self) -> List[CapabilityNode]:
        return [n for n in self._nodes.values() if n.usable]

    def summary(self):
        by_state = {s: 0 for s in STATES}
        by_kind = {}
        for n in self._nodes.values():
            by_state[n.state] += 1
            by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
        return {"total": len(self._nodes), "by_state": {k: v for k, v in by_state.items() if v},
                "by_kind": by_kind, "tested": sum(1 for n in self._nodes.values() if n.tested),
                "usable": sum(1 for n in self._nodes.values() if n.usable)}

    def to_dict(self):
        return {"summary": self.summary(), "nodes": [n.to_dict() for n in self._nodes.values()]}
