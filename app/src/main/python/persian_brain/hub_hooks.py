"""
Persian conversation brain - the road from a chat message to the hub
====================================================================
`brain.py` calls five functions here, only in the FULL scope (the Android app / an activated Core):

  early(brain, text)      before the Persian gate: the answer to the hub's open question; a pasted extension package
                          (`ext.v1`) or model card; a sentence that an INSTALLED extension asks for
  command(brain, turn)    a hub command (capability map, extensions, internet, models, Android, the extension prompt)
  gap_reply(brain, turn)  nothing else answered: if the sentence asks for something the app cannot do yet, say exactly
                          what exists, what is missing and the one honest next step
  llm_reply(brain, turn)  still nothing: when the user has imported a real language model and it is usable, it answers
  unsupported(brain, turn) the old «I cannot build that» answer, plus the way to extend the app from inside it

`early` and `command` return `(sub, reply)`; nothing changes in the app unless the user has said an explicit «بله» to
the hub's question (`answer_pending`). A hub that cannot be reached never breaks the conversation: the brain just does
what it did before.
"""

import json
import re

from self_builder import fa_text

from . import hub_brain
from . import hub_commands as HC
from . import hub_intents as HI
from . import hub_messages as HM
from . import hub_messages_llm as HL
from . import hub_messages_packs as HP
from . import hub_messages_self as HSM
from . import hub_messages_teacher as HTc
from . import hub_messages_tools as HT
from . import hub_self
from . import hub_state
from . import hub_teacher as HTe
from . import intents as I
from . import lexicon as lx
from . import messages as M
from . import normalization as nz

MAX_CALL_CHARS = 4000          # an installed extension is only matched against ordinary-sized messages
MAX_CARD_CHARS = 20_000
MAX_ANSWER_CHARS = 200
MAX_LLM_CHARS = 1200           # a longer message is not sent to the language model (it has a small window)
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
    try:                                                   # a start that has answered a message is a good start (pack_system.boot)
        from pack_system import boot
        boot.note_message_served()
    except Exception:
        pass


def packs(brain):
    """The pack manager of this brain's app (nothing is created on disk), or None."""
    return HC.pack_manager(brain.memory)


def _bind(brain):
    """Tell the pack registry which brain is talking (packs reach the hub and memory through it). Never raises."""
    try:
        from pack_system.registry import REGISTRY
        REGISTRY.bind(brain)
    except Exception:
        pass


def _risky_word(toks, word):
    """For the second question of a risky pack: a plain yes is not enough, only a yes that says «مطمئنم»."""
    sure = any(t.startswith("مطمئن") for t in toks)
    if sure and word is None and len(toks) <= 5 and set(toks) & lx.CONFIRM_WORDS:
        return "confirm"
    if word == "confirm" and not sure:
        return "need_sure"
    return word


def _guard(brain, text, fn):
    try:
        return fn()
    except Exception as exc:                               # the hub must never break a conversation
        brain._log_error(exc, text)
        return HT.unexpected()


# ================================================================== early
def early(brain, text):
    memory, clock = brain.memory, brain._clock
    _bind(brain)
    mine = hub_brain.early(brain, text)                   # Prompt 959: the emergency words and the cloud brain's own open question
    if mine is not None:
        return mine
    state = hub_state.load(memory, clock)
    toks = fa_text.words(nz.normalize(text)) if len(text) <= MAX_ANSWER_CHARS else []
    word = I.answer_word(toks) if toks else None
    if state is not None:
        if state[0] == "pack_install_risky" and toks:
            word = _risky_word(toks, word)
            if word == "need_sure":                       # the question stays open; nothing is installed
                return "answer:pack_install_risky", HP.risky_needs_word()
        if word:
            return "answer:" + state[0], _guard(brain, text, lambda: answer_pending(brain, state, word))
        _withdraw(brain, state)                           # any other message withdraws the open question
    elif word:
        old = hub_state.lapsed(memory, clock)             # a bare yes / no to a question nobody can answer any more
        if old is not None:
            _withdraw(brain, old)
            return "expired", HM.question_expired(old[0])
    pasted = _guard_pair(brain, text, lambda: _pasted_pack(brain, text))
    if pasted is None:
        pasted = _guard_pair(brain, text, lambda: _pasted(brain, text))
    if pasted is not None:
        return pasted
    called = _guard_pair(brain, text, lambda: _extension_call(brain, text))
    if called is not None:
        return called
    return _guard_pair(brain, text, lambda: _pack_early(brain, text))


