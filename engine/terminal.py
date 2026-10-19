#!/usr/bin/env python3
# terminal.py — a terminal emulator widget for the Pack Studio TUI.
#
# Embeds a subprocess (pi in interactive TUI mode) inside a Textual
# widget: the subprocess runs in a PTY, its output is parsed by pyte
# (a terminal emulator), and the screen buffer is rendered as Rich
# Text. Keyboard input is forwarded to the PTY.
#
# Why: the ask_questions extension renders its full questionnaire dialog
# (tabs, previews, notes, review tab) in pi's TUI. Over RPC it falls
# back to simple select/input dialogs. By embedding pi's actual TUI,
# the questionnaire renders natively — no custom popup to maintain.
#
# Usage:
#   from terminal import TerminalPane
#   pane = TerminalPane(["pi", "--skill", "pack-factory"], cols=80, rows=24)
#   yield pane  # inside a Textual screen

import os
import pty
import subprocess
import threading

import pyte
from rich.text import Text
from textual.widgets import Static


class TerminalPane(Static):
    """A terminal emulator widget — runs a subprocess in a PTY and
    renders its output inside a Textual widget.

    - The subprocess runs in a PTY (pty.openpty).
    - A background thread reads the PTY master, feeds pyte (terminal
      emulator), and triggers a refresh.
    - render() converts the pyte screen buffer to a Rich Text object
      (with colors/styles).
    - on_key() forwards keystrokes to the PTY (so the user can interact
      with the subprocess — e.g., the ask_questions questionnaire dialog).
    """

    # Map Textual key names to terminal bytes
    KEY_MAP = {
        "enter": b"\r",
        "escape": b"\x1b",
        "backspace": b"\x7f",
        "tab": b"\t",
        "space": b" ",
        "up": b"\x1b[A",
        "down": b"\x1b[B",
        "right": b"\x1b[C",
        "left": b"\x1b[D",
        "home": b"\x1b[H",
        "end": b"\x1b[F",
        "delete": b"\x1b[3~",
        "pageup": b"\x1b[5~",
        "pagedown": b"\x1b[6~",
        "f1": b"\x1bOP",
        "f2": b"\x1bOQ",
        "f3": b"\x1bOR",
        "f4": b"\x1bOS",
    }

    # Map pyte color names to Rich style names
    COLOR_MAP = {
        "black": "black",
        "red": "red",
        "green": "green",
        "brown": "yellow",
        "yellow": "yellow",
        "blue": "blue",
        "magenta": "magenta",
        "cyan": "cyan",
        "white": "white",
        "default": "",
    }

    def __init__(self, command, cols=80, rows=24, **kwargs):
        super().__init__("", **kwargs)
        self.command = command
        self.cols = cols
        self.rows = rows
        # NOTE: `screen` is a Textual property (the widget's parent
        # screen) — name the pyte terminal `term` instead.
        self.term = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.term)
        self.master_fd = None
        self.proc = None
        self._reader = None
        self._lock = threading.Lock()
        self.can_focus = True  # receive keyboard input

    def on_mount(self):
        self._spawn()
        self._start_reader()

    def _spawn(self):
        """Spawn the subprocess in a PTY."""
        master_fd, slave_fd = pty.openpty()
        # Set the PTY window size
        import fcntl
        import struct
        import termios
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        self.master_fd = master_fd
        self.proc = subprocess.Popen(
            self.command,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
            env={**os.environ, "TERM": "xterm-256color",
                 "COLUMNS": str(self.cols), "LINES": str(self.rows)},
        )
        os.close(slave_fd)

    def _start_reader(self):
        """Start a background thread to read the PTY output."""
        def reader():
            while self.proc and self.proc.poll() is None:
                try:
                    data = os.read(self.master_fd, 65536)
                    if not data:
                        break
                    with self._lock:
                        self.stream.feed(data)
                    # Trigger a refresh on the app thread
                    try:
                        self.app.call_from_thread(self.refresh)
                    except RuntimeError:
                        break  # app is shutting down
                except OSError:
                    break
        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()

    def render(self):
        """Render the terminal screen as a Rich Text object."""
        with self._lock:
            lines = []
            for y in range(self.rows):
                line = Text()
                for x in range(self.cols):
                    char = self.term.buffer[y][x]
                    style = self._char_style(char)
                    line.append(char.data, style=style or None)
                lines.append(line)
            return Text("\n").join(lines)

    def _char_style(self, char):
        """Map a pyte character's attributes to a Rich style string."""
        parts = []
        if char.bold:
            parts.append("bold")
        if char.italics:
            parts.append("italic")
        if char.underscore:
            parts.append("underline")
        if char.reverse:
            parts.append("reverse")
        # Foreground color
        fg = self.COLOR_MAP.get(char.fg, "")
        if fg:
            parts.append(fg)
        # Background color (pyte uses "bg" attribute)
        bg = self.COLOR_MAP.get(char.bg, "")
        if bg:
            parts.append(f"on {bg}")
        return " ".join(parts)

    def on_key(self, event):
        """Forward keystrokes to the PTY."""
        if self.master_fd is None:
            return
        key_bytes = self.KEY_MAP.get(event.key)
        if key_bytes is None and len(event.key) == 1:
            # Single character (letters, digits, punctuation)
            key_bytes = event.key.encode()
        if key_bytes is None and event.character:
            # Use the character if the key name didn't match
            key_bytes = event.character.encode()
        if key_bytes:
            try:
                os.write(self.master_fd, key_bytes)
            except OSError:
                pass
        event.stop()  # don't propagate to other widgets

    def on_click(self, event):
        """Focus the terminal on click."""
        self.focus()

    def on_unmount(self):
        """Kill the subprocess when the widget is unmounted."""
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

    def write(self, data):
        """Write bytes to the PTY (programmatic input)."""
        if self.master_fd:
            try:
                os.write(self.master_fd, data)
            except OSError:
                pass

    def send_text(self, text):
        """Send text to the subprocess (as if typed)."""
        self.write(text.encode())
