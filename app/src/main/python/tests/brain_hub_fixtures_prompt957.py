"""
Shared, DETERMINISTIC test doubles and sample packages for the Prompt-957 hub tests (not a test module itself).

* extension packages the app has no built-in archetype for: a Gregorian -> Jalali date converter (real algorithm, five
  known dates), a prime-factor tool, a clock reader (`clock` permission) and a page word counter (`network` permission);
* malicious / broken packages that must be rejected;
* a scripted Android bridge, fake fetch / stream transports and a real n-gram model file for the model manager.
Nothing here touches the real network, the real phone or the real clock.
"""

import hashlib
import json
import os
import sys
from collections import namedtuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from android_adapters import AndroidBridge
from android_adapters.bridge import BridgeConnectivity, BridgeRequestResult
from model_runtime import train_ngram_model
from net_tools import StreamResponse, TransportResponse

JALALI_SOURCE = '''def run(gy, gm, gd):
    offsets = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        y = gy - 1600
    else:
        jy = 0
        y = gy - 621
    y2 = y + 1 if gm > 2 else y
    days = 365 * y + (y2 + 3) // 4 - (y2 + 99) // 100 + (y2 + 399) // 400 - 80 + gd + offsets[gm - 1]
    jy = jy + 33 * (days // 12053)
    days = days % 12053
    jy = jy + 4 * (days // 1461)
    days = days % 1461
    if days > 365:
        jy = jy + (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return {'jy': jy, 'jm': jm, 'jd': jd}
'''

# five dates with a well-known Jalali equivalent
JALALI_DATES = ((2024, 3, 20, 1403, 1, 1), (2023, 3, 21, 1402, 1, 1), (1970, 1, 1, 1348, 10, 11),
                (2000, 1, 1, 1378, 10, 11), (2024, 3, 19, 1402, 12, 29))


def jalali_pkg(answer="{gy}/{gm}/{gd} میلادی = {jy}/{jm}/{jd} شمسی", title="تبدیل تاریخ میلادی به شمسی", **over):
    pkg = {
        "schema": "ext.v1", "id": "jalali_date", "title": title,
        "description": "تاریخ میلادی (سال، ماه، روز) را به تاریخ شمسی تبدیل می‌کند.",
        "inputs": [{"name": "gy", "type": "integer", "min": 1700, "max": 2600, "label": "سال میلادی"},
                   {"name": "gm", "type": "integer", "min": 1, "max": 12, "label": "ماه میلادی"},
                   {"name": "gd", "type": "integer", "min": 1, "max": 31, "label": "روز میلادی"}],
        "outputs": [{"name": "jy", "type": "integer", "label": "سال شمسی"}, {"name": "jm", "type": "integer", "label": "ماه شمسی"},
                    {"name": "jd", "type": "integer", "label": "روز شمسی"}],
        "source": JALALI_SOURCE,
        "triggers": ["تاریخ شمسی {gy} {gm} {gd}", "{gy} {gm} {gd} را به شمسی تبدیل کن"],
        "answer": answer,
        "examples": ["تاریخ شمسی ۲۰۲۴ ۳ ۲۰"],
        "tests": [{"name": "case %d" % i, "inputs": {"gy": a, "gm": b, "gd": c}, "expect": {"jy": x, "jm": y, "jd": z}}
                  for i, (a, b, c, x, y, z) in enumerate(JALALI_DATES, 1)],
        "provenance": {"author": "test-suite", "note": "Jalali conversion (public algorithm)"},
    }
    pkg.update(over)
    return pkg


def factors_pkg():
    return {
        "schema": "ext.v1", "id": "prime_factors", "title": "تجزیه به عوامل اول",
        "description": "یک عدد صحیح را به عوامل اول تجزیه می‌کند.",
        "inputs": [{"name": "n", "type": "integer", "min": 2, "max": 1000000, "label": "عدد"}],
        "outputs": [{"name": "factors", "type": "list", "label": "عوامل"}, {"name": "count", "type": "integer", "label": "تعداد"}],
        "source": "def run(n):\n    out = []\n    d = 2\n    while d * d <= n:\n        while n % d == 0:\n            out.append(d)\n            n = n // d\n        d = d + 1\n    if n > 1:\n        out.append(n)\n    return {'factors': out, 'count': len(out)}\n",
        "triggers": ["عوامل اول {n}", "{n} را تجزیه کن"],
        "answer": "عوامل اول: {factors}",
        "tests": [{"inputs": {"n": 360}, "expect": {"factors": [2, 2, 2, 3, 3, 5], "count": 6}},
                  {"inputs": {"n": 97}, "expect": {"factors": [97], "count": 1}},
                  {"inputs": {"n": 2}, "expect": {"factors": [2], "count": 1}}],
    }


def clock_pkg():
    return {
        "schema": "ext.v1", "id": "clock_reader", "title": "ساعت دستگاه",
        "description": "ساعت و دقیقهٔ UTC را از ساعت دستگاه می‌خواند.",
        "inputs": [{"name": "unused", "type": "integer", "default": 0, "required": False}],
        "outputs": [{"name": "hour", "type": "integer", "label": "ساعت"}, {"name": "minute", "type": "integer", "label": "دقیقه"}],
        "permissions": ["clock"],
        "source": "def run(unused):\n    t = int(clock_now())\n    return {'hour': (t // 3600) % 24, 'minute': (t // 60) % 60}\n",
        "triggers": ["ساعت دستگاه", "ساعت utc"],
        "answer": "ساعت {hour}:{minute} (UTC)",
        "tests": [{"inputs": {}, "expect": {"hour": 1, "minute": 1}}],
        "fixtures": {"clock": 3660},
    }


