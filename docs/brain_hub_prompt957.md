# Prompt 957 - the brain hub, the extension runtime and the first "baby AI" growth loop

Scope: connect what the application already has to ONE honest registry and ONE request path, and let the
installed app add a genuinely new capability from the inside (no rebuild, no Claude, no external AI service),
keep it across restarts, version it, audit it and roll it back. A Persian user guide is in
`docs/baby_ai_guide_fa_prompt957.md`.

Nothing in this delivery is an AI model. The app still understands Persian through the deterministic grammar of
`persian_brain/`; the growth comes from *packages* (written by the user, by ChatGPT or by anyone) that the app
validates, tests, shows and activates only after the user's explicit «بله».

## 1. The one request path

```
WebView (interface/static: index.html, app.js, i18n.js, style.css)
  POST /api/message ----> interface/server.py              (body cap 1,000,000 bytes -> 413)
    RuntimeCore.process_input -> Core.process_input        (InputSystem.normalize: ALL whitespace runs become one space)
      -> skills -> persian_brain.get_brain(memory).respond(text, scope)       scope FULL inside the app
           hub_hooks.early      the answer to the hub's one open question / a pasted `ext.v1` package or model card /
                                 a sentence an INSTALLED extension asks for
           (the existing Persian pipeline: intents, knowledge, memory, Self-Builder, ...)
           hub_hooks.command    hub commands (capability map, extensions, internet, models, Android, extension prompt)
           hub_hooks.gap_reply  "I cannot do that yet": what exists, what exactly is missing, one honest next step
      -> brain_hub.HubService -> invoker.execute -> ext_runtime | net_tools | model_runtime | android_adapters
```

* The seven files pinned by earlier prompts (`android_entry.py`, `core/core.py`, `ael/interpreter.py`,
  `runtime_integration/bridge.py`, `interface/server.py`, `runtime_integration/runtime_core.py`,
  `runtime_growth/runtime_growth_cycle.py`) are byte-identical; the hub is reached only through `persian_brain/brain.py`,
  and only in the `full` scope (inside the application). A bare library `Core` behaves as before.
* A hub that cannot be reached never breaks the conversation: the brain falls back to what it did before.
* Anything that changes something (install, roll back, switch on/off, permission, internet, download) is first
  PROPOSED in the chat and happens only after an explicit yes; the question survives a restart (30-minute lifetime).

## 2. Packages

| Package | Modules | Role |
| --- | --- | --- |
| `brain_hub/` | `graph.py`, `catalog.py`, `gaps.py`, `invoker.py`, `service.py`, `permissions.py`, `audit.py`, `atomic.py`, `builtin_tools.py`, `templates.py` | the capability graph built from the LIVE systems, the honest "cannot yet" catalogue, the single execution choke point, the app-level permission (internet), a hash-chained hub audit log, atomic file helpers, the extension prompt for ChatGPT-like assistants |
| `ext_runtime/` | `manifest.py`, `srcvalidate.py`, `instrument.py`, `guards.py`, `sandbox.py`, `suite.py`, `patterns.py`, `intake.py`, `lifecycle.py`, `calls.py`, `hubstore.py`, `limits.py`, `errors.py` | the `ext.v1` package, static validation, metering, sandbox, acceptance suite, trigger matching, intake, the manager (propose -> approve -> verify -> activate -> invoke -> update -> rollback -> reconcile), storage |
| `net_tools/` | `policy.py`, `transport.py`, `redirects.py`, `fetch.py`, `html_text.py`, `download.py`, `permission.py`, `status.py` | one real, permission-first web read and one verified download |
| `model_runtime/` | `card.py`, `store.py`, `manager.py`, `runtimes.py`, `ngram.py`, `bridge.py` | the model lifecycle (registered -> downloading -> downloaded -> verified -> compatible -> usable) |
| `android_adapters/` | `catalog.py`, `layer.py`, `bridge.py` | what Android features exist, what they need, what is REALLY implemented |
| `persian_brain/` | `hub_state.py`, `hub_intents.py`, `hub_messages.py`, `hub_messages_tools.py`, `hub_commands.py`, `hub_hooks.py` | the Persian conversation with the hub (replies are built only from real results) |

