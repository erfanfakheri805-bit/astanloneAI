"""
Prompt 957 - the two documents that ship with the brain hub must stay true.

  docs/brain_hub_prompt957.md          the technical document: modules, states, limits, chat commands
  docs/baby_ai_guide_fa_prompt957.md   the Persian user guide: its example package and the sentences it tells the user to
                                       type are run through the REAL app (HTTP -> Core -> brain -> hub)

If the code changes and a document is not updated, a test here fails instead of the document quietly lying to the user.
"""
import json
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import audit, graph, invoker, templates
from ext_runtime import limits
from ext_runtime.lifecycle import PROPOSAL_TTL_SECONDS
from interface import server
from model_runtime import card
from persian_brain import hub_state
from tests.persian_app_case_prompt957 import AppCase
from net_tools import policy

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", "..", "docs"))
TECH = os.path.join(DOCS, "brain_hub_prompt957.md")
GUIDE = os.path.join(DOCS, "baby_ai_guide_fa_prompt957.md")
PACKAGES = ("brain_hub", "ext_runtime", "net_tools", "model_runtime", "android_adapters", "persian_brain")
HOMES = ("",) + PACKAGES + ("self_builder", "tests", "interface")
NOT_REPO_FILES = {"ext.py"}                      # the optional member name inside an extension ZIP, not a file of this tree


def read(path):
    if not os.path.isfile(path):
        raise unittest.SkipTest("the documentation is not part of this checkout layout")
    with open(path, encoding="utf-8") as f:
        return f.read()


def one_line(text):
    return " ".join(text.split())


def modules_of(package):
    return sorted(n for n in os.listdir(os.path.join(PY_ROOT, package)) if n.endswith(".py") and n != "__init__.py")


class TechnicalDocMatchesTheCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = read(TECH)
        cls.text = one_line(cls.raw)

    def test_every_python_file_the_document_names_exists(self):
        names = set(re.findall(r"`((?:[A-Za-z_]+/)*[A-Za-z_0-9]+\.py)`", self.raw)) - NOT_REPO_FILES
        self.assertGreater(len(names), 30)
        for name in sorted(names):
            self.assertTrue(any(os.path.isfile(os.path.join(PY_ROOT, home, name)) for home in HOMES), name)

    def test_the_package_table_lists_exactly_the_modules_on_disk(self):
        rows = {m.group(1): m.group(2) for m in re.finditer(r"^\| `([a-z_]+)/` \| (.+?) \| ", self.raw, flags=re.MULTILINE)}
        self.assertEqual(sorted(rows), sorted(PACKAGES))
        for package in PACKAGES:
            listed = sorted(re.findall(r"`([a-z_0-9]+\.py)`", rows[package]))
            on_disk = modules_of(package)
            if package == "persian_brain":                              # the older modules are described in self_builder_final_exit.md
                on_disk = [name for name in on_disk if name.startswith("hub_")]
            self.assertEqual(listed, on_disk, package)

    def test_the_state_table_is_the_graphs_state_machine(self):
        section = self.raw.split("## 3.")[1].split("## 4.")[0]
        rows = re.findall(r"^\| `([a-z_]+)` \| .+ \| (yes|no) \|$", section, flags=re.MULTILINE)
        self.assertEqual([name for name, _ in rows], list(graph.STATES))
        for name, usable in rows:
            self.assertEqual(usable == "yes", name in graph.USABLE_STATES, name)
        for kind in graph.BLOCKER_KINDS:
            self.assertIn("`%s`" % kind, section, kind)

    def test_the_limits_quoted_are_the_limits_enforced(self):
        quoted = [
            "The whole package is <= %s bytes" % format(limits.MAX_PACKAGE_BYTES, ","),
            "<= %s bytes of restricted Python" % format(limits.MAX_SOURCE_BYTES, ","),
            "title <= %d, description <= %d characters" % (limits.MAX_TITLE_CHARS, limits.MAX_DESCRIPTION_CHARS),
            "| `inputs` | <= %d;" % limits.MAX_INPUTS,
            "| `outputs` | 1-%d;" % limits.MAX_OUTPUTS,
            "| `triggers` | 1-%d phrases" % limits.MAX_TRIGGERS,
            "| `tests` | 1-%d cases" % limits.MAX_TESTS,
            "work budget (%s steps)" % format(limits.MAX_FUEL, ","),
            "wall-clock budget (%d s)" % limits.MAX_SECONDS,
            "the proposal lives %d days" % (PROPOSAL_TTL_SECONDS // 86400),
            "`persian_brain.hub_pending.v1` %d minutes" % (hub_state.PENDING_TTL_SECONDS // 60),
            "`persian_brain.hub_wish.v1` %d hours" % (hub_state.WISH_TTL_SECONDS // 3600),
            "(default %d s)" % policy.FetchPolicy().timeout_s,
            "at most %s bytes" % format(policy.FetchPolicy().max_bytes, ","),
            "at most %d redirects" % policy.FetchPolicy().max_redirects,
            "<= %d GiB" % (card.MAX_SIZE_BYTES // 2 ** 30),
            "rotates at %s bytes" % format(audit.MAX_BYTES, ","),
            "(body cap %s bytes -> 413)" % format(server.MAX_BODY_BYTES, ","),
        ]
        for fragment in quoted:
            self.assertIn(fragment, self.text)

    def test_the_value_lists_quoted_are_the_real_ones(self):
        for name in limits.INPUT_TYPES + limits.OUTPUT_TYPES:
            self.assertIn(name, self.text, name)
        self.assertIn("`%s`" % limits.EXT_SCHEMA, self.text)
        self.assertIn("`" + " ".join(policy.DEFAULT_CONTENT_TYPES) + "`", self.text)
        self.assertIn("formats `%s`" % " ".join(card.KNOWN_FORMATS), self.text)
        self.assertIn("optional " + ", ".join("`%s`" % name for name in limits.OPTIONAL_PERMISSIONS), self.text)

    def test_the_pinned_files_named_are_the_pinned_files_checked(self):
        from tests.test_claude_exit_audit_final_exit001 import PINNED
        bullet = one_line(self.raw.split("The seven files pinned by earlier prompts")[1].split("are byte-identical")[0])
        self.assertEqual(set(re.findall(r"`([a-z_/]+\.py)`", bullet)), set(PINNED))


# The sentences the guide (and the technical document) tell the user to type, with a fragment each real answer must contain.
CONCRETE_SENTENCES = (
    ("چطور افزونه اضافه کنم؟", "پرامپت افزونه"),
    ("پرامپت افزونه برای محاسبهٔ قسط وام", "ext.v1"),
    ("افزونه‌ها را لیست کن", "افزونه"),
    ("تاریخچهٔ افزونه‌ها", "افزونه"),
    ("نقشهٔ قابلیت‌ها را نشان بده", "نقشهٔ قابلیت‌ها"),
    ("وضعیت اینترنت", "مجوز اینترنت"),
    ("اینترنت را روشن کن", "روشنش کنم"),
    ("اینترنت را خاموش کن", "خاموش"),
    ("مدل‌ها را نشان بده", "مدل"),
    ("وضعیت اندروید را بگو", "اندروید"),
)


def first_json_block(text):
    match = re.search(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    return json.loads(match.group(1)) if match else None


class DocsWorkOnTheRealApp(AppCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.guide = read(GUIDE)
        cls.tech = read(TECH)

    def test_the_node_families_the_document_names_are_those_of_the_live_graph(self):
        self.install(templates.example_package())
        families = {node.node_id.split(".")[0] for node in invoker.build_graph(self.hub).nodes()}
        self.assertEqual(families, {"brain", "tool", "android", "infra", "gap", "ext"})
        section = self.tech.split("## 3.")[1].split("## 4.")[0]
        for family in families | {"model"}:                         # `model.<id>` appears once a model card is registered
            self.assertIn("`%s." % family, section, family)

    def test_the_example_package_in_the_guide_is_the_apps_own_example(self):
        self.assertEqual(first_json_block(self.guide), templates.example_package())

    def test_the_acceptance_walkthrough_of_the_guide_works_step_by_step(self):
        pkg = first_json_block(self.guide)
        for promised in ("پاسخ فارسی", "هنوز چیزی نصب یا فعال نشده است", "آزمون‌ها: ۲ از ۲ موفق", "نصب و فعال شد (نسخهٔ ۱)",
                         "پس از نصب از دیسک دوباره بررسی شد", "BMI شما ۲۲٫۹ است."):
            self.assertIn(promised, self.guide)                      # the guide quotes exactly what the asserts below see
        self.assertTrue(self.ask("سلام").strip())                                                   # step 1
        self.assertIn("نقشهٔ قابلیت‌ها", self.ask("نقشهٔ قابلیت‌ها را نشان بده"))                     # step 2
        self.assertIn("پرامپت افزونه", self.ask("چطور افزونه اضافه کنم؟"))                         # step 3
        proposal = self.paste(pkg)                                                                  # step 4
        self.assertIn("هنوز چیزی نصب یا فعال نشده است", proposal)
        self.assertIn("آزمون‌ها: ۲ از ۲ موفق", proposal)
        reply = self.ask("بله")                                                                     # step 5
        self.assertIn("نصب و فعال شد (نسخهٔ ۱)", reply)
        self.assertIn("پس از نصب از دیسک دوباره بررسی شد", reply)
        self.assertIn("BMI شما ۲۲٫۹ است.", self.ask("bmi وزن 70 قد 1.75"))                         # step 6
        self.start_app()                                                                            # step 7: the app was closed
        self.assertIn("BMI شما ۲۲٫۹ است.", self.ask("bmi وزن 70 قد 1.75"))
        self.assertIn("افزونه", self.ask("تاریخچهٔ افزونه‌ها"))                                    # step 8
        v2 = dict(pkg, answer="شاخص توده بدنی: {bmi}")
        self.assertIn("نسخهٔ ۲", self.paste(v2))
        self.assertIn("نسخهٔ ۲", self.ask("بله"))
        self.assertIn("شاخص توده بدنی: ۲۲٫۹", self.ask("bmi وزن 70 قد 1.75"))
        self.assertIn("از نسخهٔ ۲ به نسخهٔ ۱", self.ask("افزونهٔ محاسبهٔ شاخص توده بدنی را برگردان"))
        self.assertIn("برگشت", self.ask("بله"))
        self.assertIn("BMI شما ۲۲٫۹ است.", self.ask("bmi وزن 70 قد 1.75"))

    def test_the_sentences_the_documents_recommend_are_understood_by_the_app(self):
        for sentence, fragment in CONCRETE_SENTENCES:
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, self.guide + self.tech)
                reply = self.ask(sentence)
                self.assertIn(fragment, reply)
                if sentence == "اینترنت را روشن کن":
                    self.ask("نه")                                                                  # leave the internet off

    def test_the_guide_mentions_the_commands_of_the_command_table_that_have_no_placeholder(self):
        for sentence in ("افزونه را غیرفعال کن", "افزونه را فعال کن", "تاریخچهٔ افزونه‌ها", "افزونه‌ها را لیست کن",
                         "نقشهٔ قابلیت‌ها را نشان بده", "وضعیت اینترنت", "اینترنت را روشن کن", "اینترنت را خاموش کن",
                         "مدل‌ها را نشان بده", "وضعیت اندروید را بگو"):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, self.guide)
                self.assertIn(sentence, self.tech)


if __name__ == "__main__":
    unittest.main()
