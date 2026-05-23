from __future__ import annotations

import sys
import threading


def _beep_windows(freq: int, dur_ms: int) -> None:
    try:
        import winsound
        winsound.Beep(freq, dur_ms)
    except Exception:
        pass


def _beep_unix(freq: int, dur_ms: int) -> None:
    # Soft fallback: terminal bell
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:
        pass


def _beep(freq: int, dur_ms: int) -> None:
    if sys.platform == "win32":
        _beep_windows(freq, dur_ms)
    else:
        _beep_unix(freq, dur_ms)


def play_start() -> None:
    threading.Thread(target=_beep, args=(880, 80), daemon=True).start()


def play_stop() -> None:
    threading.Thread(target=_beep, args=(660, 80), daemon=True).start()
