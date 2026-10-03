# Prompt 822 - Signed Release APK via GitHub Actions

**Status: configured and statically validated only. The workflow has NOT been executed, no APK has been built or signed, and nothing has been run on a device.**

## 1. Extract the single ZIP
Extract `Project_Prompt822_GitHub_Ready.zip` once. Its contents are the project root (`build.gradle`, `app/`, `docs/`, `.github/` ...). Make sure the hidden `.github` folder is extracted: it holds the workflows. Do not nest the project inside an extra folder when you upload it; `.github/workflows/` must be at the repository root.

## 2. Upload to GitHub
The project has about 1,200 files, and GitHub's web uploader only accepts a limited number of files at a time (about 100), so use git or GitHub Desktop:
```
cd <extracted folder>
git init -b main
git add -A
git commit -m "Standalone AI Android baseline"
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
Use a **private** repository. No keystore or credential is in the project.

## 3. Create the signing key (once) and the four secrets
Create a keystore on your own machine (JDK `keytool`):
```
keytool -genkeypair -v -keystore release.keystore -alias <alias> -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 release.keystore      # macOS: base64 -i release.keystore
```
In the repository: Settings -> Secrets and variables -> Actions -> New repository secret. Create exactly:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the base64 text of `release.keystore` |
| `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
| `ANDROID_KEY_ALIAS` | the alias used in `keytool` |
| `ANDROID_KEY_PASSWORD` | the key password (same as the keystore password if you pressed Enter) |

If any is missing or empty, the workflow stops immediately with an error naming it. It also fails clearly if the keystore cannot be opened with those values.

## 4. Run the workflow
Actions -> **Android signed release** -> Run workflow -> enter `release_tag` (default `v0.2.0`; it must not already exist) -> Run. It runs the Python regression suite, builds with JDK 17, Python 3.12, Gradle 8.7 and the existing Chaquopy/AGP configuration (`gradle :app:assembleRelease`), verifies the signature with `apksigner`, and creates the GitHub Release. The existing manual **Android debug APK** workflow is unchanged.

## 5. Where the APK appears
Repository -> **Releases** -> the release named after your tag -> Assets. Expected asset: `StandaloneAI-0.2.0-release.apk` (`StandaloneAI-<versionName>-release.apk`; the SHA-256 is in the release notes). Build output inside the runner: `app/build/outputs/apk/release/app-release.apk`. Download the asset and install it on an arm64 Android phone (allow installs from your browser/file manager when asked).

## 6. Back up your keystore
Store `release.keystore`, its alias and both passwords in a secure place outside GitHub (password manager plus an offline copy). **If you lose the key, you can never again sign an update with the same identity**: Android will refuse to install a differently signed APK over the installed app, and you would have to uninstall it (losing its data) and publish under a new identity. Never commit the keystore or passwords; `.gitignore` already blocks `*.keystore`, `*.jks`.

## Limits
Applies to the existing app only (applicationId `com.erfan.standaloneai`, unchanged). Release minification stays off. Device compatibility, Python 3.12 on Android and the fixed port 8420 are unverified. Unverified build contingencies from Prompt 819 still apply (legacy Chaquopy `python { version }` DSL, SDK/licence resolution).
