from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from pynput import keyboard

from . import config as cfg_mod


# --- Windows keyboard-poll helper for watchdog ------------------------------
# We poll the asynchronous keyboard state directly. If any non-modifier key
# transitioned to "down" between two polls but the listener never saw it,
# the hook is genuinely deaf. This avoids the false positives you get from
# GetLastInputInfo (which is triggered by mouse movement too).
def _any_key_down_snapshot() -> int:
    """Cheap fingerprint of which keyboard keys are currently held.
    Returns 0 on non-Windows or on failure."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        get_state = ctypes.windll.user32.GetAsyncKeyState
        h = 0
        # VK 0x08..0xFE; skip mouse buttons (0x01..0x06) deliberately
        for vk in range(0x08, 0xFF):
            if get_state(vk) & 0x8000:
                h = (h * 131 + vk) & 0xFFFFFFFF
        return h
    except Exception:
        return 0
from .cleaner import clean, CleanupError
from .paster import paste
from .recorder import Recorder, MicError
from .sound import play_start, play_stop
from .transcriber import transcribe, TranscribeError


log = logging.getLogger("myflow")


def _setup_logging() -> None:
    cfg_mod.ensure_config()
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(cfg_mod.log_path(), encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def notify(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="myflow", timeout=5)
    except Exception:
        log.warning("notify failed: %s", message)


def _key_from_name(name: str):
    name = name.strip().lower()
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(f"Unknown key name: {name}")


def append_history(raw: str, cleaned: str, max_entries: int = 20) -> None:
    path = cfg_mod.history_path()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "raw": raw,
        "cleaned": cleaned,
    }
    try:
        lines: list[str] = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False))
        lines = lines[-max_entries:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.warning("history write failed: %s", e)


class App:
    def __init__(self) -> None:
        self.cfg = cfg_mod.load()
        self.recorder = Recorder(device=self.cfg.input_device)
        self.recording = False
        self.handsfree = False
        self._lock = threading.Lock()
        self._pressed: set = set()
        self._ptt_key = _key_from_name(self.cfg.hotkey_push_to_talk)
        self._handsfree_keys = {_key_from_name(k) for k in self.cfg.hotkey_handsfree}
        self._handsfree_armed = False  # debounce
        self._listener: keyboard.Listener | None = None
        self._last_event_ts = time.monotonic()
        self._watchdog_stop = threading.Event()
        # Queue used to hand work off the keyboard-hook thread. The hook MUST
        # return within ~1.5s on Windows or the OS silently unhooks it.
        self._action_queue: queue.Queue[str] = queue.Queue()

    def _suppress_current(self) -> None:
        """Tell the OS to swallow this key event so other apps don't see it."""
        try:
            if self._listener is not None:
                self._listener.suppress_event()
        except Exception:
            pass

    # --- pipeline ---

    def _run_pipeline(self, audio, duration: float) -> None:
        try:
            if duration < self.cfg.min_recording_seconds:
                log.info("ignored: %.2fs < min %.2fs", duration, self.cfg.min_recording_seconds)
                return
            log.info("transcribing %.2fs of audio (%s)", duration, self.cfg.stt_engine)
            raw = transcribe(audio, 16000, self.cfg)
            log.info("raw: %s", raw)
            if not raw.strip():
                log.info("empty transcript, skipping")
                return
            if self.cfg.anthropic_api_key:
                cleaned = clean(raw, self.cfg)
                log.info("cleaned: %s", cleaned)
            else:
                cleaned = raw
                log.info("no anthropic_api_key set; pasting raw transcript")
            if cleaned.strip():
                paste(cleaned)
                append_history(raw, cleaned)
        except (TranscribeError, CleanupError, MicError) as e:
            log.error("pipeline error: %s", e)
            notify("myflow error", str(e))
        except Exception as e:
            log.error("pipeline crash: %s\n%s", e, traceback.format_exc())
            notify("myflow error", f"{type(e).__name__}: {e}")

    def _start_recording(self) -> None:
        with self._lock:
            if self.recording:
                return
            try:
                self.recorder.start()
            except MicError as e:
                notify("myflow mic error", str(e))
                log.error("mic error: %s", e)
                return
            self.recording = True
        if self.cfg.play_start_sound:
            play_start()
        log.info("recording started")

    def _stop_recording(self) -> None:
        with self._lock:
            if not self.recording:
                return
            self.recording = False
            try:
                result = self.recorder.stop()
            except Exception as e:
                log.error("stop error: %s", e)
                notify("myflow error", f"stop failed: {e}")
                return
        if self.cfg.play_start_sound:
            play_stop()
        log.info("recording stopped")
        if result is None:
            return
        audio, duration = result
        threading.Thread(
            target=self._run_pipeline, args=(audio, duration), daemon=True
        ).start()

    # --- key handling ---

    def _handsfree_chord_pressed(self) -> bool:
        return self._handsfree_keys.issubset(self._pressed)

    def _is_managed_key(self, key) -> bool:
        return key == self._ptt_key or key in self._handsfree_keys

    # The two on_* methods are called on Windows' low-level keyboard hook
    # thread. They MUST return fast (well under 1 second) or Windows will
    # silently unhook the listener. So we only do bookkeeping here and
    # enqueue actions for a worker thread to perform.
    def on_press(self, key) -> None:
        try:
            self._last_event_ts = time.monotonic()
            self._pressed.add(key)

            if self._handsfree_chord_pressed() and not self._handsfree_armed:
                self._handsfree_armed = True
                self.handsfree = not self.handsfree
                self._action_queue.put("toggle_handsfree")
                return

            if not self.handsfree and key == self._ptt_key:
                self._action_queue.put("start")
        except Exception as e:
            log.error("on_press failed: %s", e)

    def on_release(self, key) -> None:
        try:
            self._last_event_ts = time.monotonic()
            self._pressed.discard(key)
            if self._handsfree_armed and not self._handsfree_chord_pressed():
                self._handsfree_armed = False
            if not self.handsfree and key == self._ptt_key:
                self._action_queue.put("stop")
        except Exception as e:
            log.error("on_release failed: %s", e)

    def _action_worker(self) -> None:
        """Drain the action queue. All audio + paste + API work happens here,
        never on the keyboard hook thread."""
        while not self._watchdog_stop.is_set():
            try:
                action = self._action_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if action == "start":
                    self._start_recording()
                elif action == "stop":
                    self._stop_recording()
                elif action == "toggle_handsfree":
                    log.info("handsfree -> %s", self.handsfree)
                    if self.handsfree:
                        self._start_recording()
                    else:
                        self._stop_recording()
            except Exception as e:
                log.error("action %s failed: %s", action, e)

    # --- tray ---

    def _build_icon(self):
        from PIL import Image, ImageDraw
        import pystray

        def make_image(active: bool):
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            color = (220, 60, 60, 255) if active else (60, 140, 220, 255)
            d.ellipse((6, 6, 58, 58), fill=color)
            d.ellipse((26, 18, 38, 40), fill=(255, 255, 255, 230))
            d.rectangle((30, 38, 34, 50), fill=(255, 255, 255, 230))
            return img

        def on_quit(icon, _item):
            icon.stop()

        def on_reload(icon, _item):
            try:
                self.cfg = cfg_mod.load()
                self._ptt_key = _key_from_name(self.cfg.hotkey_push_to_talk)
                self._handsfree_keys = {_key_from_name(k) for k in self.cfg.hotkey_handsfree}
                self.recorder = Recorder(device=self.cfg.input_device)
                notify("myflow", "config reloaded")
            except Exception as e:
                notify("myflow", f"reload failed: {e}")

        def on_open_log(_icon, _item):
            p = str(cfg_mod.log_path())
            try:
                if sys.platform == "win32":
                    os.startfile(p)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", p])
                else:
                    subprocess.Popen(["xdg-open", p])
            except Exception as e:
                log.error("open log failed: %s", e)

        def on_toggle_hf(_icon, _item):
            self.handsfree = not self.handsfree
            if self.handsfree:
                self._start_recording()
            else:
                self._stop_recording()

        menu = pystray.Menu(
            pystray.MenuItem("Toggle hands-free", on_toggle_hf),
            pystray.MenuItem("Reload config", on_reload),
            pystray.MenuItem("Open log", on_open_log),
            pystray.MenuItem("Quit", on_quit),
        )
        return pystray.Icon("myflow", make_image(False), "myflow", menu)

    def _start_listener(self) -> None:
        listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self._listener = listener
        self._last_event_ts = time.monotonic()
        listener.start()
        log.info("listening for %s", self.cfg.hotkey_push_to_talk)

    def _restart_listener(self, reason: str) -> None:
        """Tear down and re-create the keyboard listener. Crucially, do the
        teardown in a separate fire-and-forget thread with a timeout, so a
        hung `listener.stop()` can NEVER wedge the watchdog."""
        log.warning("restarting keyboard listener: %s", reason)
        old = self._listener
        self._listener = None

        def _kill_old():
            try:
                if old is not None:
                    old.stop()
            except Exception as e:
                log.warning("listener stop failed: %s", e)

        t = threading.Thread(target=_kill_old, name="myflow-stop-old", daemon=True)
        t.start()
        t.join(timeout=2.0)  # never wait more than 2s
        if t.is_alive():
            log.warning("old listener.stop() did not return in 2s; orphaning it")

        time.sleep(0.2)
        try:
            self._start_listener()
        except Exception as e:
            log.error("listener restart failed: %s", e)

    def _watchdog(self) -> None:
        """Keep the keyboard hook healthy.

        - Restart immediately if the listener thread died.
        - Detect a genuinely-deaf hook by polling the OS async keyboard state:
          if the OS reports keys held down but the listener never sees them
          across multiple ticks, the hook is gone. This avoids false positives
          from mouse-only activity (which the previous heuristic suffered).
        - Force a precautionary rebuild every 6 hours.
        - Skip checks while a recording is actively in progress.
        """
        last_rebuild = time.monotonic()
        last_heartbeat = time.monotonic()
        last_tick = time.monotonic()
        REBUILD_INTERVAL = 30 * 60.0       # rebuild every 30 minutes (was 6h)
        HEARTBEAT_INTERVAL = 10 * 60.0     # log liveness every 10 minutes
        SLEEP_RESUME_GAP = 60.0            # gap > 60s between ticks = OS slept
        TICK = 10.0
        # Number of consecutive ticks with "OS sees keys, listener doesn't"
        # before we declare the hook deaf.
        deaf_ticks_required = 3
        deaf_ticks = 0
        prev_snapshot = 0
        while not self._watchdog_stop.wait(TICK):
            try:
                now = time.monotonic()
                # Detect a long gap between ticks: the OS suspended us. Force
                # a rebuild because keyboard hooks frequently die across sleep.
                gap = now - last_tick
                last_tick = now
                if gap > SLEEP_RESUME_GAP:
                    self._restart_listener(f"OS resume detected (gap {gap:.0f}s)")
                    last_rebuild = now
                    last_heartbeat = now
                    deaf_ticks = 0
                    prev_snapshot = 0
                    continue

                # Periodic heartbeat so silent hangs become visible in the log
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    log.info("watchdog heartbeat (listener alive=%s)",
                             self._listener is not None and self._listener.is_alive())
                    last_heartbeat = now

                if self.recording:
                    deaf_ticks = 0
                    prev_snapshot = 0
                    continue

                if self._listener is None or not self._listener.is_alive():
                    self._restart_listener("listener thread not alive")
                    last_rebuild = now
                    deaf_ticks = 0
                    prev_snapshot = 0
                    continue

                snap = _any_key_down_snapshot()
                # The OS reports a key transition: was 0, now non-zero, and
                # the listener still hasn't seen anything since last tick.
                if snap != 0 and prev_snapshot == 0:
                    since_event = time.monotonic() - self._last_event_ts
                    if since_event > TICK:
                        deaf_ticks += 1
                    else:
                        deaf_ticks = 0
                else:
                    # No clean transition observed; don't accumulate evidence
                    deaf_ticks = max(0, deaf_ticks - 1)
                prev_snapshot = snap

                if deaf_ticks >= deaf_ticks_required:
                    self._restart_listener(
                        f"hook deaf (OS-reported keypresses missed {deaf_ticks} ticks)"
                    )
                    last_rebuild = now
                    deaf_ticks = 0
                    prev_snapshot = 0
                    continue

                if now - last_rebuild > REBUILD_INTERVAL:
                    self._restart_listener("scheduled rebuild")
                    last_rebuild = now
                    deaf_ticks = 0
                    prev_snapshot = 0
            except Exception as e:
                log.warning("watchdog tick failed: %s", e)

    def _self_test(self) -> None:
        """Post-startup check. Fires a Windows toast so the user knows F9 is
        ready. Based on the keyboard listener (the thing that makes F9 work).
        The mic probe is best-effort and time-boxed so it can never block the
        notification on a slow/wireless device."""
        listener_ok = self._listener is not None and self._listener.is_alive()
        ptt = self.cfg.hotkey_push_to_talk

        # Best-effort mic probe in its own thread with a hard timeout.
        mic_result = {"ok": None, "err": ""}
        def _probe():
            try:
                import sounddevice as sd
                from .recorder import _resolve_device
                dev = _resolve_device(self.cfg.input_device)
                s = sd.InputStream(samplerate=16000, channels=1, dtype="float32", device=dev)
                s.start(); time.sleep(0.05); s.stop(); s.close()
                mic_result["ok"] = True
            except Exception as e:
                mic_result["ok"] = False
                mic_result["err"] = f"{type(e).__name__}: {e}"
        t = threading.Thread(target=_probe, daemon=True)
        t.start()
        t.join(timeout=4.0)

        if not listener_ok:
            log.error("self-test FAILED: keyboard listener not alive")
            notify("myflow NOT ready", "Keyboard listener failed to start. Double-click 'Fix myflow' on your Desktop.")
            return

        if mic_result["ok"] is False:
            log.warning("self-test: listener OK but mic problem: %s", mic_result["err"])
            notify("myflow ready (mic warning)", f"F9 works. Mic issue: {mic_result['err']}")
        else:
            # mic ok, or probe timed out (device slow but listener is fine)
            log.info("self-test passed; %s ready", ptt)
            notify("myflow ready", f"Press and hold {ptt.upper()} to dictate.")
    def run(self) -> None:
        self._start_listener()
        wd = threading.Thread(target=self._watchdog, name="myflow-watchdog", daemon=True)
        wd.start()
        worker = threading.Thread(target=self._action_worker, name="myflow-actions", daemon=True)
        worker.start()
        def _delayed_self_test():
            time.sleep(2.0)
            self._self_test()
        threading.Thread(target=_delayed_self_test, name="myflow-selftest", daemon=True).start()
        try:
            icon = self._build_icon()
            icon.run()
        except Exception as e:
            log.error("tray failed, running headless: %s", e)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        finally:
            self._watchdog_stop.set()
            try:
                if self._listener is not None:
                    self._listener.stop()
            except Exception:
                pass


