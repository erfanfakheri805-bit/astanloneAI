"""Prompt 957 - android_adapters: honest feature status, approval-gated permission requests, network probe.

Nothing here touches a device: bridges are plain-Python fakes and no test imports `java`.
UNVERIFIED ON DEVICE - these tests prove the Python logic against the documented Chaquopy/Android API shapes only.
"""
import dataclasses
import json
import os
import sys
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from android_adapters import (AndroidAdapterLayer, AndroidBridge, BridgeConnectivity, BridgeRequestResult, ChaquopyBridge, FEATURES,
                              FeatureSpec, NullBridge, STATES, UnknownFeatureError, detect_bridge, feature_ids, get_feature,
                              valid_permission_name)
from android_adapters.layer import DEFAULT_HANDLERS
from net_tools import network_status

RECORD = "android.permission.RECORD_AUDIO"
CAMERA = "android.permission.CAMERA"
POST = "android.permission.POST_NOTIFICATIONS"
WRITE = "android.permission.WRITE_SETTINGS"
ANSWER = "android.permission.ANSWER_PHONE_CALLS"
NET = "android.permission.ACCESS_NETWORK_STATE"
ALL_DECLARED = frozenset({RECORD, CAMERA, POST, WRITE, ANSWER, NET, "android.permission.INTERNET"})
BOTH_NATIVE = frozenset({"file_chooser", "permission_request"})
DISPATCHED = BridgeRequestResult(True, "dispatched")


class FakeBridge(AndroidBridge):
    """A scripted Android: every answer is whatever the test says; every call is recorded."""

    platform_name = "android"

    def __init__(self, sdk=34, granted=(), declared=ALL_DECLARED, native=BOTH_NATIVE, special=None, connectivity=None,
                 request=DISPATCHED):
        self.sdk, self.granted, self.declared, self.native, self.special = sdk, set(granted), declared, frozenset(native), special or {}
        self.conn = connectivity or BridgeConnectivity("online", "validated")
        self.request_result = request
        self.request_calls, self.permission_calls = [], []

    def sdk_int(self):
        return self.sdk

    def check_permission(self, name):
        self.permission_calls.append(name)
        return "granted" if name in self.granted else "denied"

    def declared_permissions(self):
        return self.declared

    def native_features(self):
        return self.native

    def request_permissions(self, names):
        self.request_calls.append(list(names))
        return self.request_result

    def connectivity(self):
        return self.conn

    def special_permission_granted(self, name):
        return self.special.get(name)


class ExplodingBridge(AndroidBridge):
    """Breaks every promise: each method raises."""

    @property
    def platform_name(self):
        raise RuntimeError("boom")

    def _boom(self, *args):
        raise RuntimeError("boom")
    sdk_int = check_permission = declared_permissions = native_features = request_permissions = connectivity = _boom
    special_permission_granted = _boom


def layer_for(**kw):
    bridge = FakeBridge(**kw)
    return AndroidAdapterLayer(bridge), bridge


def spec(**over):
    data = dict(feature_id="mic_test", title_fa="میکروفون آزمایشی", title_en="Test microphone", android_permissions=(RECORD,),
                permission_kind="runtime", min_sdk=24, needs_native_feature=None, implemented_actions=frozenset({"record"}),
                limitations_fa="x", limitations_en="x")
    data.update(over)
    return FeatureSpec(**data)


