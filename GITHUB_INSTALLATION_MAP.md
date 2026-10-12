# GITHUB_INSTALLATION_MAP - FINAL-EXIT-001 (Claude Exit)

**خلاصه (فارسی):** این بسته فقط «دلتا» است: ۳۸ فایل جدید و ۳ فایل تغییریافته (فقط افزودن خط؛ هیچ خطی حذف نشده)، بدون حذف و بدون جابه‌جایی. محتوای پوشه‌های `added/` و `modified/` را با همان ساختار پوشه روی ریشه‌ی مخزن GitHub کپی کنید (ریشه‌ی مخزن = پوشه‌ای که `app/` و `.github/` در آن است)، سپس هش‌ها را با دستورهای بخش ۳ بررسی کنید. همه‌ی فایل‌ها را می‌شود در **یک commit** گذاشت (بخش ۴). نیازی به تغییر Gradle یا workflow نیست.

## 1. What this delta is

* Baseline: the Prompt 956 project plus the FIX_CI_DELTA files - 1629 files, project hash `fc883fccd361e7277fb4dd55b821dd65206f66d59cf7d13119304c4e1f096cc8`.
* Result after installing: 1667 files, project hash `c2bfee0b33f867e78df72243c63a350df6f6ab13c5d37bb3caa53785f9bc99b9`.
* Hash definition: SHA-256 over the lines `<file sha256>  <path relative to the repository root>` sorted by path (ignoring `__pycache__` / `*.pyc`).
* **A. New files:** 38 - **B. Modified files:** 3 - **C. Deleted files:** 0 - **D. Renamed/moved files:** 0.
* **E. Required test files:** the 5 test modules listed below (they are part of the 38 new files).
* **F. Required build/config files:** none. Nothing in `.github/`, `app/build.gradle`, `build.gradle`, `settings.gradle` or `gradle.properties` changes: the Chaquopy source set already packages everything under `app/src/main/python/`, and `.github/scripts/run_regression.py` (unittest discovery) already picks the new test modules up.
* **G / H.** `manifests/FINAL_EXIT_CHANGE_MANIFEST.json` and `manifests/FINAL_EXIT_SHA256SUMS`.
* The git commit of the baseline is not known to the environment that produced this delta (no git history was provided); identify the baseline by the project hash above. The seven hash-pinned production files and the frozen tests of Prompts 715-719 and 786 are byte-identical to the baseline.

## 2. Install, in four steps (from the repository root)

```bash
# 0. be at the repository root (the folder that contains app/ and .github/) on the baseline
test -d app/src/main/python && test -d .github/workflows || { echo 'not the repository root'; exit 1; }

# 1. the three files that will be replaced must still be the baseline versions
sha256sum -c <<'EOF'
1d4aea2b2231876015a0a1e730506db81eb0a7bab0f2bc76062869e5e32a7c2f  app/src/main/python/self_upgrade/upgrade_system.py
a97ce6f7f541cf7379002f8df757204fb78df6edc3fe076fbf5d401042ef5d46  app/src/main/python/self_upgrade/version_system.py
46e17b9bf9d6ffe2b524b4264816336f10eede7c6d700d76d274009b37ca8eb0  app/src/main/python/skills/skill_system.py
EOF

# 2. unpack and copy (adds 38 files, replaces those 3; the folders self_builder/ and persian_brain/ are created)
unzip FINAL_EXIT_DELTA.zip -d /tmp/final_exit
cp -R /tmp/final_exit/FINAL_EXIT_DELTA/added/.    ./
cp -R /tmp/final_exit/FINAL_EXIT_DELTA/modified/. ./

# 3. verify the delta itself, then the installed files against the manifest
(cd /tmp/final_exit/FINAL_EXIT_DELTA && sha256sum -c manifests/FINAL_EXIT_SHA256SUMS)
python3 - <<'EOF'
import hashlib, json
m = json.load(open('/tmp/final_exit/FINAL_EXIT_DELTA/manifests/FINAL_EXIT_CHANGE_MANIFEST.json'))
bad = [f['github_path'] for f in m['files'] if hashlib.sha256(open(f['github_path'], 'rb').read()).hexdigest() != f['new_sha256']]
print('installed files that differ from the manifest:', bad or 'none')
EOF

# 4. run what CI runs (Python 3.12, standard library only)
python .github/scripts/run_regression.py
```

