"""Prompt 822 - signed release workflow and signing configuration.

Static checks only: nothing is executed, no network, no credentials. Pins
that the release workflow consumes GitHub Secrets, never stores any, and
leaves the application identity untouched.
"""

import os
import re
import unittest

_PY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ROOT = os.path.abspath(os.path.join(_PY_ROOT, "..", "..", "..", ".."))
_HAS_PROJECT = os.path.isfile(os.path.join(_ROOT, "settings.gradle"))

SECRETS = ("ANDROID_KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD",
           "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD")


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(_HAS_PROJECT, "project files not present")
class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = _read(".github", "workflows", "android-signed-release.yml")
        self.code = "\n".join(l.split("#", 1)[0] if l.lstrip().startswith("#") else l
                              for l in self.text.splitlines())

    def test_manual_only_with_tag_input(self):
        self.assertRegex(self.text, r"(?m)^on:\n  workflow_dispatch:\n    inputs:\n      release_tag:")
        triggers = re.search(r"(?ms)^on:\n(.*?)^permissions:", self.text).group(1)
        for other in ("push:", "pull_request:", "schedule:", "release:"):
            self.assertNotIn(other, triggers)
        self.assertRegex(triggers, r"required: true")

    def test_release_not_debug(self):
        self.assertIn(":app:assembleRelease", self.code)
        self.assertNotIn("assembleDebug", self.code)
        self.assertIn("app/build/outputs/apk/release/app-release.apk", self.code)

    def test_toolchain_matches_android_config(self):
        self.assertIn('java-version: "17"', self.code)
        self.assertEqual(self.code.count('python-version: "3.12"'), 2)
        self.assertIn('gradle-version: "8.7"', self.code)

    def test_contents_write_permission_for_release(self):
        block = re.search(r"(?m)^permissions:\n((?:  .+\n)+)", self.text).group(1)
        self.assertEqual(block.strip(), "contents: write")

    def test_all_four_secrets_consumed_only_via_secrets_context(self):
        for name in SECRETS:
            self.assertIn("${{ secrets.%s }}" % name, self.text)
        used = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", self.text))
        self.assertEqual(used, set(SECRETS))

    def test_no_literal_credentials(self):
        for name in SECRETS:
            for m in re.finditer(r"^\s*%s:\s*(.+)$" % name, self.text, re.M):
                self.assertTrue(m.group(1).strip().startswith("${{ secrets."), m.group(0))

    def test_fails_clearly_when_secrets_missing(self):
        self.assertIn('[ -z "${!name}" ]', self.text)
        self.assertIn("::error::Required GitHub secret", self.text)
        # The check precedes setup/build steps.
        self.assertLess(self.text.index("name: Verify required signing secrets are present"),
                        self.text.index("name: Assemble signed release APK"))
        self.assertLess(self.text.index("name: Verify required signing secrets are present"),
                        self.text.index("uses: android-actions/setup-android"))

    def test_signature_verified_and_release_created_with_asset(self):
        self.assertIn("apksigner", self.text)
        self.assertIn("verify --print-certs", self.text)
        self.assertIn("gh release create", self.text)
        self.assertIn('"$ASSET_PATH"', self.text)
        self.assertIn("StandaloneAI-${version}-release.apk", self.text)

    def test_keystore_is_temporary_and_removed(self):
        self.assertIn("$RUNNER_TEMP/release.keystore", self.text)
        self.assertIn("if: always()", self.text)
        self.assertIn("rm -f", self.text)

    def test_tag_passed_through_env_not_interpolated_in_scripts(self):
        self.assertNotIn("${{ inputs.release_tag }}", re.sub(
            r"RELEASE_TAG: \$\{\{ inputs\.release_tag \}\}", "", self.text))

    def test_debug_workflow_untouched_in_purpose(self):
        dbg = _read(".github", "workflows", "android-debug-apk.yml")
        self.assertIn(":app:assembleDebug", dbg)
        self.assertNotIn("secrets.", dbg)


@unittest.skipUnless(_HAS_PROJECT, "project files not present")
class SigningConfigTests(unittest.TestCase):
    def setUp(self):
        self.gradle = _read("app", "build.gradle")

    def test_signing_read_from_environment_only(self):
        for var in ("ANDROID_KEYSTORE_PATH", "ANDROID_KEYSTORE_PASSWORD",
                    "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD"):
            self.assertIn('System.getenv("%s")' % var, self.gradle)
        for key in ("storePassword", "keyPassword", "keyAlias", "storeFile"):
            for m in re.finditer(r"^\s*%s\s+(.+)$" % key, self.gradle, re.M):
                self.assertTrue(m.group(1).startswith(("System.getenv", "file(ksPath)")), m.group(0))

    def test_release_signing_applied_only_when_configured(self):
        self.assertRegex(self.gradle, r'if \(System\.getenv\("ANDROID_KEYSTORE_PATH"\)\)\s*\{\s*signingConfig signingConfigs\.release')

    def test_identity_unchanged(self):
        self.assertIn('applicationId "com.erfan.standaloneai"', self.gradle)
        self.assertIn("namespace 'com.erfan.standaloneai'", self.gradle)
        self.assertRegex(self.gradle, r'version\s+"3\.12"')
        self.assertIn('abiFilters "arm64-v8a"', self.gradle)

    def test_no_keystore_or_secret_files_in_repository(self):
        bad = []
        for root, dirs, files in os.walk(_ROOT):
            for f in files:
                if f.lower().endswith((".jks", ".keystore", ".p12", ".pfx", ".pem")):
                    bad.append(os.path.join(root, f))
        self.assertEqual(bad, [])
        gi = _read(".gitignore")
        for pat in ("*.keystore", "*.jks"):
            self.assertIn(pat, gi)

    def test_documentation_lists_every_secret_and_warns_about_key_loss(self):
        doc = _read("docs", "android_signed_release_prompt822.md")
        for name in SECRETS:
            self.assertIn(name, doc)
        self.assertIn("Android signed release", doc)
        self.assertIn("lose the key", doc)
        self.assertIn("NOT been executed", doc)


if __name__ == "__main__":
    unittest.main()