## 3. The capability graph (registry + invoker)

`brain_hub.invoker.build_graph(hub)` asks every live system for its truth and returns one node per capability. A node has
exactly one `state`:

| State | Meaning | Usable |
| --- | --- | --- |
| `active` | registered, enabled, permissions satisfied AND verified with evidence (tests passed, a self-check, or a real reply in this process) | yes |
| `available` | implemented and its pre-conditions hold, but it has no acceptance evidence of its own yet | yes |
| `registered` | known to a registry, not (yet) usable or verified | no |
| `permission_blocked` | implemented, a permission the user has not granted is missing | no |
| `dependency_blocked` | needs something that is not here (a model file, an engine, native code, a connection) | no |
| `pending_approval` | prepared and tested, waiting for the user's explicit yes | no |
| `scaffold_only` | a contract/validator exists in the code, nothing executes it | no |
| `not_implemented` | no implementation exists | no |
| `policy_blocked` | Android or the app's safety policy forbids it | no |
| `broken` | was registered but failed its verification (or a builder could not be read) | no |
| `disabled` | switched off by the user | no |

Every non-usable node carries its exact blockers (`permission`, `dependency`, `model`, `native_code`, `new_apk`, `hardware`, `policy`,
`consequential`, `external_service`, `design`, `approval`, `network`, `test`, `user_input`). Node families: `brain.*` (the connected conversation systems -
`active` only after real replies were served), `tool.web_fetch`, `tool.local_model`, `android.*`, `ext.<id>` and
`ext.<id>.pending`, `model.<id>`, `gap.*` (things the app cannot do yet), `infra.*` (packages that are only contracts/records
in this build, for example `infra.images_audio`, which records image/audio operations and renders nothing).

`invoker.execute(hub, node_id, action, params, user_approved=...)` is the only door: it looks the node up in a FRESH graph,
refuses anything that is not usable right now (naming the blocker), refuses unknown actions, and only then calls the owning
system. Extensions and Self-Builder capabilities enforce their own permissions again inside their managers.
Ask the app: «نقشهٔ قابلیت‌ها را نشان بده».

## 4. The extension runtime: how the installed app gets a genuinely new capability

An extension is **one JSON object** (schema `ext.v1`) that the user pastes into the chat, attaches as a `.json`/`.txt` file
(the attach button) or hands over as a small ZIP (`manifest.json` + optional `ext.py`):

| Key | Rule |
| --- | --- |
| `schema`, `id`, `title`, `description` | `ext.v1`; id `[a-z][a-z0-9_]{2,39}`; title <= 80, description <= 400 characters |
| `inputs` | <= 10; `name`, `type` (`number integer text boolean list_number list_text`), optional `label required default min max max_items` |
| `outputs` | 1-10; `name`, `type` (`number integer text boolean list json`) |
| `source` | <= 64,000 bytes of restricted Python with `def run(<inputs>)` returning a dict whose keys are exactly the outputs |
| `triggers` | 1-12 phrases such as `قسط وام {amount} با سود {annual_percent} درصد و {months} ماه`; a phrase must consume the WHOLE sentence |
| `answer` | the reply template with `{output}` placeholders (<= 300 characters) |
| `tests` | 1-24 cases (`inputs` + `expect`, or `expect_error`); **mandatory**; without a passing suite nothing is ever activated |
| `permissions`, `dependencies` | optional `clock`, `storage`, `network`; the only dependency is `math`; anything else is rejected |
| `examples`, `fixtures`, `provenance`, `version_label`, `entry`, `api` | optional; `entry` must be `run`; unknown keys are errors (a typo never silently drops a permission) |

The whole package is <= 200,000 bytes.

**Lifecycle** (every stage returns evidence; a failed stage stops the pipeline and nothing becomes active):

