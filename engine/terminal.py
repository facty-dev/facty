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

    BINDINGS = [
        ("ctrl+shift+c", "copy_selection", "Copy selection"),
    ]

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
        # Text selection (mouse drag + Ctrl+Shift+C to copy)
        self._select_start = None   # (row, col)
        self._select_end = None     # (row, col)
        self._selecting = False
        self._selected_text = ""

    def on_mount(self):
        # Delay the spawn until after the first layout pass — the
        # widget's actual size isn't known at on_mount time. This
        # ensures the terminal matches the widget (no cut-off content).
        self.call_after_refresh(self._spawn_and_start)

    def _spawn_and_start(self):
        self._resize_to_widget()
        self._spawn()
        self._start_reader()

    def on_resize(self, event):
        """Resize the terminal when the widget is resized."""
        self._resize_to_widget()

    def _resize_to_widget(self):
        """Resize the pyte terminal + PTY to match the widget's size."""
        import fcntl
        import struct
        import termios
        # Get the widget's actual size (fallback to current/defaults)
        try:
            w, h = self.size.width, self.size.height
            # If the size is 0 (not laid out yet), keep the current size
            if w > 0 and h > 0:
                new_cols = max(20, w)
                new_rows = max(5, h)
            else:
                new_cols, new_rows = self.cols, self.rows
        except Exception:
            new_cols, new_rows = self.cols, self.rows
        if new_cols == self.cols and new_rows == self.rows:
            return
        self.cols = new_cols
        self.rows = new_rows
        # Resize the pyte terminal (preserves content where possible)
        try:
            self.term.resize(new_rows, new_cols)
        except Exception:
            # If resize fails, recreate the terminal
            self.term = pyte.Screen(new_cols, new_rows)
            self.stream = pyte.ByteStream(self.term)
        # Resize the PTY (so the subprocess sees the new size)
        if self.master_fd:
            try:
                winsize = struct.pack("HHHH", new_rows, new_cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass
        self.refresh()

    def _spawn(self):
        """Spawn the subprocess in a PTY.

        The child gets a new session + the PTY slave as its controlling
        terminal (TIOCSCTTY) — pi's TUI checks for a controlling TTY and
        hangs without one (no output, no rendering)."""
        import fcntl
        import struct
        import termios
        master_fd, slave_fd = pty.openpty()
        # Set the PTY window size
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        def _setup_tty():
            """Run in the child before exec: new session + controlling TTY."""
            os.setsid()
            # fd 0 is the PTY slave (stdin) — make it the controlling TTY
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.master_fd = master_fd
        self.proc = subprocess.Popen(
            self.command,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            close_fds=True,
            preexec_fn=_setup_tty,
            env={**os.environ, "TERM": "xterm-256color",
                 "COLUMNS": str(self.cols), "LINES": str(self.rows)},
        )
        os.close(slave_fd)

    def _respond_to_queries(self, data):
        """Respond to terminal queries (pi's TUI sends OSC color queries
        and DSR/DA queries and waits for responses — without responses
        it hangs with no visible output).

        Queries and responses:
        - OSC 10 (foreground): ]10;? → ]10;rgb:ffff/ffff/ffff
        - OSC 11 (background): ]11;? → ]11;rgb:0000/0000/0000
        - OSC 4 (palette): ]4;<n>;? → ]4;<n>;rgb:RR/GG/BB
        - DSR (cursor position): \\x1b[6n → \\x1b[<row>;<col>R
        - DA (device attributes): \\x1b[c → \\x1b[?1;2c
        """
        if not self.master_fd:
            return
        # OSC 10 (foreground color)
        if b']10;?' in data:
            self.write(b'\x1b]10;rgb:ffff/ffff/ffff\x1b\\')
        # OSC 11 (background color)
        if b']11;?' in data:
            self.write(b'\x1b]11;rgb:0000/0000/0000\x1b\\')
        # OSC 4 (color palette) — respond with a default palette
        import re as _re
        for m in _re.finditer(rb'\x1b\]4;(\d+);\?', data):
            idx = int(m.group(1))
            # Default xterm palette (approximate)
            palette = {
                0: "000000", 1: "cd0000", 2: "00cd00", 3: "cdcd00",
                4: "0000ee", 5: "cd00cd", 6: "00cdcd", 7: "e5e5e5",
                8: "7f7f7f", 9: "ff0000", 10: "00ff00", 11: "ffff00",
                12: "5c5cff", 13: "ff00ff", 14: "00ffff", 15: "ffffff",
            }
            hex_color = palette.get(idx, "000000")
            r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
            self.write(f'\x1b]4;{idx};rgb:{r}/{g}/{b}\x1b\\'.encode())
        # DSR (Device Status Report — cursor position)
        if b'\x1b[6n' in data:
            self.write(b'\x1b[1;1R')
        # DA (Primary Device Attributes)
        if b'\x1b[c' in data:
            self.write(b'\x1b[?1;2c')
        # DA (Secondary Device Attributes)
        if b'\x1b[>c' in data:
            self.write(b'\x1b[>0;276;0c')

    def _start_reader(self):
        """Start a background thread to read the PTY output.

        Reads until EOF (the subprocess exits and closes the slave fd),
        NOT until the process exits — the PTY may still have buffered
        data after the process exits (e.g., a fast command like echo).

        Also responds to terminal queries (OSC color queries, DSR, DA)
        so pi's TUI doesn't hang waiting for responses.
        """
        def reader():
            while self.master_fd is not None:
                try:
                    data = os.read(self.master_fd, 65536)
                    if not data:
                        break  # EOF — the subprocess exited
                    # Respond to terminal queries (pi's TUI hangs without
                    # responses to its OSC color queries)
                    self._respond_to_queries(data)
                    with self._lock:
                        self.stream.feed(data)
                    # Trigger a refresh on the app thread — if there's
                    # no app (test) or it's shutting down, keep reading
                    # (the render() call picks up the new content).
                    try:
                        self.app.call_from_thread(self.refresh)
                    except Exception:
                        pass
                except OSError:
                    break  # PTY closed (unmount)
        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()

    def render(self):
        """Render the terminal screen as a Rich Text object.

        The terminal size matches the widget's size (dynamic resize),
        so the full screen is visible — no cut-off content, and the
        message entry bar (at the bottom) is always visible.

        Clips to the widget's actual size (in case the terminal is
        briefly larger during the initial render before the resize).

        Highlights the text selection (reverse video)."""
        with self._lock:
            # Clip to the widget's actual size — but if the size is 0×0
            # (not laid out yet), render the full terminal (otherwise the
            # pane shows a single blank cell).
            try:
                w, h = self.size.width, self.size.height
                if w > 0 and h > 0:
                    render_rows = min(self.rows, h)
                    render_cols = min(self.cols, w)
                else:
                    render_rows, render_cols = self.rows, self.cols
            except Exception:
                render_rows, render_cols = self.rows, self.cols
            # Selection range (normalized: start before end)
            sel = self._selection_range(render_rows, render_cols)
            lines = []
            for y in range(render_rows):
                line = Text()
                for x in range(render_cols):
                    char = self.term.buffer[y][x]
                    style = self._char_style(char)
                    # Highlight if in the selection
                    if sel and self._in_selection(y, x, sel):
                        style = (style + " reverse").strip() if style else "reverse"
                    line.append(char.data, style=style or None)
                lines.append(line)
            return Text("\n").join(lines)

    def _selection_range(self, max_rows, max_cols):
        """Normalize the selection to (start, end) with start <= end."""
        if self._select_start is None:
            return None
        sr, sc = self._select_start
        er, ec = self._select_end or self._select_start
        if (sr, sc) > (er, ec):
            sr, sc, er, ec = er, ec, sr, sc
        sr = max(0, min(sr, max_rows - 1))
        er = max(0, min(er, max_rows - 1))
        sc = max(0, min(sc, max_cols - 1))
        ec = max(0, min(ec, max_cols - 1))
        return ((sr, sc), (er, ec))

    def _in_selection(self, row, col, sel):
        """Check if (row, col) is in the selection range."""
        (sr, sc), (er, ec) = sel
        if row < sr or row > er:
            return False
        if row == sr and row == er:
            return sc <= col <= ec
        if row == sr:
            return col >= sc
        if row == er:
            return col <= ec
        return True

    # ── Mouse selection + clipboard ────────────────────────────────

    def on_mouse_down(self, event):
        """Start text selection (and focus the terminal)."""
        self.focus()
        self._select_start = (event.y, event.x)
        self._select_end = None
        self._selecting = True
        self._update_selection()
        self.refresh()
        event.stop()

    def on_mouse_move(self, event):
        """Extend the selection while the mouse button is held."""
        if self._selecting:
            self._select_end = (event.y, event.x)
            self._update_selection()
            self.refresh()
            event.stop()

    def on_mouse_up(self, event):
        """End the selection."""
        if self._selecting:
            self._selecting = False
            self._update_selection()
            event.stop()

    def _update_selection(self):
        """Extract the selected text from the pyte screen buffer."""
        sel = self._selection_range(self.rows, self.cols)
        if sel is None:
            self._selected_text = ""
            return
        (sr, sc), (er, ec) = sel
        lines = []
        with self._lock:
            for row in range(sr, er + 1):
                line = ""
                col_start = sc if row == sr else 0
                col_end = ec if row == er else self.cols - 1
                for col in range(col_start, col_end + 1):
                    line += self.term.buffer[row][col].data
                lines.append(line.rstrip())
        self._selected_text = "\n".join(lines)

    def action_copy_selection(self):
        """Copy the selected text to the clipboard (Ctrl+Shift+C)."""
        if self._selected_text:
            self.app.copy_to_clipboard(self._selected_text)
            n = len(self._selected_text)
            self.app.notify(f"Copied {n} chars to clipboard", timeout=2)
        else:
            self.app.notify("No selection — drag to select text first",
                            timeout=2)

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
