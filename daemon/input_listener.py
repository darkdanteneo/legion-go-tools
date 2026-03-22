#!/usr/bin/env python3
import evdev
import select
import sys
import subprocess
import os

# Set target evdev keys based on user observation (e.g. KEY_PROG1, KEY_A etc)
TARGET_KEYCODES = ["KEY_PROG1", "KEY_PROG2", "KEY_MACRO", "BTN_MODE"]

def main():
    print("Enumerating input devices...")
    try:
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    except PermissionError:
        print("ERROR: Permission denied loading input devices.")
        print("Please run this script as root/sudo, or add your user to the 'input' group:")
        print("   sudo usermod -aG input $USER")
        sys.exit(1)

    if not devices:
        print("No input devices found! Is the controller connected?")
        sys.exit(1)

    print("Watching for target hardware keys...")
    print(f"Target codes: {TARGET_KEYCODES}")

    devices_map = {dev.fd: dev for dev in devices}
    
    # Path to the visual application
    sidebar_app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sidebar", "app.py")
    
    try:
        while True:
            r, w, x = select.select(devices_map.keys(), [], [])
            for fd in r:
                for event in devices_map[fd].read():
                    if event.type == evdev.ecodes.EV_KEY:
                        key_event = evdev.categorize(event)
                        # Fire action on KEY DOWN (keystate == 1)
                        if key_event.keystate == 1:
                            kc = key_event.keycode
                            if isinstance(kc, list):
                                match = any(k in TARGET_KEYCODES for k in kc)
                            else:
                                match = kc in TARGET_KEYCODES
                                
                            if match:
                                print(f"Target key pressed! ({kc}) Toggling sidebar via D-Bus...")
                                # Call the app toggle option
                                # Ensure we call the script accurately, relying on the OS 
                                # knowing the environment. If running this via systemd, 
                                # make sure to pass DISPLAY/WAYLAND_DISPLAY via the user session.
                                subprocess.Popen(["python3", sidebar_app_path, "--toggle"])

    except KeyboardInterrupt:
        print("\nStopping listener daemon.")

if __name__ == '__main__':
    main()