1. *Package intake* - size, JSON/ZIP shape, entry names, hashes. 2. *Manifest* - strict structure and types.
3. *Source rules* - an ALLOWLIST over the syntax tree (no classes, no imports except `math`, no names or attributes starting with an
underscore, no `open/eval/exec/getattr/type`, no generators, `global`, `with`, `del`, `assert`, decorators, `str.format`).
4. *Consistency* - the code uses exactly the declared permissions and dependencies. 5. *Acceptance tests* - every case runs TWICE in
fresh sandboxes against fixtures (fixed clock, in-memory storage, canned web pages); the two runs must agree. An endless loop
is rejected here ("fuel: work budget exhausted").
6. *Proposal* - the user sees title, inputs/outputs, requested permissions, test result and the code's SHA-256 and is asked.
Nothing is installed or active; the proposal lives 7 days. 7. *Approval* («بله») - the version files are written atomically
(`modules/<id>_v<N>.py`, `manifests/<id>_v<N>.json`, never overwritten), the registry row and the permission grants are
recorded, then the installed version is **verified from disk** (hashes, re-validation, re-compilation, the tests again). A version
that fails verification is never left active. 8. *Invocation* - a normal sentence matches a trigger, the inputs are typed and
range-checked, the files' hashes and the permission grants are re-checked, and the code runs in the sandbox.
9. *Update* - a changed package for an existing id becomes version N+1; the previous version is kept. 10. *Rollback* - switches the
active version back after verifying the target; versions are never deleted. 11. *Recovery* at every start: partial writes swept,
orphan files quarantined (never executed), every active version re-verified (falling back to the newest healthy older one),
stale proposals expired, the audit hash chain checked.

**Sandbox, honestly.** The code is validated against the allowlist, instrumented (every loop step, call and
size-growing operation is metered), compiled and run with `__builtins__ = {}` in a fresh module per call, under a work budget
(250,000 steps) and a wall-clock budget (2 s) that the guards check cooperatively. There is no `eval`/`exec` of user text anywhere
in the production code (the code object is run through importlib's loader). This is a *language-level* sandbox inside the app's own
Python process, not an operating-system boundary; that is why the subset is so small, why every new executable extension needs the user's
explicit approval, and why extensions have no file, process, camera, microphone or phone access at all.

**The whitespace pitfall (found by the acceptance tests).** `Core` folds every run of whitespace in a message into ONE space
before anything reads it, which destroys space-based Python indentation inside a pasted package. Three measures, none of which
guesses or repairs code: the page (`i18n.js: protectPackage`) rewrites a package that is about to be sent so that every run of spaces is a
JSON ` ` escape (the JSON means exactly the same); the prompt for assistants (`brain_hub/templates.py`) tells authors to
indent with a tab (`\t` in JSON); and a rejection whose syntax error mentions indentation says why. A package typed by hand with
space indentation therefore needs the page (or tabs) - which is also the honest answer when it is rejected.

## 5. Web, models and Android - what is real

**Web (`net_tools/`).** Off by default. «اینترنت را روشن کن» asks first and records the user's grant atomically; «اینترنت را خاموش کن»
revokes at once (the gate reads the live grant on every request). A read is one GET with: https only (plain http exists only as an explicit policy switch the app never turns on), no user-info, strict URL
parsing, refusal of every non-public address (loopback, private, link-local, metadata, carrier-grade NAT, numeric IPv4 spellings,
IPv4-mapped IPv6 ...) on the resolved AND the connected peer address, certificate and host-name verification, one wall-clock deadline
(default 8 s), at most 262,144 bytes, no compressed bodies, at most 3 redirects each re-validated, a content-type allowlist
(`text/html text/plain application/json application/xml text/xml application/xhtml+xml text/markdown text/csv`) and HTML reduced to
readable text. Offline, blocked or failing, it says exactly why (a stable code plus a Persian message); chat and memory never need it.
The audit line keeps the host and path only, never a query string.

**Models (`model_runtime/`).** A model is described by a card (`model_id, title, version, format, source_url, sha256, size_bytes, license`,
formats `ngram-json gguf onnx tflite`, <= 8 GiB, https source). Registering downloads nothing. Download needs the user's explicit yes,
the internet permission, an accepted licence (permissive ones pass; ones that need review - CC-BY-SA, GPL, OpenRAIL, Llama, Gemma ... - need your explicit
acknowledgement; restricted and unknown ones are refused), enough free space and a matching SHA-256; a mismatch moves the file to `.rejected/`. A file becomes **usable** only after size + hash,
licence/format, a runtime that REALLY loaded it and a REAL inference smoke test; after a restart a persisted "usable" is trusted
only while the file's size and mtime are unchanged. Engines: `ngram-json` (a small statistical n-gram model - real, deterministic, offline, but
NOT a language model; the trainer exists in the code, no chat command trains one yet) and `gguf` through `llama_cpp` **only if that package is really installed** (it is not in this APK, so a GGUF model
is reported `dependency_blocked` with the exact reason); `onnx`/`tflite` have no engine. Honest limit: the chat does not yet generate
text through a downloaded model; it is reachable through `hub.ask_model` and the invoker's `generate` action.