PowerShell (Windows) equivalent of step 2: `Expand-Archive FINAL_EXIT_DELTA.zip $env:TEMP\final_exit; Copy-Item -Recurse -Force $env:TEMP\final_exit\FINAL_EXIT_DELTA\added\* .; Copy-Item -Recurse -Force $env:TEMP\final_exit\FINAL_EXIT_DELTA\modified\* .`

If you upload through the GitHub web interface instead: create each file at the destination below ("Add file -> Upload files" keeps folders when you drag the contents of `added/` and `modified/` onto the repository root).

## 3. Every file: source, destination, action

Source paths are relative to `FINAL_EXIT_DELTA/`; destinations are complete repository-relative paths. "Replaces an existing file" is **yes** only for the 3 MODIFIED files.

### 1. NEW

* **Source:** `added/app/src/main/python/self_builder/__init__.py`
* **Destination:** `app/src/main/python/self_builder/__init__.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** none inside the project (it imports nothing)
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `f4f4cc99be40ca39c2ab55cf02e72d8d2bcc9c1bb2c59f3c49aeeb57fac0c1e4`

### 2. NEW

* **Source:** `added/app/src/main/python/self_builder/builder.py`
* **Destination:** `app/src/main/python/self_builder/builder.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/expr.py`, `self_builder/fa_text.py`, `self_builder/loader.py`, `self_builder/policy.py`, `self_builder/registry.py`, `self_builder/repair.py`, `self_builder/request_parser.py`, `self_builder/sandbox.py`, `self_builder/spec.py`, `self_builder/store.py`, `self_builder/templates.py`, `self_builder/validator.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `b03edc2994ef71e0ed2fb9f37fce85e86e89ed704807b1fd7092dcb5421a5fe8`

### 3. NEW

* **Source:** `added/app/src/main/python/self_builder/errors.py`
* **Destination:** `app/src/main/python/self_builder/errors.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** none inside the project (it imports nothing)
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `92dd816e8b30b1254504ade9b8eef671f82928c969c7f4af66744a0c32e8098c`

### 4. NEW

* **Source:** `added/app/src/main/python/self_builder/expr.py`
* **Destination:** `app/src/main/python/self_builder/expr.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/mathcore.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `38f556818d689c19d7f5ea877f46f60b0f990b4e457bcd0eab603da587ec993b`

### 5. NEW

* **Source:** `added/app/src/main/python/self_builder/fa_text.py`
* **Destination:** `app/src/main/python/self_builder/fa_text.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `understanding/persian_nlu.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `c27d2a2f44e258b6970af05252c330f6794d578e5483edc000e0a5150ab21352`

### 6. NEW

* **Source:** `added/app/src/main/python/self_builder/helpers.py`
* **Destination:** `app/src/main/python/self_builder/helpers.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/mathcore.py`, `self_builder/textops.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `4d077ce54b883910007ed3a411c1d8959266cea720d0107d1c01193724a13fd4`

### 7. NEW

* **Source:** `added/app/src/main/python/self_builder/loader.py`
* **Destination:** `app/src/main/python/self_builder/loader.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/policy.py`, `self_builder/registry.py`, `self_builder/sandbox.py`, `self_builder/spec.py`, `self_builder/store.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `99b5baf1ea27cd83d0c07b71adb401f1ef76305c09c690e2216d8c80fdab7e98`

### 8. NEW

