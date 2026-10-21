"""
brain_hub.invoker - build the capability graph from the LIVE systems, and run a node through one choke point
===========================================================================================================
`build_graph(hub)` asks each real system for its truth (extension manager, Self-Builder registry, model manager,
Android adapter layer, permission store, web status) and turns it into `CapabilityNode`s with an exact state. A builder
that fails does not hide anything: it adds a `broken` node that says which part could not be read.

`execute(hub, node_id, action, params, user_approved=...)` is the single execution entry point. It looks the node up in a FRESH
graph, refuses anything that is not usable right now (naming the exact blocker), refuses unknown actions, and only then
calls the owning system. Extensions and Self-Builder capabilities enforce their own permissions again inside their
managers; nothing here bypasses them.
"""

from dataclasses import asdict, dataclass
from typing import Optional

from . import catalog, gaps
from .graph import Blocker, CapabilityGraph, CapabilityNode, USABLE_STATES, state_label

__all__ = ["build_graph", "execute", "ExecutionResult"]


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    code: str            # ok | unknown_node | not_usable | unknown_action | approval_required | bad_params | failed
    node_id: str
    state: str
    message_fa: str
    message_en: str
    data: Optional[dict] = None

    def to_dict(self):
        return asdict(self)


def _bk(kind, fa, en):
    return Blocker(kind, fa, en)


def _clip(items, limit):
    return tuple(str(i)[:200] for i in list(items)[:limit])


# ======================================================================== brain
def _brain_nodes(hub):
    out = []
    for area in catalog.CONNECTED:
        node_id = "brain." + area.area_id
        common = dict(node_id=node_id, kind="brain", title_fa=area.title_fa, title_en=area.title_en,
                      summary_fa=area.summary_fa, summary_en=area.summary_en, entry=area.entry)
        if not catalog.package_present(area.package):
            out.append(CapabilityNode(state="not_implemented", blockers=(
                _bk("dependency", "این بسته در این نسخه از برنامه نیست.", "This package is not part of this build."),), **common))
            continue
        if area.area_id == "conversation":
            served = hub.served_count(node_id)
            if served:
                out.append(CapabilityNode(state="active", tested=True, evidence=("%d پاسخ واقعی در این اجرا" % served,), **common))
            else:
                out.append(CapabilityNode(state="available", **common))
        elif area.area_id == "memory":
            probe = None
            try:
                probe = hub.memory.query_one("SELECT 1 AS ok") if hub.memory is not None else None
            except Exception:
                probe = None
            if probe is not None:
                out.append(CapabilityNode(state="active", tested=True, evidence=("پایگاه داده به یک پرسش واقعی جواب داد",), **common))
            else:
                out.append(CapabilityNode(state="dependency_blocked", blockers=(
                    _bk("dependency", "حافظهٔ برنامه در این اجرا در دسترس نیست.", "The app's memory is not available in this run."),),
                    **common))
        else:
            out.append(CapabilityNode(state="available", **common))
    return out


