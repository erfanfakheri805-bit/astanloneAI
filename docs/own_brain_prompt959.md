# Prompt 959 (stage B) - the phone's OWN brain («مغز خودکار»)

Scope: the user's decisive request after testing the corrective release - the app must provision **by itself** the language brain it lacks: **no key,
no account, no cost, no other AI service**, completely his own. This document says what that honestly is, what was built, and what no test here
could prove.

**What "an AI language of its own" really is.** A language model reads Persian directly; there is no separate translator in front of it. The model
FILE is the brain. "Free + keyless + his own" therefore means one thing: an **open-weight model file that the app downloads once and runs on the phone**.
It costs storage (1-2.6 GB), memory (RAM), battery and time (CPU-only answers take seconds to minutes), and a model small enough for a phone is not as
clever as the big cloud assistants. There is no reliable free, keyless, cloud option; the optional cloud brain of stage A (`docs/brain_v2_prompt959.md`)
stays what it was: his own key, off by default.

A Persian user guide is in `docs/own_brain_guide_fa_prompt959.md`. Nothing here was run on a real phone or with a real engine: the tests use a fake
engine bridge, a stand-in JVM engine for the Java side and a loopback file server (see section 10).

## 1. The rule of the own brain

| # | condition | where it is enforced |
| --- | --- | --- |
| 1 | nothing is downloaded before an explicit «بله» to a consent card that states the size, the source, the cost and the honest limits | `OwnBrain.start(key, consent=True)` - the argument must be exactly `True`; the chat asks first |
| 2 | the APK must contain the engine AND the engine must have the API the bridge calls, otherwise the download is pointless and is **refused before it starts** | `engine_missing` (a build without `-PwithLiteRtLm=true`; detail `dependency_missing`) or `engine_missing` with detail `api_mismatch` (`LiteRtLmBridge.probe()` found a piece of the engine's API missing, named in the refusal) |
| 3 | the phone must have the RAM and the free space; a fact that cannot be read is never guessed | `ownbrain_catalog.fits`, `ram_unknown`, `not_enough_space` |
| 4 | the phone must be online | `offline` |
| 5 | only the pinned file is accepted: https, the catalogue's hosts only, the exact SHA-256, an announced size near the pinned size | `net_tools.resumable.download_resumable` |
| 6 | "ready" is said only after the model has produced a real answer to a real question | `_pipeline`: download (SHA-256 verified) -> register -> adopt the file into the model store -> `prepare_model` (verify, compatibility, load, smoke test) |
| 7 | the app-wide internet switch («اینترنت را خاموش کن») rules this download like everything else: the gate handed to the downloader says yes only while the job runs AND that switch is on; the yes to the card (which says so) switches it on, nothing else ever does | `OwnBrain.network_on`, the gate in `__init__`, `_allow_internet` (only in `start`, only after the preflight passed), `network_off` / `network_failed` |

Everything the model writes is shown as TEXT. It is never run, never taken as a command, and the engine is given no tools.

## 2. Modules

| Package | Modules | Role |
| --- | --- | --- |
| `brain_hub/` | `ownbrain.py`, `ownbrain_catalog.py`, `ownbrain_state.py` | the service (`OwnBrain`: start / resume / retry / cancel / halt / delete / tick / test, one worker thread), the two-entry catalogue, the phone facts (RAM from `/proc/meminfo`, free space) and the small atomic state file |
| `net_tools/` | `resumable.py` | the resumable, verified download of one big file (partial file, `Range`, checks before the first byte is stored, SHA-256 at the end) and `abort_all()` in `transport.py` (cuts the sockets in flight) |
| `model_runtime/` | `litertlm_runtime.py` (+ the two-lock refactor of `manager.py`) | the `.litertlm` engine runtime with the crash guard; the manager's short registry lock and long operation lock |
| Java | `LiteRtLmBridge.java` | the one small reflection door to the engine library (the Java layer was three thin files here; stage B, the body, made it five: see `body_prompt959.md`) |
| `persian_brain/` | `hub_ownbrain.py`, `hub_ownbrain_commands.py`, `hub_messages_ownbrain.py` | the chat side: the open question, the commands, every Persian sentence |
| existing (small changes) | `brain_hub/llm.py`, `brain_hub/invoker.py`, `persian_brain/hub_hooks.py`, `hub_commands.py`, `hub_messages_self.py`, `hub_messages_llm.py`, `hub_messages_tools.py` | the chat engine path and the deadline, the capability texts, the hooks, the self-knowledge answers; `hub_commands.h_net_off` also stops a running own-brain download (section 4) |
| build | `app/build.gradle`, `.github/workflows/android-debug-apk.yml` | the optional engine flag and the three-rung build ladder (section 7) |

Files on disk (under the hub root): `own_brain/state.json` (plain facts only: which brain, which phase, how many bytes, the last failure code, when
the user agreed; at most 8192 bytes; written atomically; a damaged or foreign file is set aside and the state starts empty - it can never make the
app believe it has a brain it does not have). The unfinished download lives in
`own_brain/<key>-<first 12 hex of the hash>/model.litertlm.partial`; once the SHA-256 matched, the file is registered and moved into the model
registry's own store (and the empty folder goes), where the engine loads it from. Nothing secret is stored.

## 3. The catalogue (data only - `ownbrain_catalog.py`)

| key | model | size | accepted deviation | needs RAM | recommended from |
| --- | --- | --- | --- | --- | --- |
| `strong` | Gemma 4 E2B, `litert-community` (Apache-2.0) | about 2.59 GB (a hint) | 8 % | 4.8 GB | 6.8 GB |
| `light` | Qwen3.5 0.8B int8, `litert-community` (Apache-2.0) | 964,566,992 bytes (exact) | 2 % | 3.0 GB | any phone that fits |

* Both are fetched with one plain request: no login, no click-through licence; only `huggingface.co` / `hf.co` are ever contacted.
* A model needs its size (with the accepted deviation) **plus 400 MB** of free space left over; a half-finished download counts for what it already
  holds. `recommend()` picks the strong brain only on a phone with comfortable memory.
* The SHA-256 is the real guard. The light brain's hash was read from its model page and re-checked during this stage; the strong brain's hash was read
  earlier and **could not be re-checked in this session**. If a hash is wrong the download is refused at the first answer (`remote_changed`) or deleted at
  the end (`hash_mismatch`) and nothing is installed - the cost of a wrong pin is a failed download, never a wrong file.
* Adding a model means adding an entry with a hash read from its page, and a test. Models that need an account or a terms page (Gemma 3, Llama ...) and
  any URL taken from a chat message are deliberately not here.

## 4. The life of a download

Phases: `idle -> downloading -> installing -> ready`, plus `paused` and `failed`. `downloading` includes a `verify` sub-step (hashing 1-3 GB takes minutes);
`installing` is: register the verified file and adopt it into the model store, the compatibility check, load into the engine, first real question.

* **Resume.** The bytes go to `<file>.partial` and stay across attempts, restarts and pauses; each new connection asks `Range: bytes=<have>-` and checks
  that the answer really starts there. A server that ignores `Range` makes it start over - it never appends a whole file to a partial one.
* **Checks before a byte is stored.** Hugging Face's `x-linked-etag` must equal the pinned SHA-256 and `x-linked-size` the announced length; a changed file is
  refused in the first second.
* **Pause / emergency.** «دانلود مغز را متوقف کن» and «ایست» stop only the DOWNLOAD. A pause lets the downloader see the stop for 3 seconds and cuts the
  sockets only if it does not (a worker blocked in a read of a dead connection); the emergency stop cuts them at once (`abort_all`). The partial stays. A
  paused download resumes by «ادامه دانلود مغز»; only one case resumes by itself - the app was closed in the middle - once per service life and only with
  the consent the user gave earlier (and only while the internet switch is still on).
* **The internet switch.** The downloader obeys the app-wide switch like every other network use. The «بله» to the card switches it on when it is off
  (the card says so, and the reply to the yes says it did); a refused start (no engine, too little memory or space, offline, no consent) changes no
  permission. Turning the switch off («اینترنت را خاموش کن») stops a running download **at once** - the chat command tells the service, which cuts the
  sockets - and what was fetched stays (pause code `net_off`); a revoke that does not come through the chat is seen by the downloader between two chunks.
  «ادامه», «تلاش دوباره» and the automatic try after a restart **never switch it on again by themselves**: while it is off they are refused with the
  way forward («اینترنت را روشن کن», then the same command again) - unless the whole file is already on the phone (including a model whose load
  failed but whose file is still in the store): then nothing needs the network and nothing is asked. A download stopped by the switch is not continued
  automatically by a restart; the install step and the first test use no network and are not touched by the switch.
* **The install step cannot be interrupted** (a native model load and a first question take minutes). While it runs, a pause, a delete and «ایست» say so
  plainly, change nothing and remove nothing from under it; the chat itself never waits for it.
* **Delete** asks first (the file, the partial and the state; it reports the space really freed) and is refused while the install runs.
* **Idle unload.** Ten minutes after the last question the engine's memory is given back (what it takes while answering is only an ESTIMATE the card states as such: the
  file size x 1.2 rounded to half a gigabyte - about 3 GB for the strong brain, about 1 GB for the light one; nothing was measured). The next answer loads it again
  (slower), under a 170-second deadline.