**Android (`android_adapters/`).** Nine features are described with their permission, API level and native requirement: file picker,
microphone, camera, notifications, system settings, phone calls, network state, battery, clipboard. Only `network_state.read` has an
implemented action; the rest are permission-checked descriptions, never "working". A permission dialog is requested only on explicit
approval, only for a feature that has an implemented action, and only if this APK has the native hook (`MainActivity.NATIVE_FEATURES`,
`requestAndroidPermissions`); the answer is observed later, never assumed. Everything is `verified_on_device = False`: the Chaquopy calls
follow the documented APIs but were exercised against hand-written fakes only. The page's attach button needs the new
`MainActivity.onShowFileChooser` (a new APK); an older APK simply has no file chooser. The manifest still declares only `INTERNET`
(a frozen Prompt-956 test pins that), so the real network-state probe reports "unknown" until `ACCESS_NETWORK_STATE` is added together with
an update of that test.

## 6. Chat commands (Persian)

| Say | What happens |
| --- | --- |
| «چطور افزونه اضافه کنم؟» | the four-step recipe and the honest limits |
| «پرامپت افزونه برای …» | the ready-made request for any assistant (embeds your wish and the live rules, with a valid example) |
| paste / attach an `ext.v1` package | validated, tested, shown with its permissions; **nothing is installed yet** |
| «بله» / «نه» | installs and verifies / declines the open proposal (any other message withdraws the question) |
| «افزونه‌ها را لیست کن» · «تاریخچهٔ افزونه‌ها» | what is installed (state, version, tests) / the audited history |
| «افزونه را غیرفعال کن» · «افزونه را فعال کن» · «افزونهٔ … را برگردان» | switch off (asks) / on (asks) / previous version (asks) |
| «نقشهٔ قابلیت‌ها را نشان بده» | the live capability map with counts per state |
| «اینترنت را روشن کن» · «اینترنت را خاموش کن» · «وضعیت اینترنت» | ask-then-grant / revoke at once / the real state |
| «صفحهٔ https://… را بخوان» | one permission-gated read |
| «مدل‌ها را نشان بده» · «مدل X را دانلود کن» | registered models and engines / approval-gated download |
| «وضعیت اندروید را بگو» | each Android feature's exact state |
| «برام یک ویدیو بساز» (and similar wishes) | the exact missing piece, never a promise |

## 7. Security boundaries

* **Least privilege, explicit approval.** Internet, installing or updating an extension, rolling back, switching on, an extension's
  permissions, downloading a model and Android permission dialogs all need an exact `True` from the chat layer, which passes it only after
  the user's «بله». Reading and restricting (list, history, status, internet OFF, extension permission OFF) happen at once.
* **Never** silently installs an APK, runs a shell command, grants itself an Android permission, evaluates user text, runs
  downloaded code outside the extension sandbox, calls an external AI service or needs an API key. No secret or signing key is in the tree.
* **Validated input.** Extension ids, names, paths in ZIPs (no `..`, absolute paths, symlinks, odd characters), entry names, sizes, hashes,
  input/output types and ranges, dependency names (`math` only), trigger patterns, URLs, model-card fields and file names in the `inbox/` folder
  (a plain file name, never a path) are checked before use; a damaged state file is set aside and the app fails closed.
* **Atomic writes** everywhere (temp file in the same directory -> fsync -> `os.replace`); version files are never overwritten (a stale file with the
  same name is quarantined first); the registry is a SQLite database (synchronous=FULL) with numbered migrations.