# ================================================================== extensions
def _extension_nodes(hub):
    out = []
    if not hub.has_extensions():
        return out
    if hub._manager() is None:                                  # the store is there but cannot be opened: say so, do not hide it
        return [CapabilityNode(
            node_id="hub.extension_store", kind="tool", title_fa="حافظهٔ افزونه‌ها", title_en="Extension store", state="broken",
            summary_fa="پایگاه دادهٔ افزونه‌ها خراب یا ناخوانا است؛ هیچ افزونه‌ای اجرا یا نصب نمی‌شود تا ترمیم شود.",
            summary_en="The extension database is damaged or unreadable; no extension runs or installs until it is repaired.",
            entry="hub.repair_extension_store (با تأیید صریح؛ فایل قدیمی پاک نمی‌شود)",
            blockers=(_bk("test", "پایگاه دادهٔ افزونه‌ها باز نشد؛ «ترمیم حافظهٔ افزونه‌ها» آن را کنار می‌گذارد و از نو شروع می‌کند.",
                          "The extension database could not be opened; 'repair the extension store' sets it aside and starts fresh."),),
            evidence=(str(hub.ext_error)[:80] or "store_unusable",), actions=("repair",))]
    for cap in hub.extensions():
        cid = cap["capability_id"]
        perms = cap.get("permissions") or {}
        missing = list(perms.get("missing") or [])
        state = {"active": "active" if cap.get("tested") else "available", "disabled": "disabled",
                 "permission_blocked": "permission_blocked", "broken": "broken"}.get(cap.get("state"), "broken")
        blockers = ()
        if state == "permission_blocked":
            blockers = tuple(_bk("permission", "این افزونه مجوز «%s» را می‌خواهد و هنوز داده نشده است." % m,
                                 "This extension needs the '%s' permission, which has not been granted." % m) for m in missing)
        elif state == "broken":
            blockers = (_bk("test", "تأیید نسخهٔ فعال ناموفق بود؛ با «برگردان» یا نصب دوبارهٔ بسته درست می‌شود.",
                            "Verification of the active version failed; rolling back or reinstalling the package fixes it."),)
        elif state == "disabled":
            blockers = (_bk("approval", "خودت غیرفعالش کرده‌ای؛ برای روشن‌کردن باید تأیید کنی.", "You switched it off; turning it on needs your approval."),)
        tests = "آزمون‌های پذیرش گذشته" if cap.get("tested") else "بدون گزارش آزمون موفق"
        evidence = ("نسخهٔ %s" % cap.get("active_version"), tests) + (("مجوزها: " + "، ".join(perms.get("granted") or []),) if perms.get("granted") else ())
        out.append(CapabilityNode(
            node_id="ext." + cid, kind="extension", title_fa=cap.get("title") or cid, title_en=cap.get("title") or cid, state=state,
            summary_fa=cap.get("description") or "", summary_en=cap.get("description") or "", tested=bool(cap.get("tested")),
            entry="پیام ← brain.conversation ← hub.match_extension ← ext_runtime (sandbox)", version=cap.get("active_version"),
            blockers=blockers, examples_fa=_clip(cap.get("examples") or [], 3), evidence=evidence,
            actions=("invoke",) if state in USABLE_STATES else ()))
    for prop in hub.pending_proposals():
        out.append(CapabilityNode(
            node_id="ext.%s.pending" % prop["capability_id"], kind="extension", title_fa=prop.get("title") or prop["capability_id"],
            title_en=prop.get("title") or prop["capability_id"], state="pending_approval",
            summary_fa="بسته اعتبارسنجی و آزمایش شده و منتظر تأیید توست؛ تا تأیید نکنی چیزی نصب یا فعال نمی‌شود.",
            summary_en="The package was validated and tested and waits for your approval; nothing is installed or active until you approve.",
            tested=True, entry="پیشنهاد ← تأیید صریح کاربر ← نصب و فعال‌سازی", version=prop.get("planned_version"),
            blockers=(_bk("approval", "منتظر «بله» تو.", "Waiting for your yes."),),
            evidence=("پیشنهاد %s" % prop["proposal_id"],)))
    return out


# =================================================================== self-builder
def _self_builder_nodes(hub):
    from self_builder.registry import CAP_ACTIVE
    sb = hub._sb()
    out = []
    if sb is None or not sb.exists():
        return out
    for rec in sb.capabilities(include_disabled=True):
        tests = rec.get("tests") or {}
        tested = tests.get("ok") is True
        usable = rec.get("status") == CAP_ACTIVE and rec.get("version") is not None
        state = ("active" if tested else "available") if usable else "disabled"
        evidence = (("نسخهٔ %s" % rec.get("version"),) if rec.get("version") is not None else ()) + \
                   (("آزمون‌ها %s/%s" % (tests.get("passed"), tests.get("total")),) if tested else ())
        out.append(CapabilityNode(
            node_id="sb." + rec["id"], kind="self_builder", title_fa=rec.get("title") or rec["id"], title_en=rec.get("title") or rec["id"],
            state=state, summary_fa=rec.get("description") or "", summary_en=rec.get("description") or "", tested=tested and usable,
            entry="پیام ← brain.conversation ← self_builder (قالب‌های بازبینی‌شده)", version=rec.get("version"),
            blockers=() if usable else (_bk("approval", "غیرفعال است.", "It is switched off."),), evidence=evidence,
            actions=("invoke",) if usable else ()))
    return out


