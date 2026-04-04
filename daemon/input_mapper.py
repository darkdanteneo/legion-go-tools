import evdev
import select
import threading
import time

# Legion Go Vendor and Controller PIDs
LEN_VID = 0x17EF
LEN_PIDS = [0x6182, 0x6183, 0x6184, 0x6185, 0x61EB, 0x61EC, 0x61ED, 0x61EE]

def get_legion_devices():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    legion_devs = []
    for dev in devices:
        if dev.info.vendor == LEN_VID and dev.info.product in LEN_PIDS:
            if "Touchpad" not in dev.name and "Keyboard" not in dev.name:
                legion_devs.append(dev)
    return legion_devs

class InputMapper:
    def __init__(self):
        self.running = False
        self.thread = None
        self.uinput = None
        self.grabbed_devs = []
        
        # We spoof an Xbox 360 Controller so browsers and Steam automatically pick it up natively
        self.capabilities = {
            evdev.ecodes.EV_KEY: [
                evdev.ecodes.BTN_A, evdev.ecodes.BTN_B, evdev.ecodes.BTN_X, evdev.ecodes.BTN_Y,
                evdev.ecodes.BTN_TL, evdev.ecodes.BTN_TR,
                evdev.ecodes.BTN_TL2, evdev.ecodes.BTN_TR2, 
                evdev.ecodes.BTN_SELECT, evdev.ecodes.BTN_START, evdev.ecodes.BTN_MODE,
                evdev.ecodes.BTN_THUMBL, evdev.ecodes.BTN_THUMBR,
            ],
            evdev.ecodes.EV_ABS: [
                (evdev.ecodes.ABS_X, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (evdev.ecodes.ABS_Y, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (evdev.ecodes.ABS_RX, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (evdev.ecodes.ABS_RY, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                (evdev.ecodes.ABS_Z, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (evdev.ecodes.ABS_RZ, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (evdev.ecodes.ABS_HAT0X, evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (evdev.ecodes.ABS_HAT0Y, evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ]
        }

        # Button swap logic from UI
        self.button_remap = {
            evdev.ecodes.BTN_X: evdev.ecodes.BTN_Y,
            evdev.ecodes.BTN_Y: evdev.ecodes.BTN_X,
        }
        
        # Axis mapping logic for weird kernel driver outputs
        self.axis_remap = {
            evdev.ecodes.ABS_Z: evdev.ecodes.ABS_Z,
            evdev.ecodes.ABS_RZ: evdev.ecodes.ABS_RZ,
            evdev.ecodes.ABS_BRAKE: evdev.ecodes.ABS_Z,
            evdev.ecodes.ABS_GAS: evdev.ecodes.ABS_RZ,
        }

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self._cleanup()

    def _cleanup(self):
        for dev in self.grabbed_devs:
            try:
                dev.ungrab()
            except: pass
        self.grabbed_devs = []
        if self.uinput:
            self.uinput.close()
            self.uinput = None

    def _loop(self):
        print("[InputMapper] Starting virtual Xbox 360 mapping translation...")
        
        while self.running:
            # 1. Grab devices if we haven't already
            if not self.grabbed_devs:
                devs = get_legion_devices()
                if not devs:
                    time.sleep(2)
                    continue
                
                for d in devs:
                    try:
                        d.grab()
                        self.grabbed_devs.append(d)
                        print(f"[InputMapper] Grabbed native controller: {d.name}")
                    except Exception as e:
                        print(f"[InputMapper] Failed to grab {d.name}: {e}")
                
                if not self.grabbed_devs:
                    time.sleep(2)
                    continue

            # 2. Setup Virtual UInput sink if we don't have one
            if not self.uinput:
                try:
                    # Dynamically determine capabilities boundaries to prevent axis wrap-around!
                    dynamic_caps = {evdev.ecodes.EV_KEY: self.capabilities[evdev.ecodes.EV_KEY]}
                    abs_caps = {}
                    
                    # Store defaults in a mapping dictionary
                    defaults = {code: info for code, info in self.capabilities[evdev.ecodes.EV_ABS]}
                    
                    # Scan grabbed dev for their real limits and override our defaults!
                    for dev in self.grabbed_devs:
                        if evdev.ecodes.EV_ABS in dev.capabilities():
                            for code, info in dev.capabilities()[evdev.ecodes.EV_ABS]:
                                target_code = self.axis_remap.get(code, code)
                                if target_code in defaults:
                                    defaults[target_code] = info
                                    print(f"[InputMapper] Mapped physical bound for {target_code}: min={info.min}, max={info.max}")
                    
                    dynamic_caps[evdev.ecodes.EV_ABS] = list(defaults.items())
                    
                    self.uinput = evdev.UInput(
                        events=dynamic_caps,
                        name="Virtual Xbox 360 Controller",
                        vendor=0x045E,
                        product=0x028E,
                        version=0x0110
                    )

                    print("[InputMapper] Created Virtual Xbox 360 UInput Device.")
                except Exception as e:
                    print(f"[InputMapper] Failed to create virtual device: {e}")
                    self._cleanup()
                    time.sleep(2)
                    continue

            # 3. Read events from existing controllers
            r, _, _ = select.select(self.grabbed_devs, [], [], 1.0)
            for fd in r:
                try:
                    for event in fd.read():
                        self._process_event(event)
                except Exception as e:
                    print(f"[InputMapper] Error reading from grabbed device: {e}")
                    self._cleanup()
                    break # drop out to re-grab later

    def _process_event(self, event):
        # Pass Sync events
        if event.type == evdev.ecodes.EV_SYN:
            self.uinput.write_event(event)

        # Map Keys/Buttons
        elif event.type == evdev.ecodes.EV_KEY:
            mapped_code = self.button_remap.get(event.code, event.code)
            # Only write known Xbox buttons
            if mapped_code in self.capabilities[evdev.ecodes.EV_KEY]:
                self.uinput.write(evdev.ecodes.EV_KEY, mapped_code, event.value)
        
        # Map Axes
        elif event.type == evdev.ecodes.EV_ABS:
            mapped_axis = self.axis_remap.get(event.code, event.code)
            # Filter standard Xbox axes
            # extract axes from tuples
            supported_axes = [item[0] for item in self.capabilities[evdev.ecodes.EV_ABS]]
            if mapped_axis in supported_axes:
                self.uinput.write(evdev.ecodes.EV_ABS, mapped_axis, event.value)
                if event.code in [evdev.ecodes.ABS_BRAKE, evdev.ecodes.ABS_GAS, evdev.ecodes.ABS_Z, evdev.ecodes.ABS_RZ]:
                    print(f"[InputMapper] Trigger {event.code} raw value: {event.value}")

