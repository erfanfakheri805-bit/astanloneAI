"""
Shared base for the Prompt-957 ACCEPTANCE tests (not a test module itself): the installed app, started as closely as a test
can start it and driven only through its real front door.

* storage layout and brain scope come from `android_entry.AndroidFilesDirAdapter` (the very adapter the Android entry point
  installs), so the Persian brain runs in its FULL scope for the same reason it does on the phone;
* the request path is the real one: HTTP `POST /api/message` -> `interface.server` handler -> `RuntimeCore.process_input`
  -> `Core` -> skills -> Persian brain -> hub;
* only the outside world is a scripted double: web transport, model download transport, Android bridge, clock.

`start_app()` is "the app starts" again on the same files folder (new RuntimeCore, new hub, new server), so a restart is real.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import android_entry
from brain_hub.service import HubService, default_root, set_hub
from interface.server import make_handler
from persian_brain import activation, get_brain
from platform_layer import reset_platform, set_platform
from runtime_integration.runtime_core import RuntimeCore
from self_builder import fa_text, service as sb_service
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_hub_case_prompt957 import FakeClock


class AppCase(unittest.TestCase):
    def setUp(self):
        self.files = tempfile.mkdtemp(prefix="app_")
        self.addCleanup(shutil.rmtree, self.files, ignore_errors=True)
        self.clock = FakeClock()
        self.fetch = F.FakeFetchTransport()
        self.stream = F.FakeStreamTransport(F.MODEL_BYTES)
        self.core = self.hub = self.server = None
        self.port = 0
        self.addCleanup(self.stop_app)
        self.start_app()

    # ------------------------------------------------------------------ the app
    def start_app(self):
        self.stop_app()
        set_platform(android_entry.AndroidFilesDirAdapter(self.files))
        self.core = RuntimeCore()
        memory = self.core.memory
        self.hub = HubService(default_root(memory), memory=memory, clock=self.clock, transport=self.fetch,
                              download_transport=self.stream, free_space_fn=F.PLENTY, bridge=F.HubFakeBridge())
        set_hub(memory, self.hub)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.core))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop_app(self):
        server, core, hub = self.server, self.core, self.hub
        self.server = self.core = self.hub = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if hub is not None:
            hub.close()
        if core is not None:
            memory = core.memory
            try:
                service = sb_service.get_service(memory)
                if service is not None:
                    service.close()
            finally:
                memory._conn.close()
        reset_platform()

    @property
    def memory(self):
        return self.core.memory

    @property
    def brain(self):
        return get_brain(self.core.memory)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port

    # ------------------------------------------------------------------ the front door
    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=20) as response:
            return response.status, response.headers.get("Content-Type"), response.read()

    def post(self, path, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")        # like the page's JSON.stringify
        request = urllib.request.Request(self.url + path, data=data,
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def ask(self, text):
        """One chat turn through the real HTTP route; returns the reply text."""
        status, body = self.post("/api/message", {"text": text})
        self.assertEqual(status, 200, body)
        self.assertIsInstance(body.get("reply"), str)
        return body["reply"]

    def paste(self, pkg):
        return self.ask("این بسته را بررسی کن:\n```json\n" + json.dumps(pkg, ensure_ascii=False, indent=1) + "\n```")

    def install(self, pkg):
        """Paste, check that nothing changed before the user's «بله», then check the verified activation. Returns the final reply."""
        before = self.active_version(pkg["id"])
        proposal = self.paste(pkg)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertEqual(self.active_version(pkg["id"]), before)
        reply = self.ask("بله")
        self.assertIn("نصب و فعال شد", reply)
        self.assertNotEqual(self.active_version(pkg["id"]), before)
        return reply

    def active_version(self, cid):
        cap = self.hub.extension(cid)
        return cap.get("active_version") if cap else None

    def installed_ids(self):
        return sorted(c["capability_id"] for c in self.hub.extensions())