* **Crash guard.** A marker `<model>.loading` is written before the engine loads and lifted only after the first real answer. A marker found at the next
  start means the last load never finished: the model is not loaded again by itself (`crashed_before`); the user decides («مغز را دوباره امتحان کن») or
  chooses the lighter brain.
* **Two locks in `ModelManager`.** A short one for the registry (`status`, `list_models`, `is_usable`, `model_path` never wait for a long answer) and a long
  one for load / test / answer / remove (two long things never overlap, and a removal waits instead of pulling the file from under an answer);
  `cancel_all` takes none and `unload(wait=False)` never waits.

## 5. The chat side (`persian_brain/hub_ownbrain*.py`)

Order of the hooks for one message: the emergency words and the cloud brain's open question first (`hub_brain.early`; «ایست» / «ادامه» then also reach the
own brain: `after_emergency`), then the own brain's open question (`hub_ownbrain.early`, which also gives an interrupted download its one automatic
continuation), and among the commands the cloud brain's, then the own brain's, then the older hub commands.

* **One open question at a time**, in its own key (`persian_brain.ownbrain_pending.v1`, 30-minute lifetime, types `consent` and `delete`). The dialogue
  module's closed set of pending types (pinned by older tests) is not widened. A new topic withdraws the question; nothing was started.