def words_pkg():
    """A `network` extension. NOTE: the live `web_fetch_text` returns the page's visible TEXT (tags removed), not its HTML."""
    return {
        "schema": "ext.v1", "id": "page_words", "title": "شمارش کلمات صفحه",
        "description": "تعداد کلمات متن یک صفحهٔ وب را می‌شمارد.",
        "inputs": [{"name": "url", "type": "text"}],
        "outputs": [{"name": "words", "type": "integer"}],
        "permissions": ["network"],
        "source": "def run(url):\n    page = web_fetch_text(url)\n    return {'words': len(page.split())}\n",
        "triggers": ["کلمات صفحه {url}"],
        "tests": [{"inputs": {"url": "https://a.test/"}, "expect": {"words": 4}}],
        "fixtures": {"web": {"https://a.test/": "one two three four"}},
    }


def broken_tests_pkg():
    """Its own acceptance test is wrong: it must be rejected at the `tests` stage and never become active."""
    return jalali_pkg(tests=[{"name": "wrong", "inputs": {"gy": 2024, "gm": 3, "gd": 20}, "expect": {"jy": 1400, "jm": 1, "jd": 1}}])


MALICIOUS = {
    "escape": "def run(gy, gm, gd):\n    return ().__class__.__bases__[0].__subclasses__()\n",
    "import": "import os\ndef run(gy, gm, gd):\n    return os.getcwd()\n",
    "open": "def run(gy, gm, gd):\n    return open('/etc/passwd').read()\n",
    "eval": "def run(gy, gm, gd):\n    return eval('1+1')\n",
    "endless": "def run(gy, gm, gd):\n    while True:\n        pass\n",
}


def malicious_pkg(kind):
    pkg = jalali_pkg(id="evil_ext", title="افزونهٔ مخرب", source=MALICIOUS[kind],
                     tests=[{"inputs": {"gy": 2024, "gm": 3, "gd": 20}, "expect": {"jy": 1, "jm": 1, "jd": 1}}])
    return pkg


def dumps(pkg):
    return json.dumps(pkg, ensure_ascii=False)


# ----------------------------------------------------------------------------- web doubles
def fetch_reply(body="<html><head><title>سلام</title></head><body>متن آزمایشی</body></html>", status=200,
                ctype="text/html; charset=utf-8"):
    return TransportResponse(status, {"content-type": ctype}, body.encode("utf-8"), False, "93.184.216.34")


class FakeFetchTransport:
    """Callable `fetch_text` transport: replays its items; records every request (None of them is a real socket)."""

    def __init__(self, *items):
        self.items, self.requests = list(items) or [fetch_reply()], []

    def __call__(self, request):
        self.requests.append(request)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item


class FakeStreamTransport:
    """`download_file` transport (uses `.stream`): one verified model file, delivered in chunks."""

    def __init__(self, data, status=200, ctype="application/octet-stream"):
        self.data, self.status, self.ctype, self.requests = data, status, ctype, []

    def stream(self, request):
        self.requests.append(request)
        chunks = [self.data[i:i + 1500] for i in range(0, len(self.data), 1500)]
        return StreamResponse(self.status, {"content-type": self.ctype}, "93.184.216.34", lambda: iter(chunks), lambda: None,
                              declared_length=len(self.data))

    def __call__(self, request):  # pragma: no cover - downloads must use .stream
        raise AssertionError("downloads must stream")


# ------------------------------------------------------------------------------ model doubles
MODEL_TEXTS = ["سلام دوست من. امروز هوا خیلی خوب است.", "من به مدرسه می‌روم و کتاب می‌خوانم.", "سلام، حال شما چطور است؟",
               "امروز هوا خوب است و من خوشحالم.", "کتاب خوب دوست خوب است."]
MODEL_BYTES = train_ngram_model(MODEL_TEXTS)
MODEL_SHA = hashlib.sha256(MODEL_BYTES).hexdigest()
MODEL_URL = "https://models.example.org/fa-ngram.json"
MODEL_ID = "fa-ngram"
Usage = namedtuple("Usage", "total used free")
PLENTY = lambda _path: Usage(10 ** 12, 0, 10 ** 12)  # noqa: E731


def model_card(**over):
    data = dict(model_id=MODEL_ID, title="مدل آزمایشی", version="1.0", format="ngram-json", source_url=MODEL_URL,
                sha256=MODEL_SHA, size_bytes=len(MODEL_BYTES), license="mit")
    data.update(over)
    return data


# ------------------------------------------------------------------------------ Android double
ALL_PERMS = frozenset({"android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE",
                       "android.permission.RECORD_AUDIO", "android.permission.CAMERA"})
NET_STATE = "android.permission.ACCESS_NETWORK_STATE"


class HubFakeBridge(AndroidBridge):
    platform_name = "android"

    def __init__(self, sdk=34, granted=(NET_STATE,), declared=ALL_PERMS, native=("file_chooser", "permission_request"),
                 connectivity=None, dispatched=True):
        self.sdk, self.granted, self.declared = sdk, set(granted), frozenset(declared)
        self.native, self.conn, self.dispatched = frozenset(native), connectivity or BridgeConnectivity("online", "validated"), dispatched
        self.request_calls = []

    def sdk_int(self):
        return self.sdk

    def check_permission(self, name):
        return "granted" if name in self.granted else "denied"

    def declared_permissions(self):
        return self.declared

    def native_features(self):
        return self.native

    def request_permissions(self, names):
        self.request_calls.append(list(names))
        return BridgeRequestResult(self.dispatched, "dispatched" if self.dispatched else "no_activity")

    def connectivity(self):
        return self.conn

    def special_permission_granted(self, name):
        return None