# ---------------------------------------------------------------------- a capability nobody hard-coded
# A monthly loan instalment (annuity formula). Not one of the app's archetypes and not the prompt template's example.
# Expected values were computed independently (closed-form annuity in plain Python, checked against the published
# "1,000,000,000 at 12% for 60 months = 22,244,448" figure).
LOAN_VECTORS = ((120_000_000, 18, 12, 11_001_599, 132_019_190), (50_000_000, 0, 10, 5_000_000, 50_000_000),
                (300_000_000, 24, 36, 11_769_856, 423_714_808), (1_000_000_000, 12, 60, 22_244_448, 1_334_666_861))
LOAN_ROUNDED_VECTORS = ((120_000_000, 18, 12, 11_002_000, 132_024_000), (50_000_000, 0, 10, 5_000_000, 50_000_000))
LOAN_ASK = "قسط وام ۱۲۰۰۰۰۰۰۰ با سود ۱۸ درصد و ۱۲ ماه"


def loan_sentence(amount, percent, months):
    return "قسط وام %d با سود %d درصد و %d ماه" % (amount, percent, months)


def loan_answer(payment, total):
    """The sentence the extension answers with (numbers in Persian digits, like every reply of the app)."""
    return "قسط ماهانه: %s تومان؛ جمع پرداختی: %s تومان" % (fa_text.fa_number(payment), fa_text.fa_number(total))


def loan_source(indent="\t", thousands=False):
    """The extension's Python source. `indent` is one level of indentation (a tab survives the chat's whitespace folding
    unaided; spaces need the UI's protection); `thousands` is the v2 behaviour: the instalment is rounded to 1,000."""
    lines = ["def run(amount, annual_percent, months):",
             "@monthly = annual_percent / 1200",
             "@if monthly == 0:",
             "@@payment = amount / months",
             "@else:",
             "@@factor = (1 + monthly) ** months",
             "@@payment = amount * monthly * factor / (factor - 1)"]
    if thousands:
        lines.append("@payment = round(payment / 1000) * 1000")
    lines.append("@return {'payment': round(payment), 'total': round(payment * months)}")
    return "\n".join(line.replace("@", indent) for line in lines) + "\n"


def loan_pkg(indent="\t", thousands=False, padding_bytes=0, **over):
    """`padding_bytes` adds comment lines to the source so the package reaches the size of a hand-written one
    (the extension runtime ignores comments)."""
    source = loan_source(indent, thousands)
    if padding_bytes:
        note = "# " + "یادداشت توضیحی برای بررسی بسته " * 3 + "\n"
        source = note * max(1, padding_bytes // len(note.encode("utf-8"))) + source
    vectors = LOAN_ROUNDED_VECTORS if thousands else LOAN_VECTORS
    pkg = {
        "schema": "ext.v1", "id": "loan_installment", "title": "قسط ماهانهٔ وام",
        "description": "با مبلغ وام، سود سالانه (درصد) و تعداد ماه، قسط ماهانهٔ یکسان و جمع پرداختی را حساب می‌کند.",
        "inputs": [{"name": "amount", "type": "number", "min": 100000, "max": 1000000000000, "label": "مبلغ وام"},
                   {"name": "annual_percent", "type": "number", "min": 0, "max": 100, "label": "سود سالانه (درصد)"},
                   {"name": "months", "type": "integer", "min": 1, "max": 600, "label": "تعداد ماه"}],
        "outputs": [{"name": "payment", "type": "integer", "label": "قسط ماهانه"}, {"name": "total", "type": "integer", "label": "جمع پرداختی"}],
        "source": source,
        "triggers": ["قسط وام {amount} با سود {annual_percent} درصد و {months} ماه",
                     "قسط ماهانه وام {amount} سود {annual_percent} مدت {months} ماه"],
        "answer": "قسط ماهانه: {payment} تومان؛ جمع پرداختی: {total} تومان",
        "examples": [LOAN_ASK],
        "tests": [{"name": "case %d" % i, "inputs": {"amount": a, "annual_percent": r, "months": n},
                   "expect": {"payment": pay, "total": tot}} for i, (a, r, n, pay, tot) in enumerate(vectors, 1)],
        "provenance": {"author": "acceptance-suite", "note": "annuity formula (public)"},
    }
    pkg.update(over)
    return pkg


__all__ = ["AppCase", "loan_pkg", "loan_source", "loan_sentence", "loan_answer", "LOAN_ASK", "LOAN_VECTORS", "LOAN_ROUNDED_VECTORS", "activation"]