class CatalogTests(unittest.TestCase):
    def test_the_catalog_lists_the_expected_features_and_each_spec_is_valid(self):
        self.assertEqual(set(feature_ids()), {"file_picker", "microphone", "camera", "notifications", "settings_write", "telephony",
                                              "network_state", "battery_status", "clipboard"})
        for fid, item in FEATURES.items():
            self.assertEqual(item.feature_id, fid)
            self.assertTrue(item.title_fa and item.title_en and item.limitations_fa and item.limitations_en)
            self.assertIs(get_feature(fid), item)

    def test_only_what_is_really_coded_is_listed_as_implemented(self):
        implemented = {fid: set(item.implemented_actions) for fid, item in FEATURES.items() if item.implemented_actions}
        self.assertEqual(implemented, {"network_state": {"read"}})
        listed = {(fid, action) for fid, item in FEATURES.items() for action in item.implemented_actions}
        self.assertEqual(listed, set(DEFAULT_HANDLERS))  # every listed action has code and every handler is listed

    def test_permission_names_are_validated(self):
        for good in (RECORD, "android.permission.A", "android.permission.USE_FULL_SCREEN_INTENT"):
            self.assertTrue(valid_permission_name(good), good)
        for bad in ("RECORD_AUDIO", "android.permission.", "android.permission.record", "android.permission.A B", "com.x.PERM",
                    "android.permission.A\n", None, 5, "android.permission." + "A" * 61, "x" * 19 + "RECORD_AUDIO",
                    "com.example.app.RECORD_AUDIO_SOMETHING", "android.permission.ا"):
            self.assertFalse(valid_permission_name(bad), repr(bad))

    def test_invalid_specs_are_refused(self):
        with self.assertRaises(ValueError):
            spec(permission_kind="root")
        with self.assertRaises(ValueError):
            spec(android_permissions=("not-a-permission",))
        with self.assertRaises(ValueError):
            spec(permission_kind="none")  # a permission is listed but the kind says none
        with self.assertRaises(ValueError):
            spec(permission_kind="runtime", android_permissions=())

    def test_notifications_need_a_permission_only_from_api_33(self):
        item = FEATURES["notifications"]
        self.assertEqual(item.permissions_needed(32), ())
        self.assertEqual(item.permissions_needed(33), (POST,))
        self.assertEqual(FEATURES["microphone"].permissions_needed(24), (RECORD,))
        self.assertEqual(FEATURES["clipboard"].permissions_needed(34), ())

    def test_telephony_limitation_is_stated_plainly(self):
        item = FEATURES["telephony"]
        self.assertTrue(item.policy_limited)
        self.assertIn("call audio", item.limitations_en)
        self.assertIn("conversation", item.limitations_en)
        self.assertIn("call-screening", item.limitations_en)
        self.assertIn("صدای تماس", item.limitations_fa)
        self.assertEqual(item.min_sdk, 26)

    def test_get_feature_is_safe_for_junk(self):
        for junk in (None, 5, [], "nope", "", "../x"):
            self.assertIsNone(get_feature(junk))


class OffDeviceTests(unittest.TestCase):
    def test_null_bridge_degrades_every_feature_precisely(self):
        layer = AndroidAdapterLayer(NullBridge())
        for status in layer.all_statuses():
            self.assertEqual((status.state, status.code), ("unavailable_platform", "not_android"), status.feature_id)
            self.assertFalse(status.verified_on_device)
            self.assertFalse(status.can_request_permission)
            self.assertTrue(status.message_fa and status.message_en)
        self.assertEqual(len(layer.all_statuses()), len(FEATURES))

    def test_the_default_layer_has_a_null_bridge(self):
        self.assertEqual(AndroidAdapterLayer().status("camera").state, "unavailable_platform")

    def test_nothing_can_be_requested_or_invoked_off_device(self):
        layer = AndroidAdapterLayer(NullBridge())
        result = layer.request_permission("microphone", user_approved=True)
        self.assertEqual((result.dispatched, result.code), (False, "unavailable_platform"))
        run = layer.invoke("network_state", "read")
        self.assertEqual((run.ok, run.code), (False, "unavailable_platform"))
        self.assertIsNone(layer.network_probe())

    def test_detect_bridge_in_a_normal_python_is_the_null_bridge(self):
        self.assertNotIn("java", sys.modules)
        bridge = detect_bridge()
        self.assertIsInstance(bridge, NullBridge)
        self.assertEqual(bridge.platform_name, "none")

    def test_a_java_module_in_the_runtime_gives_the_chaquopy_bridge_built_from_its_own_functions(self):
        fake = types.ModuleType("java")
        fake.jclass = lambda name: None
        fake.jarray = lambda element: (lambda items: list(items))
        sys.modules["java"] = fake                                  # what Chaquopy provides on a device
        self.addCleanup(sys.modules.pop, "java", None)
        detected = detect_bridge()
        self.assertIsInstance(detected, ChaquopyBridge)
        self.assertEqual(detected.platform_name, "android")
        self.assertIsInstance(ChaquopyBridge(), ChaquopyBridge)

    def test_a_java_module_that_lacks_jclass_or_jarray_is_not_taken_for_chaquopy(self):
        sys.modules["java"] = types.ModuleType("java")
        self.addCleanup(sys.modules.pop, "java", None)
        self.assertIsInstance(detect_bridge(), NullBridge)

    def test_chaquopy_bridge_cannot_be_built_without_the_java_module(self):
        with self.assertRaises(ImportError):
            ChaquopyBridge()

    def test_null_bridge_answers(self):
        bridge = NullBridge()
        self.assertEqual((bridge.sdk_int(), bridge.check_permission(RECORD), bridge.declared_permissions(),
                          bridge.native_features(), bridge.special_permission_granted(WRITE)), (None, "unknown", None, frozenset(), None))
        self.assertEqual(bridge.connectivity(), BridgeConnectivity("unknown", "unavailable_platform"))
        self.assertFalse(bridge.request_permissions([RECORD]).dispatched)