* **Source:** `added/app/src/main/python/self_builder/lock.py`
* **Destination:** `app/src/main/python/self_builder/lock.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `56531340ef9d7ec475b7cce8c5e84309e1a259f4939305fa33e575aadf6f574f`

### 9. NEW

* **Source:** `added/app/src/main/python/self_builder/matcher.py`
* **Destination:** `app/src/main/python/self_builder/matcher.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/fa_text.py`, `self_builder/policy.py`, `self_builder/registry.py`, `self_builder/request_parser.py`, `self_builder/textops.py`, `self_builder/units.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `7b38e1258243969d9f2b9ddc5480a350ffd9ff16e2e476c08c762de3bc696a93`

### 10. NEW

* **Source:** `added/app/src/main/python/self_builder/mathcore.py`
* **Destination:** `app/src/main/python/self_builder/mathcore.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `c09829c304141bbc36cfa25ba8dd3851c3fdeb6da61f910cba2944bf4f9f1984`

### 11. NEW

* **Source:** `added/app/src/main/python/self_builder/mirror.py`
* **Destination:** `app/src/main/python/self_builder/mirror.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `capabilities/capability_system.py`, `self_upgrade/version_system.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `21e5f7ab948275dac50747755a1ee628b0062f5aa0ef40ddaadac911b694ddf5`

### 12. NEW

* **Source:** `added/app/src/main/python/self_builder/policy.py`
* **Destination:** `app/src/main/python/self_builder/policy.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/errors.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `4d385efeb35655d704d740b89d3aa8bf0fb1a5d47a6d1560ecb24b8a8229e3a7`

### 13. NEW

* **Source:** `added/app/src/main/python/self_builder/registry.py`
* **Destination:** `app/src/main/python/self_builder/registry.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/store.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `df6aa46afa9d41b4a58758e7cb38522fa8e5258fefce3ec207fad813d5edb023`

### 14. NEW

* **Source:** `added/app/src/main/python/self_builder/repair.py`
* **Destination:** `app/src/main/python/self_builder/repair.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/expr.py`, `self_builder/fa_text.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `2b7867893a7d9294aace99c85be5b9bef8469ca43bc82faea499db1281b605ca`

### 15. NEW

* **Source:** `added/app/src/main/python/self_builder/request_parser.py`
* **Destination:** `app/src/main/python/self_builder/request_parser.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/expr.py`, `self_builder/fa_text.py`, `self_builder/policy.py`, `self_builder/repair.py`, `self_builder/textops.py`, `self_builder/units.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `2699116e24d2ae186adc65baf3a2b6cf14612df94e67d8e3c933e77a32c049c7`

### 16. NEW

* **Source:** `added/app/src/main/python/self_builder/sandbox.py`
* **Destination:** `app/src/main/python/self_builder/sandbox.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/helpers.py`, `self_builder/mathcore.py`, `self_builder/policy.py`, `self_builder/templates.py`, `self_builder/validator.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `1afe9b4d1b0a6f1ced0e7dabf977c5197014eeabbbf0961009b7b87efd1897f3`

### 17. NEW

* **Source:** `added/app/src/main/python/self_builder/service.py`
* **Destination:** `app/src/main/python/self_builder/service.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/builder.py`, `self_builder/errors.py`, `self_builder/loader.py`, `self_builder/matcher.py`, `self_builder/mirror.py`, `self_builder/policy.py`, `self_builder/registry.py`, `self_builder/sandbox.py`, `self_builder/store.py`, `self_builder/workspace.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `a74f14234f5436de7cf3c215a9804287bc2268d3dfa1d5255de0cc014f5f687a`

### 18. NEW

* **Source:** `added/app/src/main/python/self_builder/spec.py`
* **Destination:** `app/src/main/python/self_builder/spec.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/expr.py`, `self_builder/fa_text.py`, `self_builder/policy.py`, `self_builder/textops.py`, `self_builder/units.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `33dcf33e4def3e8e5ad8a7ea8c846254015da5edb0f9b77746c015555f2da0f2`

### 19. NEW