# ======================================================================= tools
def _tool_nodes(hub):
    out = []
    granted = hub.permissions.is_granted("network")
    net = hub.network_status()
    served = hub.served_count("tool.web_fetch")
    common = dict(node_id="tool.web_fetch", kind="tool", title_fa="خواندن صفحهٔ وب", title_en="Web page reading",
                  summary_fa="خواندن یک صفحهٔ https به‌صورت متن، با مهلت و سقف حجم و رد آدرس‌های داخلی؛ فقط با مجوز اینترنتی که خودت داده‌ای.",
                  summary_en="Reads one https page as text, with time and size limits and private addresses refused; only with the internet permission you granted.",
                  entry="پیام ← brain.conversation ← hub.fetch ← net_tools", actions=("fetch",),
                  examples_fa=("صفحهٔ https://example.com را بخوان",))
    if not granted:
        out.append(CapabilityNode(state="permission_blocked", blockers=(
            _bk("permission", "اجازهٔ اینترنت داده نشده؛ بگو «اینترنت را روشن کن».", "Internet access has not been granted; say 'turn the internet on'."),),
            evidence=("وضعیت اینترنت دستگاه: %s" % net.state,), **common))
    elif net.state == "offline":
        out.append(CapabilityNode(state="dependency_blocked", blockers=(_bk("network", net.message_fa, net.message_en),),
                                  evidence=("وضعیت اینترنت دستگاه: offline",), **common))
    elif served:
        out.append(CapabilityNode(state="active", tested=True, evidence=("%d خواندن موفق در این اجرا" % served,), **common))
    else:
        out.append(CapabilityNode(state="available", evidence=("وضعیت اینترنت دستگاه: %s" % net.state, "هنوز خواندن واقعی انجام نشده"), **common))
    out.append(_local_model_node(hub))
    return out


def _local_model_node(hub):
    models = hub.list_models()
    engines = hub.model_runtimes_info()
    usable = [m for m in models if m.usable]
    common = dict(node_id="tool.local_model", kind="tool", title_fa="مدل زبانی محلی", title_en="Local language model",
                  entry="پیام ← hub.ask_model ← model_runtime ← (n-gram یا llama.cpp)", actions=("generate",),
                  summary_fa="مدلی که روی خود گوشی بارگذاری و با یک آزمون استنتاج واقعی تأیید شده باشد. مدل n-gram همراه برنامه فقط ادامهٔ متن می‌سازد و یک مدل زبانی بزرگ (LLM) نیست.",
                  summary_en="A model that was loaded on this phone and confirmed by a real inference test. The bundled n-gram model only continues text and is not an LLM.")
    if usable:
        return CapabilityNode(state="active", tested=True, evidence=_clip(("%s: آزمون استنتاج گذشت" % m.model_id for m in usable), 3), **common)
    blockers = []
    if not models:
        blockers.append(_bk("model", "هیچ مدلی ثبت نشده؛ کارت یک مدل را بفرست یا فایلش را در پوشهٔ ورودی بگذار.",
                            "No model is registered; send a model card or put its file in the inbox folder."))
    else:
        blockers.append(_bk("model", "مدل‌های ثبت‌شده هنوز همهٔ مراحل تأیید (هش، سازگاری، بارگذاری، آزمون واقعی) را نگذرانده‌اند.",
                            "The registered models have not passed every stage yet (hash, compatibility, load, real test)."))
    if not any(e["available"] and "gguf" in e["formats"] for e in engines):
        blockers.append(_bk("native_code", "موتور مدل‌های بزرگ (llama.cpp) روی این دستگاه نصب نیست و در این APK هم همراه نشده است.",
                            "The engine for larger models (llama.cpp) is not installed on this device or bundled in this APK."))
    return CapabilityNode(state="registered" if models else "dependency_blocked", blockers=tuple(blockers),
                          evidence=("مدل‌های ثبت‌شده: %d" % len(models),), **common)