def _withdraw(brain, state):
    """Forget the open question. An install proposal it pointed to is declined as well: the user was told it would be set aside."""
    ptype, data = state
    hub_state.clear(brain.memory)
    if ptype in ("pack_install", "pack_install_risky"):
        _decline_pack(brain, data)
        return
    if ptype == "teacher_send":
        HTe.drop_draft(brain, data)
        return
    if ptype != "install":
        return
    hub = get_hub(brain)
    if hub is None:
        return
    try:
        hub.decline_proposal(data["proposal_id"])
    except Exception as exc:                              # tidying up must never break the conversation
        brain._log_error(exc, "")


def _decline_pack(brain, data):
    pm = packs(brain)
    if pm is None:
        return
    try:
        pm.decline(data["proposal_id"])
    except Exception as exc:                              # tidying up must never break the conversation
        brain._log_error(exc, "")


def _guard_pair(brain, text, fn):
    try:
        return fn()
    except Exception as exc:
        brain._log_error(exc, text)
        return "error", HT.unexpected()


# ------------------------------------------------------------------ pasted packs (code.v1 / lang.v1)
def _pasted_pack(brain, text, ctx=None):
    """A `=== PACK ... ===` text or a JSON object with a pack schema, pasted in the chat -> the review + the question, else None.
    `ctx` is the caller's own context when the text did not come from the user's message (a teacher answer), so the question is opened the same way."""
    if "code.v" not in text and "lang.v" not in text and "=== PACK" not in text:
        return None
    from pack_system import intake
    schema = intake.declared_schema(text)
    if schema is None:
        return None
    if schema not in ("code.v1", "lang.v1"):
        return "pack", HP.other_schema(schema)
    pm = packs(brain)
    if pm is None:
        return "pack", HT.unexpected()
    result = pm.propose(text, origin="chat")
    status = result.get("status")
    if status == "pending_approval":
        data = {"proposal_id": result["proposal_id"], "pack_id": result["pack_id"], "title": str(result.get("title") or result["pack_id"])[:200],
                "kind": result["kind"], "planned_version": result.get("planned_version")}
        ctx = ctx if ctx is not None else HC.Ctx(brain, get_hub(brain))
        if not ctx.arm("pack_install", data):
            pm.decline(result["proposal_id"])
            return "pack", HT.unexpected()
        return "pack", HP.proposal(result)
    if status == "noop_identical":
        return "pack", HP.proposal_noop(result)
    if result.get("code") == "E_PACK_NONE":
        return "pack", HP.pack_not_found()
    if status == "rejected":
        return "pack", HP.proposal_rejected(result)
    return "pack", HP.proposal_failed(result)


def _pack_context(brain, text, norm=None):
    from pack_system.api import ChatContext
    norm = nz.normalize(text) if norm is None else norm
    return ChatContext(text, norm, fa_text.words(norm), None, brain)


def _pack_early(brain, text):
    """A sentence an installed code pack wants before the Persian brain looks at it (`stage="early"`), or None."""
    if len(text) > MAX_CALL_CHARS:
        return None
    from pack_system.registry import REGISTRY
    if not REGISTRY.has_stage("early"):
        return None
    found = REGISTRY.run_chat("early", _pack_context(brain, text))
    return ("pack:" + found[0], found[2]) if found else None


def _pack_fallback(brain, turn):
    """Nothing else answered: a code pack's fallback handler, then the language packs (retrieval). None when neither answers."""
    pm = packs(brain)
    if pm is None or not pm.exists():
        return None
    from pack_system.registry import REGISTRY
    if REGISTRY.has_stage("fallback"):
        found = REGISTRY.run_chat("fallback", _pack_context(brain, turn.text, turn.norm))
        if found:
            return found[2]
    match = pm.lang.answer(turn.text)
    return match.answer if match is not None else None


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
        if ptype in ("pack_install", "pack_install_risky"):
            _decline_pack(brain, data)
            return HM.declined()
        if ptype == "teacher_send":
            HTe.drop_draft(brain, data)
            return HTc.declined()
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


def _c_model_import(ctx, d):
    """The user said «بله» to importing a model file: hash + copy, then the whole verification pipeline, and say what really happened."""
    hub, name, model_id = ctx.hub, d["file_name"], d["model_id"]
    staged = hub.find_inbox_file(name) or {}
    before = hub.model_status(model_id)
    status = hub.import_unknown_model(name, model_id=model_id, license_ack=True)
    if not status.ok:
        return HL.import_failed(status, name, staged.get("size", 0))
    report = hub.prepare_model(model_id)
    title = (hub.model_status(model_id).card or {}).get("title") or model_id
    return HL.import_done(model_id, title, report, imported_before=before.state not in ("unregistered", "registered", "failed"))


def _c_repair(ctx, d):
    res = ctx.hub.repair_extension_store(user_approved=True)
    return res.get("message_fa") or ("چیزی برای ترمیم نبود." if res.get("status") == "nothing_to_repair" else HM.hub_error(res))