_lock_file_handle = None


def _acquire_single_instance_lock() -> bool:
    """Ensure only one myflow runs at a time. Returns True on success."""
    global _lock_file_handle
    lock_path = cfg_mod.config_dir() / "myflow.lock"
    try:
        if sys.platform == "win32":
            import msvcrt
            f = open(lock_path, "a+b")
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                f.close()
                return False
            _lock_file_handle = f
            return True
        else:
            import fcntl
            f = open(lock_path, "a+b")
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                return False
            _lock_file_handle = f
            return True
    except Exception as e:
        log.warning("single-instance lock failed: %s (continuing)", e)
        return True  # don't block startup if lock infra itself broke


def main() -> None:
    _setup_logging()

    if not _acquire_single_instance_lock():
        log.info("another myflow instance is already running; exiting")
        return

    cfg = cfg_mod.load()
    if not cfg.anthropic_api_key:
        log.info("anthropic_api_key missing; cleanup disabled, raw transcripts will be pasted")
    if cfg.stt_engine == "openai" and not cfg.openai_api_key:
        notify("myflow", f"Add openai_api_key to {cfg_mod.config_path()}")
        log.warning("openai_api_key missing")

    # Crash-restart loop: if App.run() ever raises, sleep with backoff and retry.
    # We never want a single bad event to permanently kill the dictation tool.
    backoff = 2.0
    while True:
        try:
            App().run()
            log.info("App.run() returned cleanly; exiting")
            return
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt; exiting")
            return
        except Exception as e:
            log.error("top-level crash: %s\n%s", e, traceback.format_exc())
            notify("myflow crashed", f"{type(e).__name__}: {e}. Restarting...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


if __name__ == "__main__":
    main()
