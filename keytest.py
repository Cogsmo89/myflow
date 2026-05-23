"""Press Right Alt a few times. Then press ESC to quit."""
from pynput import keyboard

def on_press(key):
    print(f"PRESS:   {key!r}")

def on_release(key):
    print(f"RELEASE: {key!r}")
    if key == keyboard.Key.esc:
        return False

print("Press your hotkey (Right Alt) a few times, then ESC to exit.")
with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