def _model_nodes(hub):
    out = []
    for m in hub.list_models():
        card = m.card or {}
        reasons = set(m.reasons)
        blockers = []
        if m.usable:
            state = "active"
        elif m.state == "failed":
            state = "broken"
            blockers.append(_bk("test", m.message_fa, m.message_en))
        elif "license_needs_ack" in reasons or (m.state == "registered" and m.license_policy == "needs_review" and not m.license_ack):
            state = "pending_approval"
            blockers.append(_bk("approval", "مجوز این مدل باید خودت بازبینی و تأیید کنی.", "You must review and acknowledge this model's licence."))
        elif m.state == "registered" and m.license_policy in ("restricted", "unknown"):
            state = "policy_blocked"
            blockers.append(_bk("policy", "مجوز این مدل محدودکننده یا ناشناخته است و برنامه آن را دانلود نمی‌کند.",
                                "This model's licence is restricted or unknown, so the app will not download it."))
        elif reasons & {"dependency_missing", "no_runtime_for_format", "runtime_hint_unavailable"}:
            state = "dependency_blocked"
            blockers.append(_bk("native_code", "موتور اجرای این قالب روی این دستگاه نیست.", "The engine for this format is not on this device."))
        else:
            state = "registered"                                  # no file yet -> a model is missing; a file -> the checks are pending
            blockers.append(_bk("model" if m.state == "registered" else "test", m.message_fa, m.message_en))
        out.append(CapabilityNode(
            node_id="model." + m.model_id, kind="model", title_fa=card.get("title") or m.model_id, title_en=card.get("title") or m.model_id,
            state=state, summary_fa=m.message_fa, summary_en=m.message_en, tested=m.usable,
            entry="hub.prepare_model: هش ← سازگاری ← بارگذاری ← آزمون استنتاج", blockers=tuple(blockers),
            evidence=_clip(("وضعیت: %s" % m.state, "قالب: %s" % card.get("format", "?")), 2), actions=("generate",) if m.usable else ()))
    return out


# ====================================================================== android
def _android_nodes(hub):
    out = []
    for st in hub.android_statuses():
        fid = st.feature_id
        base = dict(node_id="android." + fid, kind="android", title_fa=_feature_title(fid, "fa"), title_en=_feature_title(fid, "en"),
                    summary_fa=st.message_fa, summary_en=st.message_en, entry="hub.android_* ← android_adapters ← MainActivity (Java)",
                    actions=tuple(st.actions))
        missing = [str(x) for x in st.missing]
        if fid == "file_picker":                         # the WebView does the picking; Python has no action for it
            if st.state == "ready":
                out.append(CapabilityNode(state="available", evidence=("انتخاب‌گر فایل در APK هست؛ روی دستگاه آزموده نشده",), **base))
            else:
                out.append(CapabilityNode(state="dependency_blocked", blockers=(
                    _bk("new_apk", "این APK انتخاب‌گر فایل را ندارد یا برنامه روی اندروید اجرا نمی‌شود.", "This APK has no file chooser or the app is not running on Android."),), **base))
            continue
        if st.state == "limited_by_android_policy":
            state, blockers = "policy_blocked", (_bk("policy", st.message_fa, st.message_en),)
        elif not st.implemented:
            state = "not_implemented"
            blockers = (_bk("design", "برای این ویژگی هنوز هیچ عملیاتی پیاده‌سازی نشده است.", "No action is implemented for this feature yet."),)
            if st.state in ("permission_not_declared", "permission_required", "special_permission_required"):
                blockers += (_bk("permission", "مجوز لازم: %s" % ("، ".join(missing) or "؟"), "Permission needed: %s" % (", ".join(missing) or "?")),)
        elif st.state == "ready":
            state, blockers = "available", ()
        elif st.state in ("permission_required", "special_permission_required"):
            state, blockers = "permission_blocked", (_bk("permission", st.message_fa, st.message_en),)
        else:
            state, blockers = "dependency_blocked", (_bk("dependency", st.message_fa, st.message_en),)
        out.append(CapabilityNode(state=state, blockers=blockers, evidence=("هنوز روی دستگاه واقعی آزموده نشده",), **base))
    return out