* **Audit.** Extensions: a hash-chained history in `hub.db` (proposed, approved, activated, declined, rejected, rolled back, disabled, auto-rollback ...).
  Hub: `hub_audit.jsonl`, also hash-chained (permissions, web reads as host + path only, model approvals/downloads, Android requests, recoveries).
  The chat shows both in Persian («تاریخچهٔ افزونه‌ها»).

## 8. Where things are stored (app-private, next to the app's `memory.db`)

```
<app files dir>/.../brain_hub/
    permissions.json          the user's internet grant
    hub_audit.jsonl           hub-level, hash-chained history (rotates at 1,000,000 bytes)
    extensions/               hub.db (+ hub.lock), modules/<id>_v<N>.py, manifests/<id>_v<N>.json, quarantine/
    models/                   registry.json, files/<model_id>/<version>/model.bin, .rejected/
    inbox/                    where a model file may be placed to import it
```

Nothing is created until something needs to be written. The hub's one open question and the last unsupported wish are kept in the app's
key-value store (`persian_brain.hub_pending.v1` 30 minutes, `persian_brain.hub_wish.v1` 24 hours), validated on every load.

## 9. Tests

All under `app/src/main/python/tests/`, plain `unittest`, standard library only (the browser tests additionally use Playwright + Chromium and are
skipped when those are not installed; the Node helper tests are skipped without Node). Run from `app/src/main/python`:

```
python -m unittest discover -s tests -p "*_prompt957.py" -t .
```

| Files | Covers |
| --- | --- |
| `test_ext_runtime_manifest_prompt957.py`, `test_ext_runtime_sandbox_prompt957.py`, `test_ext_runtime_lifecycle_prompt957.py` | manifest validation, the source allowlist with malicious samples, metering and limits, the manager's propose/approve/verify/activate/update/rollback/reconcile, interrupted writes, tampering |
| `test_brain_hub_core_prompt957.py`, `test_brain_hub_service_prompt957.py`, `test_brain_hub_invoker_prompt957.py`, `test_brain_hub_models_invoker_prompt957.py`, `test_brain_hub_tools_prompt957.py`, `test_brain_hub_templates_prompt957.py` | graph states and evidence, gaps, permissions, audit chain, service recovery, the invoker choke point, the prompt template (its example is installed by the real manager) |
| `test_net_tools_policy_prompt957.py`, `..._transport_...`, `..._fetch_...`, `..._download_...` | URL/IP classification, raw-socket transport against local servers, redirects, content types, size and time limits, verified downloads |
| `test_model_runtime_core_prompt957.py`, `test_model_runtime_manager_prompt957.py` | model cards, registry, the state machine, hash/size mismatch, licence policy, interrupted downloads, smoke test, restart trust |
| `test_android_adapters_prompt957.py` | the feature catalog, status derivation for every feature, permission dispatch rules, a misbehaving bridge |
| `test_persian_hub_state_intents_prompt957.py`, `..._extensions_...`, `..._extension_state_...`, `..._tools_...` | the Persian grammar of the hub commands, the open question and its lifetime, whole extension conversations, tools in chat |
| `test_persian_hub_ui_prompt957.py` | the page: attach button, shortened display, package protection (Node helper tests, the real route and Chromium), starter chips, phone sizes |
| `test_baby_ai_acceptance_prompt957.py` | **the acceptance suite**, driven only through the real front door (HTTP `POST /api/message` -> Core -> brain -> hub), plus a real `android_entry.start()` process killed and restarted on the same folder |
| `test_docs_prompt957.py` | this document and the Persian guide still match the code (files, counts, limits, commands, the example package) |

