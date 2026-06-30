from __future__ import annotations

import sys
from pathlib import Path


def app_source_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_resource_path(*parts: str) -> Path:
    return app_source_root().joinpath(*parts)