def _feature_title(feature_id, lang):
    from android_adapters import get_feature
    spec = get_feature(feature_id)
    if spec is None:
        return feature_id
    return spec.title_fa if lang == "fa" else spec.title_en


# =============================================================== scaffolds + gaps
def _scaffold_nodes(hub):
    out = []
    for area in catalog.SCAFFOLDS:
        present = area.package is None or catalog.package_present(area.package)
        out.append(CapabilityNode(
            node_id="infra." + area.area_id, kind="infra", title_fa=area.title_fa, title_en=area.title_en,
            state="scaffold_only" if present else "not_implemented", summary_fa=area.summary_fa, summary_en=area.summary_en,
            blockers=area.missing if present else (
                _bk("dependency", "این بسته در این نسخه نیست.", "This package is not in this build."),)))
    return out


def _gap_nodes(hub):
    return [CapabilityNode(node_id="gap." + g.gap_id, kind="gap", title_fa=g.title_fa, title_en=g.title_en, state=g.state,
                           summary_fa=g.exists_fa, summary_en=g.exists_en, blockers=g.blockers, examples_fa=g.examples_fa)
            for g in gaps.GAPS]


_BUILDERS = (_brain_nodes, _extension_nodes, _self_builder_nodes, _tool_nodes, _model_nodes, _android_nodes,
             _scaffold_nodes, _gap_nodes)


def build_graph(hub):
    nodes, seen = [], set()
    for builder in _BUILDERS:
        try:
            produced = builder(hub)
        except Exception as exc:
            produced = [CapabilityNode(
                node_id="hub.%s_error" % builder.__name__.strip("_"), kind="tool", title_fa="خطا در خواندن بخشی از وضعیت",
                title_en="A part of the status could not be read", state="broken",
                summary_fa="این بخش از گراف خوانده نشد؛ نتیجه ناقص است و چیزی پنهان نشده.",
                summary_en="This part of the graph could not be read; the result is incomplete and nothing is hidden.",
                blockers=(_bk("test", type(exc).__name__, type(exc).__name__),), evidence=(builder.__name__.strip("_"),))]
        for node in produced:
            if node.node_id not in seen:
                seen.add(node.node_id)
                nodes.append(node)
    return CapabilityGraph(nodes)


# ===================================================================== execute
def _refusal(node, code, fa, en, data=None):
    return ExecutionResult(False, code, node.node_id if node else "", node.state if node else "", fa, en, data)


def _not_usable(node):
    lines_fa = ["«%s» الان قابل اجرا نیست: %s." % (node.title_fa, state_label(node.state))]
    lines_en = ["'%s' cannot run right now: %s." % (node.title_en, state_label(node.state, "en"))]
    for b in node.blockers[:3]:
        lines_fa.append("- " + b.text_fa)
        lines_en.append("- " + b.text_en)
    return _refusal(node, "not_usable", "\n".join(lines_fa), "\n".join(lines_en), {"blockers": [b.kind for b in node.blockers]})


