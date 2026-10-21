"""
Persian conversation brain - hub command handlers
=================================================
One small function per hub command (see `hub_intents`). Each one calls the hub - the single choke point for the
extension runtime, the web reader, local models and the Android adapters - and answers from the REAL result.

Anything that changes something (install, roll back, switch an extension on, grant a permission, internet on, download
or remove a model, repair a damaged store) is NOT done here: the handler opens the hub's one question
(`hub_state`) and asks; the change happens in `hub_hooks.answer_pending` after the user's explicit «بله».
Reading and restricting (list, history, status, read a page when the internet is on, switch the internet or an
extension permission OFF) happen at once because they cannot grant anything.
"""

from . import hub_intents as HI
from . import hub_messages as HM
from . import hub_messages_tools as HT
from . import hub_state


class Ctx:
    """What a handler needs: the brain, the hub and (for commands typed in chat) the current turn."""

    def __init__(self, brain, hub, turn=None):
        self.brain, self.hub, self.turn = brain, hub, turn
        self.memory = brain.memory
        self.clock = brain._clock
        self.norm = turn.norm if turn is not None else ""

    def arm(self, type_, data):
        """Open the hub's question and withdraw any other open question (there is only ever one). False if it cannot be stored."""
        if not hub_state.save(self.memory, type_, data, self.clock):
            return False
        if self.turn is not None:
            self.turn.dlg.clear_pending()
        else:
            from .dialogue import Dialogue
            try:
                dlg = Dialogue(self.memory, self.clock).load()
                if dlg.pending is not None:
                    dlg.clear_pending()
                    dlg.commit()
            except Exception:
                pass
        return True

    def network_on(self):
        try:
            return bool(self.hub.permissions.is_granted("network"))
        except Exception:
            return False


# ------------------------------------------------------------------ helpers
def _store_problem(ctx):
    """The reply when the extension store is damaged (the repair question is then open), else None."""
    if ctx.hub.extension_store_state() == "damaged":
        ctx.arm("repair_store", {})
        return HM.store_unusable_ask()
    return None


def _pick_extension(ctx, action):
    """(extension summary, None) or (None, reply): the one the sentence names, else the only one installed."""
    problem = _store_problem(ctx)
    if problem:
        return None, problem
    caps = ctx.hub.extensions()
    if not caps:
        return None, HM.no_extensions()
    cid = ctx.hub.find_extension(ctx.norm)
    cap = next((c for c in caps if c.get("capability_id") == cid), None) if cid else None
    if cap is None and len(caps) == 1:
        cap = caps[0]
    if cap is None:
        return None, HM.which_extension(action, caps)
    return cap, None


def _pick_model(ctx, cmd, action):
    """(model status, None) or (None, reply)."""
    models = ctx.hub.list_models()
    if not models:
        return None, HT.no_models()
    mid = cmd.slots.get("model_id")
    if mid is None and len(models) == 1:
        mid = models[0].model_id
    if mid is None:
        return None, HT.which_model(action, models)
    st = ctx.hub.model_status(mid)
    if st.state == "unregistered":
        return None, (st.message_fa or HT.no_models()) + " " + HT.which_model(action, models)
    return st, None


def _titles(ctx):
    return {c.get("capability_id"): c.get("title") for c in ctx.hub.extensions()}


# ------------------------------------------------------------------ overview
def h_overview(ctx, cmd):
    graph = ctx.hub.graph()
    summary = graph.summary()
    usable = [n.title_fa for n in graph.usable() if n.kind != "gap"][:14]
    gaps = []
    for node in graph.nodes():
        if node.kind == "gap" and not node.usable:
            why = node.blockers[0].text_fa if node.blockers else ""
            gaps.append("• %s — %s%s" % (node.title_fa, node.to_dict()["state_label_fa"], ("؛ " + why) if why else ""))
    limit = 14 if cmd.slots.get("missing") else 6
    return HT.overview(summary, usable, gaps[:limit], missing_only=bool(cmd.slots.get("missing")))


# ------------------------------------------------------------------ extensions
def h_ext_list(ctx, cmd):
    problem = _store_problem(ctx)
    if problem:
        return problem
    return HM.ext_list(ctx.hub.extensions(), ctx.hub.pending_proposals())


def h_ext_history(ctx, cmd):
    problem = _store_problem(ctx)
    if problem:
        return problem
    cid = ctx.hub.find_extension(ctx.norm)
    return HM.ext_history(ctx.hub.extension_history(cid, limit=10), _titles(ctx))


