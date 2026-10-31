"""
native_bridge.rawjvm - the unsafe door: any Android class, for a pack that declared `unsafe_native`
===================================================================================================
A pack that declares `unsafe_native` is installed only after a second, explicit confirmation. It may then reach Android's
own classes through `api.android.jvm.jclass(name)` - without a new APK. The classes that would let it get around the app's
own gates are still refused here: the network (the hub's internet permission is the only gate), downloads, web views, the
package installer, device administration, accounts, reflection, process control and the app's own accessibility service (the screen
of other apps is reached only through `ScreenDoor`, which checks the user's per-app allowance).
"""

from .jvm import valid_class_name
from .result import fail, ok

__all__ = ["RawJvm", "class_allowed"]

_ALLOWED_PREFIXES = ("android.", "androidx.", "java.util.", "java.text.", "java.time.", "org.json.", "com.erfan.standaloneai.",
                     "java.lang.String", "java.lang.Math", "java.lang.Integer", "java.lang.Long", "java.lang.Double",
                     "java.lang.Boolean", "java.lang.Character", "java.lang.Number", "java.lang.Object", "java.lang.Thread")
_DENIED_PREFIXES = ("android.webkit.", "android.net.", "android.app.DownloadManager", "android.app.admin.", "android.content.pm.PackageInstaller",
                    "android.os.Process", "android.os.Debug", "android.system.", "android.accounts.", "android.security.",
                    "android.telephony.SmsManager", "android.app.ActivityThread", "android.app.Instrumentation", "dalvik.", "java.lang.reflect",
                    "java.lang.invoke", "java.util.concurrent.Executors", "androidx.work.", "android.app.job.", "android.net.wifi.",
                    # the screen service of OTHER apps is reached only through `ScreenDoor` (its allow-list and deny-list); a pack that
                    # declared `unsafe_native` must not be able to skip them by calling the service class directly
                    "com.erfan.standaloneai.PyAccessibilityService")
_EXCEPTIONS = ("android.net.Uri",)


def class_allowed(name):
    if not valid_class_name(name):
        return False
    if any(name == ok_name or name.startswith(ok_name + "$") for ok_name in _EXCEPTIONS):
        return True
    if any(name.startswith(prefix) for prefix in _DENIED_PREFIXES):
        return False
    return any(name.startswith(prefix) for prefix in _ALLOWED_PREFIXES)


class RawJvm:
    def __init__(self, jvm):
        self._jvm = jvm

    def jclass(self, name):
        """The Java class (static methods, constants, constructor). Raises `PermissionError` for a class that is never allowed."""
        if not class_allowed(name):
            raise PermissionError("کلاس «%s» از این در مجاز نیست." % str(name)[:80])
        return self._jvm.jclass(name)

    def context(self):
        return self._jvm.context()

    def sdk_int(self):
        return self._jvm.sdk_int()

    def allowed(self, name):
        return class_allowed(name)

    def check(self, name):
        return ok({"allowed": True}) if class_allowed(name) else fail("not_allowed", "کلاس مجاز نیست.")
