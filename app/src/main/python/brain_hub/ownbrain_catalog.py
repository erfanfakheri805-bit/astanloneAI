"""
brain_hub.ownbrain_catalog - which free, open language models the app may fetch BY ITSELF for its own brain
=========================================================================================================
The assistant's "own brain" is a real language model that lives on the phone: no key, no account, no money, no other AI service.
This file is only DATA: the short list of models the app is allowed to download without being handed a file, each pinned to the exact
SHA-256 of the file (read from the model's own page on Hugging Face), so a changed or swapped file is refused by the downloader.

Rules for an entry
* open licence that needs no click-through (Apache-2.0): the file can be fetched with one plain request, no login, no gate;
* the source is the model's own repository (`litert-community`, the on-device packaging of Google's LiteRT-LM engine);
* only the hosts below are ever contacted (the redirect to the download CDN stays inside `hf.co`);
* the size is a HINT (the SHA-256 is the real guard): a server that announces a size far from it is refused before a byte is stored.

`recommend()` picks the entry that fits THIS phone from its memory and free space; `fits()` says why one does not.

What is NOT here, on purpose: any model that needs an account or a terms-acceptance page (Gemma 3, Llama ...), any other host, and any
"download this URL" taken from a chat message. Adding a model means adding an entry here, with a hash read from its page, and a test.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

__all__ = ["BrainChoice", "CHOICES", "STRONG", "LIGHT", "ALLOWED_HOSTS", "get", "by_model_id", "recommend", "fits", "rel_dest", "FitReport"]

ALLOWED_HOSTS = ("huggingface.co", "hf.co")
GB = 1_000_000_000
MB = 1_000_000

STRONG = "strong"
LIGHT = "light"


@dataclass(frozen=True)
class BrainChoice:
    key: str                  # "strong" | "light"
    model_id: str             # the id in the model registry (a-z 0-9 . _ -)
    title: str                # shown in the registry (Latin)
    short_fa: str             # how the chat names it
    version: str
    url: str                  # https, on ALLOWED_HOSTS
    sha256: str               # of the whole file (from the model's page)
    size_hint: int            # bytes, approximate unless exact_size
    tolerance: float          # accepted deviation of the announced size from the hint (0.08 = 8 %)
    exact_size: int           # bytes, or 0 when only the hint is known
    license: str
    min_ram: int              # total RAM (bytes) below which this model is not offered
    comfortable_ram: int      # total RAM (bytes) from which it is the recommended one
    languages: Tuple[str, ...]
    persian_fa: str           # an honest sentence about its Persian
    source_fa: str            # who made it, in words

    @property
    def max_bytes(self) -> int:
        return int(self.size_hint * (1 + self.tolerance)) + 1

    @property
    def rel_dest(self) -> str:
        return rel_dest(self)


STRONG_CHOICE = BrainChoice(
    key=STRONG, model_id="own-gemma4-e2b", title="Gemma 4 E2B (on-device, LiteRT-LM)", short_fa="مغز قوی‌تر (Gemma 4 E2B)", version="1",
    url="https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm",
    sha256="181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c",
    size_hint=2_590_000_000, tolerance=0.08, exact_size=0, license="apache-2.0",
    min_ram=4_800_000_000, comfortable_ram=6_800_000_000, languages=("fa", "en", "ar", "tr", "ur"),
    persian_fa="چندزبانه است و فارسی را قابل‌قبول می‌فهمد و می‌نویسد، ولی مدلی کوچک است: گاهی اشتباه یا ساده‌گو می‌شود",
    source_fa="ساختهٔ گوگل (Gemma 4)، با مجوز آزادِ Apache-2.0، آماده‌شده برای اجرا روی گوشی")

LIGHT_CHOICE = BrainChoice(
    key=LIGHT, model_id="own-qwen35-08b", title="Qwen3.5 0.8B (on-device, LiteRT-LM)", short_fa="مغز سبک (Qwen3.5 ۰٫۸B)", version="1",
    url="https://huggingface.co/litert-community/Qwen3.5-0.8B/resolve/main/Qwen3.5-0.8B_int8.litertlm",
    sha256="25447e2550082aed6145bbc755ec4da5d535f98f6a0c386865fdae2ccb88aed1",
    size_hint=964_566_992, tolerance=0.02, exact_size=964_566_992, license="apache-2.0",
    min_ram=3_000_000_000, comfortable_ram=0, languages=("fa", "en", "ar", "zh"),
    persian_fa="خیلی کوچک و سریع است ولی فارسی‌اش ضعیف‌تر است؛ برای حرف‌های ساده و کوتاه خوب است، برای پرسش‌های دقیق نه",
    source_fa="ساختهٔ Qwen (علی‌بابا)، با مجوز آزادِ Apache-2.0، آماده‌شده برای اجرا روی گوشی")

CHOICES: Tuple[BrainChoice, ...] = (STRONG_CHOICE, LIGHT_CHOICE)

# Free space kept untouched on the phone after the download: a phone with 0 bytes left misbehaves.
SAFETY_FREE = 400 * MB


def rel_dest(choice: BrainChoice) -> str:
    """The place of the unfinished / finished download under the own-brain folder (the hash prefix keeps two versions apart)."""
    return "%s-%s/model.litertlm" % (choice.key, choice.sha256[:12])


def get(key: object) -> Optional[BrainChoice]:
    for choice in CHOICES:
        if choice.key == key:
            return choice
    return None


def by_model_id(model_id: object) -> Optional[BrainChoice]:
    for choice in CHOICES:
        if choice.model_id == model_id:
            return choice
    return None


@dataclass(frozen=True)
class FitReport:
    ok: bool
    code: str                 # ok | ram_too_small | ram_unknown | not_enough_space
    need_bytes: int = 0
    have_bytes: int = 0


def fits(choice: BrainChoice, ram_bytes: int, free_bytes: int, already_have: int = 0) -> FitReport:
    """Can THIS phone take this model? `already_have` is what of the file is already on the phone (a half download counts)."""
    if not isinstance(ram_bytes, int) or isinstance(ram_bytes, bool) or ram_bytes <= 0:
        return FitReport(False, "ram_unknown")
    if ram_bytes < choice.min_ram:
        return FitReport(False, "ram_too_small", choice.min_ram, ram_bytes)
    need = max(0, int(choice.size_hint * (1 + choice.tolerance)) - max(0, int(already_have))) + SAFETY_FREE
    if not isinstance(free_bytes, int) or isinstance(free_bytes, bool) or free_bytes < need:
        return FitReport(False, "not_enough_space", need, max(0, int(free_bytes)) if isinstance(free_bytes, int) else 0)
    return FitReport(True, "ok", need, int(free_bytes))


def recommend(ram_bytes: int, free_bytes: int, already_have: int = 0) -> Optional[BrainChoice]:
    """The best entry this phone can take, or None. The strong one only on a phone with comfortable memory; otherwise the light one."""
    strong, light = STRONG_CHOICE, LIGHT_CHOICE
    if isinstance(ram_bytes, int) and ram_bytes >= strong.comfortable_ram and fits(strong, ram_bytes, free_bytes, already_have).ok:
        return strong
    if fits(light, ram_bytes, free_bytes, already_have).ok:
        return light
    return None
