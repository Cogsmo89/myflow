from __future__ import annotations

import threading
import numpy as np
import sounddevice as sd


class MicError(RuntimeError):
    pass


SAMPLE_RATE = 16000
CHANNELS = 1


def _resolve_device(device):
    """Accept int index, name substring, or empty -> default."""
    if device is None or device == "":
        return None
    if isinstance(device, int):
        return device
    s = str(device).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # Substring match against input devices
    needle = s.lower()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and needle in d["name"].lower():
            return i
    raise MicError(f"Input device not found matching: {device!r}")


class Recorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE, device=None):
        self.sample_rate = sample_rate
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if status:
            # Log under-runs etc but keep recording
            pass
        with self._lock:
            self._frames.append(indata.copy())

    def _open_stream(self):
        dev = _resolve_device(self.device)
        return sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            device=dev,
            callback=self._callback,
        )

    def start(self) -> None:
        if self._stream is not None:
            return
        self._frames = []
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                if attempt == 1:
                    # Re-enumerate devices (handles USB/Bluetooth hot-plug)
                    try:
                        sd._terminate()
                        sd._initialize()
                    except Exception:
                        pass
                self._stream = self._open_stream()
                self._stream.start()
                return
            except (sd.PortAudioError, MicError) as e:
                last_err = e
                self._stream = None
            except Exception as e:
                last_err = e
                self._stream = None
        raise MicError(f"Microphone unavailable after retry: {last_err}")

    def stop(self) -> tuple[np.ndarray, float] | None:
        if self._stream is None:
            return None
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            if not self._frames:
                return None
            audio = np.concatenate(self._frames, axis=0).flatten().astype(np.float32)
        duration = len(audio) / self.sample_rate
        return audio, duration
