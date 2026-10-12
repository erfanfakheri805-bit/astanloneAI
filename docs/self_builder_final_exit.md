# FINAL-EXIT-001 - the controlled Self-Builder and the Persian conversation brain

This document describes what was added for prompt FINAL-EXIT-001, how it is wired into the
existing application, what it guarantees, how to run its tests - and, just as important, what it
is **not**.

## 1. What it is, and what it is not

The application can now add a *supported* capability to itself, from an ordinary Persian
request, without a developer and without any external AI service:

```
user request -> analyze -> check capabilities -> identify gap -> change plan
             -> generate (allowed files only) -> validate -> test
             -> [analyze failure -> safe repair -> retest]
             -> checkpoint -> apply -> persist -> register -> version -> audit
```

The capability is persisted, versioned, reversible, and is still there (and usable) after the
application is killed and started again.

"Supported" has a precise meaning: **a reviewed template archetype exists for it**
(`self_builder/policy.py: SUPPORTED_ARCHETYPES`):

| Archetype | Example request | What is generated |
| --- | --- | --- |
| `unit_conversion` | «یک مبدل کیلومتر به مایل بساز» | `value * scale + shift`, factor taken from the unit table or stated by the user («هر ۱ فوت برابر ۳۰٫۴۸ سانتی‌متر است») |
| `formula` | «فرمول مساحت دایره را یاد بگیر: pi * r ** 2» | an arithmetic expression over named numeric variables |
| `text_tool` | «ابزاری بساز که تعداد کلمات متن را بشمارد» | a chain (at most 3) of the reviewed text operations in `textops.py` |

What it is **not**:

* It is not a code-generating model. Modules are instantiated from fixed templates out of a
  validated spec. A request outside the three archetypes is answered honestly
  («نمی‌توانم این را خودم بسازم …») and never guessed at.
* It is not "Jarvis" and not a general AI. It does not control the device, the network, files
  outside its own directory, or other applications. The only permission a capability can have is
  `compute` (pure computation over numbers or text).
* It does not use Claude, OpenAI or any other external AI, API key or network access - at build
  time or at run time.

## 2. What the user can do (all in Persian)

| Intent | Example |
| --- | --- |
| Ask for a missing capability | «من یک قابلیت جدید نیاز دارم» -> the brain asks which kind; «تبدیل کیلومتر به مایل» builds it |
| Build directly | «یک ماشین حساب BMI بساز: وزن / (قد * قد)» |
| Use what was built | «۱۰ کیلومتر چند مایل است؟»، «تعداد کلمات را بشمار: سلام دنیای زیبا»، «BMI را حساب کن» |
| Inspect | «چه کارهایی بلدی؟»، «جزئیات تبدیل کیلومتر به مایل»، «وضعیت قابلیت‌ها»، «تاریخچه ساخت قابلیت‌ها» |
| Improve | the same request with another factor («… که هر ۱ کیلومتر برابر ۰٫۶ مایل است») -> asks for confirmation, then creates version 2 |
| Go back | «برگرد به نسخهٔ قبلی» does it at once; after «جواب غلط بود» the brain offers it and «بله» really does it |
| Switch off | «قابلیت تبدیل کیلومتر به مایل را خاموش کن» (files and versions are kept) |
| AEL | `UPGRADE word_counter IS ابزاری بساز که تعداد کلمات متن را بشمارد` reaches the same builder; legacy upgrades such as `UPGRADE faster_matching IS improve the matching speed` behave exactly as before |

When a user asks for something the registry does not have, the answer is the honest one: «این
قابلیت را فعلاً ندارم … بسازمش؟ (بله / نه)». When the registry exists but cannot be read, the
brain says it is *unavailable* rather than claiming the capability does not exist.

## 3. Package `self_builder/` (24 modules)

