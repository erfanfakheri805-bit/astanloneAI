"""
Test support (Prompt 959, stage B): a fake Android runtime for the BODY doors.

`FakeBodyJava` is `FakeJava` (Prompt 958) plus the few classes the body doors touch: `BodyService` (the foreground service), the power
and activity managers, the SMS inbox (a content resolver + cursor) and the package info. Hand-written from Android's documented API - it
proves the DOORS' logic (what they call, what they refuse, how they report), not that Android behaves like this. Not a test module.
"""

from tests.native_support_prompt958 import FakeJava

__all__ = ["FakeBodyJava", "SecurityException", "NOW"]

NOW = 1_800_000_000.0                      # the fake clock the SMS tests use (seconds)


class SecurityException(Exception):
    pass


class FakeBodyJava(FakeJava):
    def __init__(self, *, sms=(), service_allowed=True, ignoring=False, power_save=False, dialog_allowed=True,
                 memory=(8_000_000_000, 3_000_000_000, False),
                 version=("0.2.0", 2), abis=("arm64-v8a", "armeabi-v7a"), features=("body_service", "file_chooser", "permission_request",
                                                                               "voice_input", "accessibility"), **kw):
        self.sms = list(sms)                          # newest first: (address, body, date in milliseconds)
        self.service_allowed, self.service_running = service_allowed, False
        self.service_calls = []                       # ("hold", title, text, percent) / ("release",)
        self.ignoring, self.power_save, self.memory = ignoring, power_save, memory
        self.dialog_allowed, self.permission_requests = dialog_allowed, []     # MainActivity.requestAndroidPermissions: shown? / what was asked
        self.version, self.abis = version, abis
        self.queries = []
        super().__init__(features=features, **kw)
        self._extend()

    def _extend(self):
        fake = self
        base_ctx = self.ctx

        class Cursor:
            def __init__(self, rows):
                self.rows, self.at, self.closed = rows, -1, False

            def moveToNext(self):
                self.at += 1
                return self.at < len(self.rows)

            def getString(self, index):
                value = self.rows[self.at][index]
                return None if value is None else str(value)

            def getLong(self, index):
                return int(self.rows[self.at][index])

            def close(self):
                self.closed = True
                fake.last_cursor = self

        class Resolver:
            def query(self, uri, columns, selection, args, order):
                fake.queries.append((uri.text, list(columns), selection, args, order))
                if "READ_SMS" not in " ".join(fake.granted):
                    raise SecurityException("READ_SMS")
                return Cursor(list(fake.sms))

        class PowerManager:
            def isIgnoringBatteryOptimizations(self, package):
                return fake.ignoring

            def isPowerSaveMode(self):
                return fake.power_save

        class MemoryInfo:
            def __init__(self):
                self.totalMem, self.availMem, self.lowMemory = 0, 0, False

        class ActivityManager:
            def getMemoryInfo(self, info):
                info.totalMem, info.availMem, info.lowMemory = fake.memory

        class PackageInfo:
            def __init__(self):
                self.versionName, self.versionCode = fake.version[0], fake.version[1]

            def getLongVersionCode(self):
                return fake.version[1]

        class PackageManager:
            def getPackageInfo(self, package, flags):
                return PackageInfo()

        class Context:
            def __getattr__(self, name):                # everything the 958 context knows
                return getattr(base_ctx, name)

            def getSystemService(self, name):
                if name == "power":
                    return PowerManager()
                if name == "activity":
                    return ActivityManager()
                return base_ctx.getSystemService(name)

            def getContentResolver(self):
                return Resolver()

            def getPackageManager(self):
                return PackageManager()

        class BodyService:
            @staticmethod
            def hold(ctx, title, text, percent):
                fake.service_calls.append(("hold", title, text, percent))
                fake.service_running = bool(fake.service_allowed)
                return fake.service_allowed

            @staticmethod
            def release(ctx):
                fake.service_calls.append(("release",))
                fake.service_running = False

            @staticmethod
            def isRunning():
                return fake.service_running

        class Build:
            MODEL, MANUFACTURER, SUPPORTED_ABIS = "TestPhone", "Acme", list(fake.abis)

        base_main = self.classes["com.erfan.standaloneai.MainActivity"]

        class MainActivity(base_main):                # everything the 958 fake knows, plus the permission dialog
            @staticmethod
            def requestAndroidPermissions(names):
                fake.permission_requests.append(list(names))
                return fake.dialog_allowed

        self.ctx = Context()
        self.classes.update({"com.erfan.standaloneai.BodyService": BodyService, "android.app.ActivityManager$MemoryInfo": MemoryInfo,
                             "android.os.Build": Build, "com.erfan.standaloneai.MainActivity": MainActivity})
