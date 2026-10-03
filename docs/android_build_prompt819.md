# Prompt 819 - Build-Readiness Audit and Real-Build Handoff

Status: **BLOCKED - APK NOT BUILT / UNVERIFIED.** Build files were not modified. The project is build-ready as far as static inspection can show; that is not a build result.

## Environment (Prompt 819 sandbox)
Outbound HTTPS to github.com, api.github.com, dl.google.com, maven.google.com, services.gradle.org, plugins.gradle.org, repo.maven.apache.org and chaquo.com all return HTTP 403 (`x-deny-reason: host_not_allowed`). No `javac` (JDK 17), Gradle, Android SDK, `sdkmanager` or `gh`; `ANDROID_HOME` unset.

## Static configuration audit (unchanged since Prompt 815)
| Item | Value |
|---|---|
| Chaquopy | `com.chaquo.python:gradle:17.0.0` (supports AGP 7.3-9.2, Python 3.10-3.14) |
| Android Gradle Plugin | 8.5.2 (needs Gradle >= 8.7) |
| Gradle | 8.7 via `gradle/actions/setup-gradle`; no wrapper committed |
| JDK | 17 (Temurin); `compileOptions` Java 17 |
| Python (on-device / buildPython) | 3.12 / 3.12 |
| ABI | `arm64-v8a` only (3.12 is 64-bit only on Chaquopy) |
| compileSdk / targetSdk / minSdk | 34 / 34 / 24 (Chaquopy 17 minimum is 24) |
| applicationId / namespace | `com.erfan.standaloneai` |
| Dependencies | `androidx.appcompat:appcompat:1.7.0` only; no pip block |
| Workflow | `.github/workflows/android-debug-apk.yml`, `workflow_dispatch` only, ubuntu-24.04, runs Python regression then `gradle --no-daemon :app:assembleDebug` |
| Expected APK path | `app/build/outputs/apk/debug/app-debug.apk` |
| Expected artifact | `standalone-ai-debug-apk` (upload path glob `app/build/outputs/apk/debug/*.apk`) |

## Watch items for the first real run (no change made)
- `python { version "3.12" }` uses Chaquopy's legacy Groovy DSL, which Chaquopy 17's docs describe as deprecated but still available. If the log rejects it, the fix is moving it to a `chaquopy { defaultConfig { version = "3.12" } }` block.
- Root `clean` task uses `rootProject.buildDir` (deprecated in Gradle 8, not used by `assembleDebug`).
- Android SDK platform 34 / build-tools are fetched on demand; this depends on `android-actions/setup-android` accepting licenses.
These are contingencies, not known failures.

## Handoff
Push the project to GitHub -> Actions -> "Android debug APK" -> Run workflow, then supply the failing log or the artifact (path, byte size, SHA-256). Device verification remains a separate step after a successful build.