| Module | Role |
| --- | --- |
| `policy.py`, `errors.py` | allowlists (archetypes, permissions, operations, directories, file-name patterns, suffixes) and every resource limit; stable error codes |
| `fa_text.py`, `mathcore.py`, `expr.py`, `units.py`, `textops.py`, `helpers.py` | Persian text helpers; total math primitives; the closed expression language with its own tokenizer and parser (**no** `eval`/`compile` of user text); the unit table (exact rational factors); the reviewed text operations; the only names generated code may call |
| `spec.py`, `templates.py` | capability spec (JSON, never executed) and the template instantiation that turns it into one module plus a JSON test suite whose expected values come from an *independent* reference path (exact `Fraction` arithmetic, the tree evaluator, the reviewed text operations) - a real differential test |
| `validator.py`, `sandbox.py` | AST allowlist (no imports, attributes, loops, comprehensions, lambdas, conditionals, `__`-names ...); loader that reads the bytes once, hash-checks, validates and runs *those* bytes in a namespace whose `__builtins__` is empty |
| `workspace.py`, `lock.py`, `store.py`, `registry.py`, `loader.py` | the only place files are touched (atomic writes, `Policy.resolve()` on every path); the crash-proof SQLite workspace lock; the SQLite store with numbered migrations; the persistent registry; integrity verification, manifest and start-up reconciliation |
| `request_parser.py`, `matcher.py`, `repair.py` | Persian request analysis (fixed grammar over closed word lists); invocation matching derived from the capability records themselves; failure classification and bounded safe repair |
| `builder.py`, `mirror.py`, `service.py` | the build/rollback/disable pipeline; mirroring into the legacy `capabilities` / `upgrades` / `versions` tables of `memory.db`; the one facade the application talks to |

### Stages (stable names, recorded in order on every build)

`request, analyze, spec, check_capabilities, identify_gap, plan, generate, validate, test,
[analyze_failure, repair, retest], checkpoint, apply, persist, register, version, audit`

Build statuses: `applied`, `noop_identical` (exactly this capability already exists),
`needs_confirmation` (a "guess" repair or a deviating user factor needs a yes), `failed`.
Version statuses: `active`, `superseded`, `rolled_back`, `broken`.

### Safe repair

Failures are classified by their stable code and mapped to a small fixed list of repairs
(operator normalisation `× ÷ ^`, word operators «ضرب در», identifier mapping of Persian variable
names, implicit multiplication ...). *Safe* repairs are applied automatically (at most
`MAX_REPAIR_ATTEMPTS = 6`, every attempt logged); a repair that changes the meaning is a *guess*
and always needs the user's confirmation or a verifying example. Names are never silently
turned into products (`log(x)` stays a call).

## 4. Security boundaries

* **Where it can write:** one root, `<directory of memory.db>/self_builder` - on Android
  `files_dir/data/self_builder`. The application's own source tree (the APK's python assets) is
  never written to; a test fingerprints the tree before and after the whole scenario.
* **What it can create:** only the file patterns of `policy.py` (`modules/<id>_v<n>.py`,
  `tests/<id>_v<n>.json`, `specs/<id>_v<n>.json`, `checkpoints/ck_<n>.json`, `staging/stg_*`,
  `quarantine/q_*`, plus `manifest.json`, `self_builder.db`, `self_builder.lock`). Separators, `..`
  and symlinks are refused.
* **What generated code can do:** call the pure helpers of `helpers.py` and nothing else. The
  validator guarantees the shape (two functions, one `return` each); the sandbox runs it with an
  empty `__builtins__`, never registers it in `sys.modules`, never reads or writes bytecode
  caches, and enforces a soft per-call time budget and finite, size-checked results. Generated
  modules are executed through the standard import machinery only after steps 1-3 of
  `sandbox.py`; user text is never given to `eval`/`exec`/`compile`.
* **Limits (`policy.py`):** source 12,000 bytes, tests 40,000 bytes, expression 240 characters /
  160 nodes / depth 24, 8 variables, 48 test cases, 200 capabilities, 60 versions per capability,
  request 2,000 characters, 4,000 characters of text input per call, 0.5 s per call.
  Variable names must start with a letter (a leading underscore, e.g. `__builtins__`, is
  rejected by the tokenizer).
* **Audit:** every run has an `upgrade_log` row and hash-chained `audit_log` events; the chain is
  re-verified at start-up and by the status command.
* **No network, no subprocess, no external AI:** the Claude Exit audit test runs the real
  application in subprocesses under an audit hook (`sys.addaudithook`) that records every
  connection or name resolution to a non-loopback host and every `subprocess.Popen`,
  `os.system`, `os.posix_spawn`, `os.fork`, `os.exec` and `ctypes.dlopen`, and asserts that
  nothing was recorded during the whole scenario.