* **Source:** `added/app/src/main/python/self_builder/store.py`
* **Destination:** `app/src/main/python/self_builder/store.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `26bb9f79191917fbd2ff344d9428f52b260dc4afb0ceaf65bf9725e2d4955444`

### 20. NEW

* **Source:** `added/app/src/main/python/self_builder/templates.py`
* **Destination:** `app/src/main/python/self_builder/templates.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/expr.py`, `self_builder/mathcore.py`, `self_builder/policy.py`, `self_builder/spec.py`, `self_builder/textops.py`, `self_builder/units.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `b7d653f479bd60e53332e8cee449c28bf65baa275204119677090fbb2a877070`

### 21. NEW

* **Source:** `added/app/src/main/python/self_builder/textops.py`
* **Destination:** `app/src/main/python/self_builder/textops.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/mathcore.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `fb0334777b4d34eaf0d3e15226c15e476a6383214bb3c85393b7ac82c6b3b69d`

### 22. NEW

* **Source:** `added/app/src/main/python/self_builder/units.py`
* **Destination:** `app/src/main/python/self_builder/units.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/fa_text.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `2be966f8558408939932fcb7ebfb169b0d7f910d53dad0cf116080cc4e67eb0a`

### 23. NEW

* **Source:** `added/app/src/main/python/self_builder/validator.py`
* **Destination:** `app/src/main/python/self_builder/validator.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/helpers.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `73edb74bd6f08cf2195caaab31404ebf6d48cbad826382c0ff1b4a7f156249d9`

### 24. NEW

* **Source:** `added/app/src/main/python/self_builder/workspace.py`
* **Destination:** `app/src/main/python/self_builder/workspace.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/self_builder/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/errors.py`, `self_builder/lock.py`, `self_builder/policy.py`
* **Required ordering:** commit 1 of 4 (package `self_builder/`; nothing else needs to exist first; install before commits 2-3)
* **SHA-256 (new):** `d0e94e65b5f293273f0522338231fdd5e02e21cf5f36cff554e79b49aed12013`

### 25. NEW

* **Source:** `added/app/src/main/python/persian_brain/__init__.py`
* **Destination:** `app/src/main/python/persian_brain/__init__.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `persian_brain/brain.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `ea9f36d28161627ae18b494b99116df089a6ee4abd07d17196ee625d0ccea60e`

### 26. NEW

* **Source:** `added/app/src/main/python/persian_brain/activation.py`
* **Destination:** `app/src/main/python/persian_brain/activation.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `platform_layer/__init__.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `3ff898b27176c8e52812f0b7b7e4e262049917ad901e9742602857853c1b716d`

### 27. NEW

* **Source:** `added/app/src/main/python/persian_brain/brain.py`
* **Destination:** `app/src/main/python/persian_brain/brain.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `concepts/concept_system.py`, `knowledge/knowledge_system.py`, `learning/learning_system.py`, `persian_brain/__init__.py`, `persian_brain/activation.py`, `persian_brain/dialogue.py`, `persian_brain/intents.py`, `persian_brain/messages.py`, `persian_brain/normalization.py`, `self_builder/__init__.py`, `self_builder/builder.py`, `self_builder/fa_text.py`, `self_builder/matcher.py`, `self_builder/policy.py`, `self_builder/registry.py`, `self_builder/request_parser.py`, `self_builder/service.py`, `self_builder/textops.py`, `self_builder/units.py`, `understanding/__init__.py`, `understanding/persian_nlu.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `620574a28f070a572a8effebae083b81babfaceada15e971c15612d948737e30`

### 28. NEW

* **Source:** `added/app/src/main/python/persian_brain/dialogue.py`
* **Destination:** `app/src/main/python/persian_brain/dialogue.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** none inside the project (standard library only: json, time)
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `f1b4d21d9f79f4e326ff524dc773ba19662c6dba7b0dc58ce868820eb739daec`

### 29. NEW

