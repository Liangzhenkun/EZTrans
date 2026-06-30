from __future__ import annotations

import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import keyboard
from PIL import Image, ImageDraw
from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayItem

from .config import AppPaths, SettingsStore
from .constants import (
    APP_NAME,
    APP_AUTHOR,
    APP_RELEASE_DATE,
    APP_VERSION,
    DEFAULT_WINDOW_GEOMETRY,
    FULL_WINDOW_GEOMETRY,
    LANGUAGE_LABELS,
    LOCAL_MODEL_PROFILES,
    SUPPORTED_LANGUAGE_CODES,
    TRANSLATION_MODE_LABELS,
)
from .models import TranslationResult
from .runtime import app_resource_path
from .services.dictionary_db import DictionaryDatabase
from .services.example_service import ExampleService
from .services.resource_manager import ResourceManager
from .services.speech_service import SpeechService
from .services.translation_service import TranslationService
from .services.update_service import UpdateService
from .settings import AppSettings


class EZTransApp:
    def __init__(
        self,
        root: tk.Tk,
        paths: AppPaths,
        settings_store: SettingsStore,
        db: DictionaryDatabase,
        example_service: ExampleService,
        resource_manager: ResourceManager,
        speech_service: SpeechService,
        update_service: UpdateService,
    ) -> None:
        self.root = root
        self.paths = paths
        self.settings_store = settings_store
        self.settings = settings_store.load()
        self.settings.compact_view = True
        self.db = db
        self.example_service = example_service
        self.resource_manager = resource_manager
        self.speech_service = speech_service
        self.update_service = update_service
        self.speech_service.configure(self.settings)
        self.translation_service = TranslationService(
            db,
            resource_manager,
            example_service,
            self.settings,
        )
        self._translation_job: str | None = None
        self._tray_icon: TrayIcon | None = None
        self._registered_hotkey_handle = None
        self._settings_window: tk.Toplevel | None = None
        self._last_input_snapshot = ""
        self._translate_request_id = 0
        self._activity_job: str | None = None
        self._activity_kind: str | None = None
        self._activity_text = ""
        self._activity_spinner_index = 0
        self._spinner_frames = ["◐", "◓", "◑", "◒"]
        self._build_root()
        self._build_widgets()
        self._configure_tray()
        self._register_hotkey()
        self._bootstrap_resources_async()
        self._start_input_watchdog()
        if self.settings.auto_check_updates and self.resource_manager.is_online():
            self.root.after(1800, lambda: self.check_updates_async(silent=True))

    def _build_root(self) -> None:
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry(self.settings.geometry)
        self.root.minsize(390, 280)
        self.root.configure(bg="#f4f1ea")
        self.root.attributes("-topmost", self.settings.topmost)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

    def _build_widgets(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f1ea")
        style.configure("TLabel", background="#f4f1ea", foreground="#1b1b1b")
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Muted.TLabel", background="#f4f1ea", foreground="#5f5a52", font=("Segoe UI", 9))

        self.main_frame = ttk.Frame(self.root, padding=12)
        self.main_frame.pack(fill="both", expand=True)

        self.source_var = tk.StringVar(value=self.settings.source_lang)
        self.target_var = tk.StringVar(value=self.settings.target_lang)
        self.topmost_var = tk.BooleanVar(value=self.settings.topmost)
        self.mode_var = tk.StringVar(value=self._mode_label(self.settings.translation_mode))
        self.compact_view_var = tk.BooleanVar(value=self.settings.compact_view)
        self.pin_label_var = tk.StringVar(value="")
        self.compact_mode_hint_var = tk.StringVar(value="")
        self.activity_var = tk.StringVar(value="")
        self.detected_var = tk.StringVar(value="")

        title_bar = ttk.Frame(self.main_frame)
        title_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(title_bar, text="EZTrans", style="Header.TLabel").pack(side="left")
        self.status_var = tk.StringVar(value="Initializing...")
        ttk.Button(title_bar, text="Settings", width=9, command=self.open_settings_window).pack(side="right")
        self.expand_button = ttk.Button(title_bar, text="", width=9, command=self.toggle_compact_view)
        self.expand_button.pack(side="right", padx=(0, 6))

        self.compact_mode_hint_label = ttk.Label(
            self.main_frame,
            textvariable=self.compact_mode_hint_var,
            style="Muted.TLabel",
            anchor="w",
        )

        self.full_controls_frame = ttk.Frame(self.main_frame)
        self.full_controls_frame.pack(fill="x", pady=(0, 8))

        self.source_combo = ttk.Combobox(
            self.full_controls_frame,
            state="readonly",
            width=14,
            values=[f"{code} - {LANGUAGE_LABELS[code]}" for code in SUPPORTED_LANGUAGE_CODES],
        )
        self.source_combo.pack(side="left")
        self.source_combo.set(f"{self.settings.source_lang} - {LANGUAGE_LABELS[self.settings.source_lang]}")
        self.source_combo.bind("<<ComboboxSelected>>", lambda _: self._on_language_change())

        self.target_combo = ttk.Combobox(
            self.full_controls_frame,
            state="readonly",
            width=16,
            values=[f"{code} - {LANGUAGE_LABELS[code]}" for code in SUPPORTED_LANGUAGE_CODES if code != "auto"],
        )
        self.target_combo.pack(side="left", padx=6)
        self.target_combo.set(f"{self.settings.target_lang} - {LANGUAGE_LABELS[self.settings.target_lang]}")
        self.target_combo.bind("<<ComboboxSelected>>", lambda _: self._on_language_change())

        ttk.Button(self.full_controls_frame, text="Swap", command=self.swap_languages).pack(side="left")
        self.mode_combo = ttk.Combobox(
            self.full_controls_frame,
            state="readonly",
            width=11,
            textvariable=self.mode_var,
            values=[self._mode_label(key) for key in TRANSLATION_MODE_LABELS],
        )
        self.mode_combo.pack(side="right")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _: self._on_mode_change())

        input_header = ttk.Frame(self.main_frame)
        input_header.pack(fill="x")
        ttk.Label(input_header, text="Input", style="Header.TLabel").pack(side="left")
        ttk.Button(input_header, text="Clear", width=8, command=self.clear_text).pack(side="right")

        self.input_text = ScrolledText(
            self.main_frame,
            height=3,
            font=("Segoe UI", 11),
            wrap="word",
            bd=1,
            relief="solid",
        )
        self.input_text.pack(fill="x", pady=(4, 10))
        self.input_text.bind("<KeyRelease>", self._on_input_changed)
        self.input_text.focus_set()

        self.compact_actions_frame = ttk.Frame(self.main_frame)
        self.compact_actions_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(self.compact_actions_frame, text="🔊", width=3, command=self.speak_output).pack(side="left")

        self.full_actions_frame = ttk.Frame(self.main_frame)
        self.full_actions_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(self.full_actions_frame, text="Translate", command=self.translate_now).pack(side="left")
        ttk.Button(self.full_actions_frame, text="Copy", command=self.copy_output).pack(side="left", padx=4)
        ttk.Button(self.full_actions_frame, text="🔊", width=3, command=self.speak_output).pack(side="left")
        ttk.Button(self.full_actions_frame, text="History", command=self.open_history_window).pack(side="left", padx=(4, 0))
        self.pin_checkbox = tk.Checkbutton(
            self.full_actions_frame,
            textvariable=self.pin_label_var,
            variable=self.topmost_var,
            command=self.toggle_topmost,
            bg="#f4f1ea",
            activebackground="#f4f1ea",
            fg="#1b1b1b",
            selectcolor="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        self.pin_checkbox.pack(side="right")

        ttk.Label(self.main_frame, text="Main Translation", style="Header.TLabel").pack(anchor="w")
        self.translation_box = ScrolledText(
            self.main_frame,
            height=3,
            font=("Segoe UI", 11),
            wrap="word",
            bd=1,
            relief="solid",
        )
        self.translation_box.pack(fill="x", pady=(4, 8))
        self.translation_box.insert("1.0", "Ready.")

        self.footer_frame = ttk.Frame(self.main_frame)
        self.footer_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(self.footer_frame, textvariable=self.activity_var, style="Muted.TLabel", anchor="w").pack(fill="x")
        ttk.Label(
            self.footer_frame,
            textvariable=self.status_var,
            style="Muted.TLabel",
            anchor="w",
            justify="left",
        ).pack(fill="x")

        self.detail_frame = ttk.Frame(self.main_frame)
        self.detail_frame.pack(fill="both", expand=True)
        self.lexical_section = ttk.Frame(self.detail_frame)
        self.lexical_header = ttk.Label(self.lexical_section, text="Dictionary", style="Header.TLabel")
        self.lexical_header.pack(anchor="w")
        self.lexical_box = ScrolledText(self.lexical_section, height=4, font=("Segoe UI", 10), wrap="word", bd=1, relief="solid")
        self.lexical_box.pack(fill="x", pady=(4, 8))
        self.lexical_box.configure(state="disabled")

        self.examples_section = ttk.Frame(self.detail_frame)
        self.examples_header = ttk.Label(self.examples_section, text="Examples", style="Header.TLabel")
        self.examples_header.pack(anchor="w")
        self.examples_box = ScrolledText(self.examples_section, height=5, font=("Segoe UI", 10), wrap="word", bd=1, relief="solid")
        self.examples_box.pack(fill="both", expand=True, pady=(4, 10))
        self.examples_box.configure(state="disabled")

        self._update_pin_button()
        self._update_compact_mode_hint()
        self._apply_view_mode(initial=True)

    def _configure_tray(self) -> None:
        try:
            image = Image.new("RGB", (64, 64), "#d9c7a1")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#2b3a42")
            draw.text((20, 20), "EZ", fill="#f4f1ea")
            menu = TrayMenu(
                TrayItem("Show / Hide", lambda: self.root.after(0, self.toggle_visibility)),
                TrayItem("Quit", lambda: self.root.after(0, self.quit_app)),
            )
            self._tray_icon = TrayIcon(APP_NAME, image, APP_NAME, menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception as exc:
            self.status_var.set(f"Tray unavailable: {exc}")

    def _register_hotkey(self) -> None:
        try:
            if self._registered_hotkey_handle is not None:
                keyboard.remove_hotkey(self._registered_hotkey_handle)
            self._registered_hotkey_handle = keyboard.add_hotkey(
                self.settings.hotkey,
                lambda: self.root.after(0, self.show_window),
            )
        except Exception as exc:
            self.status_var.set(f"Hotkey disabled: {exc}")

    def _bootstrap_resources_async(self) -> None:
        def worker() -> None:
            try:
                notes = self.resource_manager.bootstrap(self.settings, self._set_status_threadsafe)
                if notes:
                    self._set_status_threadsafe(" | ".join(notes))
                else:
                    self._set_status_threadsafe("Ready.")
            except Exception as exc:
                self._set_status_threadsafe(f"Bootstrap failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_input_changed(self, _event=None) -> None:
        if self._translation_job is not None:
            self.root.after_cancel(self._translation_job)
        self._translation_job = self.root.after(120, self.translate_now)

    def _start_input_watchdog(self) -> None:
        def tick() -> None:
            current = self.input_text.get("1.0", "end").strip()
            if current != self._last_input_snapshot:
                self._last_input_snapshot = current
                if self._translation_job is not None:
                    self.root.after_cancel(self._translation_job)
                if current:
                    self._translation_job = self.root.after(120, self.translate_now)
                else:
                    self._clear_activity()
                    self._set_translation_text("Ready.")
                    self._set_lexical_entries([])
                    self._set_examples([])
                    self._update_result_status(message="Idle.")
            try:
                self.root.after(120, tick)
            except RuntimeError:
                return

        self.root.after(120, tick)

    def _selected_source_code(self) -> str:
        return self.source_combo.get().split(" - ", 1)[0]

    def _selected_target_code(self) -> str:
        return self.target_combo.get().split(" - ", 1)[0]

    def _mode_label(self, mode_key: str) -> str:
        return TRANSLATION_MODE_LABELS.get(mode_key, TRANSLATION_MODE_LABELS["local"])

    def _sync_main_mode_display(self, mode_key: str) -> None:
        label = self._mode_label(mode_key)
        self.mode_var.set(label)
        try:
            self.mode_combo.set(label)
        except Exception:
            pass
        self._update_compact_mode_hint()

    def _selected_mode(self) -> str:
        selected = self.mode_var.get()
        for key, label in TRANSLATION_MODE_LABELS.items():
            if label == selected:
                return key
        return "local"

    def _profile_label(self, profile_key: str) -> str:
        profile = LOCAL_MODEL_PROFILES.get(profile_key) or LOCAL_MODEL_PROFILES["compact"]
        return profile["label"]

    def _profile_key_from_label(self, label: str) -> str:
        for key, profile in LOCAL_MODEL_PROFILES.items():
            if profile["label"] == label:
                return key
        return "compact"

    def _help_lines(self) -> list[str]:
        return [
            "1. Compact mode is the small always-ready window.",
            "2. Expand shows language, history, dictionary, and AI examples.",
            "3. Local Model uses only installed offline packages on this PC.",
            "4. AI API uses your OpenAI-compatible endpoint such as DeepSeek or GLM.",
            "5. Dictionary appears only for word or phrase lookups.",
            "6. Examples appear only in AI API mode.",
            "7. Pin keeps EZTrans above other windows.",
        ]

    def open_about_dialog(self, parent: tk.Misc | None = None) -> None:
        self._open_info_dialog(
            title="About EZTrans",
            lines=[
                f"Version: {APP_VERSION}",
                f"Author: {APP_AUTHOR}",
                f"Email: zhenkun_liang@163.com",
                f"Release date: {APP_RELEASE_DATE}",
                "",
                "EZTrans is a lightweight desktop translator focused on quick local use with optional AI enhancement.",
            ],
            parent=parent or self.root,
        )

    def open_help_dialog(self, parent: tk.Misc | None = None) -> None:
        self._open_info_dialog(
            title="EZTrans Help",
            lines=self._help_lines(),
            parent=parent or self.root,
        )

    def _open_info_dialog(self, title: str, lines: list[str], parent: tk.Misc) -> None:
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.geometry("460x260")
        dialog.configure(bg="#f4f1ea")
        dialog.transient(parent)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        body = ScrolledText(frame, height=10, font=("Segoe UI", 9), wrap="word", bd=1, relief="solid")
        body.pack(fill="both", expand=True)
        body.insert("1.0", "\n".join(lines))
        body.configure(state="disabled")

        def close_dialog() -> None:
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()
            try:
                parent.grab_set()
                parent.focus_force()
            except Exception:
                pass

        ttk.Button(frame, text="Close", command=close_dialog).pack(anchor="e", pady=(10, 0))
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.grab_set()
        dialog.focus_force()

    def _update_pin_button(self) -> None:
        self.pin_label_var.set("Pin")
        return
        self.pin_label_var.set("✓ Pin" if self.topmost_var.get() else "Pin")

    def _update_compact_mode_hint(self) -> None:
        mode_label = self._mode_label(self.settings.translation_mode)
        target_label = LANGUAGE_LABELS.get(self._selected_target_code(), self._selected_target_code())
        self.compact_mode_hint_var.set(f"Current mode: {mode_label} | source: auto-detect | target: {target_label}")

    def _refresh_detail_visibility(self, has_lexical_entries: bool | None = None, has_examples: bool | None = None) -> None:
        if self.compact_view_var.get():
            return
        show_lexical = bool(has_lexical_entries)
        show_examples = self._selected_mode() == "ai" and bool(has_examples)

        if show_lexical:
            if not self.lexical_section.winfo_manager():
                self.lexical_section.pack(fill="x", pady=(0, 4))
        else:
            self.lexical_section.pack_forget()

        if show_examples:
            if not self.examples_section.winfo_manager():
                self.examples_section.pack(fill="both", expand=True)
        else:
            self.examples_section.pack_forget()

        if show_lexical or show_examples:
            self.detail_frame.pack_configure(fill="both", expand=True)
        else:
            self.detail_frame.pack_configure(fill="x", expand=False)

        self._resize_window(self._geometry_size(FULL_WINDOW_GEOMETRY)[0], self._full_window_height())

    def _apply_view_mode(self, initial: bool = False) -> None:
        compact = self.compact_view_var.get()
        self.settings.compact_view = compact
        self.expand_button.configure(text="Expand" if compact else "Compact")
        compact_width, compact_height = self._geometry_size(DEFAULT_WINDOW_GEOMETRY)
        full_width, _ = self._geometry_size(FULL_WINDOW_GEOMETRY)

        if compact:
            self.full_controls_frame.pack_forget()
            self.full_actions_frame.pack_forget()
            self.detail_frame.pack_forget()
            if not self.compact_actions_frame.winfo_manager():
                self.compact_actions_frame.pack(fill="x", pady=(0, 10), before=self.translation_box)
            self.input_text.configure(height=3)
            self.translation_box.configure(height=3)
            self.lexical_section.pack_forget()
            self.examples_section.pack_forget()
            if not self.compact_mode_hint_label.winfo_manager():
                self.compact_mode_hint_label.pack(fill="x", pady=(0, 8), after=self.main_frame.winfo_children()[0])
            if not self.footer_frame.winfo_manager():
                self.footer_frame.pack(fill="x", pady=(0, 8), after=self.translation_box)
            self._resize_window(compact_width, compact_height, initial=initial)
        else:
            self.compact_actions_frame.pack_forget()
            if not self.full_controls_frame.winfo_manager():
                self.full_controls_frame.pack(fill="x", pady=(0, 8), after=self.main_frame.winfo_children()[0])
            if not self.full_actions_frame.winfo_manager():
                self.full_actions_frame.pack(fill="x", pady=(0, 10), before=self.translation_box)
            if not self.detail_frame.winfo_manager():
                self.detail_frame.pack(fill="both", expand=True)
            if not self.footer_frame.winfo_manager():
                self.footer_frame.pack(fill="x", pady=(0, 8), after=self.translation_box)
            self.input_text.configure(height=4)
            self.translation_box.configure(height=4)
            self.compact_mode_hint_label.pack_forget()
            lexical_has_content = bool(self.lexical_box.get("1.0", "end").strip())
            examples_has_content = bool(self.examples_box.get("1.0", "end").strip()) and self.examples_box.get("1.0", "end").strip() != "No examples yet."
            self._refresh_detail_visibility(lexical_has_content, examples_has_content)
            self._resize_window(full_width, self._full_window_height(), initial=initial)
        self._save_settings()

    def _geometry_size(self, geometry: str) -> tuple[int, int]:
        size_part = geometry.split("+", 1)[0]
        width_text, _, height_text = size_part.partition("x")
        return int(width_text), int(height_text)

    def _full_window_height(self) -> int:
        _, default_height = self._geometry_size(FULL_WINDOW_GEOMETRY)
        has_lexical = self.lexical_section.winfo_manager()
        has_examples = self.examples_section.winfo_manager()
        if has_lexical and has_examples:
            return max(default_height + 140, 600)
        if has_lexical or has_examples:
            return max(default_height + 60, 520)
        return default_height

    def _resize_window(self, width: int, height: int, initial: bool = False) -> None:
        current_x = self.root.winfo_x() if self.root.winfo_ismapped() else 120
        current_y = self.root.winfo_y() if self.root.winfo_ismapped() else 120
        geometry = f"{width}x{height}+{current_x}+{current_y}"
        if initial and self.settings.geometry:
            try:
                _, _, position = self.settings.geometry.partition("+")
                if position:
                    x_str, _, y_str = position.partition("+")
                    if x_str and y_str:
                        geometry = f"{width}x{height}+{int(x_str)}+{int(y_str)}"
            except Exception:
                pass
        self.root.geometry(geometry)
        self.settings.geometry = geometry

    def toggle_compact_view(self) -> None:
        self.compact_view_var.set(not self.compact_view_var.get())
        self._apply_view_mode()

    def _on_language_change(self) -> None:
        self.settings.source_lang = self._selected_source_code()
        self.settings.target_lang = self._selected_target_code()
        self._save_settings()
        self.translate_now()

    def _on_mode_change(self) -> None:
        selected_mode = self._selected_mode()
        self.settings.translation_mode = selected_mode
        self._sync_main_mode_display(selected_mode)
        self._save_settings()
        self.translate_now()

    def _request_retranslate(self, delay_ms: int = 0) -> None:
        if self._translation_job is not None:
            try:
                self.root.after_cancel(self._translation_job)
            except Exception:
                pass
            self._translation_job = None
        if delay_ms <= 0:
            self.translate_now()
        else:
            self._translation_job = self.root.after(delay_ms, self.translate_now)

    def _save_settings(self) -> None:
        self.settings.topmost = self.topmost_var.get()
        self.settings.compact_view = self.compact_view_var.get()
        self.settings.translation_mode = self._selected_mode()
        self.settings.geometry = self.root.geometry()
        self.settings_store.save(self.settings)

    def _set_activity(self, kind: str, text: str, use_spinner: bool = False) -> None:
        self._activity_kind = kind
        self._activity_text = text
        self._activity_spinner_index = 0
        if self._activity_job is not None:
            try:
                self.root.after_cancel(self._activity_job)
            except Exception:
                pass
            self._activity_job = None
        if not text:
            self.activity_var.set("")
            return
        if use_spinner:
            self._tick_activity_spinner()
            return
        self.activity_var.set(text)

    def _clear_activity(self, kind: str | None = None) -> None:
        if kind is not None and self._activity_kind != kind:
            return
        if self._activity_job is not None:
            try:
                self.root.after_cancel(self._activity_job)
            except Exception:
                pass
            self._activity_job = None
        self._activity_kind = None
        self._activity_text = ""
        self.activity_var.set("")

    def _tick_activity_spinner(self) -> None:
        if not self._activity_text:
            self.activity_var.set("")
            self._activity_job = None
            return
        frame = self._spinner_frames[self._activity_spinner_index % len(self._spinner_frames)]
        self._activity_spinner_index += 1
        self.activity_var.set(f"{frame} {self._activity_text}")
        self._activity_job = self.root.after(140, self._tick_activity_spinner)

    def _update_result_status(self, result: TranslationResult | None = None, message: str = "") -> None:
        if message:
            self.detected_var.set(message)
            self.status_var.set(message)
            return
        if result is None:
            self.detected_var.set("")
            self.status_var.set("")
            return
        target_label = LANGUAGE_LABELS.get(result.tgt_lang, result.tgt_lang)
        if result.src_lang == "auto" or self.compact_view_var.get():
            source_summary = f"Auto-detected: {LANGUAGE_LABELS.get(result.detected_lang, result.detected_lang)} -> {target_label}"
        else:
            source_summary = f"Source: {LANGUAGE_LABELS.get(result.detected_lang, result.detected_lang)} -> {target_label}"
        provider_summary = f"{result.provider_kind}:{result.provider_id}"
        summary = f"{source_summary} | {provider_summary}"
        if result.notes:
            summary += " | " + " | ".join(result.notes)
        self.detected_var.set(summary)
        self.status_var.set(summary)

    def translate_now(self) -> None:
        text = self.input_text.get("1.0", "end").strip()
        self._last_input_snapshot = text
        if not text:
            self._set_translation_text("Ready.")
            self._set_lexical_entries([])
            self._set_examples([])
            self._clear_activity()
            self._update_result_status(message="Idle.")
            return
        self._set_activity("translating", "Translating...", use_spinner=True)
        src_lang = "auto" if self.compact_view_var.get() else self._selected_source_code()
        tgt_lang = self._selected_target_code()
        translation_mode = self._selected_mode()
        self._translate_request_id += 1
        request_id = self._translate_request_id

        def worker() -> None:
            try:
                result = self.translation_service.translate(text, src_lang, tgt_lang, translation_mode)
                self.root.after(
                    0,
                    lambda request_id=request_id, result=result: self._render_result_if_latest(request_id, result),
                )
            except Exception as exc:
                self.root.after(
                    0,
                    lambda request_id=request_id, exc=exc: self._render_error_if_latest(request_id, exc),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _render_result_if_latest(self, request_id: int, result: TranslationResult) -> None:
        if request_id != self._translate_request_id:
            return
        self._render_result(result)

    def _render_error_if_latest(self, request_id: int, exc: Exception) -> None:
        if request_id != self._translate_request_id:
            return
        self._clear_activity("translating")
        self._set_translation_text(f"[Error] {exc}")
        self._update_result_status(message=f"Translation failed: {exc}")

    def _render_result(self, result: TranslationResult) -> None:
        self._clear_activity("translating")
        self._set_translation_text(result.translated_text or "(no result)")
        self._set_lexical_entries(result.lexical_entries)
        self._set_examples(result.examples)
        self._update_result_status(result=result)

    def _set_translation_text(self, text: str) -> None:
        self.translation_box.delete("1.0", "end")
        self.translation_box.insert("1.0", text)

    def _set_lexical_entries(self, entries) -> None:
        self.lexical_box.configure(state="normal")
        self.lexical_box.delete("1.0", "end")
        if entries:
            lines = []
            for idx, entry in enumerate(entries, start=1):
                line = f"{idx}. {entry.headword}\n   {entry.gloss}"
                if entry.reading:
                    line += f"\n   reading: {entry.reading}"
                if entry.pos:
                    line += f"\n   type: {entry.pos}"
                lines.append(line)
            self.lexical_box.insert("1.0", "\n\n".join(lines))
        self.lexical_box.configure(state="disabled")
        current_examples = self.examples_box.get("1.0", "end").strip()
        has_examples = bool(current_examples) and current_examples != "No examples yet."
        self._refresh_detail_visibility(bool(entries), has_examples)

    def _set_examples(self, examples) -> None:
        self.examples_box.configure(state="normal")
        self.examples_box.delete("1.0", "end")
        if not examples:
            self.examples_box.insert("1.0", "No examples yet.")
        else:
            lines = []
            for idx, example in enumerate(examples, start=1):
                lines.append(
                    f"{idx}. {example.source_text}\n   {example.target_text}\n   source: {example.source_name}\n"
                )
            self.examples_box.insert("1.0", "\n".join(lines))
        self.examples_box.configure(state="disabled")
        current_lexical = self.lexical_box.get("1.0", "end").strip()
        self._refresh_detail_visibility(bool(current_lexical), bool(examples))

    def swap_languages(self) -> None:
        source = self._selected_source_code()
        target = self._selected_target_code()
        if source == "auto":
            source = "en" if target != "en" else "zh"
        self.source_combo.set(f"{target} - {LANGUAGE_LABELS[target]}")
        self.target_combo.set(f"{source} - {LANGUAGE_LABELS[source]}")
        self._on_language_change()

    def clear_text(self) -> None:
        self.input_text.delete("1.0", "end")
        self._clear_activity()
        self._set_translation_text("Ready.")
        self._set_lexical_entries([])
        self._set_examples([])
        self._update_result_status(message="Cleared.")

    def copy_output(self) -> None:
        text = self.translation_box.get("1.0", "end").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied translation.")

    def speak_output(self) -> None:
        text = self.translation_box.get("1.0", "end").strip()
        if not text or text == "Ready.":
            return
        lang = self._selected_target_code()
        self._set_activity("speaking", "Speaking...")

        def handle_done(state: str) -> None:
            def update() -> None:
                self._clear_activity("speaking")
                if state == "error":
                    self.status_var.set("Speech failed.")
                elif state == "canceled":
                    self.status_var.set("Speech canceled.")

            try:
                self.root.after(0, update)
            except RuntimeError:
                return

        self.speech_service.speak(text, lang, on_done=handle_done)

    def toggle_topmost(self) -> None:
        enabled = self.topmost_var.get()
        self.root.attributes("-topmost", enabled)
        self.settings.topmost = enabled
        self._update_pin_button()
        self._save_settings()
        self.status_var.set("Pinned on top." if enabled else "Pin disabled.")

    def refresh_resources(self) -> None:
        def worker() -> None:
            try:
                notes = self.resource_manager.ensure_local_profile(self.settings.local_model_profile)
                text = " | ".join(notes) if notes else "Resources already ready."
                self._set_status_threadsafe(text)
            except Exception as exc:
                self._set_status_threadsafe(f"Resource refresh failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _install_local_profile_async(self, profile_key: str, rerun_translation: bool = False) -> None:
        def worker() -> None:
            try:
                notes = self.resource_manager.ensure_local_profile(profile_key, progress=self._set_status_threadsafe)
                if notes:
                    self._set_status_threadsafe(" | ".join(notes))
                else:
                    self._set_status_threadsafe("Selected local model package is ready.")
                if rerun_translation:
                    try:
                        self.root.after(0, lambda: self._request_retranslate())
                    except RuntimeError:
                        return
            except Exception as exc:
                self._set_status_threadsafe(f"Local model install failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def open_settings_window(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("Settings")
        window.geometry("560x500")
        window.configure(bg="#f4f1ea")
        window.transient(self.root)
        window.grab_set()
        window.focus_force()
        self._settings_window = window
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)

        mode_var = tk.StringVar(value=self._mode_label(self.settings.translation_mode))
        api_url = tk.StringVar(value=self.settings.openai_base_url)
        api_key = tk.StringVar(value=self.settings.openai_api_key)
        hotkey_var = tk.StringVar(value=self.settings.hotkey)
        speech_backend_var = tk.StringVar(value=self.settings.speech_backend)
        profile_var = tk.StringVar(value=self._profile_label(self.settings.local_model_profile))
        installed_pairs = self.resource_manager.get_installed_argos_pairs()
        profile_status_var = tk.StringVar(
            value=f"Installed pairs: {len(installed_pairs)} | current package: {self._profile_label(self.settings.local_model_profile)}"
        )

        ttk.Label(frame, text="Translation mode").grid(row=0, column=0, sticky="w", pady=4)
        mode_combo = ttk.Combobox(
            frame,
            state="readonly",
            textvariable=mode_var,
            values=[self._mode_label(key) for key in TRANSLATION_MODE_LABELS],
        )
        mode_combo.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="AI API URL").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=api_url, width=36).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="AI API key").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=api_key, width=36, show="*").grid(row=2, column=1, sticky="ew", pady=4)
        ai_test_row = ttk.Frame(frame)
        ai_test_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Button(ai_test_row, text="Test AI", command=lambda: self._test_ai_from_settings(window, api_url, api_key)).pack(side="left")
        ttk.Label(frame, text="Local model package").grid(row=4, column=0, sticky="w", pady=4)
        profile_combo = ttk.Combobox(
            frame,
            state="readonly",
            textvariable=profile_var,
            values=[profile["label"] for profile in LOCAL_MODEL_PROFILES.values()],
        )
        profile_combo.grid(row=4, column=1, sticky="ew", pady=4)

        install_row = ttk.Frame(frame)
        install_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(install_row, textvariable=profile_status_var).pack(side="left")
        ttk.Button(
            install_row,
            text="Install / Update",
            command=lambda: self._install_local_profile_async(self._profile_key_from_label(profile_var.get())),
        ).pack(side="right")

        ttk.Label(frame, text="Global hotkey").grid(row=6, column=0, sticky="w", pady=4)
        hotkey_entry = ttk.Entry(frame, textvariable=hotkey_var, width=24, state="readonly")
        hotkey_entry.grid(row=6, column=1, sticky="w", pady=4)
        ttk.Button(frame, text="Record", command=lambda: self._open_hotkey_recorder(window, hotkey_var)).grid(
            row=6, column=1, sticky="e", pady=4
        )
        ttk.Label(frame, text="Speech backend").grid(row=7, column=0, sticky="w", pady=4)
        speech_combo = ttk.Combobox(
            frame,
            state="readonly",
            textvariable=speech_backend_var,
            values=["system", "piper"],
        )
        speech_combo.grid(row=7, column=1, sticky="ew", pady=4)
        voice_row = ttk.Frame(frame)
        voice_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(2, 4))
        ttk.Label(voice_row, text="Neural voice file").pack(side="left")
        ttk.Button(voice_row, text="Import Piper Voice", command=lambda: self._import_piper_voice(window)).pack(side="right")
        ttk.Button(voice_row, text="Clear", command=self._clear_piper_voice).pack(side="right", padx=6)
        frame.columnconfigure(1, weight=1)

        about_row = ttk.Frame(frame)
        about_row.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(about_row, text="About", command=lambda: self.open_about_dialog(window)).pack(side="left")
        ttk.Button(about_row, text="Help", command=lambda: self.open_help_dialog(window)).pack(side="left", padx=6)
        ttk.Label(
            about_row,
            text=f"Version {APP_VERSION}",
        ).pack(side="right")

        def close_settings() -> None:
            try:
                window.grab_release()
            except Exception:
                pass
            self._settings_window = None
            window.destroy()
            try:
                self.root.focus_force()
            except Exception:
                pass

        def save_settings() -> None:
            previous_mode = self.settings.translation_mode
            previous_api_url = self.settings.openai_base_url.strip()
            for key, label in TRANSLATION_MODE_LABELS.items():
                if label == mode_var.get():
                    selected_mode = key
                    break
            else:
                selected_mode = previous_mode
            self.settings.translation_mode = selected_mode
            self.settings.local_model_profile = self._profile_key_from_label(profile_var.get())
            self.settings.hotkey = hotkey_var.get().strip()
            self.settings.speech_backend = speech_backend_var.get().strip()
            self.settings.openai_api_key = api_key.get().strip()
            self.settings.openai_base_url = api_url.get().strip()
            if self.settings.openai_base_url != previous_api_url:
                self.settings.openai_model = ""
            self.settings_store.save(self.settings)
            self._sync_main_mode_display(self.settings.translation_mode)
            self.speech_service.configure(self.settings)
            self._register_hotkey()
            close_settings()
            self.status_var.set("Settings saved.")
            if self.settings.translation_mode == "local":
                self._install_local_profile_async(self.settings.local_model_profile, rerun_translation=True)
            else:
                self._request_retranslate()

        window.protocol("WM_DELETE_WINDOW", close_settings)
        ttk.Button(frame, text="Save", command=save_settings).grid(row=10, column=0, pady=12, sticky="w")

    def _test_ai_from_settings(
        self,
        parent: tk.Toplevel,
        api_url_var: tk.StringVar,
        api_key_var: tk.StringVar,
    ) -> None:
        self.status_var.set("Testing AI API...")

        def worker() -> None:
            try:
                temp_settings = AppSettings(**self.settings.to_dict())
                temp_settings.openai_base_url = api_url_var.get().strip()
                temp_settings.openai_api_key = api_key_var.get().strip()
                temp_service = TranslationService(
                    self.db,
                    self.resource_manager,
                    self.example_service,
                    temp_settings,
                )
                ok, message = temp_service.test_ai_connection()
                self.root.after(
                    0,
                    lambda ok=ok, message=message: self._show_ai_test_result(parent, ok, message),
                )
            except Exception as exc:
                self.root.after(
                    0,
                    lambda exc=exc: self._show_ai_test_result(parent, False, f"Unexpected error: {exc}"),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_ai_test_result(self, parent: tk.Toplevel, ok: bool, message: str) -> None:
        if ok:
            self.status_var.set("AI API test passed.")
            self._open_info_dialog("AI Test Result", [message], parent)
            return
        self.status_var.set("AI API test failed.")
        self._open_info_dialog(
            "AI Test Result",
            [
                "Connection failed.",
                "",
                message,
                "",
                "Check API URL, API key, and whether the provider exposes an OpenAI-compatible chat endpoint.",
            ],
            parent,
        )

    def _open_hotkey_recorder(self, parent: tk.Toplevel, target_var: tk.StringVar) -> None:
        dialog = tk.Toplevel(parent)
        dialog.title("Record Hotkey")
        dialog.geometry("320x120")
        dialog.transient(parent)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Press the shortcut you want.").pack(anchor="w")
        preview_var = tk.StringVar(value=target_var.get() or "Press keys...")
        preview = ttk.Entry(frame, textvariable=preview_var, state="readonly", width=30)
        preview.pack(fill="x", pady=10)

        def on_keypress(event) -> str:
            key = event.keysym.lower()
            if key in {"shift_l", "shift_r", "control_l", "control_r", "alt_l", "alt_r"}:
                return "break"
            parts: list[str] = []
            if event.state & 0x0004:
                parts.append("ctrl")
            if event.state & 0x0001:
                parts.append("shift")
            if event.state & 0x0008 or event.state & 0x20000:
                parts.append("alt")
            normalized_key = {
                "return": "enter",
                "escape": "esc",
                "prior": "pageup",
                "next": "pagedown",
            }.get(key, key)
            if normalized_key not in parts:
                parts.append(normalized_key)
            combo = "+".join(parts)
            preview_var.set(combo)
            target_var.set(combo)
            dialog.after(120, dialog.destroy)
            return "break"

        dialog.bind("<KeyPress>", on_keypress)
        dialog.focus_force()

    def _import_piper_voice(self, parent: tk.Toplevel) -> None:
        model_path = filedialog.askopenfilename(
            parent=parent,
            title="Choose Piper model (.onnx)",
            filetypes=[("ONNX Model", "*.onnx")],
        )
        if not model_path:
            return
        config_path = model_path + ".json"
        if not Path(config_path).exists():
            messagebox.showerror("Piper", "Matching .onnx.json config file was not found.")
            return
        piper_dir = self.paths.resources_dir / "piper"
        piper_dir.mkdir(parents=True, exist_ok=True)
        target_model = piper_dir / "voice.onnx"
        target_config = piper_dir / "voice.onnx.json"
        shutil.copy2(model_path, target_model)
        shutil.copy2(config_path, target_config)
        self.settings.piper_model_path = str(target_model)
        self.settings.piper_config_path = str(target_config)
        self.settings_store.save(self.settings)
        self.speech_service.configure(self.settings)
        self.status_var.set("Piper voice imported.")

    def _clear_piper_voice(self) -> None:
        self.settings.piper_model_path = ""
        self.settings.piper_config_path = ""
        self.settings_store.save(self.settings)
        self.speech_service.configure(self.settings)
        self.status_var.set("Piper voice cleared.")

    def open_history_window(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("History")
        window.geometry("760x420")
        window.configure(bg="#f4f1ea")
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)

        columns = ("time", "src", "tgt", "input", "translation")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for name, label, width in [
            ("time", "Time", 150),
            ("src", "Src", 50),
            ("tgt", "Tgt", 50),
            ("input", "Input", 230),
            ("translation", "Translation", 230),
        ]:
            tree.heading(name, text=label)
            tree.column(name, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        for item in self.db.list_history(limit=300):
            tree.insert(
                "",
                "end",
                values=(
                    item.created_at.replace("T", " ")[:19],
                    item.detected_lang,
                    item.tgt_lang,
                    item.input_text[:80],
                    item.translated_text[:80],
                ),
            )

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))

        def export_csv() -> None:
            default_name = f"eztrans-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
            path = filedialog.asksaveasfilename(
                parent=window,
                title="Export history as CSV",
                defaultextension=".csv",
                initialfile=default_name,
                filetypes=[("CSV", "*.csv"), ("JSON", "*.json")],
            )
            if not path:
                return
            self.db.export_history(Path(path))
            self.status_var.set(f"History exported to {path}")

        def export_json() -> None:
            default_name = f"eztrans-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            path = filedialog.asksaveasfilename(
                parent=window,
                title="Export history as JSON",
                defaultextension=".json",
                initialfile=default_name,
                filetypes=[("JSON", "*.json"), ("CSV", "*.csv")],
            )
            if not path:
                return
            self.db.export_history(Path(path))
            self.status_var.set(f"History exported to {path}")

        ttk.Button(buttons, text="Export CSV", command=export_csv).pack(side="left")
        ttk.Button(buttons, text="Export JSON", command=export_json).pack(side="left", padx=6)

    def check_updates_async(self, silent: bool = False) -> None:
        def worker() -> None:
            try:
                app_update = self.update_service.check_app_update(self.settings)
                model_updates = self.resource_manager.check_model_updates()
                self.root.after(0, lambda: self._handle_update_results(app_update, model_updates, silent))
            except Exception as exc:
                self._set_status_threadsafe(f"Update check failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _handle_update_results(self, app_update, model_updates, silent: bool) -> None:
        messages = []
        if app_update.has_update:
            messages.append(f"App update: {app_update.current_version} -> {app_update.latest_version}")
        if model_updates:
            messages.extend(f"{item.identifier}: {item.current_version} -> {item.latest_version}" for item in model_updates)
        if not messages:
            if not silent:
                self.status_var.set("No updates found.")
            return
        self.status_var.set(" | ".join(messages))
        if app_update.has_update and app_update.download_url and not silent:
            should_download = messagebox.askyesno(
                "App Update",
                f"Download {app_update.latest_version} now?",
            )
            if should_download:
                self._download_app_update_async(app_update)
        if model_updates and not silent:
            should_apply = messagebox.askyesno(
                "Model Updates",
                "Install updated offline translation models now?",
            )
            if should_apply:
                self._apply_model_updates_async()

    def _download_app_update_async(self, app_update) -> None:
        def worker() -> None:
            try:
                target = self.update_service.download_app_update(app_update, self.paths.temp_dir / "updates")
                self._set_status_threadsafe(f"App update downloaded to {target}")
            except Exception as exc:
                self._set_status_threadsafe(f"App update download failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_model_updates_async(self) -> None:
        def worker() -> None:
            try:
                notes = self.resource_manager.apply_model_updates()
                self._set_status_threadsafe(" | ".join(notes) if notes else "Models already up to date.")
            except Exception as exc:
                self._set_status_threadsafe(f"Model update failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def hide_to_tray(self) -> None:
        self.settings.geometry = self.root.geometry()
        self._save_settings()
        self.root.withdraw()
        self.status_var.set("Hidden to tray.")

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", self.topmost_var.get())
        self.input_text.focus_set()

    def toggle_visibility(self) -> None:
        if self.root.state() == "withdrawn":
            self.show_window()
        else:
            self.hide_to_tray()

    def quit_app(self) -> None:
        self.settings.geometry = self.root.geometry()
        self._save_settings()
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        if self._tray_icon is not None:
            self._tray_icon.stop()
        self.root.destroy()

    def _set_status_threadsafe(self, message: str) -> None:
        try:
            self.root.after(0, lambda message=message: self.status_var.set(message))
        except RuntimeError:
            return


def build_app(root: tk.Tk) -> EZTransApp:
    paths = AppPaths()
    store = SettingsStore(paths)
    db = DictionaryDatabase(paths.dictionary_db)
    example_service = ExampleService(db, app_resource_path("resources", "seed_examples.json"))
    resource_manager = ResourceManager(paths, db, example_service)
    speech_service = SpeechService()
    update_service = UpdateService(resource_manager)
    return EZTransApp(
        root=root,
        paths=paths,
        settings_store=store,
        db=db,
        example_service=example_service,
        resource_manager=resource_manager,
        speech_service=speech_service,
        update_service=update_service,
    )