class StatusTests(unittest.TestCase):
    def test_unknown_sdk_is_not_guessed(self):
        layer, _ = layer_for(sdk=None)
        status = layer.status("microphone")
        self.assertEqual((status.state, status.code), ("unavailable_platform", "sdk_unknown"))

    def test_an_old_android_is_reported_with_the_needed_level(self):
        layer, _ = layer_for(sdk=25)
        status = layer.status("telephony")
        self.assertEqual((status.state, status.missing), ("not_supported_on_this_android", ("android_api_26",)))

    def test_file_picker_needs_the_native_chooser_of_this_apk(self):
        layer, _ = layer_for(native=())
        status = layer.status("file_picker")
        self.assertEqual((status.state, status.missing), ("native_bridge_missing", ("file_chooser",)))
        self.assertIn("APK", status.message_fa)
        ready = layer_for(native={"file_chooser"})[0].status("file_picker")
        self.assertEqual((ready.state, ready.implemented, ready.actions), ("ready", False, ()))
        self.assertIn("هیچ عملیاتی", ready.message_fa)

    def test_microphone_goes_through_every_permission_state(self):
        undeclared = layer_for(declared=frozenset())[0].status("microphone")
        self.assertEqual((undeclared.state, undeclared.missing, undeclared.can_request_permission), ("permission_not_declared", (RECORD,), False))
        denied = layer_for()[0].status("microphone")
        self.assertEqual((denied.state, denied.missing, denied.can_request_permission), ("permission_required", (RECORD,), True))
        no_hook = layer_for(native=())[0].status("microphone")
        self.assertEqual((no_hook.state, no_hook.can_request_permission), ("permission_required", False))
        unknown_manifest = layer_for(declared=None)[0].status("microphone")
        self.assertEqual((unknown_manifest.state, unknown_manifest.can_request_permission), ("permission_required", False))
        granted = layer_for(granted={RECORD})[0].status("microphone")
        self.assertEqual((granted.state, granted.code, granted.implemented, granted.missing), ("ready", "ok", False, ()))
        self.assertIn("Jarvis", granted.message_en)

    def test_an_unreadable_permission_counts_as_not_granted(self):
        class Unsure(FakeBridge):
            def check_permission(self, name):
                return "unknown"
        status = AndroidAdapterLayer(Unsure()).status("camera")
        self.assertEqual((status.state, status.missing), ("permission_required", (CAMERA,)))

    def test_notifications_by_api_level(self):
        self.assertEqual(layer_for(sdk=32)[0].status("notifications").state, "ready")
        self.assertEqual(layer_for(sdk=33)[0].status("notifications").state, "permission_required")
        self.assertEqual(layer_for(sdk=33, granted={POST})[0].status("notifications").state, "ready")
        self.assertEqual(layer_for(sdk=33, declared=frozenset())[0].status("notifications").state, "permission_not_declared")

    def test_a_special_permission_can_only_be_granted_by_the_user(self):
        self.assertEqual(layer_for(declared=frozenset())[0].status("settings_write").state, "permission_not_declared")
        for special in ({WRITE: False}, {}, {WRITE: None}):
            status = layer_for(special=special)[0].status("settings_write")
            self.assertEqual((status.state, status.missing, status.can_request_permission), ("special_permission_required", (WRITE,), False), special)
        self.assertEqual(layer_for(special={WRITE: True})[0].status("settings_write").state, "ready")

    def test_telephony_is_limited_by_android_policy_whatever_the_permission(self):
        for kw in (dict(), dict(granted={ANSWER}), dict(declared=frozenset())):
            status = layer_for(**kw)[0].status("telephony")
            self.assertEqual((status.state, status.code), ("limited_by_android_policy", "android_policy"), kw)
            self.assertIn("call audio", status.message_en)
            self.assertIn("صدای تماس", status.message_fa)
        self.assertEqual(layer_for()[0].status("telephony").missing, (ANSWER,))
        self.assertEqual(layer_for(granted={ANSWER})[0].status("telephony").missing, ())

    def test_network_state_is_the_one_implemented_feature(self):
        status = layer_for(granted={NET})[0].status("network_state")
        self.assertEqual((status.state, status.implemented, status.actions), ("ready", True, ("read",)))
        undeclared = layer_for(declared=frozenset())[0].status("network_state")
        self.assertEqual(undeclared.state, "permission_not_declared")
        self.assertEqual(layer_for()[0].status("network_state").state, "permission_not_declared")  # denied install-time permission

    def test_battery_and_clipboard_are_ready_but_explicitly_not_implemented(self):
        layer, _ = layer_for()
        for fid in ("battery_status", "clipboard"):
            status = layer.status(fid)
            self.assertEqual((status.state, status.implemented), ("ready", False), fid)
            self.assertIn("پیاده‌سازی نشده", status.message_fa)

    def test_every_status_uses_a_known_state_is_json_safe_and_never_claims_device_verification(self):
        for kw in (dict(), dict(sdk=25), dict(sdk=None), dict(native=()), dict(declared=None), dict(granted=ALL_DECLARED)):
            for status in layer_for(**kw)[0].all_statuses():
                self.assertIn(status.state, STATES)
                self.assertIs(status.verified_on_device, False)
                json.dumps(status.to_dict(), ensure_ascii=False)

    def test_status_objects_are_immutable_and_cannot_be_built_as_verified(self):
        status = layer_for()[0].status("camera")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            status.verified_on_device = True
        with self.assertRaises(dataclasses.FrozenInstanceError):
            status.state = "ready"
        with self.assertRaises(TypeError):
            type(status)("x", "ready", "ok", "a", "b", verified_on_device=True)

    def test_unknown_feature_ids_raise_a_specific_error(self):
        layer, _ = layer_for()
        for junk in ("nope", None, 5, "../x", ""):
            with self.assertRaises(UnknownFeatureError):
                layer.status(junk)

    def test_a_bridge_that_raises_everywhere_never_breaks_the_layer(self):
        layer = AndroidAdapterLayer(ExplodingBridge())
        for status in layer.all_statuses():
            self.assertEqual(status.state, "unavailable_platform")
        self.assertIsNone(layer.network_probe())
        self.assertFalse(layer.request_permission("microphone", user_approved=True).dispatched)
        self.assertFalse(layer.invoke("network_state", "read").ok)

    def test_a_bridge_that_returns_garbage_is_treated_as_unknown(self):
        class Garbage(FakeBridge):
            def sdk_int(self):
                return "34"

            def native_features(self):
                return 5

            def declared_permissions(self):
                return "x"
        self.assertEqual(AndroidAdapterLayer(Garbage()).status("camera").code, "sdk_unknown")

        class Garbage2(FakeBridge):
            def native_features(self):
                return 5

            def declared_permissions(self):
                return "x"

            def connectivity(self):
                return "online"
        layer = AndroidAdapterLayer(Garbage2())
        self.assertEqual(layer.status("file_picker").state, "native_bridge_missing")
        self.assertEqual(layer.status("camera").can_request_permission, False)
        self.assertIsNone(layer.network_probe())