* **Source:** `added/app/src/main/python/persian_brain/intents.py`
* **Destination:** `app/src/main/python/persian_brain/intents.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `persian_brain/__init__.py`, `persian_brain/lexicon.py`, `persian_brain/normalization.py`, `self_builder/__init__.py`, `self_builder/fa_text.py`, `self_builder/request_parser.py`, `self_builder/units.py`, `understanding/__init__.py`, `understanding/persian_nlu.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `afe5d863d946981287ccbde4dca2f0a88948b41edaa27892249a8edfc8bf1ef8`

### 30. NEW

* **Source:** `added/app/src/main/python/persian_brain/lexicon.py`
* **Destination:** `app/src/main/python/persian_brain/lexicon.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/fa_text.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `77c150665caae99dd5c56b5d7e970177e5e2fffe12ea720d104b342b293fc9ae`

### 31. NEW

* **Source:** `added/app/src/main/python/persian_brain/messages.py`
* **Destination:** `app/src/main/python/persian_brain/messages.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/fa_text.py`, `self_builder/policy.py`, `self_builder/textops.py`, `self_builder/units.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `a793651f9baec8f1f7a96bc7ce306450214103231682a307dd5b818916dc635e`

### 32. NEW

* **Source:** `added/app/src/main/python/persian_brain/normalization.py`
* **Destination:** `app/src/main/python/persian_brain/normalization.py`
* **Action:** Upload as a new file (the folder `app/src/main/python/persian_brain/` does not exist yet: create it by copying - the file `__init__.py` of the package is part of this delta).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/fa_text.py`
* **Required ordering:** commit 2 of 4 (package `persian_brain/`; needs `self_builder/` from commit 1)
* **SHA-256 (new):** `d9497925308207f054f67ef2dcf33e682bad4d23af888db2e0eedd3d536b0d3a`

### 33. NEW

* **Source:** `added/app/src/main/python/tests/test_claude_exit_audit_final_exit001.py`
* **Destination:** `app/src/main/python/tests/test_claude_exit_audit_final_exit001.py`
* **Action:** Upload as a new file (into the existing folder `app/src/main/python/tests/`).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/__init__.py`, `self_builder/policy.py`, `self_builder/service.py`
* **Required ordering:** commit 4 of 4 (tests and docs; they import the packages and hooks from commits 1-3)
* **SHA-256 (new):** `e291bf51eba71f575c2e078e72f05a56919d6ab0b0c4e71781cdf02ac5b1e69d`

### 34. NEW

* **Source:** `added/app/src/main/python/tests/test_persian_brain_final_exit001.py`
* **Destination:** `app/src/main/python/tests/test_persian_brain_final_exit001.py`
* **Action:** Upload as a new file (into the existing folder `app/src/main/python/tests/`).
* **Replaces an existing file:** no
* **Dependencies:** `core/core.py`; `memory/memory_system.py`; `persian_brain/` (8 modules); `platform_layer/__init__.py`; `runtime_integration/bridge.py`; `self_builder/` (5 modules)
* **Required ordering:** commit 4 of 4 (tests and docs; they import the packages and hooks from commits 1-3)
* **SHA-256 (new):** `3669b2ac06ac2f9b81284b24421dfd7a3b28f7cb0e53a30bad4eb41dc897f427`

### 35. NEW

* **Source:** `added/app/src/main/python/tests/test_self_builder_foundations_final_exit001.py`
* **Destination:** `app/src/main/python/tests/test_self_builder_foundations_final_exit001.py`
* **Action:** Upload as a new file (into the existing folder `app/src/main/python/tests/`).
* **Replaces an existing file:** no
* **Dependencies:** `self_builder/` (13 modules)
* **Required ordering:** commit 4 of 4 (tests and docs; they import the packages and hooks from commits 1-3)
* **SHA-256 (new):** `b421861c97d6f21098016e741e7175abfc933d60ad34e64b4e7dc9fa238639a1`

### 36. NEW