def h_ext_rollback(ctx, cmd):
    cap, reply = _pick_extension(ctx, "برگردانم")
    if cap is None:
        return reply
    cid = cap["capability_id"]
    versions = ctx.hub.extension_versions(cid)
    wanted = cmd.slots.get("version")
    healthy = [v["version"] for v in versions if v.get("status") in ("superseded", "rolled_back")
               and (cap.get("active_version") is None or v["version"] < cap["active_version"])]
    if wanted is not None and wanted not in [v["version"] for v in versions if v.get("status") in ("superseded", "rolled_back")]:
        return HM.rollback_failed({"code": "E_EXT_BAD_TARGET"})
    if wanted is None and not healthy:
        return HM.rollback_failed({"status": "nothing_to_roll_back"})
    target = wanted if wanted is not None else max(healthy)
    if not ctx.arm("rollback", {"capability_id": cid, "title": cap["title"], "to_version": target}):
        return HT.unexpected()
    return HM.ask_rollback(cap["title"], cap.get("active_version"), target)


def h_ext_disable(ctx, cmd):
    cap, reply = _pick_extension(ctx, "غیرفعال کنم")
    if cap is None:
        return reply
    if cap.get("state") == "disabled":
        return "افزونهٔ «%s» همین حالا هم غیرفعال است." % cap["title"]
    if not ctx.arm("disable", {"capability_id": cap["capability_id"], "title": cap["title"]}):
        return HT.unexpected()
    return HM.ask_disable(cap["title"])


def h_ext_enable(ctx, cmd):
    cap, reply = _pick_extension(ctx, "فعال کنم")
    if cap is None:
        return reply
    if cap.get("state") == "active":
        return "افزونهٔ «%s» همین حالا هم فعال است." % cap["title"]
    if not ctx.arm("enable", {"capability_id": cap["capability_id"], "title": cap["title"]}):
        return HT.unexpected()
    return HM.ask_enable(cap["title"])


def _permission_choice(named, pool):
    """The one permission meant: the named one that is in `pool`, else the only one in `pool`, else None."""
    chosen = [p for p in named if p in pool]
    if len(chosen) == 1:
        return chosen[0]
    return pool[0] if len(pool) == 1 and not named else None


def h_ext_perm_grant(ctx, cmd):
    cap, reply = _pick_extension(ctx, "مجوز بدهم")
    if cap is None:
        return reply
    perms = cap.get("permissions") or {}
    pool = list(perms.get("missing") or [])
    if not pool:
        return "افزونهٔ «%s» مجوز ندادهٔ دیگری ندارد؛ هر چه اعلام کرده از قبل داده شده است." % cap["title"]
    perm = _permission_choice(cmd.slots.get("permissions") or [], pool)
    if perm is None:
        return "کدام مجوز را به «%s» بدهم؟ یکی از این‌ها: %s." % (cap["title"], HM.perm_names(pool))
    if not ctx.arm("perm_grant", {"capability_id": cap["capability_id"], "title": cap["title"], "permission": perm}):
        return HT.unexpected()
    return HM.ask_permission(cap["title"], perm)


def h_ext_perm_revoke(ctx, cmd):
    cap, reply = _pick_extension(ctx, "مجوزش را بگیرم")
    if cap is None:
        return reply
    perms = cap.get("permissions") or {}
    pool = list(perms.get("granted") or [])
    perm = _permission_choice(cmd.slots.get("permissions") or [], pool)
    if not pool:
        return "افزونهٔ «%s» هیچ مجوز اضافه‌ای ندارد که بشود گرفت." % cap["title"]
    if perm is None:
        return "کدام مجوز را از «%s» بگیرم؟ یکی از این‌ها: %s." % (cap["title"], HM.perm_names(pool))
    res = ctx.hub.revoke_extension_permission(cap["capability_id"], perm)
    if res.get("status") == "revoked":
        return HM.permission_revoked(res, cap["title"])
    return HM.permission_failed(res)


# ------------------------------------------------------------------ internet
def h_net_status(ctx, cmd):
    return HM.net_status(ctx.network_on(), ctx.hub.network_status())


def h_net_on(ctx, cmd):
    if ctx.network_on():
        return HM.net_on_done(False)
    if not ctx.arm("net_on", {}):
        return HT.unexpected()
    return HM.ask_net_on()


def h_net_off(ctx, cmd):
    change = ctx.hub.revoke_permission("network")
    if change.ok:
        return HM.net_off_done()
    return HM.net_change_failed(change.code)


def h_fetch(ctx, cmd):
    url = cmd.slots["url"]
    result = ctx.hub.fetch(url)
    data = result.to_dict()
    if result.ok:
        return HM.fetch_ok(data)
    if result.code == "permission_denied" and ctx.arm("net_on", {"url": url}):
        return "اینترنت برنامه خاموش است، پس صفحه را نخواندم.\n" + HM.ask_net_on(url)
    return HM.fetch_failed(data)


# ------------------------------------------------------------------ models
def h_models_list(ctx, cmd):
    return HT.models_list(ctx.hub.list_models(), ctx.hub.model_runtimes_info())


