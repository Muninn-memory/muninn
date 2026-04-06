#!/usr/bin/env python3
"""
Ravens Control Panel GUI for Muninn and Huginn.

Requirements addressed:
- Native dark GUI (customtkinter)
- Select bot/command, configure args
- Run subprocess with real-time output
- Forward stdin for interactive modes
- Persist command history in .ravens_history.json
- Click history to re-execute
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter.messagebox as messagebox

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "customtkinter is not installed. Run launch_ravens.bat to auto-install it."
    ) from exc


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
CREATE_NEW_PROCESS_GROUP = 0x00000200 if IS_WIN else 0
PROJECT_DIR = Path(__file__).resolve().parent
HISTORY_FILE = PROJECT_DIR / ".ravens_history.json"
MAX_HISTORY = 50
OUTPUT_SNIPPET_CHARS = 2000
DEFAULT_DISPATCH_ENDPOINT = "http://localhost:8000/task"


def resolve_python_executable() -> str:
    """Prefer local venv python, then current python (fallback)."""
    if IS_WIN:
        candidate = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
        if candidate.exists():
            return str(candidate)
    exe = Path(sys.executable)
    if exe.stem.lower() == "pythonw":
        alt = exe.with_name("python.exe")
        if alt.exists():
            return str(alt)
    return sys.executable


@dataclass(frozen=True)
class ArgDef:
    key: str
    label: str
    kind: str  # combo|entry
    flag: str | None = None
    required: bool = False
    default: str = ""
    values: tuple[str, ...] = ()
    placeholder: str = ""


@dataclass(frozen=True)
class CommandDef:
    description: str
    base_args: tuple[str, ...]
    interactive: bool
    args: tuple[ArgDef, ...]


COMMANDS: dict[str, dict[str, CommandDef]] = {
    "Muninn": {
        "chat": CommandDef(
            description="Conversation loop with model selection and optional session id.",
            base_args=("cli.py", "muninn", "chat"),
            interactive=True,
            args=(
                ArgDef(
                    key="model",
                    label="Model",
                    kind="combo",
                    flag="--model",
                    default="deepseek",
                    values=("deepseek", "claude"),
                ),
                ArgDef(
                    key="deepseek_mode",
                    label="DeepSeek Mode",
                    kind="combo",
                    flag="--deepseek-mode",
                    default="chat",
                    values=("chat", "reasoner"),
                ),
                ArgDef(
                    key="session",
                    label="Session UUID (optional)",
                    kind="entry",
                    flag="--session",
                    placeholder="Leave empty for new session",
                ),
            ),
        ),
        "memory list": CommandDef(
            description="List stored memories from Supabase.",
            base_args=("cli.py", "muninn", "memory", "list"),
            interactive=False,
            args=(
                ArgDef(
                    key="type",
                    label="Type (optional)",
                    kind="entry",
                    flag="--type",
                    placeholder="note | preference | result",
                ),
            ),
        ),
        "memory search": CommandDef(
            description="Search stored memories by text.",
            base_args=("cli.py", "muninn", "memory", "search"),
            interactive=False,
            args=(
                ArgDef(
                    key="query",
                    label="Search text",
                    kind="entry",
                    required=True,
                    placeholder="Example: meeting yesterday",
                ),
            ),
        ),
        "mcp server": CommandDef(
            description="Run MCP stdio server (debug/integration use).",
            base_args=("mcp_server.py",),
            interactive=True,
            args=(),
        ),
    },
    "Huginn": {
        "server": CommandDef(
            description="Run Huginn FastAPI server (webhooks + /task).",
            base_args=("-m", "uvicorn", "huginn.server:app", "--host", "0.0.0.0", "--port", "8000"),
            interactive=False,
            args=(),
        ),
        "terminal chat": CommandDef(
            description="Terminal REPL for web search and summaries.",
            base_args=("cli.py", "huginn", "chat"),
            interactive=True,
            args=(),
        ),
        "telegram bot": CommandDef(
            description="Run Telegram bot in polling mode.",
            base_args=("huginn.py",),
            interactive=False,
            args=(),
        ),
    },
}


class HistoryManager:
    def __init__(self, path: Path, max_entries: int = MAX_HISTORY):
        self.path = path
        self.max_entries = max_entries
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self.entries = [e for e in raw if isinstance(e, dict)]
        except Exception:
            self.entries = []

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.entries[: self.max_entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_started(
        self,
        *,
        bot: str,
        command: str,
        arg_values: dict[str, str],
        argv: list[str],
        cmdline: str,
    ) -> str:
        entry_id = uuid.uuid4().hex
        entry = {
            "id": entry_id,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "bot": bot,
            "command": command,
            "arg_values": arg_values,
            "argv": argv,
            "cmdline": cmdline,
            "exit_code": None,
            "output_snippet": "",
        }
        self.entries.insert(0, entry)
        self.entries = self.entries[: self.max_entries]
        self._save()
        return entry_id

    def finish(self, entry_id: str, exit_code: int, output_snippet: str) -> None:
        for entry in self.entries:
            if entry.get("id") == entry_id:
                entry["exit_code"] = exit_code
                entry["output_snippet"] = output_snippet[-OUTPUT_SNIPPET_CHARS:]
                break
        self._save()


class RavensApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Ravens Control Panel")
        self.geometry("1140x760")
        self.minsize(940, 620)

        self.python_path = resolve_python_executable()
        self.history = HistoryManager(HISTORY_FILE)

        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[tuple[str, str | int]] = queue.Queue()
        self.current_history_id: str | None = None
        self.current_command_name: str | None = None
        self.current_output: str = ""
        self.pending_run_from_history: dict[str, Any] | None = None
        self.done_guard = False

        self.arg_widgets: dict[str, ctk.CTkBaseClass] = {}

        self.bot_var = ctk.StringVar(value=next(iter(COMMANDS.keys())))
        self.command_var = ctk.StringVar(value="")
        self.status_var = ctk.StringVar(value="Ready.")
        self.dispatch_channel_var = ctk.StringVar(value="interno")
        self.dispatch_busy = False

        self._build_ui()
        self._configure_output_tags()
        self._on_bot_change()
        self._refresh_history()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._poll_output_queue)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, width=320, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(7, weight=1)
        left.grid_propagate(False)

        ctk.CTkLabel(
            left,
            text="Ravens",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(20, 2))
        ctk.CTkLabel(
            left,
            text="Muninn + Huginn Control Panel",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 18))

        ctk.CTkLabel(
            left,
            text="BOT",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray",
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 4))

        bot_row = ctk.CTkFrame(left, fg_color="transparent")
        bot_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 12))
        bot_row.grid_columnconfigure((0, 1), weight=1)
        for idx, bot in enumerate(COMMANDS.keys()):
            ctk.CTkRadioButton(
                bot_row,
                text=bot,
                variable=self.bot_var,
                value=bot,
                command=self._on_bot_change,
            ).grid(row=0, column=idx, sticky="w", padx=8)

        ctk.CTkLabel(
            left,
            text="COMMAND",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray",
        ).grid(row=4, column=0, sticky="w", padx=18, pady=(0, 4))

        self.command_combo = ctk.CTkComboBox(
            left,
            variable=self.command_var,
            command=self._on_command_change,
        )
        self.command_combo.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 6))

        self.description_label = ctk.CTkLabel(
            left,
            text="",
            wraplength=270,
            justify="left",
            font=ctk.CTkFont(size=11),
            text_color="#8a8a8a",
        )
        self.description_label.grid(row=6, column=0, sticky="nw", padx=18, pady=(0, 4))

        self.args_frame = ctk.CTkScrollableFrame(
            left,
            label_text="ARGUMENTS",
            label_font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.args_frame.grid(row=7, column=0, sticky="nsew", padx=10, pady=(0, 8))
        self.args_frame.grid_columnconfigure(0, weight=1)

        action_row = ctk.CTkFrame(left, fg_color="transparent")
        action_row.grid(row=8, column=0, sticky="ew", padx=12, pady=12)
        action_row.grid_columnconfigure((0, 1), weight=1)

        self.run_button = ctk.CTkButton(
            action_row,
            text="Run",
            command=self._run_current_selection,
            height=40,
            fg_color="#1f6f4a",
            hover_color="#175437",
        )
        self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.stop_button = ctk.CTkButton(
            action_row,
            text="Stop",
            command=self._stop_clicked,
            height=40,
            state="disabled",
            fg_color="#7a2626",
            hover_color="#5e1d1d",
        )
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 12), pady=10)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=4)
        right.grid_rowconfigure(4, weight=1)

        out_head = ctk.CTkFrame(right, fg_color="transparent")
        out_head.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        out_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            out_head,
            text="OUTPUT",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            out_head,
            text="Clear",
            width=70,
            height=26,
            command=self._clear_output,
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=1, padx=(4, 0))
        ctk.CTkButton(
            out_head,
            text="Copy",
            width=70,
            height=26,
            command=self._copy_output,
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=2, padx=(4, 0))

        self.output_box = ctk.CTkTextbox(
            right,
            state="disabled",
            wrap="word",
            fg_color="#0d0d0d",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.output_box.grid(row=1, column=0, sticky="nsew")

        ctk.CTkLabel(
            right,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", pady=(4, 2))

        stdin_row = ctk.CTkFrame(right, fg_color="transparent")
        stdin_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        stdin_row.grid_columnconfigure(0, weight=1)
        self.stdin_entry = ctk.CTkEntry(
            stdin_row,
            placeholder_text="Send stdin to active process",
            state="disabled",
        )
        self.stdin_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stdin_entry.bind("<Return>", self._send_stdin)
        self.stdin_button = ctk.CTkButton(
            stdin_row,
            text="Send",
            width=90,
            state="disabled",
            command=self._send_stdin,
        )
        self.stdin_button.grid(row=0, column=1)

        self.bottom_tabs = ctk.CTkTabview(right)
        self.bottom_tabs.grid(row=4, column=0, sticky="nsew", pady=(0, 2))

        history_tab = self.bottom_tabs.add("History")
        history_tab.grid_columnconfigure(0, weight=1)
        history_tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            history_tab,
            text="Click an entry to re-run",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(2, 2), padx=4)

        self.history_frame = ctk.CTkScrollableFrame(history_tab, fg_color="#101010", height=160)
        self.history_frame.grid(row=1, column=0, sticky="nsew")
        self.history_frame.grid_columnconfigure(0, weight=1)

        dispatch_tab = self.bottom_tabs.add("Dispatch")
        dispatch_tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dispatch_tab,
            text="Task",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        self.dispatch_task_box = ctk.CTkTextbox(dispatch_tab, height=90, wrap="word")
        self.dispatch_task_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

        channel_row = ctk.CTkFrame(dispatch_tab, fg_color="transparent")
        channel_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))
        channel_row.grid_columnconfigure((1, 3), weight=1)
        ctk.CTkLabel(channel_row, text="Channel", width=70).grid(row=0, column=0, sticky="w")
        self.dispatch_channel_combo = ctk.CTkComboBox(
            channel_row,
            values=["interno", "telegram", "whatsapp", "instagram"],
            variable=self.dispatch_channel_var,
        )
        self.dispatch_channel_combo.grid(row=0, column=1, sticky="ew", padx=(6, 12))
        ctk.CTkLabel(channel_row, text="Sender", width=70).grid(row=0, column=2, sticky="w")
        self.dispatch_sender_entry = ctk.CTkEntry(
            channel_row,
            placeholder_text="chat/user id (optional)",
        )
        self.dispatch_sender_entry.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        endpoint_row = ctk.CTkFrame(dispatch_tab, fg_color="transparent")
        endpoint_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        endpoint_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(endpoint_row, text="Endpoint", width=70).grid(row=0, column=0, sticky="w")
        self.dispatch_endpoint_entry = ctk.CTkEntry(endpoint_row)
        self.dispatch_endpoint_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.dispatch_endpoint_entry.insert(0, DEFAULT_DISPATCH_ENDPOINT)

        self.dispatch_button = ctk.CTkButton(
            dispatch_tab,
            text="Enviar para Huginn",
            command=self._dispatch_task_clicked,
            fg_color="#2b5da8",
            hover_color="#204a86",
            height=36,
        )
        self.dispatch_button.grid(row=4, column=0, sticky="ew", padx=8, pady=(2, 8))

    def _configure_output_tags(self) -> None:
        text = self.output_box._textbox
        text.tag_configure("cmd", foreground="#2cc4d3")
        text.tag_configure("stdin", foreground="#74d37a")
        text.tag_configure("info", foreground="#f7b252")
        text.tag_configure("err", foreground="#f26a6a")
        text.tag_configure("norm", foreground="#dddddd")

    def _on_bot_change(self) -> None:
        bot = self.bot_var.get()
        commands = list(COMMANDS[bot].keys())
        self.command_combo.configure(values=commands)
        self.command_var.set(commands[0])
        self._on_command_change()

    def _on_command_change(self, _unused: str | None = None) -> None:
        bot = self.bot_var.get()
        name = self.command_var.get()
        cfg = COMMANDS[bot][name]
        self.description_label.configure(text=cfg.description)
        self._build_arg_fields(cfg.args)

    def _build_arg_fields(self, args: tuple[ArgDef, ...]) -> None:
        for child in self.args_frame.winfo_children():
            child.destroy()
        self.arg_widgets.clear()

        if not args:
            ctk.CTkLabel(
                self.args_frame,
                text="No extra arguments for this command.",
                text_color="#666666",
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=6, pady=10)
            return

        for arg in args:
            ctk.CTkLabel(
                self.args_frame,
                text=arg.label,
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=6, pady=(10, 2))

            if arg.kind == "combo":
                widget = ctk.CTkComboBox(self.args_frame, values=list(arg.values))
                if arg.default:
                    widget.set(arg.default)
                elif arg.values:
                    widget.set(arg.values[0])
            else:
                widget = ctk.CTkEntry(
                    self.args_frame,
                    placeholder_text=arg.placeholder,
                )
                if arg.default:
                    widget.insert(0, arg.default)

            widget.pack(fill="x", padx=6, pady=(0, 2))
            self.arg_widgets[arg.key] = widget

    def _collect_arg_values(self) -> tuple[dict[str, str] | None, str | None]:
        bot = self.bot_var.get()
        command = self.command_var.get()
        cfg = COMMANDS[bot][command]
        values: dict[str, str] = {}

        for arg in cfg.args:
            widget = self.arg_widgets[arg.key]
            value = widget.get().strip()
            if arg.required and not value:
                return None, f"Required field is empty: {arg.label}"
            values[arg.key] = value
        return values, None

    def _build_command(self, arg_values: dict[str, str]) -> list[str]:
        bot = self.bot_var.get()
        command = self.command_var.get()
        cfg = COMMANDS[bot][command]

        # Force UTF-8 mode in child Python processes on Windows so accents
        # from Rich/CLI output are decoded consistently in this GUI.
        argv = [self.python_path, "-X", "utf8", "-u", *cfg.base_args]
        for arg in cfg.args:
            value = arg_values.get(arg.key, "").strip()
            if not value:
                continue
            if arg.flag:
                argv.extend([arg.flag, value])
            else:
                argv.append(value)
        return argv

    def _format_cmdline(self, argv: list[str]) -> str:
        return " ".join(self._quote(a) for a in argv)

    @staticmethod
    def _quote(value: str) -> str:
        if any(ch in value for ch in (" ", "\t", '"')):
            return '"' + value.replace('"', '\\"') + '"'
        return value

    def _load_subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env_file = PROJECT_DIR / ".env"
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                env.setdefault(key, value)
        # Keep child subprocess stdio in UTF-8 to avoid mojibake/replacement chars.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _run_current_selection(self) -> None:
        if self._is_running():
            return
        arg_values, error = self._collect_arg_values()
        if arg_values is None:
            self._write_output(f"[ERROR] {error}\n", "err")
            return

        argv = self._build_command(arg_values)
        self._start_process(argv=argv, arg_values=arg_values)

    def _start_process(self, *, argv: list[str], arg_values: dict[str, str]) -> None:
        bot = self.bot_var.get()
        command = self.command_var.get()
        cfg = COMMANDS[bot][command]

        self.current_output = ""
        self.current_command_name = command
        self.done_guard = False

        cmdline = self._format_cmdline(argv)
        started_at = datetime.now().strftime("%H:%M:%S")
        self._write_output(f"\n[{started_at}] > {cmdline}\n", "cmd")

        self.current_history_id = self.history.add_started(
            bot=bot,
            command=command,
            arg_values=arg_values,
            argv=argv,
            cmdline=cmdline,
        )
        self._refresh_history()

        creationflags = CREATE_NO_WINDOW
        if IS_WIN:
            creationflags |= CREATE_NEW_PROCESS_GROUP

        try:
            self.process = subprocess.Popen(
                argv,
                cwd=str(PROJECT_DIR),
                env=self._load_subprocess_env(),
                stdin=subprocess.PIPE if cfg.interactive else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except Exception as exc:
            self._write_output(f"[ERROR] Failed to start process: {exc}\n", "err")
            self.status_var.set("Failed to start process.")
            self.process = None
            return

        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        if cfg.interactive:
            self.stdin_entry.configure(state="normal")
            self.stdin_button.configure(state="normal")
            self.stdin_entry.focus()
        else:
            self.stdin_entry.configure(state="disabled")
            self.stdin_button.configure(state="disabled")

        self.status_var.set(f"Running: {bot} > {command}")
        threading.Thread(target=self._reader_thread, daemon=True).start()

    def _reader_thread(self) -> None:
        if not self.process or not self.process.stdout:
            return
        try:
            while True:
                chunk = self.process.stdout.read(1)
                if chunk == "":
                    break
                self.output_queue.put(("line", chunk))
        except Exception as exc:
            self.output_queue.put(("line", f"\n[reader-error] {exc}\n"))

        exit_code = self.process.wait()
        self.output_queue.put(("done", exit_code))

    def _poll_output_queue(self) -> None:
        try:
            while True:
                kind, payload = self.output_queue.get_nowait()
                if kind == "line":
                    text = str(payload)
                    self.current_output = (self.current_output + text)[-OUTPUT_SNIPPET_CHARS:]
                    self._write_output(text, "norm")
                elif kind == "done" and not self.done_guard:
                    self.done_guard = True
                    self._on_process_done(int(payload))
                elif kind == "dispatch_done":
                    self._on_dispatch_done(str(payload))
        except queue.Empty:
            pass
        self.after(60, self._poll_output_queue)

    def _on_process_done(self, exit_code: int) -> None:
        symbol = "OK" if exit_code == 0 else "ERR"
        self._write_output(f"\n--- {symbol} process finished (exit {exit_code}) ---\n\n", "info")
        self.status_var.set(f"Finished with exit {exit_code}.")

        if self.current_history_id:
            self.history.finish(
                self.current_history_id,
                exit_code=exit_code,
                output_snippet=self.current_output,
            )
            self._refresh_history()
            self.current_history_id = None

        self.process = None
        self.stdin_entry.configure(state="disabled")
        self.stdin_button.configure(state="disabled")
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

        if self.pending_run_from_history is not None:
            entry = self.pending_run_from_history
            self.pending_run_from_history = None
            self._reexecute_history_entry(entry)

    def _stop_clicked(self) -> None:
        self._stop_process()

    def _stop_process(self) -> None:
        if not self._is_running():
            return
        proc = self.process
        if proc is None:
            return
        try:
            proc.terminate()
            self.status_var.set("Stopping process...")
        except Exception as exc:
            self._write_output(f"\n[ERROR] failed to stop process: {exc}\n", "err")

    def _send_stdin(self, _event: Any = None) -> None:
        if not self._is_running() or self.process is None or self.process.stdin is None:
            return
        text = self.stdin_entry.get()
        if not text:
            return
        self.stdin_entry.delete(0, "end")
        try:
            self.process.stdin.write(text + "\n")
            self.process.stdin.flush()
            self._write_output(f">> {text}\n", "stdin")
        except Exception:
            self._write_output("[ERROR] stdin is not available.\n", "err")

    def _dispatch_task_clicked(self) -> None:
        if self.dispatch_busy:
            return

        task = self.dispatch_task_box.get("1.0", "end").strip()
        if not task:
            self._write_output("[ERROR] Dispatch task is empty.\n", "err")
            return

        endpoint = self.dispatch_endpoint_entry.get().strip() or DEFAULT_DISPATCH_ENDPOINT
        channel = self.dispatch_channel_var.get().strip().lower() or "interno"
        sender = self.dispatch_sender_entry.get().strip()

        self.dispatch_busy = True
        self.dispatch_button.configure(state="disabled")
        self.status_var.set(f"Dispatching task to {channel}...")
        self._write_output(f"\n[DISPATCH] {channel} -> {endpoint}\n", "cmd")

        threading.Thread(
            target=self._dispatch_worker,
            args=(task, channel, sender, endpoint),
            daemon=True,
        ).start()

    def _dispatch_worker(self, task: str, channel: str, sender: str, endpoint: str) -> None:
        payload = {
            "task": task,
            "channel": channel,
            "sender": sender or "dispatch",
            "session_id": "",
            "metadata": {"source": "ravens_gui"},
        }
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=240) as response:
                body = response.read().decode("utf-8", errors="replace")
            parsed: Any
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}

            session = ""
            answer = ""
            if isinstance(parsed, dict):
                session = str(parsed.get("session_id", "") or "")
                answer = str(parsed.get("answer", "") or parsed.get("response", "") or "")
            if not answer:
                if isinstance(parsed, (dict, list)):
                    answer = json.dumps(parsed, ensure_ascii=False, indent=2)
                else:
                    answer = str(parsed)

            self.output_queue.put(("line", f"[DISPATCH] session={session or 'n/a'}\n"))
            self.output_queue.put(("line", f"{answer}\n"))
            self.output_queue.put(("dispatch_done", "Dispatch completed."))
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            self.output_queue.put(
                ("line", f"[DISPATCH-ERROR] HTTP {exc.code}: {error_body or exc.reason}\n")
            )
            self.output_queue.put(("dispatch_done", "Dispatch failed."))
        except Exception as exc:
            self.output_queue.put(("line", f"[DISPATCH-ERROR] {exc}\n"))
            self.output_queue.put(("dispatch_done", "Dispatch failed."))

    def _on_dispatch_done(self, status: str) -> None:
        self.dispatch_busy = False
        self.dispatch_button.configure(state="normal")
        self.status_var.set(status)

    def _clear_output(self) -> None:
        self.output_box.configure(state="normal")
        self.output_box.delete("1.0", "end")
        self.output_box.configure(state="disabled")

    def _copy_output(self) -> None:
        text = self.output_box.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Output copied.")

    def _write_output(self, text: str, tag: str = "norm") -> None:
        self.output_box.configure(state="normal")
        self.output_box._textbox.insert("end", text, tag)
        self.output_box.see("end")
        self.output_box.configure(state="disabled")

    def _refresh_history(self) -> None:
        for child in self.history_frame.winfo_children():
            child.destroy()

        if not self.history.entries:
            ctk.CTkLabel(
                self.history_frame,
                text="No executions yet.",
                text_color="#666666",
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=8, pady=10)
            return

        for entry in self.history.entries[:20]:
            ts = str(entry.get("ts", ""))[11:16]
            bot = str(entry.get("bot", ""))
            command = str(entry.get("command", ""))
            rc = entry.get("exit_code")
            rc_str = "-" if rc is None else str(rc)
            label = f"[{ts}] {bot} > {command} (exit {rc_str})"
            button = ctk.CTkButton(
                self.history_frame,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color=("#dddddd", "#2b2b2b"),
                text_color=("black", "#bcbcbc"),
                font=ctk.CTkFont(size=11, family="Consolas"),
                command=lambda item=entry: self._history_clicked(item),
            )
            button.pack(fill="x", padx=2, pady=1)

            snippet = str(entry.get("output_snippet", "")).strip()
            if snippet:
                compact = snippet.replace("\n", " | ")
                compact = compact[-120:]
                ctk.CTkLabel(
                    self.history_frame,
                    text=f"  ... {compact}",
                    anchor="w",
                    text_color="#7a7a7a",
                    font=ctk.CTkFont(size=10),
                ).pack(fill="x", padx=6, pady=(0, 4))

    def _history_clicked(self, entry: dict[str, Any]) -> None:
        if self._is_running():
            should_switch = messagebox.askyesno(
                "Switch running process",
                "A process is currently running. Stop it and re-run this history command?",
            )
            if not should_switch:
                return
            self.pending_run_from_history = entry
            self._stop_process()
            return
        self._reexecute_history_entry(entry)

    def _reexecute_history_entry(self, entry: dict[str, Any]) -> None:
        bot = str(entry.get("bot", ""))
        command = str(entry.get("command", ""))
        arg_values = entry.get("arg_values")
        if not isinstance(arg_values, dict):
            arg_values = {}

        if bot not in COMMANDS or command not in COMMANDS[bot]:
            self._write_output(
                f"[ERROR] History command no longer exists: {bot} > {command}\n",
                "err",
            )
            return

        self.bot_var.set(bot)
        self._on_bot_change()
        self.command_var.set(command)
        self._on_command_change()

        for key, value in arg_values.items():
            widget = self.arg_widgets.get(key)
            if widget is None:
                continue
            try:
                if isinstance(widget, ctk.CTkComboBox):
                    widget.set(str(value))
                else:
                    widget.delete(0, "end")
                    widget.insert(0, str(value))
            except Exception:
                continue

        valid_arg_values, error = self._collect_arg_values()
        if valid_arg_values is None:
            self._write_output(f"[ERROR] Cannot re-run history item: {error}\n", "err")
            return
        argv = self._build_command(valid_arg_values)
        self._start_process(argv=argv, arg_values=valid_arg_values)

    def _is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _on_close(self) -> None:
        if self._is_running():
            try:
                self.process.terminate()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    app = RavensApp()
    app.mainloop()


if __name__ == "__main__":
    main()
