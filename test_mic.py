"""Record 3 seconds, transcribe, clean. Verifies the pipeline."""
from __future__ import annotations

import sys
import time

import numpy as np
import sounddevice as sd

from myflow import config as cfg_mod
from myflow.cleaner import clean
from myflow.transcriber import transcribe


DURATION = 3.0
SR = 16000


def main() -> int:
    cfg_mod.ensure_config()
    cfg = cfg_mod.load()
    print(f"config: {cfg_mod.config_path()}")
    print(f"engine: {cfg.stt_engine}")

    if not cfg.anthropic_api_key:
        print("WARN: anthropic_api_key not set; cleanup will fail.")
    if cfg.stt_engine == "openai" and not cfg.openai_api_key:
        print("ERROR: openai_api_key not set and stt_engine=openai")
        return 2

    print(f"\nRecording {DURATION:.0f}s from default mic. Speak now...")
    for i in (3, 2, 1):
        print(f"  starting in {i}...")
        time.sleep(1)
    print("  GO")
    audio = sd.rec(int(DURATION * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    audio = audio.flatten().astype(np.float32)
    print(f"  captured {len(audio)/SR:.2f}s, peak={np.max(np.abs(audio)):.3f}")

    print("\nTranscribing...")
    raw = transcribe(audio, SR, cfg)
    print(f"raw: {raw!r}")

    if not raw.strip():
        print("(empty transcript)")
        return 0

    if cfg.anthropic_api_key:
        print("\nCleaning...")
        cleaned = clean(raw, cfg)
        print(f"cleaned: {cleaned!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
