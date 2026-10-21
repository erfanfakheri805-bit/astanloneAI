"""
android_adapters - an honest adapter layer between the Python brain and Android (Prompt 957)
===========================================================================================
    layer = AndroidAdapterLayer(detect_bridge())
    layer.status("microphone")                       # exact state: not_android / permission_required / ready ...
    layer.request_permission("camera", user_approved=True)   # only with explicit approval, only when needed
    layer.network_probe()                            # True / False / None  (for net_tools.network_status)

Everything off-device degrades to a precise `unavailable_platform`. Nothing here has been run on a
real device (`verified_on_device` is always False), and only `network_state.read` is an implemented
action: the other features are described and permission-checked but NOT implemented yet.
"""

from .bridge import (AndroidBridge, BridgeConnectivity, BridgeRequestResult, ChaquopyBridge, NullBridge, detect_bridge)
from .catalog import FEATURES, FeatureSpec, feature_ids, get_feature, valid_permission_name
from .layer import (AndroidAdapterLayer, FeatureStatus, InvokeResult, PermissionRequestResult, STATES, UnknownFeatureError)

__all__ = [
    "AndroidBridge", "BridgeConnectivity", "BridgeRequestResult", "ChaquopyBridge", "NullBridge", "detect_bridge", "FEATURES",
    "FeatureSpec", "feature_ids", "get_feature", "valid_permission_name", "AndroidAdapterLayer", "FeatureStatus", "InvokeResult",
    "PermissionRequestResult", "STATES", "UnknownFeatureError",
]
