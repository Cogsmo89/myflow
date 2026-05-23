# myflow

A local Wispr-Flow-style dictation tool. Hold a hotkey, speak, release. Whisper transcribes, Claude cleans up the transcript, and the result is pasted into the focused app.

## Install

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Python 3.11+ is required.

## First run

```bash
python -m myflow.main
```

On first launch, myflow creates its config dir and writes a default `config.toml`:

- Windows: `%APPDATA%\myflow\config.toml`
- macOS / Linux: `~/.config/myflow/config.toml`

Edit it and add your API keys:

```toml
anthropic_api_key = "sk-ant-..."
openai_api_key    = "sk-..."        # only needed if stt_engine = "openai"
stt_engine        = "openai"         # or "local"
local_whisper_model = "base"         # base, small, medium, large-v3
hotkey_push_to_talk = "alt_r"        # right Alt / right Option
hotkey_handsfree    = ["alt_r", "space"]
min_recording_seconds = 0.3
play_start_sound = true
cleanup_model = "claude-haiku-4-5"
```

You can also set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` as environment variables; they override empty config values.

## Usage

- **Push-to-talk**: hold `Right Alt` (Windows) / `Right Option` (Mac), speak, release. The cleaned transcript is pasted at the cursor.
- **Hands-free toggle**: press `Right Alt + Space` to start continuous recording. Press it again to stop.
- **Tray menu**: quit, reload config (after editing `config.toml`), open the log, toggle hands-free.

Recordings shorter than `min_recording_seconds` are ignored. The last 20 transcripts (raw + cleaned) are stored in `history.jsonl` next to the config.

## Running without API keys

Set `stt_engine = "local"` and leave both API keys blank. myflow will run faster-whisper locally and paste the **raw** transcript (no filler-word stripping or punctuation cleanup). The first run downloads the Whisper model (~140 MB for `base`).

If you later add an `anthropic_api_key`, cleanup turns on automatically — no other changes needed.

## Switching STT engines

- `stt_engine = "openai"` — sends audio to the OpenAI Whisper API (`whisper-1`). Fastest, requires `openai_api_key`.
- `stt_engine = "local"` — runs `faster-whisper` locally. No API cost. The model (`base` ≈ 140 MB) is downloaded on first use to your HuggingFace cache.

## Verify the pipeline

Before binding hotkeys, sanity-check mic + APIs:

```bash
python test_mic.py
```

It records 3 seconds, transcribes, and prints the raw + cleaned text.

## macOS permissions

System Settings → Privacy & Security:

- **Microphone** — allow Terminal (or whichever app is running Python)
- **Accessibility** — required for global hotkey + paste keystroke
- **Input Monitoring** — required so pynput sees the right Option key

You usually need to fully quit and relaunch the terminal after granting these.

If the right Option key isn't detected, change `hotkey_push_to_talk` to `"alt"` or another key (any name from [pynput's `Key` enum](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.Key)).

## Windows notes

- No special permissions required. Just run `python -m myflow.main`.
- The default beep uses `winsound.Beep`.

## Troubleshooting

- **No mic / PortAudio error** — check Windows mic privacy settings or default input device. Run `python -c "import sounddevice; print(sounddevice.query_devices())"` to inspect devices.
- **Paste does nothing** — some apps block synthetic keystrokes. Verify clipboard contains the text; paste manually.
- **`anthropic_api_key not set`** — fill it in `config.toml` or export `ANTHROPIC_API_KEY`.
- **Logs** — `myflow.log` next to your config file, or use the tray menu's "Open log".

## Project layout

```
myflow/
  main.py          entrypoint, tray, hotkey listener, state machine
  recorder.py      audio capture (sounddevice, 16 kHz mono)
  transcriber.py   OpenAI Whisper API or faster-whisper
  cleaner.py       Anthropic cleanup (claude-haiku-4-5)
  paster.py        clipboard write + paste keystroke
  config.py        loads config.toml, manages config dir
  sound.py         start/stop beeps
  prompts/
    cleanup.txt    editable system prompt for the cleanup model
test_mic.py        3-second pipeline smoke test
requirements.txt
```
