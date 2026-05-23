from __future__ import annotations

import sys
import time
import pyperclip
from pynput.keyboard import Controller, Key


_kb = Controller()


def paste(text: str) -> None:
    if not text:
        return
    pyperclip.copy(text)
    time.sleep(0.05)
    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with _kb.pressed(mod):
        _kb.press("v")
        _kb.release("v")
