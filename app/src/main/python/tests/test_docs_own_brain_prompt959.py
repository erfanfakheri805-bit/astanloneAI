"""
Prompt 959 (stage B) - the two documents about the phone's OWN brain («مغز خودکار») must stay true.

  docs/own_brain_prompt959.md           the technical document: the rules, the modules, the catalogue, the life of a download, the build ladder
  docs/own_brain_guide_fa_prompt959.md  the Persian user guide: every sentence it tells the user to say is run through the REAL classifiers (a hint
                                        that does not work is a bug), every number it states is the code's, and the messages it explains are the
                                        app's real messages

If the code changes and a document is not updated, a test here fails instead of the document quietly lying to the user. (This file found two dead
hints in the guide the first time it ran: «مغز چقدر جا می‌گیرد؟» is deliberately NOT an own-brain command - a bare «مغز …؟» may be the human brain -
and «خودت کارهای لازمت را فراهم کن» was not understood; the first was corrected in the guide, the second in the classifier.)
"""
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import llm, ownbrain, ownbrain_catalog as catalog, ownbrain_state
from model_runtime import litertlm_runtime
from net_tools.resumable import RESUMABLE_MESSAGES
from persian_brain import hub_brain_commands as BC
from persian_brain import hub_intents as HI
from persian_brain import hub_messages_ownbrain as BM
from persian_brain import hub_ownbrain
from persian_brain import hub_ownbrain_commands as OC
from persian_brain import normalization as nz
from self_builder import fa_text

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", ".."))
DOCS = os.path.join(REPO, "docs")
TECH = os.path.join(DOCS, "own_brain_prompt959.md")
GUIDE = os.path.join(DOCS, "own_brain_guide_fa_prompt959.md")
GRADLE = os.path.join(REPO, "app", "build.gradle")
WORKFLOW = os.path.join(REPO, ".github", "workflows", "android-debug-apk.yml")
JAVA_DIR = os.path.join(REPO, "app", "src", "main", "java", "com", "erfan", "standaloneai")
TESTS = os.path.join(PY_ROOT, "tests")
DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(number):
    return str(number).translate(DIGITS)


def read(path):
    if not os.path.isfile(path):
        raise unittest.SkipTest("%s is not part of this checkout layout" % os.path.basename(path))
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def flat(text):
    return re.sub(r"\s+", " ", text)


def all_quoted(text):
    found = []
    for match in re.finditer(r"«([^»]+)»", text):
        phrase = match.group(1).strip()
        if phrase not in found:
            found.append(phrase)
    return found


def section(text, number):
    match = re.search(r"^## %s\..*?(?=^## |\Z)" % re.escape(str(number).translate(DIGITS)), text, re.S | re.M)
    return match.group(0) if match else ""


def own(phrase):
    norm = nz.normalize(phrase)
    return OC.classify(phrase, norm, fa_text.words(norm))


def routes(phrase):
    """Every way the app understands `phrase` besides the own brain's classifier: the app-wide internet switch, the emergency words, the answers
    to the open question («بله», «نه», «سبک», «قوی»), and the clarification word."""
    norm = nz.normalize(phrase)
    toks = fa_text.words(norm)
    found = set()
    command = HI.classify(phrase, norm, toks, named_pack=True)
    if command is not None:
        found.add(command.kind)
    for name, test in (("halt", BC.is_halt), ("resume", BC.is_resume), ("clarify", BC.is_clarify)):
        if test(toks):
            found.add(name)
    for word in (OC.choose_word(toks), OC.confirm_word(toks)):
        if word:
            found.add(word)
    return found


