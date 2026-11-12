"""
Persian conversation brain - the teacher commands (asking another assistant, letting the app look into another app)
===================================================================================================================
Handlers for the `teacher_*` / `access_settings` hub commands and the two confirmations («بله») behind them. The work is done by
`teacher.service`; this module only decides what to ASK first and says what really happened.

What needs the user's explicit «بله» (one open question, see `hub_state`):
    teacher_send    the request leaves the app (share sheet / clipboard + the other app or its website)
    teacher_screen  the app may look into ONE other app for a limited time (the typing recipe)

What happens at once (it only reads or restricts): status, list of assistants, cancel, taking the permission back,
opening Android's accessibility page (the user switches the service on himself), reading the answer when the user says it arrived.
Whatever an assistant answers is TEXT: a pack goes through the pack system's own review and its own «بله»; an answer is only shown.

The user's OWN cloud brain is one more "assistant" («از مغزت بخواه برایم X بسازد»): the same two-step question, but the request is sent
by the app itself, in ONE tool-less request with his own key (see `brain_v2.service.BrainV2.author`) - never to another app. What comes
back is TEXT like any other answer: a pack is reviewed (not run) and installed only after his second «بله».
"""

from . import hub_brain
from . import hub_intents as HI
from . import hub_messages_brain as BM
from . import hub_messages_teacher as HTc
from . import hub_messages_tools as HT
from . import hub_state

ALLOW_MINUTES = 30
OPEN_FOR_CHAT = frozenset({"sent", "running", "captured"})        # states in which «جواب آمد» / «خودت انجام بده» mean something


def service(ctx_or_brain, hub=None):
    """The teacher service of this app's hub, or None (nothing is created on disk before a mission is made)."""
    hub = hub if hub is not None else getattr(ctx_or_brain, "hub", None)
    if hub is None:
        return None
    try:
        from teacher import service as teacher_service
        return teacher_service.get_service(hub)
    except Exception:
        return None


def mission_is_open(brain, hub):
    """Is there a mission a «جواب آمد» can belong to? Cheap and never raises."""
    svc = service(brain, hub)
    if svc is None:
        return False
    try:
        latest = svc.store.latest(only_open=True)
    except Exception:
        return False
    return bool(latest and latest["state"] in OPEN_FOR_CHAT)


def _title(assistant_id):
    from teacher import assistants
    found = assistants.get(assistant_id)
    return found.title if found else "دستیار"


def _row(rows, assistant_id):
    return next((r for r in rows if r["id"] == assistant_id), None) or {"id": assistant_id, "title": _title(assistant_id), "installed": False,
                                                                       "package": "", "site": ""}