def _pm_call(ctx, fn):
    pm = packs(ctx.brain)
    return fn(pm) if pm is not None else HT.unexpected()


def _c_pack_install(ctx, d, risky_confirmed=False):
    def run(pm):
        res = pm.approve(d["proposal_id"], user_approved=True, confirm_risky=risky_confirmed)
        if res.get("status") == "confirm_required":                # a second, deliberate question for a risky pack
            if ctx.arm("pack_install_risky", d):
                return HP.ask_risky(res)
            pm.decline(d["proposal_id"])
            return HT.unexpected()
        return HP.approved(res) if res.get("status") == "applied" else HP.approve_failed(res)
    return _pm_call(ctx, run)


def _c_pack_install_risky(ctx, d):
    return _c_pack_install(ctx, d, risky_confirmed=True)


def _c_pack_rollback(ctx, d):
    def run(pm):
        res = pm.rollback(d["pack_id"], d.get("to_version"))
        return HP.rolled_back(res) if res.get("status") == "rolled_back" else HP.rollback_failed(res)
    return _pm_call(ctx, run)


def _c_pack_disable(ctx, d):
    return _pm_call(ctx, lambda pm: (lambda r: HP.disabled(r) if r.get("status") == "disabled" else HP.switch_failed(r))(pm.disable(d["pack_id"])))


def _c_pack_enable(ctx, d):
    return _pm_call(ctx, lambda pm: (lambda r: HP.enabled(r) if r.get("status") == "enabled" else HP.switch_failed(r))(pm.enable(d["pack_id"], user_approved=True)))


def _c_pack_remove(ctx, d):
    return _pm_call(ctx, lambda pm: (lambda r: HP.removed(r) if r.get("status") == "removed" else HP.switch_failed(r))(pm.remove(d["pack_id"], user_approved=True)))


def _c_pack_safe_leave(ctx, d):
    def run(pm):
        pm.leave_safe_mode()
        return HP.safe_left(pm.activate_all(at_boot=False))
    return _pm_call(ctx, run)


_CONFIRMED = {"install": _c_install, "rollback": _c_rollback, "disable": _c_disable, "enable": _c_enable,
              "perm_grant": _c_perm_grant, "net_on": _c_net_on, "model_download": _c_model_download,
              "model_license": _c_model_license, "model_remove": _c_model_remove, "model_import": _c_model_import, "repair_store": _c_repair,
              "pack_install": _c_pack_install, "pack_install_risky": _c_pack_install_risky, "pack_rollback": _c_pack_rollback,
              "pack_disable": _c_pack_disable, "pack_enable": _c_pack_enable, "pack_remove": _c_pack_remove,
              "pack_safe_leave": _c_pack_safe_leave, **HTe.CONFIRMED}


# ================================================================== commands
def command(brain, turn):
    """`(kind, reply)` when the sentence is a hub command, else None. A command is a new topic: it withdraws any open dialogue question."""
    mine = hub_brain.command(brain, turn)                  # Prompt 959: «مغز ابری را فعال کن», «وضعیت مغز ابری», «کلید را فراموش کن» ...
    if mine is not None:
        return mine
    hub = get_hub(brain)
    named = False
    if hub is not None:
        try:
            named = hub.has_extensions() and hub.find_extension(turn.norm) is not None
        except Exception:
            named = False
    named_pack = False
    pm = packs(brain)
    if pm is not None and pm.exists():
        try:
            named_pack = pm.find(turn.text) is not None
        except Exception:
            named_pack = False
    teacher_open = HTe.mission_is_open(brain, hub) if hub is not None else False
    cmd = HI.classify(turn.text, turn.norm, turn.toks, named, named_pack, teacher_open)
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


def _self_snapshot(brain):
    """What this phone's app really has right now, as plain data (see `hub_self.snapshot`). Never raises."""
    hub = get_hub(brain)
    return hub_self.snapshot(hub, packs(brain), HTe.service(brain, hub) if hub is not None else None,
                             hub_state.load_wish(brain.memory, brain._clock))


def _registry_lines(turn):
    """The lines about what the assistant built for itself (the Self-Builder registry), or None when it cannot be read. Never raises."""
    try:
        service = getattr(turn, "service", None)
        if service is None or service.unavailable() is not None:
            return None
        return M.capability_registry_lines(service.capabilities())
    except Exception:
        return None


def help_reply(brain, turn):
    """«راهنما» in the full app: the older list (what the Self-Builder does) plus the ways the assistant can grow from inside. Never raises."""
    try:
        return M.help_text() + "\n" + HSM.help_more()
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return M.help_text()