def mic_layer(**kw):
    """A layer whose catalog contains a TEST feature with an implemented action, so the dispatch path can be exercised."""
    bridge = FakeBridge(**kw)
    handlers = {("mic_test", "record"): lambda layer, params: {"recorded": True}}
    return AndroidAdapterLayer(bridge, features={"mic_test": spec()}, handlers=handlers), bridge


class RequestPermissionTests(unittest.TestCase):
    def test_without_explicit_approval_android_is_never_asked(self):
        layer, bridge = mic_layer()
        for approved in (False, None, 1, "yes", "True", [True], 0):
            result = layer.request_permission("mic_test", user_approved=approved)
            self.assertEqual((result.dispatched, result.code), (False, "approval_required"), approved)
        self.assertEqual(layer.request_permission("mic_test").code, "approval_required")  # the default is "not approved"
        self.assertEqual(bridge.request_calls, [])

    def test_an_approved_request_for_a_declared_denied_permission_is_dispatched_and_not_called_a_grant(self):
        layer, bridge = mic_layer()
        result = layer.request_permission("mic_test", user_approved=True)
        self.assertEqual((result.dispatched, result.code, result.permissions), (True, "dispatched", (RECORD,)))
        self.assertEqual(bridge.request_calls, [[RECORD]])
        self.assertIn("هنوز نمی‌دانم", result.message_fa)
        self.assertNotIn("granted", result.message_en.lower().replace("not", ""))  # it never says the user granted anything

    def test_a_refusal_never_reaches_android(self):
        for kw, code in ((dict(declared=frozenset()), "permission_not_declared"), (dict(granted={RECORD}), "already_granted"),
                         (dict(native=()), "cannot_request"), (dict(declared=None), "cannot_request"),
                         (dict(native={"file_chooser"}), "cannot_request"), (dict(sdk=None), "unavailable_platform"),
                         (dict(sdk=20), "not_supported_on_this_android")):
            layer, bridge = mic_layer(**kw)
            result = layer.request_permission("mic_test", user_approved=True)
            self.assertEqual((result.dispatched, result.code), (False, code), kw)
            self.assertEqual(bridge.request_calls, [], kw)

    def test_only_the_missing_permissions_are_requested(self):
        two = spec(feature_id="duo", android_permissions=(RECORD, CAMERA))
        bridge = FakeBridge(granted={RECORD})
        layer = AndroidAdapterLayer(bridge, features={"duo": two}, handlers={("duo", "record"): lambda l, p: {}})
        result = layer.request_permission("duo", user_approved=True)
        self.assertEqual((result.dispatched, result.permissions), (True, (CAMERA,)))
        self.assertEqual(bridge.request_calls, [[CAMERA]])

    def test_bridge_failures_are_reported_honestly(self):
        for answer, code in ((BridgeRequestResult(False, "not_dispatched"), "not_dispatched"),
                             (BridgeRequestResult(False, "bridge_error", "RuntimeError"), "bridge_error"),
                             (None, "bridge_error"), ("garbage", "bridge_error")):
            layer, bridge = mic_layer(request=answer)
            result = layer.request_permission("mic_test", user_approved=True)
            self.assertEqual((result.dispatched, result.code), (False, code), answer)

    def test_a_raising_bridge_during_the_request_is_reported_not_raised(self):
        class Raises(FakeBridge):
            def request_permissions(self, names):
                raise RuntimeError("secret detail")
        layer = AndroidAdapterLayer(Raises(), features={"mic_test": spec()}, handlers={})
        result = layer.request_permission("mic_test", user_approved=True)
        self.assertEqual((result.dispatched, result.code), (False, "bridge_error"))
        self.assertNotIn("secret", result.message_en + result.message_fa)

    def test_least_privilege_no_permission_for_features_that_do_nothing_yet(self):
        layer, bridge = layer_for()
        for fid in ("microphone", "camera", "notifications", "telephony"):
            result = layer.request_permission(fid, user_approved=True)
            self.assertEqual((result.dispatched, result.code), (False, "feature_not_implemented"), fid)
        self.assertEqual(bridge.request_calls, [])

    def test_special_install_and_no_permission_features_cannot_be_requested(self):
        layer, bridge = layer_for(granted={NET})
        self.assertEqual(layer.request_permission("settings_write", user_approved=True).code, "not_runtime_permission")
        self.assertEqual(layer.request_permission("network_state", user_approved=True).code, "not_runtime_permission")
        self.assertEqual(layer.request_permission("file_picker", user_approved=True).code, "no_permission_needed")
        self.assertEqual(bridge.request_calls, [])

    def test_unknown_feature_requests(self):
        layer, bridge = layer_for()
        for junk in ("nope", None, 5, "../x"):
            self.assertEqual(layer.request_permission(junk, user_approved=True).code, "unknown_feature")
        self.assertEqual(bridge.request_calls, [])

    def test_the_decision_is_seen_only_by_re_checking_the_status(self):
        layer, bridge = mic_layer()
        self.assertEqual(layer.status("mic_test").state, "permission_required")
        layer.request_permission("mic_test", user_approved=True)
        self.assertEqual(layer.status("mic_test").state, "permission_required")  # asking does not change anything by itself
        bridge.granted.add(RECORD)  # the user pressed "allow" in Android's dialog
        self.assertEqual(layer.status("mic_test").state, "ready")