* **Commands** (rule-based, no model involved): get the brain («مغز خودت را بگیر» and many spoken variants, also «خودت کارهای لازمت را فراهم کن» -
  the user's own words for the same wish), status, pause, continue, delete, test, try again, and explanations («مغز خودکار چیست؟», «مغز خودت چقدر جا می‌گیرد؟»).
  A sentence is a command only when it NAMES the brain next to an action; «مغز انسان …» is a general question, «مغز ابری …» and a key or an API next to
  the word belong to the cloud brain, and «از مغزت بخواه …» is a request TO a brain (the teacher route).
* **Short phrases without the noun** («دانلود را متوقف کن», «ادامه دانلود», «دوباره امتحان کن», «چقدر مونده؟») are the own brain's only while it has a
  download or a failure they could mean; otherwise the older commands (the hub's model downloads) keep them.
* **The consent card** says what it is, where it comes from, how big, how much RAM and battery, how slow, that it is untested on THIS phone and not as
  clever as ChatGPT; the user may pick the other brain with «سبک» / «قوی» (the question stays open); «چرا؟» is explained and the question stays open.
* **Every number is the service's number**; "ready" is said only after a real answer; a failure names its reason in words and what stays.

## 6. How a free sentence is answered

The chain for a sentence is: the app's rules and skills -> the honest "I cannot do that yet" gap answer -> **`hub_hooks.llm_reply` (the model on the phone,
the own brain included)** -> the user's own cloud brain (only if he switched it on) -> the honest "I do not know" with the way forward. So the own brain
is asked BEFORE any cloud service, and a sentence reaches the cloud only when no model on the phone could answer it. `llm_reply` takes a sentence of
2-1200 characters that is not a bare yes / no and gives it to `brain_hub.llm.LlmBrain`. A chat engine (`.litertlm`) is given the instruction, the last
**3** turns and the new message as separate parts (it applies the model's own chat template); the answer is limited to **256** tokens, under a
**170-second** deadline for the own brain (**100 seconds** for the other engines - the first answer after the app starts has to load the model), cleaned
of stray template tokens and thinking blocks, and shown as text. A busy engine, a timeout and a failure are said plainly; the idle timer restarts after
each answer. «ایست» cancels the download and also ASKS the local engine to drop an answer that is being generated (stage B, the body: `body_prompt959.md`; a
request, not a command: see the honest limits; never during the install step, which cannot be interrupted).

## 7. The build: engine in or out

The engine is native code built INTO the APK; it cannot be added from a running app. `-PwithLiteRtLm=true` adds
`com.google.ai.edge.litertlm:litertlm-android:0.19.1` (pinned: the version the first real build resolved from `latest.release`, so every build is the same build), three `pickFirst` packaging rules for native files plus a `resources { pickFirsts }` rule
for duplicate licence and notice files, **raises `minSdk` from 24 to 26** and disables the AAR-metadata check **only in that variant** (the engine library
may declare a newer compileSdk than the project's 34). The minSdk rise comes from the first real build log (build 19, LiteRT-LM 0.19.1): the dex tool
stopped with `Invoke-customs are only supported starting with Android O (--min-api 26)`, so the engine's code needs Android 8.0 or newer; the plain and the
MediaPipe builds keep minSdk 24. The GitHub workflow tries three rungs in this order and keeps the first that builds:

1. with the LiteRT-LM engine (`with_litertlm`, `continue-on-error`, its log is the `litertlm-build-log` artifact when it fails),
2. with the older MediaPipe engine (`-PwithLlm=true`: only `.task` files can run),
3. plain (the app chats; it cannot run a language-model file).

The release notes state which engine this APK has. **An APK without the LiteRT-LM engine cannot use the downloaded model - and the chat says so BEFORE
downloading** (`engine_missing`). Rung 1 FAILED in the first real build (the `minSdk` message above; everything before the dex step had passed) and
the APK of that build had no engine; the minSdk rise is the fix, and whether rung 1 now builds is known only from the next real build. The ladder exists so
that a failure of rung 1 costs the engine, not the build. `LITERTLM_VERSION` is printed in the release notes so the real version is known.

**The debug signing key.** A debug APK is signed with the key Android's tools create on the runner; a fresh runner makes a fresh key every time, so Android
refused to install a build over the previous one and the user had to uninstall it - which deletes the chats and the downloaded brain (gigabytes). The
workflow therefore restores `~/.android/debug.keystore` from the Actions cache (`actions/cache@v4`, key `debug-keystore-v1`, no `restore-keys`) before the
first rung; the cache action saves the file at the end of a successful job when none was restored. It is Android's own DEBUG key (public by convention),
no secret is read, and the release notes say `Signing key: the SAVED debug key` (install over the old app) or `a NEW debug key` (uninstall once). GitHub may
drop an unused cache after about a week; then one more uninstall is needed. Whether `~/.android` is where the runner's Gradle puts the key was not
verifiable offline: if it is elsewhere, the note says the key could NOT be saved and nothing else changes.

**The pre-download probe.** The bridge reaches the engine by reflection, so an engine whose API differs from what the bridge expects would only show at
load time - after a download of gigabytes. `LiteRtLmBridge.probe()` therefore checks WITHOUT any model file that every piece `load()` and `chat()` call
exists (classes, constructors, methods) and answers `OK\nready` or `ERR\napi_mismatch\n<the first missing piece>`; `LiteRtLmRuntime.availability()` turns
that into `api_mismatch` and the own brain refuses to start (nothing fetched), naming the piece. A probe that cannot be asked never blocks (`load()` then
reports the real failure). `LiteRtLmBridge.api()` lists the engine's real public classes and signatures (class names only, at most 6000 characters) so
that a mismatch can be read off the self-test report instead of guessed. The probe mirrors what the bridge does; it does not prove that the real engine
loads a real model - only a phone can.

**The shape of `EngineConfig`, from the engine's own source.** The engine's `Config.kt` declares `data class EngineConfig(modelPath, backend = Backend.CPU(),
visionBackend = null, audioBackend = null, maxNumTokens = null, maxNumImages = null, cacheDir = null)` WITHOUT `@JvmOverloads` (only `ConversationConfig`,
`ThinkingConfig` and two small sampler classes have it). Java therefore sees ONE public constructor with all seven parameters, plus Kotlin's synthetic
"default values" constructor (an extra `int` mask and a marker). The bridge builds the WIDEST public constructor that starts `(String, Backend)` and has only
object types after that (so the synthetic one is never taken): the path, the CPU back-end, `null` for every optional piece, and the token limit in the first
`Integer` slot (`maxNumTokens`). An older or newer version with fewer or more optional parameters works the same way. The probe goes one step further than
"a constructor exists": it BUILDS that configuration once as a dry run (it is plain data, no model is touched), so an engine that refuses the call is caught
before any download, and the probe names the exception (`EngineConfig(String, Backend): IllegalArgumentException`). `cacheDir` is left `null`: by the
engine's own documentation it then uses the directory of the model file and may put cache files there, which the first run on a phone has to measure.
This reading is of the engine's `main` branch; the pinned release (0.19.1) could differ, which is exactly what the probe and the listing are for.

## 8. Honest limits

* **Nothing ran on a phone.** The engine, its speed, its memory use, its Persian quality and its stability are unmeasured. The first real answer after a
  load is slow; a 2.6 GB model on a phone with 6 GB of RAM may be killed by Android (the crash guard stops a loop; it cannot catch a native crash).
* **The strong brain's hash could not be re-verified** in this session (see section 3); the light brain's was.
* **Hugging Face may need a VPN in Iran.** Python's HTTPS on the phone (the CA store under Chaquopy) was not verified in the field.
* **The download is kept alive by the background service of the body** (stage B, the body: `body_prompt959.md`), which was not run on a phone either: Android may
  refuse to start it from the background (Android 12+). Without the service the download only progresses while the app is open; if Android closes the
  app the download continues from the partial next time.
* **The install and first test cannot be interrupted.** «ایست» now also asks the engine to drop a running answer (stage B, the body); that is a request - the
  engine may finish its current step first - and it was only exercised against a stand-in engine.
* A small model makes mistakes, and its Persian is weaker than a big cloud assistant's; it must not be relied on for medical, legal or financial decisions.
* Storage: 1-2.6 GB. Deleting it («مغز را پاک کن») gives the space back.

## 9. What was NOT changed

The seven production files that earlier stages pinned are byte-identical (`android_entry.py`, `core/core.py`, `ael/interpreter.py`,
`runtime_integration/bridge.py`, `interface/server.py`, `runtime_integration/runtime_core.py`, `runtime_growth/runtime_growth_cycle.py`). The Android manifest
is unchanged (no new permission, no new service in this piece), `versionCode 2` / `versionName "0.2.0"` stay, the Java layer stays thin (three files in this piece; five after the body, stage B),
and the dependencies stay minimal (appcompat, the Kotlin BOM, and - only with the flags - the two engine libraries). Older tests were changed only
consciously, each with the reason written in the test (`# Prompt 959 (a conscious change of this pin, was ...)`).

## 10. Tests

All under `app/src/main/python/tests/`; none touches the real network or a real model.

| file | what it proves |
| --- | --- |
| `test_ownbrain_catalog_prompt959.py` | the two entries (pinned URL host, hash shape, sizes), `fits` / `recommend` with the 400 MB margin and a half download |
| `test_ownbrain_service_prompt959.py` | the service: consent, preflight codes, resume / retry, pause codes, state file, restart, idle unload, delete, the free-space waiver for an installed model |
| `test_ownbrain_commands_prompt959.py` | the classifier: what is and is not an own-brain command, the cloud brain and teacher routes left alone |
| `test_ownbrain_chat_prompt959.py` | the real chat path (`POST /api/message` style) for every step, every reply built from the facts, the one open question |
| `test_ownbrain_threaded_prompt959.py` | a REAL worker thread against a gated loopback server: live status, «ایست», delete in the middle, the chat never waiting |
| `test_ownbrain_install_step_prompt959.py` | the install / first-test step that cannot be interrupted, and the stop commands' effect on the sockets |
| `test_ownbrain_internet_prompt959.py` | the internet switch: the gate, the yes that switches it on (and only a successful start), the refusals that never switch it on, the live download stopped by «اینترنت را خاموش کن» and by a revoke that bypasses the chat |
| `test_net_tools_resumable_prompt959.py`, `test_net_tools_abort_prompt959.py` | the resumable download (Range, checks before the first byte, hash, cancel) and `abort_all` against a silent real socket |
| `test_litertlm_runtime_prompt959.py`, `test_litertlm_bridge_jvm_prompt959.py` | the runtime and the crash guard against a fake bridge; the Java bridge compiled against a stand-in engine (a drifted API is reported, not fatal) |
| `test_model_runtime_locks_prompt959.py` | the two locks, readers and the stop never blocked by an answer, no deadlock under stress |
| `test_docs_own_brain_prompt959.py` | this document and the Persian guide stay true: the numbers are the code's, every sentence the guide tells the user to say is understood by the real classifiers |

Mutation checks were run on the risky parts (the lock design against the old single lock, the stop paths, the resume ordering): the new tests fail
when the protected behaviour is removed.
