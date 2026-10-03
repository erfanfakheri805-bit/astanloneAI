# Prompt 821 - Android Baseline Freeze and Real-World Handoff

## Final status (exact)
| Item | Status |
|---|---|
| APK built | **NO** |
| APK verified | **NO** |
| Device verified | **NO** |
| Build status | **BLOCKED BY EXTERNAL BUILD ENVIRONMENT** |

No APK, APK size, APK SHA-256, artifact output, install result or logcat exists. None is claimed. Prompts 817-820 each ran in a sandbox with no GitHub, Maven/Gradle or Android SDK network access, no JDK 17 compiler, no Gradle and no adb/emulator (HTTP 403 `host_not_allowed`).

## Frozen baseline
Versus the original Prompt 814 project, the only changes are the Android packaging layer: `build.gradle`, `app/build.gradle`, `.gitignore`, `.github/workflows/android-debug-apk.yml`, `tests/test_android_packaging_boundary_prompt815.py`, notes under `docs/` and the per-prompt parts manifests. **No Python production module was changed**; `data/memory.db` is byte-identical to the baseline.

## Final Android build configuration
Chaquopy 17.0.0; Android Gradle Plugin 8.5.2; Gradle 8.7 (installed by the workflow, no wrapper); JDK 17 (Temurin); Python 3.12 on device and as buildPython; ABI `arm64-v8a` only; compileSdk/targetSdk 34, minSdk 24; applicationId `com.erfan.standaloneai`; sole dependency `androidx.appcompat:appcompat:1.7.0`; no pip block; INTERNET is the only permission. Workflow `Android debug APK` is `workflow_dispatch` only (ubuntu-24.04): Python regression, then `gradle --no-daemon :app:assembleDebug`, uploading artifact `standalone-ai-debug-apk` from `app/build/outputs/apk/debug/*.apk` (expected file `app-debug.apk`).

## Real-world steps
1. Reconstruct the 12 parts into one directory.
2. Push it to a GitHub repository.
3. Actions -> "Android debug APK" -> Run workflow.
4. Download artifact `standalone-ai-debug-apk`; record `app-debug.apk` size and SHA-256.
5. Install on an Android device (arm64) and collect first-launch logcat (tags `python.stdout`/`python.stderr`; check port 8420 startup).
6. Only then make fixes for genuine errors. Known contingencies: legacy Chaquopy `python { version }` DSL, SDK/licence resolution, Python 3.12 on device, fixed port 8420.

## Not started
No post-APK feature work. Prompt 822 has not been started.
