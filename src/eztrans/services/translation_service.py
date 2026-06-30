from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests
from langdetect import DetectorFactory, LangDetectException, detect

from ..models import DictionaryEntry, ExampleSentence, HistoryRecord, TranslationResult
from ..settings import AppSettings
from ..utils import looks_like_single_term, utc_now_iso
from .dictionary_db import DictionaryDatabase
from .example_service import ExampleService
from .resource_manager import ResourceManager

DetectorFactory.seed = 0


class TranslationService:
    def __init__(
        self,
        db: DictionaryDatabase,
        resource_manager: ResourceManager,
        example_service: ExampleService,
        settings: AppSettings,
    ) -> None:
        self.db = db
        self.resource_manager = resource_manager
        self.example_service = example_service
        self.settings = settings
        self._resolved_runtime_cache: dict[str, tuple[str, str]] = {}

    def detect_language(self, text: str, preferred_target: str) -> str:
        if re.search(r"[\u4e00-\u9fff]", text):
            return "zh"
        try:
            code = detect(text)
        except LangDetectException:
            code = "en" if preferred_target != "en" else "zh"
        if code == "no":
            return "nb"
        if code not in {"zh", "en", "fi", "sv", "da", "nb"}:
            return "en" if preferred_target != "en" else "zh"
        return code

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        translation_mode: str,
    ) -> TranslationResult:
        cleaned = text.strip()
        detected = src_lang if src_lang != "auto" else self.detect_language(cleaned, tgt_lang)
        actual_source = detected
        is_term_lookup = looks_like_single_term(cleaned)
        lexical_entries = self._find_lexical_entries(cleaned, actual_source, tgt_lang) if is_term_lookup else []
        translated = self.resource_manager.translate_offline(cleaned, actual_source, tgt_lang)
        notes: list[str] = []
        provider_id = "offline-argos"
        provider_kind = "offline"
        use_ai = translation_mode == "ai"
        if use_ai:
            if not self.settings.openai_base_url.strip():
                raise RuntimeError("AI mode needs an API URL in Settings.")
            ai_result = self._translate_ai(cleaned, actual_source, tgt_lang)
            if ai_result:
                translated = ai_result["text"]
                provider_id = ai_result["provider"]
                provider_kind = "ai"
                notes.append("Translated with AI API.")
            else:
                notes.append("AI temporarily unavailable; fell back to local model.")
        if is_term_lookup and not lexical_entries and translated:
            lexical_entries = [
                DictionaryEntry(
                    src_lang=actual_source,
                    tgt_lang=tgt_lang,
                    headword=cleaned,
                    gloss=translated,
                    source="offline-translation",
                    score=0.5,
                )
            ]
        examples: list[ExampleSentence] = []
        if use_ai:
            examples = self._generate_ai_examples(cleaned, actual_source, tgt_lang, is_term_lookup)
            if not examples:
                notes.append("AI examples unavailable.")
        self.db.add_history_record(
            HistoryRecord(
                created_at=utc_now_iso(),
                input_text=cleaned,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                detected_lang=actual_source,
                translated_text=translated,
                provider_id=provider_id,
                provider_kind=provider_kind,
            )
        )
        return TranslationResult(
            input_text=cleaned,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            detected_lang=actual_source,
            translated_text=translated,
            lexical_entries=lexical_entries[:6],
            examples=examples[:2],
            provider_id=provider_id,
            provider_kind=provider_kind,
            notes=notes,
        )

    def _find_lexical_entries(self, text: str, src_lang: str, tgt_lang: str) -> list[DictionaryEntry]:
        entries = self.db.search_entries(src_lang, tgt_lang, text)
        if entries:
            return entries
        if src_lang != "en" and tgt_lang != "en":
            pivot_entries = self.db.search_entries(src_lang, "en", text)
            if pivot_entries:
                return pivot_entries
        return []

    def _generate_ai_examples(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        is_term_lookup: bool,
    ) -> list[ExampleSentence]:
        headers = self._build_openai_headers()
        if headers is None:
            return []
        mode_prompt = (
            "Create two short bilingual dictionary-style usage examples for the queried word or phrase. "
            "Keep the wording natural and the scenarios practical."
            if is_term_lookup
            else "Create two short bilingual example sentences that stay close to the user's topic, scene, and intent."
        )
        payload = self._call_openai_json(
            headers=headers,
            system_prompt=(
                "You create bilingual example sentences. "
                "Return JSON with key 'examples', an array of objects with keys "
                "'source_text' and 'target_text'. " + mode_prompt
            ),
            user_payload={
                "text": text,
                "source_language": src_lang,
                "target_language": tgt_lang,
            },
        )
        if not payload:
            return []
        rows = payload.get("examples", [])
        results: list[ExampleSentence] = []
        for row in rows[:2]:
            source_text = str(row.get("source_text", "")).strip()
            target_text = str(row.get("target_text", "")).strip()
            if source_text and target_text:
                results.append(
                    ExampleSentence(
                        src_lang=src_lang,
                        tgt_lang=tgt_lang,
                        source_text=source_text,
                        target_text=target_text,
                        source_name="ai",
                        quality_score=0.95,
                    )
                )
        return results

    def _translate_ai(self, text: str, src_lang: str, tgt_lang: str) -> dict | None:
        try:
            headers = self._build_openai_headers()
            if headers is None:
                return None
            payload = self._call_openai_json(
                headers=headers,
                system_prompt=(
                    "You are a translation engine. Translate the user text faithfully and completely. "
                    "Do not summarize. Return JSON with key 'translation'."
                ),
                user_payload={
                    "text": text,
                    "source_language": src_lang,
                    "target_language": tgt_lang,
                },
            )
            translated = str((payload or {}).get("translation", "")).strip()
            if translated:
                original_base = self._normalize_openai_base_url(self.settings.openai_base_url)
                runtime = self._resolved_runtime_cache.get(original_base)
                provider_model = runtime[1] if runtime else "auto"
                return {"provider": f"ai-{provider_model}", "text": translated}
        except Exception:
            return None
        return None

    def _build_openai_headers(self) -> dict[str, str] | None:
        if not self.settings.openai_base_url.strip():
            return None
        headers = {"Content-Type": "application/json"}
        if self.settings.openai_api_key:
            headers["Authorization"] = f"Bearer {self.settings.openai_api_key}"
        return headers

    def test_ai_connection(self) -> tuple[bool, str]:
        headers = self._build_openai_headers()
        if headers is None:
            return False, "AI API URL is missing."
        payload = self._call_openai_json(
            headers=headers,
            system_prompt="Return JSON with key 'status' and value 'ok'.",
            user_payload={"ping": True},
        )
        if not payload:
            return False, "No working OpenAI-compatible path/model combination was detected."
        original_base = self._normalize_openai_base_url(self.settings.openai_base_url)
        runtime = self._resolved_runtime_cache.get(original_base)
        if not runtime:
            return False, "Connection test did not find a reusable runtime."
        base_url, model_name = runtime
        return True, f"Connected.\nBase URL: {base_url}\nModel: {model_name}"

    def _call_openai_json(
        self,
        headers: dict[str, str],
        system_prompt: str,
        user_payload: dict,
    ) -> dict | None:
        original_base = self._normalize_openai_base_url(self.settings.openai_base_url)
        candidate_runtimes = self._candidate_ai_runtimes(headers)
        for base_url, model_name in candidate_runtimes:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
            for use_json_mode in (True, False):
                message = self._post_chat_completion(
                    base_url=base_url,
                    headers=headers,
                    model_name=model_name,
                    messages=messages,
                    use_json_mode=use_json_mode,
                )
                if not message:
                    continue
                payload = self._extract_json_payload(message)
                if payload is not None:
                    self._resolved_runtime_cache[original_base] = (base_url, model_name)
                    return payload
        return None

    def _normalize_openai_base_url(self, url: str) -> str:
        base_url = url.strip().rstrip("/")
        for suffix in ["/chat/completions", "/completions", "/models"]:
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        return base_url

    def _candidate_openai_base_urls(self, url: str) -> list[str]:
        base_url = self._normalize_openai_base_url(url)
        if not base_url:
            return []
        candidates = [base_url]
        parsed = urlparse(base_url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")

        if path in {"", "/"}:
            candidates.extend(
                [
                    base_url.rstrip("/") + "/v1",
                    base_url.rstrip("/") + "/api/v1",
                    base_url.rstrip("/") + "/openai/v1",
                ]
            )
            if "bigmodel" in host or "zhipu" in host or "glm" in host:
                candidates.append(base_url.rstrip("/") + "/api/paas/v4")
            if "dashscope" in host or "aliyun" in host or "qwen" in host:
                candidates.append(base_url.rstrip("/") + "/compatible-mode/v1")
            if "openrouter" in host:
                candidates.append(base_url.rstrip("/") + "/api/v1")
        return list(dict.fromkeys(candidates))

    def _candidate_ai_runtimes(self, headers: dict[str, str]) -> list[tuple[str, str]]:
        original_base = self._normalize_openai_base_url(self.settings.openai_base_url)
        cached_runtime = self._resolved_runtime_cache.get(original_base)
        runtimes: list[tuple[str, str]] = []
        if cached_runtime:
            runtimes.append(cached_runtime)
        explicit_model = self.settings.openai_model.strip()
        for base_url in self._candidate_openai_base_urls(self.settings.openai_base_url):
            if explicit_model:
                runtime = (base_url, explicit_model)
                if runtime not in runtimes:
                    runtimes.append(runtime)
            try:
                response = requests.get(base_url + "/models", headers=headers, timeout=20)
                response.raise_for_status()
                payload = response.json()
                models = payload.get("data", [])
                model_ids = [item.get("id", "") for item in models if item.get("id")]
                for model_id in self._rank_models(model_ids, base_url):
                    runtime = (base_url, model_id)
                    if runtime not in runtimes:
                        runtimes.append(runtime)
            except Exception:
                continue
        return runtimes

    def _rank_models(self, model_ids: list[str], base_url: str) -> list[str]:
        if not model_ids:
            return []
        host = urlparse(base_url).netloc.lower()

        def first_match(candidates: list[str]) -> str | None:
            lowered = [(model_id, model_id.lower()) for model_id in model_ids]
            for needle in candidates:
                for original, lowered_id in lowered:
                    if needle in lowered_id:
                        return original
            return None

        ranked: list[str] = []
        def add_match(candidates: list[str]) -> None:
            match = first_match(candidates)
            if match and match not in ranked:
                ranked.append(match)

        if "deepseek" in host:
            add_match(["deepseek-chat", "deepseek-v3", "deepseek"])
        if "bigmodel" in host or "zhipu" in host:
            add_match(["glm-4.5-flash", "glm-4-flash", "glm-4.5", "glm-4"])
        if "dashscope" in host or "aliyun" in host:
            add_match(["qwen-plus", "qwen-turbo", "qwen-max", "qwen"])
        add_match(["translate", "chat", "flash", "turbo", "qwen", "glm", "deepseek", "gpt"])
        for model_id in model_ids:
            lowered = model_id.lower()
            if any(token in lowered for token in ["embedding", "rerank", "tts", "whisper", "audio"]):
                continue
            if model_id not in ranked:
                ranked.append(model_id)
        for model_id in model_ids:
            if model_id not in ranked:
                ranked.append(model_id)
        return ranked

    def _post_chat_completion(
        self,
        base_url: str,
        headers: dict[str, str],
        model_name: str,
        messages: list[dict[str, str]],
        use_json_mode: bool,
    ) -> str | None:
        try:
            payload = {
                "model": model_name,
                "messages": messages,
            }
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            response = requests.post(
                base_url + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=40,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception:
            return None

    def _extract_json_payload(self, content: str) -> dict | None:
        text = content.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except Exception:
                return None
        object_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if object_match:
            try:
                return json.loads(object_match.group(1))
            except Exception:
                return None
        return None