* **Source:** `added/app/src/main/python/tests/test_self_builder_legacy_bridges_final_exit001.py`
* **Destination:** `app/src/main/python/tests/test_self_builder_legacy_bridges_final_exit001.py`
* **Action:** Upload as a new file (into the existing folder `app/src/main/python/tests/`).
* **Replaces an existing file:** no
* **Dependencies:** `core/core.py`; `persian_brain/__init__.py`, `persian_brain/activation.py`; `platform_layer/__init__.py`; `self_builder/` (5 modules); `self_upgrade/upgrade_system.py`, `self_upgrade/version_system.py`
* **Required ordering:** commit 4 of 4 (tests and docs; they import the packages and hooks from commits 1-3)
* **SHA-256 (new):** `3775454c910857be3090b360211ec0957673f43fa9b8d03f936d434674742a94`

### 37. NEW

* **Source:** `added/app/src/main/python/tests/test_self_builder_pipeline_final_exit001.py`
* **Destination:** `app/src/main/python/tests/test_self_builder_pipeline_final_exit001.py`
* **Action:** Upload as a new file (into the existing folder `app/src/main/python/tests/`).
* **Replaces an existing file:** no
* **Dependencies:** `memory/memory_system.py`; `self_builder/` (18 modules)
* **Required ordering:** commit 4 of 4 (tests and docs; they import the packages and hooks from commits 1-3)
* **SHA-256 (new):** `dc519d233a08e1395be7c79c09383133a80f0e96b4490b2380c84ab60ce7a458`

### 38. NEW

* **Source:** `added/docs/self_builder_final_exit.md`
* **Destination:** `docs/self_builder_final_exit.md`
* **Action:** Upload as a new file (into the existing folder `docs/`).
* **Replaces an existing file:** no
* **Dependencies:** `ael/interpreter.py`; `android_entry.py`; `core/core.py`; `interface/server.py`; `persian_brain/activation.py`; `runtime_growth/runtime_growth_cycle.py`; `runtime_integration/bridge.py`, `runtime_integration/runtime_core.py`; `self_builder/` (23 modules); `self_upgrade/upgrade_system.py`, `self_upgrade/version_system.py`; `skills/skill_system.py`; `tests/` (5 modules)
* **Required ordering:** commit 4 of 4 (tests and docs; they import the packages and hooks from commits 1-3)
* **SHA-256 (new):** `291ad9d861a6cc7420c772c136653f00d14471148bbfb5342762907d52d8d6bb`

### 39. MODIFIED

* **Source:** `modified/app/src/main/python/self_upgrade/upgrade_system.py`
* **Destination:** `app/src/main/python/self_upgrade/upgrade_system.py`
* **Action:** Replace the existing file (baseline SHA-256 `1d4aea2b2231876015a0a1e730506db81eb0a7bab0f2bc76062869e5e32a7c2f`; the change only adds lines: 55 added, 0 removed).
* **Replaces an existing file:** yes
* **Dependencies:** `persian_brain/__init__.py`, `persian_brain/activation.py`, `self_builder/__init__.py`, `self_builder/mirror.py`, `self_builder/request_parser.py`, `self_builder/service.py`, `self_upgrade/sandbox.py`, `self_upgrade/version_system.py`
* **Required ordering:** commit 3 of 4 (replace AFTER commits 1-2: the hook imports `persian_brain` / `self_builder` lazily and silently falls back to the old behaviour if they are missing, so a wrong order cannot crash the app but would leave the feature switched off)
* **SHA-256 (new):** `319d29ec37f1c31905ca212365f0aaacfeed7ac8ca01deac39d85aa09cd4c27e`

### 40. MODIFIED

* **Source:** `modified/app/src/main/python/self_upgrade/version_system.py`
* **Destination:** `app/src/main/python/self_upgrade/version_system.py`
* **Action:** Replace the existing file (baseline SHA-256 `a97ce6f7f541cf7379002f8df757204fb78df6edc3fe076fbf5d401042ef5d46`; the change only adds lines: 41 added, 0 removed).
* **Replaces an existing file:** yes
* **Dependencies:** `self_builder/__init__.py`, `self_builder/service.py`
* **Required ordering:** commit 3 of 4 (replace AFTER commits 1-2: the hook imports `persian_brain` / `self_builder` lazily and silently falls back to the old behaviour if they are missing, so a wrong order cannot crash the app but would leave the feature switched off)
* **SHA-256 (new):** `ebaed3547c2f3979ebfd3fc530500af8f9ca782b2c63a2344714b653e2787f45`