class InvokeTests(unittest.TestCase):
    def test_network_state_read_returns_what_the_bridge_reports(self):
        for conn in (BridgeConnectivity("online", "validated"), BridgeConnectivity("offline", "no_active_network"),
                     BridgeConnectivity("unknown", "not_validated")):
            layer, _ = layer_for(granted={NET}, connectivity=conn)
            result = layer.invoke("network_state", "read")
            self.assertEqual((result.ok, result.code, result.data), (True, "ok", {"state": conn.state, "code": conn.code}))

    def test_an_action_runs_only_when_the_feature_is_ready(self):
        layer, _ = layer_for(declared=frozenset())
        result = layer.invoke("network_state", "read")
        self.assertEqual((result.ok, result.code), (False, "permission_not_declared"))
        self.assertEqual(result.data, {"missing": [NET]})

    def test_unimplemented_actions_are_refused_precisely(self):
        layer, _ = layer_for(granted={NET, RECORD, CAMERA}, special={WRITE: True})
        for fid, action in (("network_state", "write"), ("network_state", "delete"), ("microphone", "record"),
                            ("camera", "take_photo"), ("battery_status", "read"), ("clipboard", "read"), ("file_picker", "pick")):
            result = layer.invoke(fid, action)
            self.assertEqual((result.ok, result.code), (False, "action_not_implemented"), (fid, action))
            self.assertIn(action, result.message_en)

    def test_permission_check_is_a_generic_action(self):
        layer, _ = layer_for()
        for fid in FEATURES:
            result = layer.invoke(fid, "permission_check")
            self.assertTrue(result.ok, fid)
            self.assertEqual(result.data["feature_id"], fid)
            self.assertIs(result.data["verified_on_device"], False)

    def test_bad_arguments(self):
        layer, _ = layer_for(granted={NET})
        for action in (None, "", "x" * 41, 5):
            self.assertEqual(layer.invoke("network_state", action).code, "bad_arguments", action)
        for params in ("x", [], 5):
            self.assertEqual(layer.invoke("network_state", "read", params).code, "bad_arguments", params)
        self.assertEqual(layer.invoke("nope", "read").code, "unknown_feature")
        self.assertEqual(layer.invoke(None, "read").code, "unknown_feature")

    def test_an_implemented_action_without_a_handler_is_still_refused(self):
        layer = AndroidAdapterLayer(FakeBridge(granted={RECORD}), features={"mic_test": spec()}, handlers={})
        result = layer.invoke("mic_test", "record")
        self.assertEqual((result.ok, result.code), (False, "action_not_implemented"))

    def test_a_handler_is_not_enough_the_action_must_also_be_listed_as_implemented(self):
        layer = AndroidAdapterLayer(FakeBridge(granted={RECORD}), features={"mic_test": spec()},
                                    handlers={("mic_test", "record"): lambda l, p: {}, ("mic_test", "secret"): lambda l, p: {"leak": 1}})
        result = layer.invoke("mic_test", "secret")
        self.assertEqual((result.ok, result.code, result.data), (False, "action_not_implemented", None))

    def test_a_handler_that_raises_reports_only_its_type(self):
        def broken(layer, params):
            raise ValueError("secret /data/x")
        layer = AndroidAdapterLayer(FakeBridge(granted={RECORD}), features={"mic_test": spec()}, handlers={("mic_test", "record"): broken})
        result = layer.invoke("mic_test", "record")
        self.assertEqual((result.ok, result.code), (False, "action_failed"))
        self.assertIn("ValueError", result.message_en)
        self.assertNotIn("secret", result.message_en + result.message_fa)

    def test_a_handler_runs_when_everything_is_ready(self):
        layer, _ = mic_layer(granted={RECORD})
        result = layer.invoke("mic_test", "record")
        self.assertEqual((result.ok, result.data), (True, {"recorded": True}))