# ================================================================== asking
def h_ask(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    from teacher import assistants
    if cmd.slots.get("assistant") == assistants.BRAIN_ID:
        return _ask_own_brain(ctx, svc, cmd)
    rows = svc.assistants()
    assistant_id = cmd.slots.get("assistant") or svc.default_assistant(rows)
    wish = cmd.slots.get("wish") or ""
    remembered = False
    if not wish:
        wish = hub_state.load_wish(ctx.memory, ctx.clock)          # «از ChatGPT بخواه» right after a «this I cannot do yet» answer
        remembered = bool(wish)
    row = _row(rows, assistant_id)
    if not wish:
        return HTc.need_wish(row["title"] if cmd.slots.get("assistant") else None)
    drafted = svc.draft(wish, cmd.slots.get("kind") or "code", assistant_id)
    if not drafted["ok"]:
        return HTc.send_failed(drafted, row["title"])
    mission = drafted["mission"]
    superseded = any(m["state"] in ("sent", "running", "captured") and m["id"] != mission["id"] for m in svc.store.missions())
    if not ctx.arm("teacher_send", {"mission_id": mission["id"], "assistant": assistant_id, "kind": mission["kind"]}):
        svc.finish(mission["id"], "cancelled", "پرسش ذخیره نشد")
        return HT.unexpected()
    site = (assistants.get(assistant_id).site if assistants.get(assistant_id) else "") or row["site"]
    return HTc.ask_send(row["title"], mission["wish"], mission["kind"], drafted["request_chars"], bool(row["installed"]), site,
                        from_memory=remembered, superseded=superseded)


def c_send(ctx, d):
    svc = service(ctx)
    mission = svc.store.get(d["mission_id"]) if svc is not None else None
    if svc is None or mission is None or mission["state"] != "drafted":
        return HTc.mission_gone()
    if mission["assistant"] == "brain":
        return _send_to_own_brain(ctx, svc, mission)
    title = _title(mission["assistant"])
    svc.supersede(mission["id"])
    result = svc.deliver(mission["id"])
    if result["ok"]:
        return HTc.sent(result, title)
    if result.get("copied"):                                           # the text IS on the clipboard: the user can finish by hand
        svc.store.update(mission["id"], state="sent", route="copy_open", note="متن در کلیپ‌بورد است؛ باز کردن برنامه ناموفق بود")
    else:
        svc.finish(mission["id"], "failed", note=str(result.get("code") or "failed")[:60])
    return HTc.send_failed(result, title)


# ================================================================== the user's own cloud brain
def _ask_own_brain(ctx, svc, cmd):
    """«از مغزت بخواه …» / «از مغز ابری‌ات بپرس …». A plain question is answered at once (it is the same as any free sentence the cloud
    brain answers); a pack request first shows exactly what leaves the phone and waits for the user's «بله»."""
    brain = hub_brain.service(ctx.brain)
    if brain is None:
        return HT.unexpected()
    wish = cmd.slots.get("wish") or ""
    remembered = False
    if not wish:
        wish = hub_state.load_wish(ctx.memory, ctx.clock)          # «از مغزت بخواه» right after a «this I cannot do yet» answer
        remembered = bool(wish)
    if not wish:
        return BM.teacher_need_wish()
    kind = cmd.slots.get("kind") or "code"
    if kind == "ask":
        reply = brain.reply(wish)
        shown = hub_brain._render(brain, reply)
        if shown is not None:
            return shown
        return BM.teacher_not_ready(reply.code) if reply.kind == "not_ready" else HT.unexpected()
    ready, why = brain.ready()
    if not ready:
        return BM.teacher_not_ready(why)
    refused = brain.precheck(wish)                                 # a secret in the wish is refused BEFORE the user is asked anything
    if refused is not None:
        return hub_brain._render(brain, refused) or HT.unexpected()
    drafted = svc.draft(wish, kind, "brain")
    if not drafted["ok"]:
        return HTc.send_failed(drafted, "مغز ابری")
    mission = drafted["mission"]
    superseded = any(m["state"] in ("sent", "running", "captured") and m["id"] != mission["id"] for m in svc.store.missions())
    if not ctx.arm("teacher_send", {"mission_id": mission["id"], "assistant": "brain", "kind": mission["kind"]}):
        svc.finish(mission["id"], "cancelled", "پرسش ذخیره نشد")
        return HT.unexpected()
    return BM.teacher_ask_send(brain.status(), mission["wish"], mission["kind"], drafted["request_chars"], from_memory=remembered,
                               superseded=superseded)


_NOT_SENT = frozenset({"halted", "not_ready", "blocked", "rate"})          # outcomes in which the request never left the phone


def _send_to_own_brain(ctx, svc, mission):
    """The user said «بله»: ONE authoring request to his own cloud brain, then the same review as any pasted pack (no execution)."""
    brain = hub_brain.service(ctx.brain)
    if brain is None:
        svc.finish(mission["id"], "cancelled", "مغز ابری در دسترس نبود")
        return HT.unexpected()
    svc.supersede(mission["id"])
    svc.store.update(mission["id"], state="sent", route="brain", note="درخواست به مغز ابری رفت؛ منتظر جواب")
    try:
        reply = brain.author(svc.request_text(mission), wish=mission["wish"])
    except Exception:                                              # `author` never raises; this keeps the mission from staying "sent" if it ever did
        svc.finish(mission["id"], "failed", "خطای داخلی")
        return HT.unexpected()
    if reply.kind != "answer":
        code = (reply.code or reply.kind)[:40]
        svc.finish(mission["id"], "cancelled" if reply.kind in _NOT_SENT or (reply.kind == "too_long" and reply.code == "request") else "failed",
                   note="مغز ابری: " + code)
        return _author_problem(reply)
    from teacher import capture
    klass = capture.classify(reply.text)
    if klass in ("pack", "other_pack"):
        fresh = svc.store.get(mission["id"]) or mission
        return _take_answer(ctx, svc, {"mission": fresh, "text": reply.text, "klass": klass, "source": "brain"})
    svc.finish(mission["id"], "failed", note="جوابِ مغز ابری بسته نبود")
    return BM.teacher_no_pack(reply.text)


def _author_problem(reply):
    kind = reply.kind
    if kind == "halted":
        return BM.halted()
    if kind == "not_ready":
        return BM.teacher_not_ready(reply.code)
    if kind == "blocked":
        return BM.blocked(reply.code, reply.label_fa, reply.secret)
    if kind == "rate":
        return BM.rate_limited()
    if kind == "too_long":
        return BM.teacher_answer_cut() if reply.code == "answer" else BM.teacher_request_too_long()
    if kind == "failed":
        return BM.teacher_failed(reply.reason_fa, reply.detail)
    return HT.unexpected()


def drop_draft(brain, data):
    """The «send» question was answered no / withdrawn: the draft is cancelled (nothing was sent). Never raises."""
    try:
        svc = service(brain, _hub_of(brain))
        if svc is not None and data.get("mission_id"):
            mission = svc.store.get(data["mission_id"])
            if mission is not None and mission["state"] == "drafted":
                svc.finish(mission["id"], "cancelled", "قبل از فرستادن کنار گذاشته شد")
    except Exception:
        pass


def _hub_of(brain):
    from . import hub_hooks
    return hub_hooks.get_hub(brain)


# ================================================================== the answer
def h_capture(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    result = svc.capture()
    mission = result.get("mission")
    if not result["ok"]:
        if result["code"] == "no_mission":
            return HTc.no_mission()
        return HTc.capture_nothing(result, _title(mission["assistant"]) if mission else "دستیار", mission["kind"] if mission else "ask")
    return _take_answer(ctx, svc, result)


def _take_answer(ctx, svc, result):
    mission, text, klass, source = result["mission"], result["text"], result["klass"], result["source"]
    title = _title(mission["assistant"])
    if klass in ("pack", "other_pack"):
        from . import hub_hooks
        pasted = hub_hooks._pasted_pack(ctx.brain, text, ctx)
        if pasted is not None:
            armed = hub_state.load(ctx.memory, ctx.clock)
            proposed = bool(armed) and armed[0] in ("pack_install",)
            svc.finish(mission["id"], "proposed" if proposed else "failed",
                       note="بسته به بررسی رفت" if proposed else "بسته پذیرفته نشد")
            return HTc.captured_pack(source, pasted[1])
    svc.finish(mission["id"], "done", note="جواب نشان داده شد", answer=text)
    return HTc.answer(title, text, source, mission["kind"])


# ================================================================== the typing recipe
def h_screen(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    mission = svc.store.latest(only_open=True)
    if mission is None or mission["state"] not in OPEN_FOR_CHAT:
        return HTc.no_mission()
    title = _title(mission["assistant"])
    state = svc.screen_state(mission)
    if state["ok"]:
        return _start_screen(svc, mission, title)
    if state["code"] == "not_allowed" and state.get("package"):
        if ctx.arm("teacher_screen", {"mission_id": mission["id"], "package": state["package"]}):
            return HTc.ask_screen(title, state["package"], ALLOW_MINUTES)
        return HT.unexpected()
    return HTc.screen_blocked(state, title)


def _start_screen(svc, mission, title):
    started = svc.start_screen_run(mission["id"])
    if started["ok"]:
        return HTc.screen_started(started, title)
    return HTc.screen_blocked(started, title)


def c_screen(ctx, d):
    svc = service(ctx)
    mission = svc.store.get(d["mission_id"]) if svc is not None else None
    if svc is None or mission is None or mission["state"] not in OPEN_FOR_CHAT:
        return HTc.mission_gone()
    svc.allow_app(d["package"], ALLOW_MINUTES)
    title = _title(mission["assistant"])
    started = _start_screen(svc, mission, title)
    return HTc.allowed(d["package"], ALLOW_MINUTES) + "\n" + started


# ================================================================== status, list, cancel, revoke, accessibility page
def h_status(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    state = svc.run_state()
    mission = state["mission"]
    return HTc.status(mission, _title(mission["assistant"]) if mission else "", state["running"], svc.allowed_apps())


def h_cancel(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    return HTc.cancelled(svc.cancel())


def h_list(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    return HTc.assistant_list(svc.assistants())


def h_revoke(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    return HTc.revoked(svc.revoke_apps())


def h_access_settings(ctx, cmd):
    svc = service(ctx)
    if svc is None:
        return HT.unexpected()
    result = svc.doors.settings.open_settings("accessibility")
    return HTc.access_settings({"ok": result.ok, "code": result.code, "detail_fa": result.detail_fa})


HANDLERS = {HI.TEACHER_ASK: h_ask, HI.TEACHER_CAPTURE: h_capture, HI.TEACHER_SCREEN: h_screen, HI.TEACHER_STATUS: h_status,
            HI.TEACHER_CANCEL: h_cancel, HI.TEACHER_LIST: h_list, HI.TEACHER_REVOKE: h_revoke, HI.ACCESS_SETTINGS: h_access_settings}
CONFIRMED = {"teacher_send": c_send, "teacher_screen": c_screen}

__all__ = ["HANDLERS", "CONFIRMED", "mission_is_open", "drop_draft", "service", "ALLOW_MINUTES"]
