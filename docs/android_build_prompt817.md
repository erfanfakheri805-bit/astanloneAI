# Prompt 817 - First Real GitHub Actions Build

Status: **BLOCKED - APK NOT BUILT.** No APK exists and none is claimed.

## Blocker (exact)
The Prompt 817 environment still cannot reach GitHub or any build-tool host. Every request returns HTTP 403 with `x-deny-reason: host_not_allowed` from the sandbox egress proxy:
`github.com`, `api.github.com`, `dl.google.com`, `services.gradle.org`, `repo.maven.apache.org`.
There is no Gradle, Android SDK or `gh` CLI, and the project is not a git repository with a remote. The "Android debug APK" workflow therefore could not be pushed, dispatched or observed, so there is no build log, no `app-debug.apk`, no byte size and no SHA-256.

## Changes
No build file was changed (no genuine build failure has been observed; nothing was guessed). Prompt 815 and 816 behaviour is unchanged. Only this note and the Prompt 817 package manifest were added.

## Still required
1. Push the reconstructed project to a GitHub repository.
2. Actions -> "Android debug APK" -> Run workflow.
3. Supply the failing log, or on success the artifact `standalone-ai-debug-apk` (`app/build/outputs/apk/debug/app-debug.apk`) so its size and SHA-256 can be recorded.