class NetworkProbeTests(unittest.TestCase):
    def test_probe_values(self):
        for conn, expected in ((BridgeConnectivity("online", "validated"), True), (BridgeConnectivity("offline", "x"), False),
                               (BridgeConnectivity("unknown", "x"), None)):
            layer, _ = layer_for(granted={NET}, connectivity=conn)
            self.assertIs(layer.network_probe(), expected, conn)

    def test_the_probe_is_unknown_when_the_network_state_feature_is_not_ready(self):
        self.assertIsNone(layer_for(declared=frozenset())[0].network_probe())
        self.assertIsNone(layer_for(sdk=None)[0].network_probe())
        self.assertIsNone(AndroidAdapterLayer(FakeBridge(granted={NET}), features={}).network_probe())

    def test_it_plugs_into_net_tools_network_status(self):
        online = network_status(layer_for(granted={NET})[0].network_probe)
        self.assertEqual((online.state, online.source), ("online", "probe"))
        offline = network_status(layer_for(granted={NET}, connectivity=BridgeConnectivity("offline", "no_active_network"))[0].network_probe)
        self.assertEqual(offline.state, "offline")
        unknown = network_status(AndroidAdapterLayer(NullBridge()).network_probe)
        self.assertEqual((unknown.state, unknown.source), ("unknown", "probe_unknown"))


# --------------------------------------------------------------------------- the Chaquopy bridge against a fake Java world

class SecurityException(Exception):  # Chaquopy exposes Java exceptions as Python classes named after the Java class
    pass


class FakeJavaWorld:
    """The documented Android/Chaquopy API shapes, as plain Python objects. Every call is recorded in `calls`."""

    def __init__(self, sdk=34, granted=(), requested=(RECORD, NET), native=("file_chooser", "permission_request"), network="validated",
                 can_write=False, request_result=True):
        self.sdk, self.granted, self.requested, self.native, self.network = sdk, set(granted), requested, native, network
        self.can_write, self.request_result = can_write, request_result
        self.calls, self.fail = [], set()
        world = self

        class Caps:
            def hasCapability(self, number):
                world.calls.append(("hasCapability", number))
                if world.network == "validated":
                    return number in (12, 16)
                if world.network == "no_validation":
                    return number == 12
                return False

        class Manager:
            def getActiveNetwork(self):
                if "security" in world.fail:
                    raise SecurityException("ACCESS_NETWORK_STATE")
                return None if world.network == "none" else object()

            def getNetworkCapabilities(self, network):
                return None if world.network == "nocaps" else Caps()

            def getActiveNetworkInfo(self):
                class Info:
                    def isConnected(self_inner):
                        return world.network == "connected"
                return None if world.network == "none" else Info()

        class PackageManager:
            def getPackageInfo(self, name, flags):
                world.calls.append(("getPackageInfo", name, flags))
                if "package" in world.fail:
                    raise RuntimeError("no package info")

                class Info:
                    requestedPermissions = None if world.requested is None else list(world.requested)
                return Info()

        class Context:
            def getPackageManager(self_inner):
                return PackageManager()

            def getPackageName(self_inner):
                return "com.erfan.standaloneai"

            def getSystemService(self_inner, name):
                world.calls.append(("getSystemService", name))
                return None if world.network == "noservice" else Manager()

        self.context = Context()

        class Python:
            @staticmethod
            def getPlatform():
                if "platform_static" in world.fail:
                    raise AttributeError("not static")
                return type("Platform", (), {"getApplication": staticmethod(lambda: world.context)})()

            @staticmethod
            def getInstance():
                return type("Inst", (), {"getPlatform": staticmethod(lambda: type("P", (), {"getApplication": staticmethod(lambda: world.context)})())})()

        class Version:
            SDK_INT = sdk

        class Compat:
            @staticmethod
            def checkSelfPermission(ctx, name):
                world.calls.append(("checkSelfPermission", name))
                if "compat" in world.fail:
                    raise RuntimeError("compat")
                return 0 if name in world.granted else -1

        class Settings:
            @staticmethod
            def canWrite(ctx):
                return world.can_write

        class MainActivity:
            NATIVE_FEATURES = list(native) if native is not None else None

            @staticmethod
            def requestAndroidPermissions(array):
                world.calls.append(("requestAndroidPermissions", list(array)))
                if "request" in world.fail:
                    raise RuntimeError("secret detail")
                return world.request_result

        if native == "absent":
            del MainActivity.NATIVE_FEATURES
        self.classes = {"com.chaquo.python.Python": Python, "android.os.Build$VERSION": Version,
                        "androidx.core.content.ContextCompat": Compat, "android.provider.Settings$System": Settings,
                        "com.erfan.standaloneai.MainActivity": MainActivity, "java.lang.String": "String"}

    def jclass(self, name):
        self.calls.append(("jclass", name))
        if name not in self.classes:
            raise RuntimeError("no such class " + name)
        return self.classes[name]

    @staticmethod
    def jarray(element):
        return lambda items: list(items)

    def bridge(self):
        return ChaquopyBridge(jclass=self.jclass, jarray=self.jarray)


