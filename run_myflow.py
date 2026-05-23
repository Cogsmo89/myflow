"""Absolute-path entrypoint for myflow.

Defends against:
- A stale single-instance lock left by Fast Startup / hard shutdown
  (deletes it so the fresh process always re-acquires cleanly)
- Zombie processes kept alive by audio-library threads after main() returns
  (forces os._exit at the end)

Orphan-killing of OLD instances is handled by myflow.cmd BEFORE launch, so
we deliberately do NOT kill other processes here (that would kill our own
sibling process from the same launch).
"""
import os, sys, time, traceback

APPDATA = os.environ.get("APPDATA", r"C:\Users\lemue\AppData\Roaming")
BOOT_LOG = os.path.join(APPDATA, "myflow", "boot.log")
LOCK = os.path.join(APPDATA, "myflow", "myflow.lock")

def _boot(msg):
    try:
        os.makedirs(os.path.dirname(BOOT_LOG), exist_ok=True)
        with open(BOOT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {msg}\n")
    except Exception:
        pass

_boot("===== run_myflow.py invoked =====")
_boot(f"executable={sys.executable}")
_boot(f"cwd={os.getcwd()}")

# Delete any stale lock so we can always re-acquire cleanly. A previous
# instance killed by sleep/shutdown may leave the lock file behind.
try:
    if os.path.exists(LOCK):
        os.remove(LOCK)
        _boot("removed stale lock")
except Exception as e:
    _boot(f"lock remove failed: {e}")

try:
    SOURCE = r"C:\myflow_app"
    if SOURCE not in sys.path:
        sys.path.insert(0, SOURCE)
    _boot(f"sys.path[0]={sys.path[0]}")
    try:
        os.chdir(SOURCE)
        _boot(f"chdir ok -> {os.getcwd()}")
    except Exception as e:
        _boot(f"chdir failed: {e}")

    _boot("importing myflow.main ...")
    from myflow.main import main
    _boot("import OK; calling main()")
    main()
    _boot("main() returned; forcing exit")
except SystemExit:
    raise
except BaseException as e:
    _boot(f"FATAL {type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    os._exit(0)