## 5. Persistence, restart and integrity

`self_builder.db` (SQLite, numbered migrations) holds `capabilities`, `capability_versions`
(nothing is ever overwritten), `upgrade_log`, `checkpoints`, `audit_log`, `usage`, `feedback`
and `meta`. Nothing the registry answers from is cached in memory.

On the first use after a start (once per process, under the workspace lock) `loader.reconcile()`:

1. marks unfinished upgrades `interrupted` and settles unfinished checkpoints;
2. verifies every **active** version: files present, SHA-256 equal to the registry, spec valid,
   AST allowlist passed, its own stored test suite passing;
3. marks a failing version `broken`, quarantines (never deletes) the file and re-activates the
   newest healthy older version - or disables the capability when none is healthy;
4. quarantines unregistered files left by a crash and clears staging;
5. re-verifies the audit chain and rewrites `manifest.json`.

The workspace lock is an exclusive transaction on a tiny SQLite file: it works between threads,
services and processes and is released by the operating system when the holder dies, so an app
killed in the middle of a build can never leave it locked.

The service is **lazy**: ordinary conversation never creates anything on disk; only `build()` does.

## 6. Versioning and rollback

* Every build that changes behaviour creates a new version with its own module/test/spec files.
* A checkpoint (previous version, file list, hashes) is recorded **before** anything is promoted.
* If validation or tests fail the failed version is never activated, staged files are removed and
  the failure is logged - the previous version keeps serving.
* `rollback()` restores the newest healthy older version (or an explicit one). It is reached from
  the chat («برگرد به نسخهٔ قبلی», or a yes to the offer that follows negative feedback) and from AEL
  (`ROLLBACK <version_id>` on a `versions` row that the Self-Builder produced). The target is
  re-verified (hashes, validation, its own tests) before it is re-activated, and the rollback
  survives a restart. No version is ever deleted, so history stays complete.

## 7. How it is wired into the existing application

Nothing in the seven hash-pinned files of the Prompt 954/955 gates was changed
(`android_entry.py`, `core/core.py`, `ael/interpreter.py`, `runtime_integration/bridge.py`,
`interface/server.py`, `runtime_integration/runtime_core.py`,
`runtime_growth/runtime_growth_cycle.py`). Three existing, unpinned modules got small,
defensive hooks:

| File | Change |
| --- | --- |
| `skills/skill_system.py` | `find_matching_skill()` first asks `persian_brain.dynamic_skill(memory, text)` (new `_dynamic_skill` method, any exception -> `None`). This is the single seam between the conversation and the brain. |
| `self_upgrade/upgrade_system.py` | `propose_upgrade()` first calls `_propose_self_built()`: only for a payload-less AEL `UPGRADE` whose description is a complete, supported build request does it run the Self-Builder; on any other input or any problem it returns `None` and the legacy lifecycle runs unchanged. |
| `self_upgrade/version_system.py` | a version row produced by the Self-Builder carries its coordinates; `rollback_to()` restores it through `service.rollback()` (and returns `None` when it cannot really restore, so a rollback that did not happen is never reported). Legacy rows - such as the `0.1.0-foundation` marker - are untouched and keep their old meaning: `ROLLBACK <id>` on them only moves the marker and changes no capability. |

The path from the APK is the existing one: Android UI -> WebView -> local HTTP server
(`/api/message`, `/api/status`) started by `android_entry.start(files_dir)` -> `RuntimeCore` ->
`Core._handle_conversation()` -> `SkillSystem` -> `persian_brain` -> `self_builder.service` ->
`files_dir/data/self_builder` + `memory.db`. The audit test drives exactly this entry point in real
subprocesses (SIGKILL between them).

## 8. Package `persian_brain/` (8 modules)

A deterministic, state-aware Persian conversation layer: normalization (Unicode, Arabic/Persian
letters, ZWNJ vs space, digit styles, punctuation, elongation) -> intent classification
(`GREETING, QUESTION, REQUEST, COMMAND, STATEMENT, TEACHING, CONTINUATION, REFERENCE, FEEDBACK,
UNKNOWN`) -> handlers that talk to the real systems (memory, knowledge, the capability registry,
the dialogue state) -> replies built from fixed templates and the facts at hand.

