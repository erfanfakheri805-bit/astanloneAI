"""
Persian conversation brain - the road from a chat message to the hub
====================================================================
`brain.py` calls four functions here, only in the FULL scope (the Android app / an activated Core):

  early(brain, text)      before the Persian gate: the answer to the hub's open question; a pasted extension package
                          (`ext.v1`) or model card; a sentence that an INSTALLED extension asks for
  command(brain, turn)    a hub command (capability map, extensions, internet, models, Android, the extension prompt)
  gap_reply(brain, turn)  nothing else answered: if the sentence asks for something the app cannot do yet, say exactly
                          what exists, what is missing and the one honest next step
  unsupported(brain, turn) the old «I cannot build that» answer, plus the way to extend the app from inside it

`early` and `command` return `(sub, reply)`; nothing changes in the app unless the user has said an explicit «بله» to
the hub's question (`answer_pending`). A hub that cannot be reached never breaks the conversation: the brain just does
what it did before.
"""

import json
import re

from self_builder import fa_text

from . import hub_commands as HC
from . import hub_intents as HI
from . import hub_messages as HM
from . import hub_messages_tools as HT
from . import hub_state
from . import intents as I
from . import messages as M
from . import normalization as nz

MAX_CALL_CHARS = 4000          # an installed extension is only matched against ordinary-sized messages
MAX_CARD_CHARS = 20_000
MAX_ANSWER_CHARS = 200
_SCHEMA_RE = re.compile(r'"schema"\s*:\s*"(ext\.v\d{1,4})"')      # the schema marker a pasted package declares


def get_hub(brain):
    """The hub of this brain's memory (nothing is created on disk), or None."""
    try:
        from brain_hub import service as hub_service
        return hub_service.get_hub(brain.memory)
    except Exception:
        return None


def note_served(brain):
    """Count a real reply of the conversation brain (evidence shown in the capability map). Never raises."""
    hub = get_hub(brain)
    if hub is not None:
        try:
            hub.note_served("brain.conversation")
        except Exception:
            pass


def _guard(brain, text, fn):
    try:
        return fn()
    except Exception as exc:                               # the hub must never break a conversation
        brain._log_error(exc, text)
        return HT.unexpected()


# ================================================================== early
def early(brain, text):
    memory, clock = brain.memory, brain._clock
    state = hub_state.load(memory, clock)
    toks = fa_text.words(nz.normalize(text)) if len(text) <= MAX_ANSWER_CHARS else []
    word = I.answer_word(toks) if toks else None
    if state is not None:
        if word:
            return "answer:" + state[0], _guard(brain, text, lambda: answer_pending(brain, state, word))
        _withdraw(brain, state)                           # any other message withdraws the open question
    elif word:
        old = hub_state.lapsed(memory, clock)             # a bare yes / no to a question nobody can answer any more
        if old is not None:
            _withdraw(brain, old)
            return "expired", HM.question_expired(old[0])
    pasted = _guard_pair(brain, text, lambda: _pasted(brain, text))
    if pasted is not None:
        return pasted
    return _guard_pair(brain, text, lambda: _extension_call(brain, text))


def _withdraw(brain, state):
    """Forget the open question. An install proposal it pointed to is declined as well: the user was told it would be set aside."""
    ptype, data = state
    hub_state.clear(brain.memory)
    if ptype != "install":
        return
    hub = get_hub(brain)
    if hub is None:
        return
    try:
        hub.decline_proposal(data["proposal_id"])
    except Exception as exc:                              # tidying up must never break the conversation
        brain._log_error(exc, "")


def _guard_pair(brain, text, fn):
    try:
        return fn()
    except Exception as exc:
        brain._log_error(exc, text)
        return "error", HT.unexpected()


# ------------------------------------------------------------------ pasted packages and cards
def _pasted(brain, text):
    if "ext.v1" not in text:
        other = _SCHEMA_RE.search(text)
        if other:                                          # a package of another format version: say so, never ignore it
            return "package", HM.package_other_schema(other.group(1))
    if "ext.v1" in text:
        hub = get_hub(brain)
        if hub is None:
            return "package", HT.hub_unavailable()
        from ext_runtime import intake
        body = intake.find_package_in_text(text)
        if body is None:
            return ("package", HM.package_not_found()) if "{" in text else None
        return "package", _propose(brain, hub, body)
    card = _find_card(text)
    if card is None:
        return None
    hub = get_hub(brain)
    if hub is None:
        return "model_card", HT.hub_unavailable()
    status = hub.register_model(card)
    if not status.ok:
        return "model_card", HT.card_not_valid(status.code) if status.code == "invalid_card" else HT.model_failure(status)
    return "model_card", HT.model_registered(status)