# ====================================================================== what the guide quotes, and in which role
OWN_COMMANDS = {                       # phrase -> (own-brain command, `bare`: a short phrase the chat acts on only while a download / failure exists)
    "مغز خودت را بگیر": (OC.GET, False),
    "خودت کارهای لازمت را فراهم کن": (OC.GET, False),
    "مغز بگیر": (OC.GET, False),                                  # quoted as the CONTRAST to «از مغزت بخواه …»
    "وضعیت مغز": (OC.STATUS, False),
    "دانلود مغز را متوقف کن": (OC.PAUSE, False),
    "ادامه دانلود مغز": (OC.RESUME, False),
    "آزمایش مغز": (OC.TEST, False),
    "مغز را دوباره امتحان کن": (OC.RETRY, False),
    "مغز را پاک کن": (OC.DELETE, False),
    "مغز خودکار چیست؟": (OC.HELP, False),
    "مغز خودت چقدر جا می‌گیرد؟": (OC.HELP, False),
    "دانلود را متوقف کن": (OC.PAUSE, True),
    "ادامه دانلود": (OC.RESUME, True),
    "دوباره امتحان کن": (OC.RETRY, True),
    "چقدر مونده؟": (OC.STATUS, True),
}
OTHER_COMMANDS = {                     # phrase -> how the rest of the app understands it
    "اینترنت را خاموش کن": HI.NET_OFF, "اینترنت را روشن کن": HI.NET_ON, "ایست": "halt", "ادامه": "resume", "چرا؟": "clarify",
    "سبک": "light", "قوی": "strong", "بله": "confirm", "نه": "deny",
}
# Prompt 959 (stage B; a conscious change of this pin): «بدنه» is the name of the next piece (the guide points at its own guide) - a name, nothing to type.
LABELS = {"بدنه", "مغزِ خودکار", "مغز", "آزموده‌شده با دوبله", "آزموده نشده", "موفقیت نهایی", "آماده", "موتور", "نگهبانِ کرش", "اینترنتِ برنامه",
          "زبانِ هوش مصنوعیِ خودش", "مترجمِ جداگانه", "رایگان + بی‌کلید + مخصوصِ خودت"}          # words and names, nothing to type
APP_SAYS = {"آماده است ✅", "دارم مغز را نصب و برای بار اول آزمایش می‌کنم", "این مرحله را نمی‌شود وسطش قطع کرد"}   # the app's own sentences
NOT_COMMANDS = {"مغزِ انسان چطور کار می‌کند؟", "مغز ابری", "کلید", "API"}                      # named as what the own brain leaves alone
TEMPLATES = {"از مغزت بخواه …"}
KNOWN = set(OWN_COMMANDS) | set(OTHER_COMMANDS) | LABELS | APP_SAYS | NOT_COMMANDS | TEMPLATES


class GuideSentencesTests(unittest.TestCase):
    def setUp(self):
        self.text = read(GUIDE)

    def test_every_quoted_phrase_has_a_known_role(self):
        unknown = [p for p in all_quoted(self.text) if p not in KNOWN and not p.startswith("Brain engine:")]
        self.assertEqual(unknown, [], "the guide quotes a phrase this test does not know: say whether it is something to say, a label, something the "
                                      "app says or something the own brain leaves alone, and put it in the matching table")

    def test_every_sentence_to_say_is_understood_as_the_command_the_guide_says(self):
        wrong = []
        for phrase, (kind, bare) in OWN_COMMANDS.items():
            command = own(phrase)
            got = None if command is None else (command.kind, bool(command.slots.get("bare")))
            if got != (kind, bare):
                wrong.append((phrase, (kind, bare), got))
        for phrase, expected in OTHER_COMMANDS.items():
            if expected not in routes(phrase):
                wrong.append((phrase, expected, sorted(routes(phrase))))
            self.assertIsNone(own(phrase), "the own brain must not take over «%s»" % phrase)
        self.assertEqual(wrong, [])

    def test_everything_the_tables_expect_is_still_in_the_guide(self):
        quoted = set(all_quoted(self.text))
        gone = sorted((set(OWN_COMMANDS) | set(OTHER_COMMANDS) | APP_SAYS | NOT_COMMANDS | TEMPLATES) - quoted)
        self.assertEqual(gone, [], "the test still checks phrases the guide no longer quotes")
        self.assertGreaterEqual(len(quoted & (set(OWN_COMMANDS) | set(OTHER_COMMANDS))), 20, "the guide must really be checked, not skipped")

    def test_the_sentences_named_as_not_the_own_brains_are_left_alone(self):
        self.assertIsNone(own("مغزِ انسان چطور کار می‌کند؟"))
        for sentence in ("مغز ابری را فعال کن", "مغز با کلید را فعال کن", "مغز API را فعال کن"):            # the cloud brain's words
            self.assertIsNone(own(sentence), sentence)
        norm = nz.normalize("مغز ابری را فعال کن")
        self.assertIsNotNone(BC.classify("مغز ابری را فعال کن", norm, fa_text.words(norm)), "the cloud brain's own command takes it")
        phrase = "از مغزت بخواه یک ماشین‌حساب بسازد"                                                     # the template «از مغزت بخواه …»
        self.assertIsNone(own(phrase))
        norm = nz.normalize(phrase)
        command = HI.classify(phrase, norm, fa_text.words(norm))
        self.assertEqual((command.kind, command.slots["assistant"]), (HI.TEACHER_ASK, "brain"))

    def test_what_the_guide_quotes_from_the_app_is_what_the_app_says(self):
        self.assertIn("آماده است ✅", BM.status({"phase": "ready", "title_fa": "x"}))
        self.assertIn("دارم مغز را نصب و برای بار اول آزمایش می‌کنم", BM.status({"phase": "installing"}))
        self.assertIn("این مرحله را نمی‌شود وسطش قطع کرد", BM.busy_installing())

    def test_the_release_notes_the_guide_quotes_are_the_workflows(self):
        workflow = read(WORKFLOW)
        notes = [p for p in all_quoted(self.text) if p.startswith("Brain engine:")]
        self.assertEqual(len(notes), 3, "the three kinds of build: LiteRT-LM included, only MediaPipe, no engine")
        for note in notes:
            for part in (piece.strip() for piece in note.split("…")):
                self.assertIn(part, workflow, "the guide quotes «%s» from the release notes; the workflow does not write it" % part)