def h_model_download(ctx, cmd):
    st, reply = _pick_model(ctx, cmd, "دانلود کنم")
    if st is None:
        return reply
    if st.license_policy == "needs_review" and not st.license_ack:
        if ctx.arm("model_license", {"model_id": st.model_id}):
            return HT.ask_model_license(st)
        return HT.unexpected()
    if st.license_policy in ("restricted", "unknown"):
        return "مجوز این مدل («%s») با این برنامه سازگار شناخته نشده و دانلود انجام نمی‌شود." % ((st.card or {}).get("license") or "?")
    if st.state not in ("registered", "failed"):
        return "مدل «%s» در وضعیتی است که دانلود لازم نیست: %s" % (st.model_id, st.message_fa)
    if not ctx.arm("model_download", {"model_id": st.model_id}):
        return HT.unexpected()
    return HT.ask_model_download(st, ctx.network_on())


def h_model_prepare(ctx, cmd):
    st, reply = _pick_model(ctx, cmd, "آماده کنم")
    if st is None:
        return reply
    return HT.model_pipeline(st.model_id, None, ctx.hub.prepare_model(st.model_id))


def h_model_remove(ctx, cmd):
    st, reply = _pick_model(ctx, cmd, "حذف کنم")
    if st is None:
        return reply
    if not ctx.arm("model_remove", {"model_id": st.model_id}):
        return HT.unexpected()
    return HT.ask_model_remove((st.card or {}).get("title") or st.model_id)


def h_model_license(ctx, cmd):
    st, reply = _pick_model(ctx, cmd, "مجوزش را تأیید کنم")
    if st is None:
        return reply
    if st.license_policy != "needs_review":
        return "مجوز این مدل نیازی به تأیید تو ندارد؛ " + ("و با این برنامه سازگار شناخته نشده است." if st.license_policy != "permissive" else "آزاد و سازگار است.")
    if st.license_ack:
        return "مجوز این مدل از قبل تأیید شده است."
    if not ctx.arm("model_license", {"model_id": st.model_id}):
        return HT.unexpected()
    return HT.ask_model_license(st)


# ------------------------------------------------------------------ Android, permissions, prompt, repair
def h_android_status(ctx, cmd):
    try:
        from android_adapters.catalog import FEATURES
        titles = {f.feature_id: f.title_fa for f in (FEATURES.values() if isinstance(FEATURES, dict) else FEATURES)}
    except Exception:
        titles = {}
    return HT.android_status(ctx.hub.android_statuses(), titles)


def h_permissions(ctx, cmd):
    return HT.permissions(ctx.hub.permission_rows(), ctx.hub.extensions())


def h_ext_prompt(ctx, cmd):
    from brain_hub import templates
    wish = cmd.slots.get("wish") or ""
    remembered = ""
    if not wish:
        remembered = hub_state.load_wish(ctx.memory, ctx.clock)
    return HM.prompt_reply(templates.build_prompt(wish or remembered), from_memory=bool(remembered))


def h_ext_help(ctx, cmd):
    return HM.ext_help()


def h_repair_store(ctx, cmd):
    state = ctx.hub.extension_store_state()
    if state == "absent":
        return "حافظهٔ افزونه‌ها هنوز ساخته نشده؛ چیزی برای ترمیم نیست."
    if state == "healthy":
        return "حافظهٔ افزونه‌ها سالم است؛ چیزی تغییر نکرد."
    ctx.arm("repair_store", {})
    return HM.store_unusable_ask()


HANDLERS = {
    HI.OVERVIEW: h_overview, HI.EXT_LIST: h_ext_list, HI.EXT_HISTORY: h_ext_history, HI.EXT_ROLLBACK: h_ext_rollback,
    HI.EXT_DISABLE: h_ext_disable, HI.EXT_ENABLE: h_ext_enable, HI.EXT_PERM_GRANT: h_ext_perm_grant,
    HI.EXT_PERM_REVOKE: h_ext_perm_revoke, HI.NET_ON: h_net_on, HI.NET_OFF: h_net_off, HI.NET_STATUS: h_net_status,
    HI.FETCH: h_fetch, HI.MODELS_LIST: h_models_list, HI.MODEL_DOWNLOAD: h_model_download, HI.MODEL_PREPARE: h_model_prepare,
    HI.MODEL_REMOVE: h_model_remove, HI.MODEL_LICENSE: h_model_license, HI.ANDROID_STATUS: h_android_status,
    HI.PERMISSIONS: h_permissions, HI.EXT_PROMPT: h_ext_prompt, HI.EXT_HELP: h_ext_help, HI.REPAIR_STORE: h_repair_store,
}

__all__ = ["Ctx", "HANDLERS"]
