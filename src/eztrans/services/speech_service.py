from __future__ import annotations

import io
import threading
import wave
import winsound
from collections.abc import Callable
from pathlib import Path

import pyttsx3
from piper import PiperVoice, SynthesisConfig

from ..settings import AppSettings


class SpeechService:
    def __init__(self) -> None:
        self._settings = AppSettings()
        self._piper_voice: PiperVoice | None = None
        self._lock = threading.RLock()
        self._active_request_id = 0
        self._current_engine = None

    def list_voices(self) -> list[str]:
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            return [voice.name for voice in voices]
        except Exception:
            return []

    def configure(self, settings: AppSettings) -> None:
        with self._lock:
            self._settings = settings
            self._piper_voice = None

    def speak(
        self,
        text: str,
        lang_code: str,
        on_done: Callable[[str], None] | None = None,
    ) -> None:
        if not text.strip():
            return
        with self._lock:
            self._active_request_id += 1
            request_id = self._active_request_id
            engine = self._current_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
        try:
            winsound.PlaySound(None, 0)
        except Exception:
            pass
        threading.Thread(
            target=self._speak_request,
            args=(request_id, text, lang_code, on_done),
            daemon=True,
        ).start()

    def _speak_request(
        self,
        request_id: int,
        text: str,
        lang_code: str,
        on_done: Callable[[str], None] | None,
    ) -> None:
        try:
            if self._use_piper():
                self._speak_with_piper(request_id, text)
            else:
                self._speak_with_system(request_id, text, lang_code)
        except Exception:
            if on_done is not None:
                on_done("error")
            return
        if on_done is not None:
            with self._lock:
                state = "done" if request_id == self._active_request_id else "canceled"
            on_done(state)

    def _speak_with_system(self, request_id: int, text: str, lang_code: str) -> None:
        engine = pyttsx3.init()
        with self._lock:
            if request_id != self._active_request_id:
                return
            self._current_engine = engine
        voice_id = self._pick_voice_id(engine, lang_code)
        if voice_id:
            engine.setProperty("voice", voice_id)
        try:
            current_rate = engine.getProperty("rate")
            engine.setProperty("rate", max(110, int(current_rate) - 20))
        except Exception:
            pass
        engine.say(text)
        engine.runAndWait()
        with self._lock:
            if self._current_engine is engine:
                self._current_engine = None

    def _use_piper(self) -> bool:
        return (
            self._settings.speech_backend == "piper"
            and Path(self._settings.piper_model_path).is_file()
        )

    def _load_piper_voice(self) -> PiperVoice:
        if self._piper_voice is not None:
            return self._piper_voice
        config_path = self._settings.piper_config_path or None
        self._piper_voice = PiperVoice.load(
            self._settings.piper_model_path,
            config_path=config_path,
            use_cuda=False,
        )
        return self._piper_voice

    def _speak_with_piper(self, request_id: int, text: str) -> None:
        voice = self._load_piper_voice()
        syn_config = SynthesisConfig(length_scale=1.15, volume=1.0)
        wav_bytes = io.BytesIO()
        with wave.open(wav_bytes, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            sample_rate = 22050
            for idx, chunk in enumerate(voice.synthesize(text, syn_config=syn_config)):
                with self._lock:
                    if request_id != self._active_request_id:
                        return
                if idx == 0:
                    sample_rate = chunk.sample_rate
                    wav_file.setframerate(sample_rate)
                wav_file.writeframes(chunk.audio_int16_bytes)
            if wav_file.getnframes() == 0:
                wav_file.setframerate(sample_rate)
        with self._lock:
            if request_id != self._active_request_id:
                return
        winsound.PlaySound(wav_bytes.getvalue(), winsound.SND_MEMORY)

    def _pick_voice_id(self, engine, lang_code: str) -> str | None:
        try:
            voices = engine.getProperty("voices")
        except Exception:
            voices = []
        for voice in voices:
            voice_text = " ".join(getattr(voice, "languages", [])) + " " + voice.name
            lowered = voice_text.lower()
            if lang_code == "zh" and "zh" in lowered:
                return voice.id
            if lang_code == "en" and "en" in lowered:
                return voice.id
        return voices[0].id if voices else None