class ChaquopyBridgeTests(unittest.TestCase):
    def test_basic_reads(self):
        world = FakeJavaWorld(sdk=33, granted={RECORD})
        bridge = world.bridge()
        self.assertEqual((bridge.platform_name, bridge.sdk_int()), ("android", 33))
        self.assertEqual((bridge.check_permission(RECORD), bridge.check_permission(CAMERA)), ("granted", "denied"))
        self.assertEqual(bridge.declared_permissions(), frozenset({RECORD, NET}))
        self.assertIn(("getPackageInfo", "com.erfan.standaloneai", 4096), world.calls)
        self.assertEqual(bridge.native_features(), frozenset({"file_chooser", "permission_request"}))

    def test_invalid_permission_names_never_reach_java(self):
        world = FakeJavaWorld()
        bridge = world.bridge()
        for bad in ("RECORD_AUDIO", "x; rm -rf", None, 5, "android.permission.a"):
            self.assertEqual(bridge.check_permission(bad), "unknown")
        self.assertFalse([c for c in world.calls if c[0] == "checkSelfPermission"])

    def test_java_exceptions_become_safe_unknowns(self):
        world = FakeJavaWorld()
        world.fail = {"compat", "package"}
        bridge = world.bridge()
        self.assertEqual(bridge.check_permission(RECORD), "unknown")
        self.assertIsNone(bridge.declared_permissions())
        broken = ChaquopyBridge(jclass=lambda name: (_ for _ in ()).throw(RuntimeError("no java")), jarray=lambda e: e)
        self.assertIsNone(broken.sdk_int())
        self.assertEqual(broken.native_features(), frozenset())
        self.assertEqual(broken.check_permission(RECORD), "unknown")
        self.assertIsNone(broken.declared_permissions())
        self.assertIsNone(broken.special_permission_granted(WRITE))
        self.assertEqual(broken.connectivity().state, "unknown")
        self.assertFalse(broken.request_permissions([RECORD]).dispatched)

    def test_sdk_zero_or_odd_values_are_unknown(self):
        for value in (0, -1):
            self.assertIsNone(FakeJavaWorld(sdk=value).bridge().sdk_int())

    def test_declared_permissions_with_no_requested_list_is_an_empty_set(self):
        self.assertEqual(FakeJavaWorld(requested=None).bridge().declared_permissions(), frozenset())

    def test_an_old_apk_without_the_native_field_has_no_native_features(self):
        self.assertEqual(FakeJavaWorld(native="absent").bridge().native_features(), frozenset())
        self.assertEqual(FakeJavaWorld(native=None).bridge().native_features(), frozenset())
        status = AndroidAdapterLayer(FakeJavaWorld(native="absent").bridge()).status("file_picker")
        self.assertEqual(status.state, "native_bridge_missing")

    def test_special_permission(self):
        self.assertIs(FakeJavaWorld(can_write=True).bridge().special_permission_granted(WRITE), True)
        self.assertIs(FakeJavaWorld(can_write=False).bridge().special_permission_granted(WRITE), False)
        self.assertIs(FakeJavaWorld(sdk=22).bridge().special_permission_granted(WRITE), True)
        self.assertIsNone(FakeJavaWorld().bridge().special_permission_granted(RECORD))

    def test_connectivity_matrix(self):
        expected = {"validated": ("online", "validated"), "no_validation": ("unknown", "not_validated"),
                    "none": ("offline", "no_active_network"), "nocaps": ("offline", "no_capabilities"),
                    "nointernet": ("offline", "no_internet_capability"), "noservice": ("unknown", "no_connectivity_service")}
        for network, answer in expected.items():
            conn = FakeJavaWorld(network=network).bridge().connectivity()
            self.assertEqual((conn.state, conn.code), answer, network)

    def test_connectivity_on_old_android_uses_the_legacy_api(self):
        self.assertEqual(FakeJavaWorld(sdk=22, network="connected").bridge().connectivity(), BridgeConnectivity("online", "legacy_api"))
        self.assertEqual(FakeJavaWorld(sdk=22, network="none").bridge().connectivity(), BridgeConnectivity("offline", "not_connected"))
        self.assertEqual(FakeJavaWorld(sdk=22, network="x").bridge().connectivity(), BridgeConnectivity("offline", "not_connected"))

    def test_a_missing_network_permission_is_reported_as_such(self):
        world = FakeJavaWorld()
        world.fail = {"security"}
        self.assertEqual(world.bridge().connectivity(), BridgeConnectivity("unknown", "permission_not_declared"))
        layer = AndroidAdapterLayer(world.bridge())
        self.assertIsNone(layer.network_probe() if layer.status("network_state").state == "ready" else None)

    def test_request_permissions_dispatches_only_valid_names(self):
        world = FakeJavaWorld()
        bridge = world.bridge()
        self.assertEqual(bridge.request_permissions([RECORD, CAMERA]), BridgeRequestResult(True, "dispatched"))
        self.assertIn(("requestAndroidPermissions", [RECORD, CAMERA]), world.calls)
        before = len(world.calls)
        for bad in ([], [RECORD] * 9, ["nope"], [RECORD, "x"], "android.permission.CAMERA", None, [5]):
            self.assertEqual(bridge.request_permissions(bad), BridgeRequestResult(False, "invalid_request"), bad)
        self.assertEqual(len(world.calls), before)

    def test_request_permissions_failures(self):
        self.assertEqual(FakeJavaWorld(request_result=False).bridge().request_permissions([RECORD]), BridgeRequestResult(False, "not_dispatched"))
        world = FakeJavaWorld()
        world.fail = {"request"}
        result = world.bridge().request_permissions([RECORD])
        self.assertEqual((result.dispatched, result.code, result.detail), (False, "bridge_error", "RuntimeError"))
        self.assertNotIn("secret", repr(result))

    def test_the_application_context_is_found_with_a_fallback_and_cached(self):
        world = FakeJavaWorld()
        world.fail = {"platform_static"}
        bridge = world.bridge()
        self.assertEqual(bridge.check_permission(RECORD), "denied")
        bridge.check_permission(CAMERA)
        self.assertEqual(len([c for c in world.calls if c == ("jclass", "com.chaquo.python.Python")]), 1)

    def test_a_missing_context_is_unknown_not_a_crash(self):
        bridge = ChaquopyBridge(jclass=FakeJavaWorld().jclass, jarray=FakeJavaWorld.jarray, context_getter=lambda: None)
        self.assertEqual(bridge.check_permission(RECORD), "unknown")
        self.assertIsNone(bridge.declared_permissions())
        self.assertEqual(bridge.connectivity().state, "unknown")


