"""
brain_hub.selftest - the one report the user can copy after trying the app on his phone  (Prompt 959, stage B)
==============================================================================================================
The user cannot run a terminal: when something does not work on his phone, the only thing that travels back is a message he pastes. This
module collects the FACTS such a message needs - which build, which Android, how much memory and storage, whether Android lets the app live
in the background, which engine the build has and whether it matches, where the own brain stands, which permissions are given, what the
foreground service answered, and WHICH KINDS of errors the app logged - and nothing else.

What is never in it: the chat, a key, a one-time code, a phone number, a file path, the text of an error (only its class name), the text
of any message. Every item is read on its own and a part that cannot be read is simply marked unknown - the report always comes out.
Nothing is sent anywhere by this module: the report is plain data; the chat shows it and the user decides what to do with it.
"""

import re
import time

__all__ = ["collect", "quick", "SECTIONS", "MAX_ERRORS", "MAX_API_CHARS"]

SECTIONS = ("app", "phone", "engine", "ownbrain", "network", "permissions", "body", "errors", "models")
MAX_ERRORS = 8
MAX_API_CHARS = 1500
_ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,60}$")
_OPERATION_BAD_RE = re.compile(r"[^A-Za-z0-9_ /.\-]")
# an absolute file path inside free text: a "/" that does not continue a word (so `Lcom/google/ai/Engine;` and `java/lang/String` stay as they are)
_PATH_RE = re.compile(r"(?<![\w.$;])/(?:[^\s/]+/)+[^\s/]*")
_PERMISSION_FEATURES = ("notifications", "sms_read", "microphone")


def _door_data(result):
    """`(ok, data, code)` of a `DoorResult`-like answer."""
    return bool(getattr(result, "ok", False)), getattr(result, "data", None), str(getattr(result, "code", "") or "")