### 41. MODIFIED

* **Source:** `modified/app/src/main/python/skills/skill_system.py`
* **Destination:** `app/src/main/python/skills/skill_system.py`
* **Action:** Replace the existing file (baseline SHA-256 `46e17b9bf9d6ffe2b524b4264816336f10eede7c6d700d76d274009b37ca8eb0`; the change only adds lines: 22 added, 0 removed).
* **Replaces an existing file:** yes
* **Dependencies:** `persian_brain/__init__.py`, `platform_layer/__init__.py`
* **Required ordering:** commit 3 of 4 (replace AFTER commits 1-2: the hook imports `persian_brain` / `self_builder` lazily and silently falls back to the old behaviour if they are missing, so a wrong order cannot crash the app but would leave the feature switched off)
* **SHA-256 (new):** `59f8db1f16a666ece0ee1422449c96d4873149b7f4eaf3c162480afd3574775f`

## 4. Commit order

**All 41 files can be uploaded in ONE commit** - that is the simplest and is what I recommend. If you prefer small commits, apply them in this order (each step is self-consistent: no file refers to a file that a later commit adds - the packages do not depend on the three hooks, the hooks are the only place where the application starts using the packages and import them lazily, and the tests come last):

1. Add the controlled Self-Builder package (self_builder/) - 24 file(s).
2. Add the Persian conversation brain (persian_brain/) - 8 file(s).
3. Wire the Self-Builder into SkillSystem, UpgradeSystem and VersionSystem (3 additive hooks) - 3 file(s).
4. Add FINAL-EXIT-001 tests and documentation - 6 file(s).

Suggested message for the single commit:

```
FINAL-EXIT-001: controlled Self-Builder and Persian conversation brain

Adds self_builder/ (template-based, validated, tested, versioned, reversible internal capability
builder: unit conversions, formulas, text tools) and persian_brain/ (deterministic Persian
conversation layer), wires them in through three additive hooks (SkillSystem, UpgradeSystem,
VersionSystem), and adds 5 test modules and docs/self_builder_final_exit.md.
No file is deleted or renamed; hash-pinned files and frozen tests are untouched.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014RRxSt6Mx7NTPJDoKHNsoo
```

## 5. Directory validation

Checked against the baseline tree (the real GitHub repository could not be reached from the environment that produced this delta, so the repository root is assumed to equal the project root: `.github/`, `app/`, `docs/`, `build.gradle`, `settings.gradle`, `gradle.properties` at the top level).

* Destination folders that already exist: `app/src/main/python/self_upgrade`, `app/src/main/python/skills`, `app/src/main/python/tests`, `docs`.
* Destination folders that do not exist yet and are created by the copy: `app/src/main/python/persian_brain`, `app/src/main/python/self_builder` (both are Python packages with an `__init__.py` in this delta).
* New top-level Python package names (`persian_brain`, `self_builder`) do not clash with any existing module or package of `app/src/main/python/`.
* Case-insensitive name collisions between added files and baseline files: none.
* `.gitignore` of the baseline does not ignore any delivered file (checked with `git add -A -n` on a scratch repository: git tracks exactly these 41 files).

## 6. What was and was not verified (details: manifests/FINAL_EXIT_CHANGE_MANIFEST.json, key `verification`)

* The Python test suites (standard library `unittest`) were run on the reconstructed project; the numbers are in the manifest.
* **The Gradle / APK build was NOT run** in the environment that produced this delta (no Android SDK, no Maven access). The first CI run of the existing `Android debug APK` workflow is the actual APK build check; nothing in the Gradle or workflow files was changed.
* The new code uses only the Python standard library (no `pip` block is needed) and Python 3.12 features available in Chaquopy 3.12.