def execute(hub, node_id, action, params=None, *, user_approved=False):
    """Run `action` on a node of the graph. Never raises; refuses with a precise code instead."""
    graph = build_graph(hub)
    node = graph.get(node_id)
    if node is None:
        return ExecutionResult(False, "unknown_node", str(node_id)[:100], "", "چنین قابلیتی در گراف نیست.",
                               "There is no such node in the graph.")
    params = params if isinstance(params, dict) else {}
    if node.kind == "android" and action == "request_permission":     # a dialog request is allowed even when blocked by permission
        if user_approved is not True:
            return _refusal(node, "approval_required", "برای درخواست مجوز باید خودت تأیید کنی.", "Requesting a permission needs your approval.")
        result = hub.android_request_permission(node_id.split(".", 1)[1], user_approved=True)
        if result is None:
            return _refusal(node, "unknown_node", "این ویژگی شناخته‌شده نیست.", "Unknown feature.")
        return ExecutionResult(bool(result.dispatched), "ok" if result.dispatched else result.code, node_id, node.state,
                               result.message_fa, result.message_en, {"dispatched": result.dispatched})
    if node.node_id == "hub.extension_store" and action == "repair":      # the one action a broken node accepts
        if user_approved is not True:
            return _refusal(node, "approval_required", "برای ترمیم حافظهٔ افزونه‌ها باید خودت تأیید کنی.",
                            "Repairing the extension store needs your approval.")
        res = hub.repair_extension_store(user_approved=True)
        ok = res.get("status") == "repaired"
        return ExecutionResult(ok, "ok" if ok else str(res.get("status")), node.node_id, node.state,
                               res.get("message_fa", ""), res.get("message_en", ""), res)
    if not node.usable:
        return _not_usable(node)
    if action not in node.actions:
        return _refusal(node, "unknown_action", "این قابلیت عملیات «%s» را ندارد." % str(action)[:30],
                        "This node has no action %r." % str(action)[:30], {"actions": list(node.actions)})
    try:
        return _dispatch(hub, node, action, params, user_approved)
    except Exception as exc:                                    # the invoker itself never breaks a conversation
        return _refusal(node, "failed", "اجرا ناموفق بود (%s)." % type(exc).__name__, "The run failed (%s)." % type(exc).__name__)


def _dispatch(hub, node, action, params, user_approved):
    kind, _, rest = node.node_id.partition(".")
    if kind == "ext":
        out = hub.invoke_extension(rest, params)
        return ExecutionResult(bool(out.get("ok")), "ok" if out.get("ok") else str(out.get("status")), node.node_id, node.state,
                               out.get("answer") or "", out.get("answer") or "", out)
    if kind == "sb":
        sb = hub._sb()
        out = sb.invoke(rest, params) if sb is not None else {"ok": False, "error": "no_registry"}
        ok = bool(out.get("ok"))
        text = str(out.get("value")) if ok else str(out.get("error"))
        return ExecutionResult(ok, "ok" if ok else text[:40], node.node_id, node.state, text, text, out)
    if node.node_id == "tool.web_fetch":
        res = hub.fetch(str(params.get("url", "")), source="invoker")
        return ExecutionResult(res.ok, res.code, node.node_id, node.state, res.message_fa, res.message_en, res.to_dict())
    if node.node_id == "tool.local_model" or kind == "model":
        model_id = rest if kind == "model" else str(params.get("model_id", ""))
        gen = hub.ask_model(model_id, str(params.get("prompt", "")), max_tokens=int(params.get("max_tokens", 64) or 64))
        return ExecutionResult(gen.ok, gen.code, node.node_id, node.state, gen.message_fa, gen.message_en,
                               {"text": gen.text, "model_id": gen.model_id, "runtime": gen.runtime})
    if kind == "android":
        layer = hub._android_layer()
        res = layer.invoke(rest, action, params, user_approved=user_approved is True)
        return ExecutionResult(res.ok, res.code, node.node_id, node.state, res.message_fa, res.message_en, res.data)
    return _refusal(node, "unknown_action", "برای این گره مسیر اجرایی تعریف نشده است.", "No execution route is defined for this node.")