def _guard(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _clean(value, limit):
    """Free text that another part of the app wrote, cut to `limit`, with every absolute file path in it replaced (the report names no path)."""
    return _PATH_RE.sub("<path>", str(value if value is not None else "")[:limit * 4])[:limit]


def _scalar(value):
    return value if value is None or isinstance(value, (bool, int, float)) else _clean(value, 120)


def _doors(hub, doors):
    if doors is not None:
        return doors
    from native_bridge import facade
    return facade.for_app(hub)


def _app(doors):
    ok, data, code = _door_data(doors.phone.app_info())
    if not ok or not isinstance(data, dict):
        return {"known": False, "code": code}
    return {"known": True, "package": str(data.get("package") or "")[:100], "version_name": str(data.get("version_name") or "")[:30],
            "version_code": int(data.get("version_code") or 0), "sdk": int(data.get("sdk") or 0), "abis": [str(a)[:20] for a in (data.get("abis") or [])][:6]}


def _phone(doors, brain):
    out = {"ram_total": 0, "ram_available": 0, "ram_low": None, "battery_known": False, "ignoring_battery": None, "power_save": None, "free": 0}
    ok, data, _ = _door_data(doors.phone.memory())
    if ok and isinstance(data, dict):
        out.update(ram_total=int(data.get("total") or 0), ram_available=int(data.get("available") or 0), ram_low=bool(data.get("low")))
    ok, data, _ = _door_data(doors.phone.battery_optimization())
    if ok and isinstance(data, dict):
        out.update(battery_known=True, ignoring_battery=bool(data.get("ignoring")), power_save=bool(data.get("power_save")))
    if brain is not None:
        facts = _guard(brain.facts, {})
        out["free"] = int(facts.get("free") or 0)
        if not out["ram_total"]:
            out["ram_total"] = int(facts.get("ram") or 0)
    return out


def _engine(hub, brain):
    out = {"available": False, "code": "unknown", "reason_fa": "", "api": ""}
    rows = _guard(hub.model_runtimes_info, [])
    row = next((r for r in rows if "litertlm" in (r.get("formats") or ())), None)
    if row is not None:
        out.update(available=bool(row.get("available")), code=_clean(row.get("code"), 60), reason_fa=_clean(row.get("reason_fa"), 200),
                   api=_clean(row.get("api"), MAX_API_CHARS))
    out["others"] = [{"name": _clean(r.get("name"), 30), "available": bool(r.get("available")), "code": _clean(r.get("code"), 40)}
                     for r in rows if r is not row][:4]
    return out


def _ownbrain(brain):
    if brain is None:
        return {"known": False}
    st = _guard(brain.status, None)
    if not isinstance(st, dict):
        return {"known": False}
    keys = ("phase", "sub", "choice", "percent", "bytes", "total", "code", "detail", "resumable", "consent")
    out = dict({k: _scalar(st.get(k)) for k in keys}, known=True)
    inst = st.get("install")
    if st.get("phase") == "installing" and isinstance(inst, dict) and inst.get("step"):      # where the install is (only while it runs)
        out.update({"install_" + k: _scalar(inst.get(k)) for k in ("step", "steps", "stage", "percent", "elapsed", "estimated")})
    return out


def _network(hub, brain):
    out = {"app_switch": None, "state": "unknown"}
    out["app_switch"] = _guard(lambda: bool(hub.permissions.is_granted("network")), None)
    out["state"] = str(_guard(lambda: hub.network_status().state, "unknown"))
    return out


def _sms_state(doors):
    """"granted" / "denied" / "unknown" - the READ_SMS permission, asked without reading anything."""
    ok, data, _ = _door_data(doors.sms.has_permission())
    if ok and isinstance(data, dict):
        return "granted" if data.get("granted") else "denied"
    return "unknown"


def _permissions(hub, doors):
    rows = {}
    for item in _guard(hub.android_statuses, []):
        fid = getattr(item, "feature_id", "")
        if fid in _PERMISSION_FEATURES:
            rows[fid] = {"state": str(getattr(item, "state", "")), "code": str(getattr(item, "code", ""))[:60]}
    if doors is not None:
        rows["sms"] = {"state": _guard(lambda: _sms_state(doors), "unknown")}
    return rows


def _body(hub, doors):
    from .body import peek_body
    body = peek_body(hub)
    out = {"native": None, "running": None, "holding": False, "jobs": [], "code": "", "dead": ""}
    features = _guard(hub.native_features, frozenset())
    out["native"] = "body_service" in features
    ok, data, code = _door_data(doors.body.running())
    if ok and isinstance(data, dict):
        out["running"] = bool(data.get("running"))
    elif code:
        out["running_code"] = code
    if body is not None:
        out.update(_guard(body.status, {}))
    return out


def _operation(value):
    """The name of what failed, without anything a request carried (the server logs `GET /path?query`): only plain path characters, cut at 40."""
    head = re.split(r"[?#]", str(value or ""), maxsplit=1)[0]
    return _OPERATION_BAD_RE.sub("?", head)[:40]


def _error_kind(message):
    """The class name that opens an error message (`ValueError: ...`) - and ONLY then: a message without the colon is not known to start with a
    class name (the server logs a bare `str(exc)`), so it says nothing; the rest of a message may hold the user's words."""
    head, colon, _rest = str(message or "").partition(":")
    head = head.strip()
    return head if colon and _ERROR_TYPE_RE.match(head) else "?"


def _errors(hub):
    memory = hub.memory
    if memory is None:
        return []
    counts = {}
    for row in _guard(lambda: memory.recent_errors(60), []):
        operation = _operation(row["operation"])
        kind = _error_kind(row["message"])
        entry = counts.setdefault((operation, kind), {"operation": operation, "type": kind, "count": 0, "last": ""})
        entry["count"] += 1
        entry["last"] = str(row["created_at"] or "")[:25]
    ranked = sorted(counts.values(), key=lambda e: (-e["count"], e["operation"], e["type"]))
    return ranked[:MAX_ERRORS]


def _models(hub):
    return len(_guard(hub.list_models, []))


def collect(hub, *, doors=None):
    """The facts, as plain data: `{"time", <section>: {...}}` for the sections in `SECTIONS`. Never raises; a part that cannot be read says so."""
    from .ownbrain import get_ownbrain
    doors = _guard(lambda: _doors(hub, doors), None)
    brain = _guard(lambda: get_ownbrain(hub), None)
    facts = {"time": _guard(lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(hub.clock()))), "")}
    if doors is None:
        facts.update(app={"known": False, "code": "no_doors"}, phone={}, body={"native": None})
    else:
        facts["app"] = _guard(lambda: _app(doors), {"known": False, "code": "error"})
        facts["phone"] = _guard(lambda: _phone(doors, brain), {})
        facts["body"] = _guard(lambda: _body(hub, doors), {"native": None})
    facts["engine"] = _guard(lambda: _engine(hub, brain), {"available": False, "code": "unknown"})
    facts["ownbrain"] = _ownbrain(brain)
    facts["network"] = _guard(lambda: _network(hub, brain), {"state": "unknown"})
    facts["permissions"] = _guard(lambda: _permissions(hub, doors), {})
    facts["errors"] = _guard(lambda: _errors(hub), [])
    facts["models"] = _guard(lambda: _models(hub), 0)
    return facts


def quick(hub, *, doors=None):
    """The few facts the access checklist needs, without the heavy parts: `{"battery": {known, ignoring, power_save}, "notifications": state,
    "sms": "granted" | "denied" | "unknown"}`. Never raises."""
    doors = _guard(lambda: _doors(hub, doors), None)
    out = {"battery": {"known": False}, "notifications": "", "sms": "unknown"}
    if doors is not None:
        ok, data, _ = _door_data(_guard(doors.phone.battery_optimization, None))
        if ok and isinstance(data, dict):
            out["battery"] = {"known": True, "ignoring": bool(data.get("ignoring")), "power_save": bool(data.get("power_save"))}
        out["sms"] = _guard(lambda: _sms_state(doors), "unknown")
    perms = _guard(lambda: _permissions(hub, None), {})
    out["notifications"] = (perms.get("notifications") or {}).get("state", "")
    return out