class EndToEndOnTheFakeDevice(unittest.TestCase):
    def test_a_fresh_install_walks_through_the_real_flow(self):
        world = FakeJavaWorld(sdk=34, granted={NET}, requested=(RECORD, NET))
        layer = AndroidAdapterLayer(world.bridge())
        self.assertEqual(layer.status("network_state").state, "ready")
        self.assertEqual(layer.invoke("network_state", "read").data, {"state": "online", "code": "validated"})
        self.assertIs(layer.network_probe(), True)
        self.assertEqual(layer.status("microphone").state, "permission_required")
        self.assertEqual(layer.status("camera").state, "permission_not_declared")  # CAMERA is not in this fake manifest
        self.assertEqual(layer.status("file_picker").state, "ready")
        self.assertEqual(layer.request_permission("microphone", user_approved=True).code, "feature_not_implemented")
        self.assertEqual(layer.status("telephony").state, "limited_by_android_policy")
        self.assertFalse([c for c in world.calls if c[0] == "requestAndroidPermissions"])
        for status in layer.all_statuses():
            self.assertIs(status.verified_on_device, False)

    def test_airplane_mode(self):
        layer = AndroidAdapterLayer(FakeJavaWorld(granted={NET}, network="none").bridge())
        self.assertIs(layer.network_probe(), False)
        self.assertEqual(network_status(layer.network_probe).state, "offline")