def _find_card(text):
    """A model card (a JSON object with `model_id` and `sha256`) inside a chat message, or None. Bounded and never raises."""
    if len(text) > MAX_CARD_CHARS or '"model_id"' not in text or '"sha256"' not in text:
        return None
    decoder = json.JSONDecoder()
    pos = text.find("{")
    for _ in range(3):
        if pos == -1:
            return None
        try:
            obj, _end = decoder.raw_decode(text, pos)
        except (ValueError, RecursionError):
            obj = None
        if isinstance(obj, dict) and "model_id" in obj and "sha256" in obj:
            return obj
        pos = text.find("{", pos + 1)
    return None


def _propose(brain, hub, body):
    result = hub.propose_package(body, origin="chat")
    status = result.get("status")
    ctx = HC.Ctx(brain, hub)
    if status == "pending_approval":
        data = {"proposal_id": result["proposal_id"], "capability_id": result["capability_id"], "title": str(result.get("title") or result["capability_id"])[:200],
                "action": result.get("action"), "planned_version": result.get("planned_version")}
        if not ctx.arm("install", data):
            hub.decline_proposal(result["proposal_id"])
            return HT.unexpected()
        return HM.proposal(result, ctx.network_on())
    if status == "noop_identical":
        return HM.proposal_noop(result)
    if status == "rejected":
        return HM.proposal_rejected(result)
    if result.get("code") == "E_HUB_EXT_STORE" and ctx.arm("repair_store", {}):
        return HM.store_unusable_ask()
    return HM.hub_error(result)


# ------------------------------------------------------------------ an installed extension
def _extension_call(brain, text):
    if len(text) > MAX_CALL_CHARS:
        return None
    hub = get_hub(brain)
    if hub is None or not hub.has_extensions():
        return None
    toks = fa_text.words(nz.normalize(text))
    if not toks or I.answer_word(toks):                   # a bare yes / no never runs an extension
        return None
    hit = hub.match_extension(text, include_disabled=True)
    status = hit.get("status")
    if status == "none":
        return None
    cid = hit.get("capability_id")
    if status == "disabled":
        return "extension", HM.ext_disabled(hit)
    if status == "needs_inputs":
        cap = hub.extension(cid) or {}
        example = next((e for e in (cap.get("examples") or []) if isinstance(e, str)), None)
        return "extension", HM.ext_needs_inputs(hit, example)
    if status == "invalid_inputs":
        return "extension", HM.ext_invalid_inputs(hit)
    if status != "invoke":
        return None
    out = hub.invoke_extension(cid, hit.get("inputs") or {})
    if out.get("ok"):
        return "extension", HM.ext_answer(out)
    reply = HM.ext_failed(out)
    ctx = HC.Ctx(brain, hub)
    if out.get("status") == "runtime_error" and not ctx.network_on():
        declared = ((hub.extension(cid) or {}).get("permissions") or {}).get("declared") or []
        if "network" in declared and ctx.arm("net_on", {}):
            reply += "\n" + HM.ask_net_on()
    return "extension", reply


# ================================================================== answers to the open question
def answer_pending(brain, state, word):
    ptype, data = state
    hub_state.clear(brain.memory)                         # a question is answered once, whatever the answer
    hub = get_hub(brain)
    if hub is None:
        return HT.hub_unavailable()
    if word != "confirm":
        if ptype == "install":
            hub.decline_proposal(data["proposal_id"])
            return HM.declined()
        return HM.nothing_changed()
    return _CONFIRMED[ptype](HC.Ctx(brain, hub), data)


def _c_install(ctx, d):
    res = ctx.hub.approve_proposal(d["proposal_id"], user_approved=True)
    if res.get("status") == "applied":
        cap = ctx.hub.extension(res.get("capability_id")) or {}
        return HM.approved(res, cap.get("examples") or [])
    return HM.approve_failed(res)


def _c_rollback(ctx, d):
    res = ctx.hub.rollback_extension(d["capability_id"], to_version=d.get("to_version"), user_approved=True)
    return HM.rolled_back(res) if res.get("status") == "rolled_back" else HM.rollback_failed(res)