* There is no sentence -> answer table; a test scans the package's AST for giant literal tables.
* Dialogue state (the one open question, the last result) is persisted in `memory.db`
  (`persian_brain.dialogue.v1`, with a TTL), so a question asked before the app was killed can
  still be answered afterwards; damaged state is validated and discarded.
* Personal facts («من عرفان هستم») and English input are left to the existing pipeline: the brain
  returns `None` for anything it cannot really handle.
* Activation (`persian_brain/activation.py`): scope `full` inside the application (any platform
  adapter other than the plain desktop one, i.e. after `android_entry.start()`), or with
  `STANDALONE_AI_PERSIAN_BRAIN=1`; scope `capabilities` for a plain library `Core` (only the
  capability domain is claimed, so the older frozen tests that pin the legacy greeting replies
  keep passing); `STANDALONE_AI_PERSIAN_BRAIN=0` switches it off.

## 9. Tests

All under `app/src/main/python/tests/`, plain `unittest`, standard library only; run from
`app/src/main/python`:

```
python -m unittest tests.test_self_builder_foundations_final_exit001 \
                   tests.test_self_builder_pipeline_final_exit001 \
                   tests.test_persian_brain_final_exit001 \
                   tests.test_self_builder_legacy_bridges_final_exit001 \
                   tests.test_claude_exit_audit_final_exit001
```

| File | Covers |
| --- | --- |
| `test_self_builder_foundations_final_exit001.py` | policy, errors, Persian text helpers, math, expression engine (precedence, errors, hostile input), units (every pair round-trips, physical constants), text operations, helpers, specs, templates (differential tests), AST validator (malicious samples), sandbox |
| `test_self_builder_pipeline_final_exit001.py` | request parser (80+ phrasings), repair, matcher, store/migrations, workspace, the build pipeline, injected failures at every stage, reconciliation (stray files, tampering, crash leftovers), service, memory mirror, persistence across real processes, the workspace lock, concurrent threads/services/processes |
| `test_persian_brain_final_exit001.py` | normalization, lexicon, a 200+ row intent table incl. negative cases, dialogue state, activation scopes, whole conversations (build, clarify, confirm, use, improve, roll back, disable), restart, robustness, the Core seam, no side effects, no reply table |
| `test_self_builder_legacy_bridges_final_exit001.py` | the three small hooks in older files, driven in-process through the real `Core`: AEL `UPGRADE` (built for real and mirrored into `upgrades` / `versions` / `capabilities`; confirmation, failure, no-op, mirror failure, any internal error -> the old lifecycle; nothing created on disk otherwise), AEL `ROLLBACK <id>` (restores for real, verified again; a rollback that could not be performed is never reported; legacy marker rows unchanged), and the defensive skill seam |
| `test_claude_exit_audit_final_exit001.py` | **the Claude Exit audit**: the real `android_entry` in three subprocesses with SIGKILLs between them - missing capability -> understood -> built -> validated -> tested -> applied -> registered -> versioned -> still there and usable after restart; improvement, rollback (also across a restart), AEL `UPGRADE`, tampered file detected and the healthy version served, legacy registries truthful, no network / subprocess activity, source tree untouched, pinned files byte-identical; plus a check that this document's module names, test files, limits and archetypes still match the code |

The tests were written against the real behaviour and were not weakened; the historical frozen
tests (Prompts 715-719, 786) were not touched.

## 10. Limitations (honest list)

* Three archetypes only. Anything else (a joke generator, accounting software, a new screen, a
  new model) is *refused*, not attempted. Extending the set means writing a new reviewed
  template, spec validator and test generator - a developer task by design.
* The self-built capabilities are pure computations. There is no capability that reads or writes
  files, uses the network or the phone's hardware, and none can be granted.
* The Persian understanding is a fixed grammar over closed word lists, not a language model:
  paraphrases far outside those lists get "I did not understand" or a clarification question.
* The brain's `full` scope is only on inside the application runtime (or with the environment
  variable); a bare `Core` used as a library keeps its legacy replies on purpose.
* A Gradle/APK build could not be executed in the environment this work was produced in (the
  Android SDK and Maven downloads are blocked). The Python side is what the APK bundles and is
  tested through the real `android_entry`; the first CI run of the existing workflow is the
  actual APK build check.
