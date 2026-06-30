from __future__ import annotations

import gzip
import io
import re
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from ..constants import CEDICT_URL, FREEDICT_BASE_URL, FREEDICT_PAIRS
from ..models import DictionaryEntry

CEDICT_LINE_RE = re.compile(
    r"^(?P<trad>\S+)\s+(?P<simp>\S+)\s+\[(?P<pinyin>[^\]]*)\]\s+/(?P<gloss>.+)/$"
)


def _clean_gloss_text(gloss: str) -> str:
    text = re.sub(r"\s+", " ", gloss).strip()
    return text[:300]


def parse_cedict_lines(lines: list[str]) -> tuple[list[DictionaryEntry], list[DictionaryEntry]]:
    zh_to_en: list[DictionaryEntry] = []
    en_to_zh: list[DictionaryEntry] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        match = CEDICT_LINE_RE.match(line)
        if not match:
            continue
        simplified = match.group("simp")
        pinyin = match.group("pinyin")
        gloss_items = [item.strip() for item in match.group("gloss").split("/") if item.strip()]
        if not gloss_items:
            continue
        joined_gloss = "; ".join(gloss_items[:6])
        zh_to_en.append(
            DictionaryEntry(
                src_lang="zh",
                tgt_lang="en",
                headword=simplified,
                gloss=joined_gloss,
                reading=pinyin,
                source="cedict",
                score=1.0,
            )
        )
        for gloss in gloss_items[:10]:
            normalized = _clean_gloss_text(gloss)
            if len(normalized) > 80 or not normalized:
                continue
            en_to_zh.append(
                DictionaryEntry(
                    src_lang="en",
                    tgt_lang="zh",
                    headword=normalized,
                    gloss=simplified,
                    reading=pinyin,
                    source="cedict",
                    score=0.8,
                )
            )
    return zh_to_en, en_to_zh


def download_and_parse_cedict() -> tuple[list[DictionaryEntry], list[DictionaryEntry]]:
    response = requests.get(CEDICT_URL, timeout=120)
    response.raise_for_status()
    payload = gzip.decompress(response.content).decode("utf-8", errors="ignore")
    return parse_cedict_lines(payload.splitlines())


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_entry_texts(entry: ET.Element) -> tuple[str, str, str]:
    headword = ""
    pos = ""
    glosses: list[str] = []
    for node in entry.iter():
        tag = _strip_ns(node.tag)
        text = (node.text or "").strip()
        if tag == "orth" and not headword and text:
            headword = text
        elif tag == "pos" and not pos and text:
            pos = text
        elif tag == "quote" and text and node.attrib.get("type") == "trans":
            glosses.append(text)
    if not glosses:
        for node in entry.iter():
            if _strip_ns(node.tag) == "def":
                text = (node.text or "").strip()
                if text:
                    glosses.append(text)
    return headword, pos, "; ".join(glosses[:6])


def _freedict_archive_url(src_lang: str, tgt_lang: str) -> tuple[str, str]:
    folder, version = FREEDICT_PAIRS[(src_lang, tgt_lang)]
    filename = f"freedict-{folder}-{version}.src.tar.xz"
    return f"{FREEDICT_BASE_URL}/{folder}/{version}/{filename}", version


def download_and_parse_freedict(src_lang: str, tgt_lang: str) -> tuple[str, list[DictionaryEntry]]:
    url, version = _freedict_archive_url(src_lang, tgt_lang)
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    archive = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:xz")
    tei_member = next((m for m in archive.getmembers() if m.name.endswith(".tei")), None)
    if tei_member is None:
        raise RuntimeError(f"No TEI file found in FreeDict archive for {src_lang}->{tgt_lang}")
    tei_bytes = archive.extractfile(tei_member).read()
    root = ET.fromstring(tei_bytes)
    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    entries: list[DictionaryEntry] = []
    for entry in root.findall(".//tei:entry", namespace):
        headword, pos, gloss = _extract_entry_texts(entry)
        if not headword or not gloss:
            continue
        entries.append(
            DictionaryEntry(
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                headword=headword,
                gloss=gloss[:300],
                pos=pos,
                source="freedict",
                score=1.0,
            )
        )
    return version, entries