def _c_disable(ctx, d):
    res = ctx.hub.disable_extension(d["capability_id"])
    return HM.disabled(res) if res.get("status") == "disabled" else HM.switch_failed(res)


def _c_enable(ctx, d):
    res = ctx.hub.enable_extension(d["capability_id"], user_approved=True)
    return HM.enabled(res) if res.get("status") == "enabled" else HM.switch_failed(res)


def _c_perm_grant(ctx, d):
    res = ctx.hub.grant_extension_permission(d["capability_id"], d["permission"], user_approved=True)
    if res.get("status") == "granted":
        return HM.permission_granted(dict(res, title=d["title"]))
    return HM.permission_failed(res)


def _c_net_on(ctx, d):
    change = ctx.hub.grant_permission("network", user_approved=True)
    if not change.ok:
        return HM.net_change_failed(change.code)
    text = HM.net_on_done(change.code == "ok")
    url = d.get("url")
    if url:
        data = ctx.hub.fetch(url).to_dict()
        text += "\n" + (HM.fetch_ok(data) if data["ok"] else HM.fetch_failed(data))
    return text


def _c_model_download(ctx, d):
    mid = d["model_id"]
    status = ctx.hub.download_model(mid, approved=True)
    if not status.ok:
        if status.code == "license_needs_ack" and ctx.arm("model_license", {"model_id": mid}):
            return status.message_fa + "\n" + HT.ask_model_license(ctx.hub.model_status(mid))
        return HT.model_pipeline(mid, status, None)
    return HT.model_pipeline(mid, status, ctx.hub.prepare_model(mid))


def _c_model_license(ctx, d):
    status = ctx.hub.acknowledge_model_license(d["model_id"])
    return HT.model_license_done(status) if status.ok else HT.model_failure(status)


def _c_model_remove(ctx, d):
    return HT.model_removed(ctx.hub.remove_model(d["model_id"]))


def _c_repair(ctx, d):
    res = ctx.hub.repair_extension_store(user_approved=True)
    return res.get("message_fa") or ("چیزی برای ترمیم نبود." if res.get("status") == "nothing_to_repair" else HM.hub_error(res))


_CONFIRMED = {"install": _c_install, "rollback": _c_rollback, "disable": _c_disable, "enable": _c_enable,
              "perm_grant": _c_perm_grant, "net_on": _c_net_on, "model_download": _c_model_download,
              "model_license": _c_model_license, "model_remove": _c_model_remove, "repair_store": _c_repair}


# ================================================================== commands
def command(brain, turn):
    """`(kind, reply)` when the sentence is a hub command, else None. A command is a new topic: it withdraws any open dialogue question."""
    hub = get_hub(brain)
    named = False
    if hub is not None:
        try:
            named = hub.has_extensions() and hub.find_extension(turn.norm) is not None
        except Exception:
            named = False
    cmd = HI.classify(turn.text, turn.norm, turn.toks, named)
    if cmd is None:
        return None
    turn.dlg.clear_pending()
    if hub is None:
        return cmd.kind, HT.hub_unavailable()
    try:
        return cmd.kind, HC.HANDLERS[cmd.kind](HC.Ctx(brain, hub, turn), cmd)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return cmd.kind, HT.unexpected()


# ================================================================== wishes the app cannot fulfil
def _gap_for(turn):
    from brain_hub import gaps
    return gaps.match_gap(turn.text)


def gap_reply(brain, turn, lead=True):
    """The honest explanation for a sentence that asks for something the app cannot do yet, or None."""
    try:
        gap = _gap_for(turn)
        if gap is None:
            return None
        hub_state.save_wish(brain.memory, turn.text, brain._clock)
        return HT.gap_reply(gap, lead=lead)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None


def unsupported(brain, turn):
    """The reply to a build request the Self-Builder does not support: the exact gap if there is one, else the old text plus a way forward."""
    detail = gap_reply(brain, turn, lead=False)
    if detail is not None:
        return M.unsupported_build() + "\n\n" + detail
    hub_state.save_wish(brain.memory, turn.text, brain._clock)
    return HT.unsupported_with_hint(M.unsupported_build())


__all__ = ["early", "command", "gap_reply", "unsupported", "answer_pending", "note_served", "get_hub"]