class GuideNumbersTests(unittest.TestCase):
    def setUp(self):
        self.text = flat(read(GUIDE))
        self.light, self.strong = catalog.LIGHT_CHOICE, catalog.STRONG_CHOICE

    def test_the_sizes_and_memory_are_what_the_app_says(self):
        size = BM.size
        self.assertIn("حدود %s (کمتر از یک گیگابایت)" % size(self.light.size_hint), self.text)
        self.assertEqual(size(self.light.size_hint), "۹۶۵ مگابایت")
        self.assertIn("| حجمِ دانلود | حدود %s (کمتر از یک گیگابایت) | حدود %s |" % (size(self.light.size_hint), size(self.strong.size_hint)), self.text)
        self.assertIn("| حداقل RAM | %s | %s |" % (size(self.light.min_ram), size(self.strong.min_ram)), self.text)
        self.assertIn("RAM حدود %s به بالا" % size(self.strong.comfortable_ram), self.text)
        self.assertIn("از **۱ تا %s** جای گوشی" % size(self.strong.size_hint), self.text)
        self.assertIn("(حدودِ %s برای مغزِ سبک و %s برای مغزِ قوی‌تر" % (BM.ram_use(self.light), BM.ram_use(self.strong)), self.text)
        self.assertLess(self.light.size_hint, catalog.GB)

    def test_the_free_space_margin_is_the_codes(self):
        self.assertEqual(self.text.count("به‌علاوهٔ %s" % BM.size(catalog.SAFETY_FREE)), 3)
        need = int(self.strong.size_hint * (1 + self.strong.tolerance)) + catalog.SAFETY_FREE
        self.assertEqual(round(need / catalog.GB), 3, "the checklist says about 3 GB free for the strong brain")
        self.assertIn("حدودِ ۳ گیگابایت جای خالی", self.text)

    def test_the_times_are_the_codes(self):
        self.assertEqual(hub_ownbrain.PENDING_TTL_SECONDS, 30 * 60)
        self.assertIn("(تا %s دقیقه)" % fa(hub_ownbrain.PENDING_TTL_SECONDS // 60), self.text)
        self.assertIn("تا %s ثانیه فرصت می‌دهم" % fa(int(llm.CHAT_DEADLINE_SECONDS)), self.text)
        self.assertEqual(ownbrain.IDLE_UNLOAD_SECONDS, 10 * 60)
        self.assertIn("بعد از ده دقیقه بیکاری", self.text)

    def test_the_status_of_every_feature_is_one_of_the_honest_labels(self):
        rows = [line for line in section(read(GUIDE), 1).splitlines() if line.startswith("| ") and not line.startswith("| ---") and "قابلیت" not in line]
        self.assertGreaterEqual(len(rows), 8)
        for row in rows:
            status = row.split(" | ")[1]
            self.assertTrue(any(label in status for label in ("آزموده‌شده با دوبله", "آزموده نشده", "هنوز نیست")), row)

    def test_the_guide_says_what_was_not_tested(self):
        # Prompt 959 (stage B; a conscious change of this pin, was "«ایست» هنوز جوابِ در حالِ ساخته‌شدن را قطع نمی‌کند"): the body made «ایست» ask the engine to drop a
        # running answer, so the old sentence would now be false; the guide must say what is true - it is only a REQUEST, and never tried with the real engine.
        for needle in ("آزموده نشده", "فیلترشکن", "هنوز هیچ‌وقت اجرا نشده", "اثرانگشتِ مغزِ قوی در این نشست دوباره تطبیق داده نشد",
                       "فرقِ Wi-Fi و اینترنتِ همراه را برنامه نمی‌داند", "جوابِ در حالِ ساخته‌شدن را فقط **درخواست** می‌کند که رها شود"):
            self.assertIn(needle, self.text)
        self.assertIn("موفقیت نهایی", self.text)


class GuideMessagesTests(unittest.TestCase):
    """The table «if the app says …»: the left cell is in the guide, and the app really says what the row explains."""

    def rows(self):
        light = catalog.LIGHT_CHOICE
        return (
            ("موتورِ مغز در این نسخه نیست", BM.blocked("engine_missing", "x", light), ("موتورِ اجرای مغزِ زبانی", "چیزی دانلود نکردم")),
            ("موتورِ مغز هست ولی با شکلی که برنامه انتظار دارد نمی‌خواند",
             BM.blocked("engine_missing", "api_mismatch", light, {"engine_code": "api_mismatch"}), ("با شکلی که برنامه از آن انتظار دارد نمی‌خواند", "چیزی دانلود نکردم")),
            ("حافظهٔ رمِ گوشی کمتر از حداقل است", BM.blocked("ram_too_small", "2000000000/3000000000", light), ("از حداقلِ لازم", "کمتر است")),
            ("نتوانستم اندازهٔ حافظه را بخوانم", BM.blocked("ram_unknown"), ("نتوانستم اندازهٔ حافظهٔ گوشی را بخوانم", "حدس نمی‌زنم")),
            ("جای آزاد کافی نیست", BM.blocked("not_enough_space", "1000000000/2000000000", light, {}), ("کافی نیست", "جا باز کن")),
            ("گوشی آفلاین است", BM.blocked("offline"), ("اینترنت ندارد",)),
            ("اینترنتِ برنامه خاموش است", BM.blocked("network_off"), ("اینترنتِ برنامه خاموش است", "اینترنت را روشن کن")),
            ("دانلود قطع شد / به سرور نرسیدم", RESUMABLE_MESSAGES["interrupted"][0], ("قطع", "از همان‌جا ادامه")),
            ("فایلِ روی سرور عوض شده", BM.failure_text("remote_changed"), ("فایلِ روی سرور عوض شده", "چیزی دانلود نشد")),
            ("اثرانگشتِ فایلِ دانلودشده نخورد", BM.failure_text("hash_mismatch"), ("دور ریخته شد", "چیزی نصب نشد")),
            ("فایل سالم است ولی موتور نتوانست مغز را بارگذاری کند", BM.failure_text("engine_load_failed"),
             ("فایل سالم است ولی موتور نتوانست مغز را بارگذاری کند", "رم")),
            ("دفعهٔ قبل وسطِ بارگذاری برنامه بسته شد", BM.failure_text("crashed_before"), ("از کار افتاد", "دوباره امتحان نمی‌کنم")),
            ("مغز به پرسشِ آزمایشی جواب نداد", BM.failure_text("smoke_test_failed"), ("پرسشِ آزمایشی", "«آماده» نمی‌گویم")),
            ("مغزِ خودم در N ثانیه جواب نداد", BM.llm_timeout(170), ("مغزِ خودم در ", " ثانیه جواب نداد", "کند است")),
            ("این مرحله را نمی‌شود وسطش قطع کرد", BM.busy_installing(), ("این مرحله را نمی‌شود وسطش قطع کرد", "چند دقیقه")),
        )

    def test_every_row_is_in_the_guide_and_in_the_apps_words(self):
        table = flat(section(read(GUIDE), 7))
        for cell, real, fragments in self.rows():
            self.assertIn(cell, table, "the guide does not explain «%s»" % cell)
            for fragment in fragments:
                self.assertIn(fragment, real, "the app no longer says «%s» for «%s»" % (fragment, cell))

    def test_the_two_refusals_that_never_change_a_permission_are_stated_as_such(self):
        text = flat(read(GUIDE))
        self.assertIn("**هیچ مجوزی عوض نمی‌شود.**", text)
        self.assertIn("کلید را هرگز خودشان دوباره روشن نمی‌کنند", text)
        self.assertIn("«بله»ی کارتِ موافقت این کلید را روشن می‌کند", text)


class GuideStructureTests(unittest.TestCase):
    def setUp(self):
        self.text = read(GUIDE)

    def test_the_ten_sections_are_there_in_order(self):
        headings = re.findall(r"^## (\S+)\.", self.text, re.M)
        self.assertEqual(headings, [fa(n) for n in range(1, 11)])

    def test_the_two_documents_point_at_each_other_and_both_exist(self):
        self.assertIn("docs/own_brain_prompt959.md", self.text)
        self.assertIn("docs/own_brain_guide_fa_prompt959.md", read(TECH))
        self.assertTrue(os.path.isfile(TECH) and os.path.isfile(GUIDE))

    def test_every_command_of_the_commands_table_is_in_the_table(self):
        table = section(self.text, 5)
        for phrase in ("مغز خودت را بگیر", "وضعیت مغز", "دانلود مغز را متوقف کن", "ادامه دانلود مغز", "آزمایش مغز", "مغز را دوباره امتحان کن",
                       "مغز را پاک کن", "مغز خودکار چیست؟", "مغز خودت چقدر جا می‌گیرد؟", "سبک", "قوی", "چرا؟", "ایست", "ادامه", "اینترنت را خاموش کن",
                       "اینترنت را روشن کن"):
            self.assertIn("«%s»" % phrase, table)
        for command in (BM.START, BM.STATUS, BM.PAUSE, BM.RESUME, BM.TEST, BM.RETRY, BM.DELETE):       # what the app's own replies tell the user to say
            self.assertIn("«%s»" % command, table)


class TechnicalDocumentTests(unittest.TestCase):
    def setUp(self):
        self.raw = read(TECH)
        self.text = flat(self.raw)
        self.light, self.strong = catalog.LIGHT_CHOICE, catalog.STRONG_CHOICE

    def test_every_module_of_the_own_brain_is_named(self):
        named = {"brain_hub": [n for n in os.listdir(os.path.join(PY_ROOT, "brain_hub")) if n.startswith("ownbrain") and n.endswith(".py")],
                 "persian_brain": [n for n in os.listdir(os.path.join(PY_ROOT, "persian_brain")) if n.startswith(("hub_ownbrain", "hub_messages_ownbrain"))
                                   and n.endswith(".py")],
                 "net_tools": ["resumable.py"], "model_runtime": ["litertlm_runtime.py"]}
        for package, names in named.items():
            self.assertTrue(names, package)
            for name in names:
                self.assertIn("`%s`" % name, self.text, "%s/%s is not in the technical document" % (package, name))
        self.assertIn("`LiteRtLmBridge.java`", self.text)

    def test_every_file_the_document_names_exists(self):
        index = set()
        for base, folders, files in os.walk(REPO):
            folders[:] = [f for f in folders if f not in (".git", "__pycache__", "node_modules")]
            index.update(files)
        missing = []
        for name in sorted(set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|java|gradle|yml|md))`", self.raw))):
            exists = os.path.basename(name) in index and (("/" not in name) or os.path.isfile(os.path.join(REPO, name)) or
                                                          os.path.isfile(os.path.join(PY_ROOT, name)))
            if not exists:
                missing.append(name)
        self.assertEqual(missing, [])

    def test_the_codes_of_the_rule_table_are_real(self):
        sources = "".join(read(os.path.join(PY_ROOT, rel)) for rel in ("brain_hub/ownbrain.py", "persian_brain/hub_messages_ownbrain.py",
                                                                       "net_tools/resumable.py", "model_runtime/litertlm_runtime.py"))
        for code in ("engine_missing", "ram_unknown", "not_enough_space", "offline", "network_off", "network_failed", "remote_changed",
                     "hash_mismatch", "crashed_before", "net_off"):
            self.assertIn("`%s`" % code, self.text, code)
            self.assertIn('"%s"' % code, sources, code)

    def test_the_catalogue_table_is_the_catalogue(self):
        light, strong = self.light, self.strong
        self.assertIn("| about %.2f GB (a hint) | %d %% | %.1f GB | %.1f GB |" % (strong.size_hint / catalog.GB, round(strong.tolerance * 100),
                                                                                   strong.min_ram / catalog.GB, strong.comfortable_ram / catalog.GB),
                      self.text)
        self.assertIn("| {:,} bytes (exact) | %d %% | %.1f GB |".format(light.size_hint) % (round(light.tolerance * 100), light.min_ram / catalog.GB),
                      self.text)
        self.assertEqual(light.exact_size, light.size_hint)
        self.assertEqual((strong.key, light.key), ("strong", "light"))
        self.assertIn("**plus %d MB** of free space" % (catalog.SAFETY_FREE // catalog.MB), self.text)
        self.assertIn("only `huggingface.co` / `hf.co` are ever contacted", self.text)
        self.assertEqual(catalog.ALLOWED_HOSTS, ("huggingface.co", "hf.co"))

    def test_the_numbers_are_the_codes(self):
        self.assertIn("at most %d bytes" % ownbrain_state.MAX_STATE_BYTES, self.text)
        self.assertIn("for %d seconds" % ownbrain.GRACE_SECONDS, self.text)
        self.assertEqual(ownbrain.IDLE_UNLOAD_SECONDS, 600)
        self.assertIn("Ten minutes after the last question", self.text)
        self.assertIn("%d-minute lifetime" % (hub_ownbrain.PENDING_TTL_SECONDS // 60), self.text)
        self.assertIn("last **%d** turns" % llm.MEMORY_TURNS, self.text)
        self.assertIn("limited to **%d** tokens" % llm.MAX_TOKENS, self.text)
        self.assertIn("**%d-second** deadline for the own brain (**%d seconds** for the other engines" % (llm.CHAT_DEADLINE_SECONDS, llm.DEADLINE_SECONDS),
                      self.text)
        self.assertEqual((BM.ram_use(self.strong), BM.ram_use(self.light)), ("۳ گیگابایت", "۱ گیگابایت"))
        self.assertIn("about 3 GB for the strong brain, about 1 GB for the light one", self.text)
        self.assertIn("the file size x 1.2 rounded to half a gigabyte", self.text)

    def test_the_names_of_the_files_and_keys_are_the_real_ones(self):
        self.assertIn("`%s/%s`" % (ownbrain_state.DIR_NAME, ownbrain_state.STATE_FILE), self.text)
        self.assertIn("`%s`" % hub_ownbrain.PENDING_KEY, self.text)
        self.assertIn("own_brain/<key>-<first 12 hex of the hash>/model.litertlm.partial", self.text)
        for choice in (self.light, self.strong):
            self.assertEqual(catalog.rel_dest(choice), "%s-%s/model.litertlm" % (choice.key, choice.sha256[:12]))
        self.assertEqual(litertlm_runtime.MARKER_SUFFIX, ".loading")
        self.assertIn("`<model>.loading`", self.text)

    def test_the_build_ladder_is_what_the_workflow_and_gradle_do(self):
        gradle, workflow = read(GRADLE), read(WORKFLOW)
        for needle in ("-PwithLiteRtLm=true", "id: with_litertlm", "id: with_engine", "litertlm-build-log", "LITERTLM_VERSION", "-PwithLlm=true"):
            self.assertIn(needle, workflow, needle)
        for needle in ("`with_litertlm`", "`continue-on-error`", "`litertlm-build-log`", "`-PwithLlm=true`", "`LITERTLM_VERSION`", "`-PwithLiteRtLm=true`"):
            self.assertIn(needle, self.text, needle)
        self.assertIn("com.google.ai.edge.litertlm:litertlm-android:0.19.1", gradle)
        self.assertEqual(re.findall(r"litertlm-android:([^'\"]+)'", gradle), ["0.19.1"])        # pinned (stage B): every build is the same build
        self.assertIn("`com.google.ai.edge.litertlm:litertlm-android:0.19.1`", self.text)
        rules = ("'**/libc++_shared.so'", "'**/libLiteRt*.so'", "'**/liblitert*.so'")
        self.assertTrue(all(rule in gradle for rule in rules))
        self.assertIn("three `pickFirst` packaging rules", self.text)
        # Prompt 959 (stage B): the engine variant is built for Android 8.0+ (minSdk 26), found in the first real build log; and it has a pre-download probe
        self.assertIn("minSdk 26", gradle)
        # Prompt 959 (stage B): the stable debug key (cache) - what the workflow does is what both documents say
        for needle in ("uses: actions/cache@v4", "path: ~/.android/debug.keystore", "key: debug-keystore-v1", "KEY_NOTE=Signing key: the SAVED debug key",
                       "KEY_NOTE=Signing key: a NEW debug key"):
            self.assertIn(needle, workflow, needle)
        for needle in ("`actions/cache@v4`", "`~/.android/debug.keystore`", "`debug-keystore-v1`", "`Signing key: the SAVED debug key`", "`a NEW debug key`"):
            self.assertIn(needle, self.text + read(GUIDE), needle)
        self.assertIn("`Signing key: the SAVED debug key`", read(GUIDE))
        self.assertIn("**raises `minSdk` from 24 to 26**", self.text)
        self.assertIn("Invoke-customs are only supported starting with Android O (--min-api 26)", self.text)
        for needle in ("`LiteRtLmBridge.probe()`", "`LiteRtLmBridge.api()`", "`api_mismatch`"):
            self.assertIn(needle, self.text, needle)
        self.assertIn('versionCode 2', gradle)
        self.assertIn('versionName "0.2.0"', gradle)

    def test_the_java_layer_is_the_five_thin_files_the_document_says(self):
        # Prompt 959 (stage B; a conscious change of this pin, was "the three thin files"): the body added BodyService.java (the foreground service of
        # long jobs) and StopReceiver.java (its notification's stop button), both explained in docs/body_prompt959.md. This document still describes
        # the own-brain piece, in which the layer had three files, and now says so.
        names = sorted(n for n in os.listdir(JAVA_DIR) if n.endswith(".java"))
        self.assertEqual(names, ["BodyService.java", "LiteRtLmBridge.java", "MainActivity.java", "PyAccessibilityService.java", "StopReceiver.java"])
        self.assertIn("the Java layer was three thin files here; stage B, the body, made it five", self.text)
        self.assertIn("the Java layer stays thin (three files in this piece; five after the body, stage B)", self.text)

    def test_the_seven_pinned_files_are_named_as_unchanged(self):
        for name in ("android_entry.py", "core/core.py", "ael/interpreter.py", "runtime_integration/bridge.py", "interface/server.py",
                     "runtime_integration/runtime_core.py", "runtime_growth/runtime_growth_cycle.py"):
            self.assertIn(name, self.text)
        self.assertIn("byte-identical", self.text)

    def test_the_test_table_names_real_files_and_misses_none(self):
        named = set(re.findall(r"`(test_[a-z0-9_]+_prompt959\.py)`", self.raw[self.raw.index("## 10. Tests"):]))
        for name in sorted(named):
            self.assertTrue(os.path.isfile(os.path.join(TESTS, name)), "%s is named in the technical document but does not exist" % name)
        mine = {n for n in os.listdir(TESTS) if n.startswith("test_") and n.endswith("_prompt959.py")
                and n.startswith(("test_ownbrain_", "test_litertlm_", "test_model_runtime_", "test_net_tools_resumable", "test_net_tools_abort",
                                  "test_docs_own_brain"))}
        self.assertEqual(sorted(mine - named), [], "a test of this stage is not in the table of the technical document")

    def test_the_document_states_its_honest_limits(self):
        # Prompt 959 (stage B; a conscious change of this pin, was "does not yet cancel a running answer"): the body made «ایست» ask the engine to drop a running
        # answer (a request, only tried against a stand-in engine), so the document says that instead.
        for needle in ("Nothing ran on a phone.", "could not be re-verified", "Hugging Face may need a VPN in Iran", "only progresses while the app is open",
                       "cannot be interrupted", "asks the engine to drop a running answer", "Storage: 1-2.6 GB"):
            self.assertIn(needle, self.text)


if __name__ == "__main__":
    unittest.main()
