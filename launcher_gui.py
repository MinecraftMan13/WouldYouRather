from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


if os.name == "nt":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "wouldyourather.launcher.controlcenter"
        )
    except Exception:
        pass


@dataclass(frozen=True)
class ProcessConfig:
    key: str
    label: str
    script_name: str
    accent: str


@dataclass(frozen=True)
class LogEntry:
    source_key: str
    source_label: str
    message: str
    level: str


class ProcessCard(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, app: "LauncherApp", config: ProcessConfig) -> None:
        super().__init__(master, fg_color="#161b22", corner_radius=18, border_width=1, border_color="#252c36")
        self.app = app
        self.config = config

        self.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self,
            text=config.label,
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color="#f4f7fb",
        )
        self.title_label.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 2))

        self.script_label = ctk.CTkLabel(
            self,
            text=config.script_name,
            font=ctk.CTkFont(size=12),
            text_color="#7f8b99",
        )
        self.script_label.grid(row=1, column=0, sticky="w", padx=18)

        self.status_badge = ctk.CTkLabel(
            self,
            text="Offline",
            width=88,
            corner_radius=999,
            fg_color="#332126",
            text_color="#ff8f98",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.status_badge.grid(row=0, column=1, rowspan=2, sticky="e", padx=18)

        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 18))
        self.action_frame.grid_columnconfigure((0, 1), weight=1)

        self.start_button = ctk.CTkButton(
            self.action_frame,
            text="Start",
            height=40,
            corner_radius=12,
            fg_color=config.accent,
            hover_color=self._shade(config.accent, 0.85),
            command=lambda: self.app.start_process(config.key),
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.stop_button = ctk.CTkButton(
            self.action_frame,
            text="Stop",
            height=40,
            corner_radius=12,
            fg_color="#242b35",
            hover_color="#303947",
            text_color="#f4f7fb",
            state="disabled",
            command=lambda: self.app.stop_process(config.key),
        )
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    @staticmethod
    def _shade(color: str, factor: float) -> str:
        color = color.lstrip("#")
        rgb = [max(0, min(255, int(int(color[i : i + 2], 16) * factor))) for i in (0, 2, 4)]
        return "#" + "".join(f"{part:02x}" for part in rgb)

    def set_running(self, running: bool) -> None:
        if running:
            self.status_badge.configure(text="Running", fg_color="#173324", text_color="#7ef0a7")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        else:
            self.status_badge.configure(text="Offline", fg_color="#332126", text_color="#ff8f98")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")


class LauncherApp(ctk.CTk):
    PROCESS_DEFS = (
        ProcessConfig("app", "Web App", "app.py", "#3b82f6"),
        ProcessConfig("proxy", "Proxy Server", "proxy_server.py", "#14b8a6"),
        ProcessConfig("bot", "Discord Bot", "discordbot.py", "#f59e0b"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.title("Would You Rather Launcher")
        self.geometry("980x640")
        self.minsize(900, 580)
        self.configure(fg_color="#0b0f14")

        self.base_dir = self._resolve_base_dir()
        self.python_path = self._resolve_python()
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.stopping_processes: set[str] = set()
        self.cards: dict[str, ProcessCard] = {}
        self.log_queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self.log_history: list[LogEntry] = [LogEntry("system", "System", "Launcher ready.", "info")]
        self.log_filter = ctk.StringVar(value="all")
        self.log_tags_configured = False

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_layout()
        self.after(700, self.poll_processes)
        self.after(150, self.flush_log_queue)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(24, 14))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Would You Rather Control Center",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#f8fafc",
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ctk.CTkLabel(
            header,
            text=f"Manage app, proxy, and bot processes from one dark-mode launcher.",
            font=ctk.CTkFont(size=14),
            text_color="#94a3b8",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

        python_label = ctk.CTkLabel(
            header,
            text=f"Python: {self.python_path}",
            font=ctk.CTkFont(size=12),
            text_color="#64748b",
        )
        python_label.grid(row=2, column=0, sticky="w", pady=(10, 0))

        summary = ctk.CTkFrame(self, fg_color="#11161d", corner_radius=20, border_width=1, border_color="#202734")
        summary.grid(row=1, column=0, sticky="ew", padx=26, pady=(0, 18))
        summary.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.running_count_label = ctk.CTkLabel(
            summary,
            text="0 Running",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#f4f7fb",
        )
        self.running_count_label.grid(row=0, column=0, sticky="w", padx=18, pady=18)

        self.start_all_button = ctk.CTkButton(
            summary,
            text="Start All",
            height=38,
            corner_radius=12,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.start_all,
        )
        self.start_all_button.grid(row=0, column=2, sticky="e", padx=(0, 10), pady=18)

        self.stop_all_button = ctk.CTkButton(
            summary,
            text="Stop All",
            height=38,
            corner_radius=12,
            fg_color="#242b35",
            hover_color="#303947",
            command=self.stop_all,
        )
        self.stop_all_button.grid(row=0, column=3, sticky="e", padx=(0, 18), pady=18)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=26, pady=(0, 24))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        cards_frame = ctk.CTkFrame(content, fg_color="transparent")
        cards_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        cards_frame.grid_columnconfigure(0, weight=1)

        for index, config in enumerate(self.PROCESS_DEFS):
            card = ProcessCard(cards_frame, self, config)
            card.grid(row=index, column=0, sticky="ew", pady=(0, 14))
            self.cards[config.key] = card

        log_frame = ctk.CTkFrame(content, fg_color="#11161d", corner_radius=20, border_width=1, border_color="#202734")
        log_frame.grid(row=0, column=1, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        log_title = ctk.CTkLabel(
            log_frame,
            text="Activity Feed",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#f4f7fb",
        )
        log_title.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

        self.log_filter_control = ctk.CTkSegmentedButton(
            log_frame,
            values=["All", "App", "Proxy", "Bot"],
            variable=self.log_filter,
            command=self.on_filter_change,
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_color="#1b2330",
            unselected_hover_color="#263244",
            text_color="#f4f7fb",
        )
        self.log_filter_control.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        self.log_filter_control.set("All")

        self.log_box = ctk.CTkTextbox(
            log_frame,
            fg_color="#0b0f14",
            border_width=0,
            text_color="#d9e1ea",
            font=("Consolas", 12),
            wrap="word",
        )
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.log_box.configure(state="disabled")
        self.render_log_history()

        footer = ctk.CTkLabel(
            self,
            text="Stopping a service closes only its Python process started by this launcher.",
            font=ctk.CTkFont(size=12),
            text_color="#64748b",
        )
        footer.grid(row=3, column=0, sticky="w", padx=28, pady=(0, 16))

    def _resolve_base_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            candidates = [
                Path(sys.executable).resolve().parent,
                Path(sys.executable).resolve().parent.parent,
            ]
        else:
            candidates = [Path(__file__).resolve().parent]

        expected_files = ("app.py", "proxy_server.py", "discordbot.py")
        for candidate in candidates:
            if all((candidate / file_name).exists() for file_name in expected_files):
                return candidate

        return candidates[0]

    def _resolve_python(self) -> Path:
        venv_python = self.base_dir / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return venv_python
        if not getattr(sys, "frozen", False):
            return Path(sys.executable)
        return Path("python")

    def append_log(self, message: str, level: str = "info") -> None:
        self._write_log_line(message, level)

    def _write_log_line(self, message: str, level: str) -> None:
        self.log_box.configure(state="normal")
        if not self.log_tags_configured:
            self.log_box._textbox.tag_config("info", foreground="#d9e1ea")
            self.log_box._textbox.tag_config("success", foreground="#7ef0a7")
            self.log_box._textbox.tag_config("warn", foreground="#fbbf24")
            self.log_box._textbox.tag_config("error", foreground="#ff8f98")
            self.log_box._textbox.tag_config("app_log", foreground="#93c5fd")
            self.log_box._textbox.tag_config("proxy_log", foreground="#99f6e4")
            self.log_box._textbox.tag_config("bot_log", foreground="#fde68a")
            self.log_tags_configured = True

        self.log_box.insert("end", message + "\n", level)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def add_log_entry(self, source_key: str, source_label: str, message: str, level: str) -> None:
        entry = LogEntry(source_key, source_label, message, level)
        self.log_history.append(entry)

        if self._entry_matches_filter(entry):
            self._write_log_line(self._format_log_entry(entry), entry.level)

    def _format_log_entry(self, entry: LogEntry) -> str:
        if entry.source_key == "system":
            return entry.message
        return f"[{entry.source_label}] {entry.message}"

    def _entry_matches_filter(self, entry: LogEntry) -> bool:
        selected = self.log_filter.get().lower()
        if selected == "all":
            return True
        return entry.source_key == selected

    def render_log_history(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        for entry in self.log_history:
            if self._entry_matches_filter(entry):
                self._write_log_line(self._format_log_entry(entry), entry.level)

    def on_filter_change(self, _value: str) -> None:
        self.render_log_history()

    def start_process(self, key: str) -> None:
        config = self._get_config(key)
        if key in self.processes and self.processes[key].poll() is None:
            self.add_log_entry("system", "System", f"{config.label} is already running.", "warn")
            self.refresh_ui()
            return

        script_path = self.base_dir / config.script_name
        if not script_path.exists():
            self.add_log_entry("system", "System", f"Missing script: {config.script_name}", "error")
            return

        creationflags = 0
        popen_kwargs: dict[str, object] = {
            "cwd": str(self.base_dir),
            "text": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 1,
        }

        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            popen_kwargs["creationflags"] = creationflags
            popen_kwargs["stdin"] = subprocess.DEVNULL

        try:
            process = subprocess.Popen(
                [str(self.python_path), "-u", str(script_path)],
                **popen_kwargs,
            )
        except Exception as exc:
            self.add_log_entry("system", "System", f"Failed to start {config.label}: {exc}", "error")
            return

        self.stopping_processes.discard(key)
        self.processes[key] = process
        self.add_log_entry("system", "System", f"Started {config.label} (PID {process.pid}).", "success")
        self._start_log_reader(config, process)
        self.refresh_ui()

    def stop_process(self, key: str) -> None:
        config = self._get_config(key)
        process = self.processes.get(key)
        if not process or process.poll() is not None:
            self.processes.pop(key, None)
            self.stopping_processes.discard(key)
            self.add_log_entry("system", "System", f"{config.label} is not running.", "warn")
            self.refresh_ui()
            return

        try:
            if os.name == "nt":
                process.terminate()
            else:
                process.terminate()
            self.stopping_processes.add(key)
            self.after(1200, lambda current_key=key: self._force_stop_if_needed(current_key))
            self.add_log_entry("system", "System", f"Stopping {config.label}...", "warn")
        except Exception as exc:
            self.stopping_processes.discard(key)
            self.add_log_entry("system", "System", f"Failed to stop {config.label}: {exc}", "error")

        self.refresh_ui()

    def _force_stop_if_needed(self, key: str) -> None:
        process = self.processes.get(key)
        config = self._get_config(key)
        if not process or process.poll() is not None:
            self.stopping_processes.discard(key)
            self.refresh_ui()
            return

        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                process.kill()
            self.add_log_entry("system", "System", f"Force-stopped {config.label}.", "warn")
        except Exception as exc:
            self.add_log_entry("system", "System", f"Could not force-stop {config.label}: {exc}", "error")
        finally:
            self.stopping_processes.discard(key)
            self.refresh_ui()

    def start_all(self) -> None:
        for config in self.PROCESS_DEFS:
            self.start_process(config.key)

    def stop_all(self) -> None:
        for config in self.PROCESS_DEFS:
            self.stop_process(config.key)

    def _get_config(self, key: str) -> ProcessConfig:
        for config in self.PROCESS_DEFS:
            if config.key == key:
                return config
        raise KeyError(f"Unknown process key: {key}")

    def refresh_ui(self) -> None:
        running_count = 0
        for config in self.PROCESS_DEFS:
            process = self.processes.get(config.key)
            running = process is not None and process.poll() is None
            self.cards[config.key].set_running(running)
            running_count += int(running)

        self.running_count_label.configure(
            text=f"{running_count} Running" if running_count != 1 else "1 Running"
        )

    def _start_log_reader(self, config: ProcessConfig, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        reader = threading.Thread(
            target=self._read_process_output,
            args=(config, process),
            daemon=True,
        )
        reader.start()

    def _read_process_output(self, config: ProcessConfig, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        try:
            for line in iter(process.stdout.readline, ""):
                text = line.strip()
                if text:
                    self.log_queue.put((config.key, config.label, text))
        except Exception as exc:
            self.log_queue.put(("error", config.label, f"Log reader error: {exc}"))
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

    def flush_log_queue(self) -> None:
        while True:
            try:
                source_key, source_label, message = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if source_key == "error":
                self.add_log_entry("system", "System", f"[{source_label}] {message}", "error")
                continue

            self.add_log_entry(source_key, source_label, message, f"{source_key}_log")

        self.after(150, self.flush_log_queue)

    def poll_processes(self) -> None:
        for key, process in list(self.processes.items()):
            exit_code = process.poll()
            if exit_code is None:
                continue

            config = self._get_config(key)
            if key in self.stopping_processes:
                self.add_log_entry("system", "System", f"{config.label} stopped.", "info")
                self.stopping_processes.discard(key)
            else:
                self.add_log_entry(
                    "system",
                    "System",
                    f"{config.label} exited with code {exit_code}.",
                    "warn" if exit_code else "info",
                )
            self.processes.pop(key, None)

        self.refresh_ui()
        self.after(700, self.poll_processes)

    def on_close(self) -> None:
        active = [key for key, process in self.processes.items() if process.poll() is None]
        for key in active:
            process = self.processes.get(key)
            if not process or process.poll() is not None:
                continue

            try:
                if os.name == "nt":
                    process.terminate()
                    process.wait(timeout=1.2)
                else:
                    process.terminate()
                    process.wait(timeout=1.2)
            except Exception:
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            check=False,
                            capture_output=True,
                            text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        process.kill()
                except Exception:
                    pass
        self.destroy()


if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
