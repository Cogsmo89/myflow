# myflow — Windows deployment & reliability setup

This documents how myflow is installed to run reliably on Windows at every
logon. The source in this repo lives in OneDrive (for editing); the *running*
copy is deployed to local disk to avoid OneDrive sync hangs.

## Layout on the machine

| Path | Purpose |
|---|---|
| `C:\Users\lemue\OneDrive\Desktop\CLAUDE CODE\Wisper Flow` | This repo — edit code here |
| `C:\myflow_app\` | Local-only copy of the source that actually runs (no OneDrive) |
| `C:\myflow_venv\` | Local-only virtualenv (no OneDrive — prevents import hangs at logon) |
| `%APPDATA%\myflow\` | Runtime data: `config.toml`, `history.jsonl`, `myflow.log`, `boot.log`, `startup.log`, `myflow.lock` |

## Why the local copies exist

When the venv or source lived in OneDrive, Windows would launch myflow at
logon before OneDrive Files-On-Demand had materialized the files, so Python's
`import` would hang forever (process alive, but never reaching the keyboard
listener). Moving both the venv and source to local disk fixes this.

## Autostart mechanisms (belt-and-suspenders)

1. **Registry Run key** — `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\myflow`
   runs `cmd /c "%APPDATA%\...\Startup\myflow.cmd"` at logon.
2. **Startup folder** — `myflow.cmd` in the user's Startup folder.

Both call `myflow.cmd`, which:
- kills any orphan myflow processes (`wmic` + `taskkill`)
- clears a stale `myflow.lock`
- launches `pythonw.exe C:\myflow_app\run_myflow.py`

`run_myflow.py` then deletes any stale lock, forces `sys.path`/cwd to
`C:\myflow_app`, runs `myflow.main`, and `os._exit`s on return so a failed
launch can never linger as a zombie.

**Windows "Restart apps after sign-in" is disabled** via
`HKCU\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\RestartApps = 0`
because it was resurrecting stale/broken processes before the launcher ran.

## Startup self-test + notification

On every launch myflow runs a self-test (~2s after start) and shows a Windows
toast:
- **"myflow ready — Press and hold F9 to dictate."** = working
- **"myflow NOT ready"** = listener failed; run the Desktop `Fix myflow` shortcut

## Updating the deployed code after editing this repo

```powershell
# from the repo root
powershell -File .\deploy_local.ps1
```
This mirrors `myflow\` into `C:\myflow_app\myflow\`. Then restart myflow
(tray → Quit, then run `myflow.cmd`, or double-click `Fix myflow.cmd`).

## Recovering when F9 stops working

Double-click **`Fix myflow.cmd`** on the Desktop. It kills stuck processes,
clears the lock, and relaunches cleanly. Watch for the "myflow ready" toast.

## Diagnostics

- `%APPDATA%\myflow\boot.log` — step-by-step entrypoint trace (how far startup got)
- `%APPDATA%\myflow\myflow.log` — runtime log incl. 10-min watchdog heartbeats
- `%APPDATA%\myflow\startup.log` — launcher (.cmd) decisions