Acceptance items of the prompt and where they are proven (`test_baby_ai_acceptance_prompt957.py`): 1 `A01FreshStart`; 2 `A02Registry`; 3 `A03NewCapability`
(a loan-instalment capability that is none of the built-in archetypes and not the prompt's example); 4 `A04Restart` and `A12RealEntryPoint`; 5 `A05Rejected`
(malicious source, endless loop, wrong hashes, oversize and other-version packages, invalid manifests, the 413 cap); 6 `A06UpdateRollback`;
7 `A07Unsupported`; 8 `A08Models`; 9 `A09Offline`; the whitespace finding `A10CodeSurvivesTheChat`. Item 10 is the full regression
(see the delivery report). Item 11 (the Android build, install and launch) could not be run in the environment this was produced in.

## 10. Audit - what was fixed and what is still blocked

**Found by reading the code and tracing real Persian messages through `Core.process_input` (not from module names):**

* Six areas run on the normal chat path (the `brain.*` nodes). Eleven packages (the `infra.*` nodes) are contracts, registries and planners that
  nothing in the chat path calls; their "executors" are boundaries without an implementation. They are now listed as `scaffold_only`/`not_implemented`
  nodes instead of being implied to work.
* The Self-Builder grows only three archetypes. The extension runtime adds a general, validated contract (Section 4) without touching it.
* There was no way to hand code, text or a file to the app from the page. The chat, the attach button and a ZIP/JSON intake now exist.
* Web retrieval and network status were placeholders (`NOT_IMPLEMENTED`, a constant). `net_tools` is a real, permission-first read; the network
  status is "unknown" without evidence and never invented. The legacy platform adapter's constant is untouched (frozen code).
* The local-model chain had no usable path. `model_runtime` adds the honest lifecycle and an always-available n-gram engine.
* Android features had no adapter layer. `android_adapters` adds one; only `network_state.read` is implemented.
* Defect found by the acceptance tests: whitespace folding broke space-indented code in pasted packages (Section 4).

**Blocked by genuine Android / device / runtime constraints (reported by the app itself when asked):**

| Wish | Exact missing piece |
| --- | --- |
| a real language model in chat; writing extension code by itself | a model plus a native engine (llama.cpp) that is not in this APK; chat generation through a downloaded model is not wired yet |
| images, video, anime/manga, music/sound, 3D | a model and an engine per medium (heavy for a phone); the image/audio operation records and the `game_creation` package are records only |
| voice, "Jarvis" wake word, speaker identification | `RECORD_AUDIO` is not declared; a foreground service (Java), speech and speaker models: a new APK first |
| camera vision | `CAMERA` not declared, native code and a vision model |
| phone calls | Android gives ordinary apps no call audio; telephony permissions not declared; default-dialer/call-screening role |
| phone settings, unlocking | `WRITE_SETTINGS` is a special permission the user grants by hand; unlocking is forbidden by Android |
| other apps (Telegram, Instagram ...), social auto-replies and posting | an Accessibility service or each service's official API and tokens, explicit approval per action, background work |
| idle background gathering | WorkManager/foreground service (Java) and the "no external AI" rule for ChatGPT/YouTube sources |
| earning money, crypto, cash-out | irreversible and consequential; needs a separate reviewed design, accounts and private keys that must never live in the app |
| changing the app's own UI from chat | the UI is static files inside the APK; a customization hook needs a new APK |
| a Windows "second body" | not designed |
| extensions using files, hardware, the phone | extensions are pure Python by design; anything with Java/native code needs a new APK (the app never builds or installs an APK) |
| network state on a real APK | `ACCESS_NETWORK_STATE` is not declared (a frozen test pins the manifest) |

**Not verified in the environment this was built in:** the Gradle build and the APK (no Android SDK, downloads blocked), installing and launching it, anything
on a real device (the WebView file chooser, permission dialogs, Chaquopy `java` calls), signing. The Java change (`MainActivity.java`) was compiled with `javac`
against hand-written stubs of the Android classes, not against the real SDK. The first run of the repository's GitHub workflow is the real build check.

## 11. Limitations (honest list)

* An extension is a small pure function (computation, optional clock, a small key-value store, optional page text). It is not a program and not an AI.
* The sandbox is a language-level one inside the app's process; the work and time budgets are checked cooperatively.
* Trigger phrases must cover the whole sentence, so a paraphrase the author did not list is not recognised (add more triggers or examples).
* Space-indented code needs the page's protection or tabs (Section 4).
* The Persian understanding is a closed grammar, not a model; unrecognised sentences get an honest "I did not understand" or a clarification.
* The graph is rebuilt from the live systems on request; its counts are a snapshot and change as the app is used.

