#!/usr/bin/env python3
import evdev
import select
import sys

def main():
    print("=" * 60)
    print("      Legion Go Button Finder Utility")
    print("=" * 60)
    
    try:
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    except PermissionError:
        print("ERROR: In order to read raw evdev inputs, you must run this script with elevated privileges.")
        print("Run:  sudo python3 utils/find_button.py")
        sys.exit(1)

    if not devices:
        print("No input devices found.")
        sys.exit(1)

    print("Detected input devices:")
    for i, device in enumerate(devices):
        print(f"[{i}] {device.path}: {device.name}")
        
    print("\n-----------------------------------------------------------")
    print("👉 ACTION REQUIRED: Press the Legion L or Legion R button!")
    print("-----------------------------------------------------------")
    print("Listening for input... (Press Ctrl+C to stop)")
    
    devices_map = {dev.fd: dev for dev in devices}
    
    try:
        while True:
            r, w, x = select.select(devices_map.keys(), [], [])
            for fd in r:
                for event in devices_map[fd].read():
                    if event.type == evdev.ecodes.EV_KEY:
                        key_event = evdev.categorize(event)
                        # Only show 'down' events to avoid double-printing
                        if key_event.keystate == 1:
                            print(f"\n[KEY EVENT HIT]")
                            print(f"Device: {devices_map[fd].name}")
                            print(f"Evdev Path: {devices_map[fd].path}")
                            print(f"Button Keycode: '{key_event.keycode}'")
                            print(f"Raw Scancode: {key_event.scancode}")
                            print("-----------------------------------------------------------")
                    elif event.type != evdev.ecodes.EV_SYN:
                        print(f"\n[NON-KEY EVENT HIT]")
                        print(f"Device: {devices_map[fd].name}")
                        print(f"Evdev Path: {devices_map[fd].path}")
                        print(f"Event Type ID: {event.type}")
                        print(f"Event Code: {event.code}, Value: {event.value}")
                        print("-----------------------------------------------------------")
    except KeyboardInterrupt:
        print("\nExiting search utility.")

if __name__ == '__main__':
    main()