def about_reply(brain, turn, records):
    """«چه کارهایی بلدی؟» (the capability list) in the full app: the same answer as «توانایی‌هات چیه؟» - everything the app really has, what it
    cannot do yet, and what it built for itself. None when it cannot be written (the caller then gives the older list). Never raises."""
    try:
        return hub_self.reply(hub_self.ABOUT, _self_snapshot(brain), M.capability_registry_lines(records))
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None


def self_reply(brain, turn):
    """A sentence about the assistant ITSELF («چه کارهایی می‌توانی؟», «مغز فارسی داری؟», «خودت را ارتقا بده», «صدایم را می‌شنوی؟»,
    «می‌توانی از ChatGPT کمک بگیری؟»): the answer written from what this app really has right now, or None. It only explains;
    nothing is started, sent or installed by it. Never raises."""
    try:
        kind = hub_self.classify(turn.norm, turn.toks)
        if kind is None:
            return None
        reply = hub_self.reply(kind, _self_snapshot(brain), _registry_lines(turn) if kind == hub_self.ABOUT else None)
        turn.intent = I.Intent("HUB", "self_" + kind, 0.9, ["self_knowledge"])
        return reply
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None


def unknown_reply(brain, turn, intent):
    """Nothing in the app answered a question or a request (no rule, no taught fact, no pack, no language model): an honest reply that says
    what is missing and the real ways to grow, instead of the core's blank fallback. The sentence is remembered, so a plain
    «از ChatGPT بخواه» can take it on. None for anything that is not a question or a request, or too short to be one. Never raises."""
    try:
        if intent is None or intent.kind not in (I.QUESTION, I.REQUEST) or len(turn.toks) < 2 or len(turn.text) > MAX_LLM_CHARS:
            return None
        remembered = hub_state.save_wish(brain.memory, turn.text, brain._clock)
        return hub_self.unknown(brain.memory, brain._clock, _self_snapshot(brain), remembered)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None


def gap_reply(brain, turn, lead=True):
    """The honest explanation for a sentence that asks for something the app cannot do yet, or None. With `lead`, first what an installed
    pack answers, then what the assistant says about itself (never a language model's guess about who it is)."""
    try:
        if lead:
            answered = _pack_fallback(brain, turn)        # an installed pack's handler or language data
            if answered is not None:
                return answered
            own = self_reply(brain, turn)                 # a question about the assistant itself is answered from what it really has
            if own is not None:
                return own
        gap = _gap_for(turn)
        if gap is None:
            return None
        hub_state.save_wish(brain.memory, turn.text, brain._clock)
        return HT.gap_reply(gap, lead=lead)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None


def llm_reply(brain, turn):
    """What the language model on the phone says to a sentence nothing else in the app could answer, or None (no usable model, or not a
    sentence for it). The model's answer is only shown as text - never run, never taken as a command. A model that is busy, too slow or
    failed is said plainly. Never raises."""
    try:
        text = (turn.text or "").strip()
        if not text or len(text) > MAX_LLM_CHARS or sum(ch.isalpha() for ch in text) < 2 or I.answer_word(turn.toks):
            return None                                        # a bare yes / no, a number, a symbol: not a question for a model
        hub = get_hub(brain)
        if hub is None or not hub.has_models():
            return None
        from brain_hub import llm as hub_llm
        llm = hub_llm.get_llm(hub)
        if llm is None:
            return None
        result = llm.reply(text)
        if result.ok:
            note = ""
            if not hub_state.llm_note_shown(brain.memory, result.model_id) and hub_state.mark_llm_note(brain.memory, result.model_id):
                title = (hub.model_status(result.model_id).card or {}).get("title") or result.model_id
                note = "\n\n" + HL.first_answer_note(title)
            return result.text + note
        if result.code in ("no_model", "bad_question"):
            return None
        if result.code == "busy":
            return HL.llm_busy()
        if result.code == "timeout":
            return HL.llm_timeout(result.seconds)
        return HL.llm_failed(result.code)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None


def cloud_reply(brain, turn, intent=None):
    """What the user's own cloud brain says to a sentence nothing else in the app could answer (only when he switched it on), or None.
    The answer is only shown as text - never run, never taken as a command. Never raises."""
    return hub_brain.reply(brain, turn, intent)


def unsupported(brain, turn):
    """The reply to a build request the Self-Builder does not support: the exact gap if there is one, else the old text plus a way forward."""
    detail = gap_reply(brain, turn, lead=False)
    if detail is not None:
        return M.unsupported_build() + "\n\n" + detail
    hub_state.save_wish(brain.memory, turn.text, brain._clock)
    return HT.unsupported_with_hint(M.unsupported_build())


__all__ = ["early", "command", "gap_reply", "self_reply", "about_reply", "help_reply", "llm_reply", "cloud_reply", "unknown_reply", "unsupported",
           "answer_pending", "note_served", "get_hub", "packs"]
