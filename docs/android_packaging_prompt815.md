# Prompt 815 - Final Android/APK Phase: Packaging Preparation

Status: **packaging path prepared. The APK has NOT been built.** No Python production module, contract or data baseline was changed.

## Existing architecture (unchanged)
Chaquopy hosts the unchanged Python tree (`app/src/main/python`). `MainActivity.java` starts Python, calls `android_entry.start(filesDir)` (installs an `AndroidFilesDirAdapter` via `platform_layer.set_platform`, builds `Core`, serves the existing HTTP UI on `127.0.0.1:8420` in a daemon thread) and shows it in a WebView. The Android layer is one Java file plus `android_entry.py`.

## Selected build path
GitHub Actions, manual `workflow_dispatch` only (`.github/workflows/android-debug-apk.yml`):
1. `python-regression` - Python 3.12, full `unittest discover`.
2. `build-debug-apk` (needs 1) - JDK 17, Python 3.12 (Chaquopy `buildPython`), Android SDK, Gradle 8.7 installed by `gradle/actions/setup-gradle` (no wrapper is committed), `gradle :app:assembleDebug`, upload `app/build/outputs/apk/debug/*.apk`.
Debug keystore only; no secrets, no signing, no release build.

## Changes
- `build.gradle`: Chaquopy `17.+` -> `17.0.0` (reproducible; AGP 8.5.2 is inside Chaquopy 17's supported 7.3-9.2).
- `app/build.gradle`: `python { version "3.12" }` (default would be 3.10; regression suite is verified on 3.12); `abiFilters` -> `arm64-v8a` only (Chaquopy 32-bit ABIs exist only for Python <= 3.11).
- Added `.gitignore` (bytecode, build output, keystores), the workflow, `tests/test_android_packaging_boundary_prompt815.py` (19 tests), this doc.

## Boundary pinned by tests
Pinned Chaquopy/AGP/minSdk/Python/ABI consistency; no `pip` block; only the appcompat dependency; INTERNET is the only permission (loopback socket); Java layer touches only `android_entry.start`; WebView has no remote URL; `android_entry` import has no side effects and needs no Android modules; adapter is confined to `files_dir`; production Python imports stdlib/project modules only; workflow is manual, secret-free, debug-only.

## Not verified here
Gradle/AGP/Chaquopy resolution, SDK 34 availability and the real APK build need network access and the Android toolchain, which this environment lacks. Python 3.12 on-device behaviour is covered only by the desktop 3.12 test run.
