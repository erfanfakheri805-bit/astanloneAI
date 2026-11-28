# The body: what keeps a long job alive, the one stop word, the self-test and the one-time code (Prompt 959, stage B)

> **Status of every statement in this document: built and tested with stand-ins - never run on a phone.** The stand-ins are a fake Android (hand-written from
> Android's documented API), a fake engine, and a `javac` compile of the Java files against the REAL `android.jar`. Whatever only a phone can show
> (how Android 12+, Android 15 and HyperOS treat the service, whether the notification's button works, whether the engine really drops an answer when it is
> asked) is listed in section 8 and is claimed nowhere else.

The Persian user guide is `docs/body_guide_fa_prompt959.md`; the piece before this one is `docs/own_brain_prompt959.md`.

## 1. What this piece is

The own brain downloads a 1-2.6 GB model. A phone that saves battery the way HyperOS does closes an app that is not on the screen, and the user cannot run a
terminal: when something does not work, the only thing that travels back is a message he pastes. The body is the small part of the app that answers that:

1. **Keep a long job alive.** ONE foreground service with ONE notification (a progress bar and a stop button «ایست») for as long as a job runs; the
   notification is the own brain's download and install, today the only job.
2. **One meaning of «ایست».** The chat word, the stop button of the chat page (it sends the same word while an answer is being written) and the notification's button all run the same code.
3. **Tell the truth about the phone.** A report the user can copy («گزارش آزمایشی»), a checklist of what only HE can switch on («چک‌لیست دسترسی‌ها»), the
   settings pages that matter (opened, never changed), and - only on his order - the newest one-time code of his text messages («کد پیامک را بخوان»).

It is **not**: an always-on service, a microphone service, something that reads messages by itself, or anything that starts without the user's agreement.
«هی جارویس» (listening all the time) needs a microphone-type service in the manifest and is a later piece.

## 2. The rules

| # | Rule | Kept by |
| --- | --- | --- |
| 1 | The body starts nothing by itself: a job exists only because the own brain, which the user agreed to, is running. | `Body.on_ownbrain` |
| 2 | The service has no work of its own: no timer, no thread, no network, no loop; the only thing it ever asks Python for is the emergency stop. | `BodyService.java`, `SafetyRulesTests` |
| 3 | Python is the brain: Java shows only what Python hands over (a title of at most 60 characters, a text of at most 160, a percent from -1 to 100). | `native_bridge/body.py` |
| 4 | A failure is a code, never a crash: when Android refuses to start the service (from the background, on Android 12 and newer) `hold()` answers false; a door that can never work in this build (`unavailable_platform`, `native_feature_missing`, `bad_class_name`) is not called again. | `Body._sync` |
| 5 | «ایست» has ONE meaning, whichever way it arrives (section 5). | `Body.emergency_stop` |
| 6 | Nothing leaves the phone: the report and a one-time code are shown in the chat and nowhere else. | `hub_body.py` |
| 7 | The report holds no secret: no chat text, no key, no code, no phone number, no file path, no error text (only error class names). | `brain_hub/selftest.py` |
| 8 | A one-time code that was shown is masked in the stored chat history a few seconds later (section 7). | `hub_body.scrub_codes` |
| 9 | The user switches permissions himself: the SMS permission only through Android's own dialog, started only by «مجوز پیامک را بده»; the settings pages are opened, never changed. | `hub_body._open`, `SmsDoor` |
| 10 | The body's two Java components (the service and the receiver) are private (`exported="false"`), every PendingIntent is immutable, no code is loaded and no program is run. | `AndroidManifest.xml`, `PendingIntentTests`, `SafetyRulesTests` |
| 11 | "Ready" is said only when the phone said so; what could not be read is marked unknown. | `hub_messages_body.py` |

## 3. The parts

| Layer | File | What it does |
| --- | --- | --- |
| Python | `brain_hub/body.py` | `Body`: the job registry (at most `MAX_JOBS = 8`, a name like `ownbrain`), the door calls (`hold` / `release`, one at a time, a progress update at most every `MIN_GAP_SECONDS = 1.5`), `emergency_stop`, and `emergency_stop_all` for every live hub; `describe_ownbrain` turns the own brain's status into the notification's words |
| Python | `brain_hub/selftest.py` | `collect` (the full report data) and `quick` (the permission and background facts only); privacy-safe |
| Python | `brain_hub/service.py` | `live_hubs()`: a copy of the list of hubs of this process (the notification's button has no chat behind it) |
| Python | `platform_boot.py` | `emergency_stop()`: the one thing Java calls; it answers a JSON string `{"ok", "hubs", "stopped", "released"}` and never raises |
| Python | `native_bridge/body.py` | the doors: `BodyDoor` (`hold`, `release`, `running` - the three static methods of `BodyService`), `PhoneDoor` (battery optimisation, app info, memory) and `SmsDoor` (permission, the newest code) |
| Python | `native_bridge/otp.py` | pure functions: `extract_code` finds the one-time code of a message, `redact` hides it |
| Python | `persian_brain/hub_body_commands.py` | the classifier of the body's sentences (a closed cascade over normalised tokens, no table of whole sentences) |
| Python | `persian_brain/hub_body.py` | the chat side: the commands, `after_emergency`, `stop_while_busy`, the masking of codes (`scrub_codes`, `tick`) |
| Python | `persian_brain/hub_messages_body.py` | every sentence the body says |
| Python | `persian_brain/hub_hooks.py`, `persian_brain/brain.py` | the lock-free bypass of «ایست» (`emergency_while_busy`) and its call before the brain's lock is taken |
| Java | `BodyService.java` | the foreground service: `hold`, `release`, `isRunning` (public static, what Python calls) and `stopFromNotification` |
| Java | `StopReceiver.java` | the notification button's receiver: it starts one worker thread that runs `BodyService.stopFromNotification` |
| Java | `LiteRtLmBridge.java` | `cancel()` of the local model's answer (section 5) |
| Java | `MainActivity.java` | announces the feature `body_service` in `NATIVE_FEATURES` |
| Page | `app.js`, `index.html`, `style.css`, `i18n.js` | the stop button: `requestStop`, the swap with «ارسال» while busy (CSS), the word `stop` |
| XML | `AndroidManifest.xml`, `strings.xml` | the service (type `dataSync`, not exported), the receiver (not exported), the permissions of section 8 and six strings |

The Java layer stays thin: five files now (`BodyService.java`, `LiteRtLmBridge.java`, `MainActivity.java`, `PyAccessibilityService.java`, `StopReceiver.java`).

## 4. The life of a background job

1. The user says «بله» to the own brain's download. The own brain tells its notifier (`Body.on_ownbrain`) its status on every change.
2. While the phase is `downloading` or `installing` the body registers the job `ownbrain` with a title, a line of text and a percent (`describe_ownbrain`: while
   downloading the percent, "N of M" and the time left; while installing (stage B3) the install account of the own brain's status - the title, the real percent as a
   determinate bar, "step N of 4: <stage>" and the elapsed time, with `(حدودی)` after the percent when it is an estimate (only the file check is measured; see
   `docs/own_brain_prompt959.md`). A status without that account, or one in the instant before the first step, keeps the old words and the percent -1, so the bar
   moves without a number). While it installs the own brain refreshes the notifier on a heartbeat, so the elapsed time moves; the door still passes an update on
   at most every 1.5 seconds.
3. `Body._sync` calls `BodyDoor.hold` -> `BodyService.hold`, which starts the foreground service (or, when it already runs, only updates its notification: the
   same notification id). One door call at a time, so a late `hold` can never come after a `release`; a progress update of the same job is passed on at most
   every 1.5 seconds, a new or ended job always goes through; more than one job shows «و N کارِ دیگر» after the first job's text.
4. The notification shows the progress bar, the text, a tap that opens the app, and the button «ایست».
5. When the phase leaves `downloading` / `installing` (ready, paused, failed, halted, deleted) the job is dropped and, with the last job, the service goes away.
6. If Android refuses the start (the app is not on the screen) the door answers `not_allowed`; the download goes on exactly as before, without the service.

## 5. «ایست»: one meaning, four ways in

| Way in | Path |
| --- | --- |
| the chat word («ایست»، «بایست»، «توقف کن»، «استاپ») | `hub_hooks.early` -> `hub_brain.early` -> the own brain's extra line -> `hub_body.after_emergency` -> `Body.emergency_stop` |
| an «ایست» request (the stop button of the page below sends one) that arrives while ANOTHER answer of this brain is still being written | `brain.respond` calls `hub_hooks.emergency_while_busy` before it takes the lock: only the exact halt words of at most `MAX_EMERGENCY_CHARS = 60` characters, only while the lock is held by someone else, only what needs no lock (`hub_body.stop_while_busy`) |
| the stop button of the chat page (it takes the place of «ارسال» while an answer is being made) | `requestStop` in `interface/static/app.js` posts «ایست» to the existing `/api/message` on a request of its own; the server (one thread per request) hands it to the bypass above |
| the notification's button | `StopReceiver` -> a worker thread -> `BodyService.stopFromNotification` -> `platform_boot.emergency_stop` -> `emergency_stop_all` for every live hub |

`Body.emergency_stop` stops, in this order, and then releases the service last:

* **download** - the own brain's `halt()`: its sockets are cut at once, what was fetched stays;
* **engine** - `hub.cancel_model_generation()` (never while the own brain installs, see below): the loaded local model's engine is ASKED to drop the answer it makes. The name is "engine" and nothing more is
  claimed: the model manager says how many engines it asked, not whether one was answering. In Java `LiteRtLmBridge.cancel()` sends the request at once and then
  every 200 ms (`CANCEL_REPEAT_MS`) for as long as the same answer goes on, at most 60 seconds (`CANCEL_GIVE_UP_MS`), because one request that arrives a moment
  before the engine has started to generate can be lost; the conversation is never closed while a request is being made on it; a stop that arrives while the
  conversation is being made generates nothing at all;
* **cloud** - the cloud brain is halted only when it was switched on and not halted yet; that stops NEW requests, a request already on its way is not recalled.

**One step is left alone: the install.** While the own brain INSTALLS a finished download (verify, load into the engine, the first test question) nothing can be
interrupted (`docs/own_brain_prompt959.md`), and the first test question is part of that step: asking the engine to drop it would only make the brain's first test
fail. So `Body.emergency_stop` does not ask the engine then (`_installing(brain)`, read AFTER the halt: a download that has just ended is installing by then), leaves the
job and the service as they are (the install goes on, so does its notification) and answers `{"stopped": [...], "released": False, "busy": True}`; the key `busy` is
there only then. The cloud brain is still halted. `emergency_stop_all` adds `"busy": True` when any hub is installing, and `platform_boot.emergency_stop()` then answers
`"ok": false` (the keys of the JSON are the same as ever), so Java keeps the notification and says «ایست انجام نشد؛ برنامه را باز کن و «ایست» را بنویس.». The chat's own reply is the own brain's note
that the install cannot be cut, without the body's lines about the engine and the notification.

The notification's button: Java asks Python and releases the service only when Python answers `"ok": true`. If Python cannot be reached or says no, the
notification stays and says «ایست انجام نشد؛ برنامه را باز کن و «ایست» را بنویس.» - a stop that silently did nothing would be worse than a notification that remains.
A process in which Python was never started has nothing running: Java then answers by itself `{"ok":true,"hubs":0,"stopped":[],"released":false}` (the same keys).

The stop button of the chat page exists because the page sends nothing while an answer is being made (`if (busy) return`: «ارسال» is disabled, Enter does nothing,
what the user typed stays in the message box, and a message is never sent twice), so a typed «ایست» could not leave the page exactly when it matters. While an answer is being made the page shows the red button in place of
«ارسال» (a rule of `style.css` on the form's `aria-busy`); pressing it posts the word `stop` of `i18n.js` (which the brain takes for a halt word; a test pins it) on
a request of its own, once per answer (the button disables itself and a flag guards it), and shows the reply as a message. The first request stays open until its
answer comes back or is cut. Enter never presses it. It was exercised in a real Chromium against the real server, the real brain and a fake engine
(`tests/test_stop_button_prompt959.py`; skipped where Node's Playwright is missing) and never on a phone.

## 6. The self-test report and the access checklist

**«گزارش آزمایشی»** (with «کپی کن»: the report is also put on the clipboard; nothing is sent anywhere, the user decides what to do with it). The data comes
from `selftest.collect` and has nine sections, `SECTIONS = ("app", "phone", "engine", "ownbrain", "network", "permissions", "body", "errors", "models")`:
which build and Android, the RAM and the free storage, whether the app is exempt from Android's battery optimisation and whether power saving is on, which
engine this build has and whether it is the expected one, where the own brain stands, the network state, which permissions are given, what the foreground
service answered, WHICH KINDS of errors were logged (at most `MAX_ERRORS = 8`, each as an operation name and an error class name with a count), and how many
models are registered. Every item is read on its own: a part that cannot be read is marked unknown and the report always comes out.

What is never in it: the chat, a key, a one-time code, a phone number, a file path (every absolute path in free text becomes `<path>`), the text of an error
(a message that does not open with a class name and a colon says only "?"), the query string of a request (`GET /path?query` is cut at the question mark),
the text of any message. Text that another part wrote (the engine's API description) is cut at `MAX_API_CHARS = 1500`. A test plants a key, a Persian secret, a
phone number, a code, paths and a token in every place and asserts that none of them comes out.

The report also says what it cannot see: HyperOS's own «شروع خودکار» and «بدون محدودیت» switches cannot be read by an app.

**«چک‌لیست دسترسی‌ها»** (`selftest.quick`) is the short form: the battery exemption, the notification permission and the SMS permission, with what the user must
switch on himself and where. **«صفحهٔ باتری را باز کن» / «تنظیمات برنامه را باز کن» / «تنظیمات اعلان را باز کن»** open Android's own pages (`battery`, `app`,
`notifications`); nothing is changed by the app.

## 7. One-time codes from text messages

Only on his order («کد پیامک را بخوان»; an optional age such as «۵ دقیقه»: the default window is `DEFAULT_MINUTES = 15`, at most `MAX_MINUTES = 120`), and only
with the `READ_SMS` permission that HE gives through Android's own dialog («مجوز پیامک را بده»; the app never grants anything). A question such as «کد تأیید چیه؟»
or a general sentence such as «رمز وای‌فای را بگو» is never taken for the command.

* **What is read.** `SmsDoor.latest_code` looks at the newest `LOOK_AT = 8` messages, newest first, and stops at the first one older than the window; for the first
  one that holds a code it returns the code, the sender and the age. The text of a message is never returned and never kept.
* **What counts as a code.** `otp.extract_code`: a number of `MIN_DIGITS = 4` to `MAX_DIGITS = 8` digits with a keyword («کد», «رمز», «تایید», «یکبار مصرف»,
  code, otp ...) near it, and never an amount, a balance, a date, a time, a phone number, a tracking or order number or a national-id number. The rule is
  deliberately conservative: a message in a wording it does not know is simply not read (the user can still read it in his messages app). It is not a model.
* **What is shown.** The reply opens with `🔑 کدی که پیدا کردم: ` and the code, then the sender on the next line. It is shown in the chat only.
* **Masking the stored copy.** The chat history is what the chat shows again after a restart, and Android's backup may copy it, so the code and the sender
  are masked in the stored history (`••••••`, `•••)`): by two timers `SCRUB_DELAYS = (4.0, 20.0)` seconds after the reply (the core stores the reply only
  after `respond` returned), AND by a persistent flag `SCRUB_KEY`, so that the start of the next turn masks it even when the app was closed within seconds.
  The mask finds the code again without knowing it (the fixed prefix of the reply), and `secure_delete` is switched on around the UPDATE so the old bytes in
  the database file are overwritten. When the plan cannot even be stored, the reply says that the masking could not be scheduled.
* **What it never does.** Send the code anywhere, use it (no autofill, no bank app is touched; bank apps stay locked), read messages by itself, or ask for the
  permission by itself.

## 8. Honest limits

* **Nothing here ran on a phone.** The service, the notification, its button, the permission dialogs and the settings pages were only exercised against a fake Android
  and the Java was only compiled against the real `android.jar`. The first real test is the user's own phone.
* **The service may be refused.** From Android 12, an app that is not on the screen may not start a foreground service; the door then answers `not_allowed`, the
  job goes on without the service, and nothing crashes. Android 14 needs the type permission (`FOREGROUND_SERVICE_DATA_SYNC`); it is declared.
* **A time limit may apply.** Android 15 limits a data-sync foreground service to about six hours in 24 hours; this is documented for apps that target Android 15,
  this app targets 34, and whether it applies was not checked on a device.
* **HyperOS may still close the app.** A foreground service is a request to Android, not a promise, and the vendor's own settings (autostart, "no restrictions",
  hiding a notification) can override it; the report shows what Android says and cannot see those switches.
* **The SMS permission has an extra door.** On Android 13 and newer an app that was installed by hand (not from a store) must first be allowed under «Allow restricted settings»
  (the app's info page, the menu at the top right) before Android lets the user grant `READ_SMS`; HyperOS's security scanner may also warn about this permission.
* **The stop of a local answer is a request.** `cancelProcess` of the engine may let the engine finish its current step; it was exercised against a stand-in
  engine only. The cloud stop prevents new requests; it does not recall one that is on its way.
* **The install cannot be stopped.** From the end of the download until the first test is over, «ایست» (typed, from the page or from the notification) halts only the cloud
  brain: the install, its first test question and its notification go on, the chat's reply says so, and the notification's button then shows «ایست انجام نشد؛ برنامه را باز کن و «ایست» را بنویس.» (Python answers
  `"ok": false`). That step takes minutes on a phone.
* **The notification exists only while a background job runs.** Its button stops everything that can be stopped, also a local answer that is being made at that moment; but when no job
  runs there is no notification and so no button - the stop button of the chat page is then the way to stop an answer that is being written (the typed word
  cannot be sent from the page while it waits; the lock-free bypass answers the button's request).
* **The stop exchange is stored like any message, in arrival order.** When «ایست» is answered while another answer is still being written, the core writes the word
  and its reply to the chat history as it does for every message, so they stand BEFORE the line of the answer that was cut (a test pins the order). The bypass itself
  takes no lock of the brain and writes nothing to the dialogue module's state (the last topic and the open question), because the turn that owns it is still running.
* **The masking has a window.** Between the reply and the first mask (at most about four seconds, or until the next message if the app was closed first) the stored
  history holds the code.
* **Cache files.** The engine may write cache files beside the model; they are removed with the model's folder.
* **A button that cannot reach Python says so.** If Python cannot be reached or does not confirm, the notification stays and tells the user to write «ایست» in the app.
* **Not built:** an always-on service, a microphone service («هی جارویس»), any wake lock, in-app updates, the Windows body.

## 9. What was not changed

* The seven pinned production files are byte-identical to their baseline: `android_entry.py`, `core/core.py`, `ael/interpreter.py`,
  `runtime_integration/bridge.py`, `interface/server.py`, `runtime_integration/runtime_core.py`, `runtime_growth/runtime_growth_cycle.py`.
* `versionCode 2` and `versionName "0.2.0"` stay literal in `app/build.gradle`; no dependency was added; no new network access; nothing that downloads, runs or
  installs anything by itself.
* Old pins that this piece made out of date were changed consciously, each with its reason written in the test (`# Prompt 959 (stage B; a conscious change of this
  pin, was ...): ...`): `tests/test_android_files_prompt958.py` and `tests/test_persian_mobile_ui_prompt956.py` (the native feature list, the permissions, the second
  service), `tests/test_android_packaging_boundary_prompt815.py` (the permissions, the five thin Java files), `tests/test_docs_own_brain_prompt959.py` (the Java file
  count and the limits that this piece made out of date), `tests/test_litertlm_bridge_jvm_prompt959.py` (the repeated-stop checks).

## 10. Tests

| File | What it proves |
| --- | --- |
| `tests/test_body_prompt959.py` | the `Body` registry and the stop: the notification's words, jobs, door failures, the own brain's notifier, concurrency, the emergency stop (and the install step it leaves alone), the module API, the bypass guard, the line after a stop, the masking plan |
| `tests/test_selftest_prompt959.py` | the report's data and its privacy (planted secrets never come out), the error section, never raising, the checklist's facts |
| `tests/test_body_chat_prompt959.py` | the chat: the commands in context, «ایست» on the normal path and behind a long answer, the code reply and the masking of the stored history, the stop during the install step, closing an open question |
| `tests/test_body_commands_prompt959.py` | the classifier: what is a body command and what is not |
| `tests/test_body_doors_prompt959.py` | the doors against a fake Android: what they call, refuse and report |
| `tests/test_body_service_prompt959.py` | the Java side against the Python side (names, argument counts, limits, JSON keys, manifest, permissions, strings, safety rules), a compile against the real `android.jar` and the compiled public surface |
| `tests/test_litertlm_bridge_jvm_prompt959.py` | the engine bridge against a stand-in engine, including the repeated stop and the closing of the conversation |
| `tests/test_stop_button_prompt959.py` | the page's stop button: the markup, style and script (static), the stop exchange through the real server and its place in the history, and a real-Chromium run of the page with two rounds |
| `tests/browser_stop_driver_prompt959.js` | not a test module: the Node script that drives the page in Chromium for the test above |
| `tests/test_docs_body_prompt959.py` | this document and its Persian guide against the code and the files |
| `tests/body_support_prompt959.py` | support (not a test module): the fake Android of the body doors |
| `tests/jvm_stub_body/` | the three flat stand-in files of the service's JVM run (`BodyServiceMain.java`, `PyObject.java`, `Python.java`) |

The JVM tests need a JDK, and `test_body_service_prompt959.py` also an Android platform jar (`ANDROID_JAR`, or `ANDROID_HOME` / `ANDROID_SDK_ROOT` with
`platforms/android-34`); without them they are skipped and say why. The GitHub runner image normally ships a JDK and an Android SDK, but this was not observed
here: if one of them is missing there, those tests are skipped (not failed) and the count of skipped tests in the log shows it.
