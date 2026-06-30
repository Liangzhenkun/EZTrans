from __future__ import annotations

APP_NAME = "EZTrans"
APP_VERSION = "0.1.1"
APP_AUTHOR = "OpenAI Codex"
APP_RELEASE_DATE = "2026-07-01"

LANGUAGE_LABELS = {
    "auto": "Auto Detect",
    "zh": "Chinese",
    "en": "English",
    "fi": "Finnish",
    "sv": "Swedish",
    "da": "Danish",
    "nb": "Norwegian Bokmal",
}

SUPPORTED_LANGUAGE_CODES = ["auto", "zh", "en", "fi", "sv", "da", "nb"]
OFFLINE_LANGUAGE_CODES = ["zh", "en", "fi", "sv", "da", "nb"]

TRANSLATION_MODE_LABELS = {
    "local": "Local Model",
    "ai": "AI API",
}

TATOEBA_LANGUAGE_CODES = {
    "zh": "cmn",
    "en": "eng",
    "fi": "fin",
    "sv": "swe",
    "da": "dan",
    "nb": "nob",
}

RESOURCE_KEYS = {
    "cedict": "dictionary:cedict",
    "examples": "examples:seed",
}

DEFAULT_WINDOW_GEOMETRY = "420x320+120+120"
FULL_WINDOW_GEOMETRY = "720x460+120+120"

LOCAL_MODEL_PROFILES = {
    "compact": {
        "label": "Compact: zh <-> en (~145 MB)",
        "description": "Chinese and English only. Fastest setup and smallest download.",
        "pairs": [("zh", "en"), ("en", "zh")],
        "download_mb": 145,
    },
    "balanced": {
        "label": "Balanced: zh/en + fi/da/nb (~554 MB)",
        "description": "Adds Finnish, Danish, and Norwegian for broader daily use.",
        "pairs": [
            ("zh", "en"),
            ("en", "zh"),
            ("en", "fi"),
            ("fi", "en"),
            ("en", "da"),
            ("da", "en"),
            ("en", "nb"),
            ("nb", "en"),
        ],
        "download_mb": 554,
    },
    "full": {
        "label": "Full Nordic: zh/en + fi/sv/da/nb (~756 MB)",
        "description": "Includes the Swedish pair as well. Largest local package.",
        "pairs": [
            ("zh", "en"),
            ("en", "zh"),
            ("en", "fi"),
            ("fi", "en"),
            ("en", "sv"),
            ("sv", "en"),
            ("en", "da"),
            ("da", "en"),
            ("en", "nb"),
            ("nb", "en"),
        ],
        "download_mb": 756,
    },
}

GITHUB_API_BASE = "https://api.github.com"
ARGOS_INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
TATOEBA_SEARCH_URL = "https://tatoeba.org/en/api_v0/search"

FREEDICT_BASE_URL = "https://download.freedict.org/dictionaries"

FREEDICT_PAIRS = {
    ("en", "fi"): ("eng-fin", "2024.10.10"),
    ("fi", "en"): ("fin-eng", "2024.10.10"),
    ("en", "sv"): ("eng-swe", "2025.11.23"),
    ("sv", "en"): ("swe-eng", "0.2"),
    ("en", "da"): ("eng-dan", "0.1.0"),
    ("da", "en"): ("dan-eng", "0.3.1"),
    ("en", "nb"): ("eng-nor", "2025.11.23"),
}
