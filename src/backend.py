import os
import glob
import time
import json
import struct
import ctypes
import fcntl
import pathlib
import subprocess
import threading
import select
import collections
import math
from gi.repository import GLib

import controller_hid

LEGION_PIDS = [0x6182, 0x6183, 0x6184, 0x6185, 0x61EB, 0x61EC, 0x61ED, 0x61EE]
VID = 0x17EF

SETTINGS_PATH = pathlib.Path.home() / ".config" / "legion-go-sidebar" / "settings.json"

# First-run defaults (user-visible: Custom profile @ 43W / 79C)
DEFAULT_SETTINGS = {
    "SET_PROFILE": "SET_PROFILE custom",
    "SET_TDP": "SET_TDP 43",
    "SET_TEMP": "SET_TEMP 79",
}

# Commands whose state we save & restore. Everything else is transient.
PERSISTENT_KEYS = {
    "SET_PROFILE", "SET_TDP", "SET_TEMP",
    "SET_CPU_BOOST", "SET_CPU_MAX_FREQ",
    "SET_GPU_FREQ", "SET_GPU_FREQ_MODE",
    "SET_FAN_CURVE", "SET_FULL_FAN",
    "SET_BATTERY_LIMIT",
    "SET_NVIDIA_OC",
}

# Re-apply order on startup / AC change. Profile MUST come first so
# the EC switches to Custom mode before ryzenadj writes TDP / temp.
APPLY_ORDER = [
    "SET_PROFILE",
    "SET_TDP",
    "SET_TEMP",
    "SET_FAN_CURVE",
    "SET_FULL_FAN",
    "SET_CPU_BOOST",
    "SET_CPU_MAX_FREQ",
    "SET_GPU_FREQ_MODE",
    "SET_GPU_FREQ",
    "SET_BATTERY_LIMIT",
    "SET_NVIDIA_OC",
]

# When the user picks one of these, drop the other (mutually exclusive intent).
CONFLICT_GROUPS = [
    ("SET_GPU_FREQ", "SET_GPU_FREQ_MODE"),
]

def is_nvidia_gpu_connected():
    import glob
    for vendor_path in glob.glob("/sys/class/drm/card*/device/vendor"):
        try:
            with open(vendor_path, "r") as f:
                if "0x10de" in f.read():
                    return True
        except:
            pass
    return False


class DeviceBackend:
    def __init__(self):
        self.toggle_callback = None
        self.keyboard_callback = None
        self.sync_callback = None
        self.telemetry_callback = None
        
        self.pending_commands = collections.OrderedDict()
        self.command_lock = threading.Lock()
        self.command_event = threading.Event()
        self.running = True
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.ryzenadj_path = "/usr/local/bin/ryzenadj"
        
        self.CONTROLLER_L_BAT = -1
        self.CONTROLLER_L_STATUS = -1
        self.CONTROLLER_R_BAT = -1
        self.CONTROLLER_R_STATUS = -1
        
        self.fds = {}
        self._find_hid_devices()
        
        self.sensor_debug = False
        self.last_sensor_log = 0
        
        # Dynamic IIO discovery
        accel_dev = self._find_iio_device("accel_3d")
        if accel_dev:
            self.accel_x = os.path.join(accel_dev, "in_accel_x_raw")
            self.accel_y = os.path.join(accel_dev, "in_accel_y_raw")
            self.accel_z = os.path.join(accel_dev, "in_accel_z_raw")
            print(f"Backend: Found Accelerometer at {accel_dev}")
        else:
            self.accel_x = "/sys/bus/iio/devices/iio:device0/in_accel_x_raw"
            self.accel_y = "/sys/bus/iio/devices/iio:device0/in_accel_y_raw"
            self.accel_z = "/sys/bus/iio/devices/iio:device0/in_accel_z_raw"

        als_dev = self._find_iio_device("als")
        if als_dev:
            self.lux_path = os.path.join(als_dev, "in_illuminance_raw")
            print(f"Backend: Found Ambient Light Sensor at {als_dev}")
        else:
            self.lux_path = "/sys/bus/iio/devices/iio:device2/in_illuminance_raw"
        
        # Auto-brightness state
        self.auto_brightness_enabled = False
        self.last_auto_br_value = -1
        self.smoothed_brightness = -1.0  # EMA-smoothed target brightness
        
        # Auto-rotation uinput state
        self.auto_rotation_enabled = False
        self.uinput_fd = None
        self._setup_uinput()
        
        # Track current display state for partial updates
        self.current_res_w = 2560
        self.current_res_h = 1600
        self.current_rate = 144
        self.current_scale = 2.5
        self.current_rot = 0  # 0 = landscape on this panel (Mutter handles native portrait)
        
        # Persistent power/thermal settings (re-applied on startup & AC events)
        self.settings_lock = threading.Lock()
        self.persisted_settings = self._load_persisted_settings()
        self._ensure_default_settings()
        self.last_ac_online = self._get_ac_online()

        self.worker_thread = threading.Thread(target=self._command_worker, daemon=True)
        self.worker_thread.start()
        
        self.hid_thread = threading.Thread(target=self._hid_loop, daemon=True)
        self.hid_thread.start()
        
        self.telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self.telemetry_thread.start()

        # Apply persisted settings on boot. Run in a thread so we don't block
        # the GUI startup, and give the EC / acpi_call a moment to settle.
        threading.Timer(5.0, self._apply_persisted_settings).start()

    def set_callbacks(self, toggle, keyboard, sync, telemetry):
        self.toggle_callback = toggle
        self.keyboard_callback = keyboard
        self.sync_callback = sync
        self.telemetry_callback = telemetry
        # Send initial sync as soon as callbacks are registered
        self._initial_sync()

    def _get_command_key(self, line):
        parts = line.strip().split()
        if not parts: return None
        cmd = parts[0]
        if cmd in ["SET_CTRL_RGB", "SET_CTRL_RGB_OFF"] and len(parts) >= 2:
            # Handle both RGB (side at end) and RGB_OFF (side at parts[1])
            side = parts[-1].upper() if cmd == "SET_CTRL_RGB" else parts[1].upper()
            return f"{cmd}_{side}"
        if cmd == "REMAP_BTN" and len(parts) >= 3:
            return f"REMAP_BTN_{parts[1]}_{parts[2].upper()}"
        return cmd

    def send_command(self, cmd_str):
        with self.command_lock:
            for line in cmd_str.split('\n'):
                key = self._get_command_key(line)
                if key:
                    self.pending_commands[key] = line
            self.command_event.set()

    def _find_iio_device(self, name):
        """Find the IIO device path by name."""
        for d in glob.glob("/sys/bus/iio/devices/iio:device*"):
            try:
                with open(os.path.join(d, "name")) as f:
                    if f.read().strip() == name:
                        return d
            except: pass
        return None

    def _find_hid_devices(self):
        dev_paths = []
        for sys_path in glob.glob("/sys/class/hidraw/hidraw*"):
            try:
                with open(os.path.join(sys_path, "device/uevent"), "r") as f:
                    uevent = f.read()
                for pid in LEGION_PIDS:
                    match_str = f"HID_ID=0003:{VID:08X}:{pid:08X}"
                    if match_str in uevent.upper():
                        dev_paths.append("/dev/" + os.path.basename(sys_path))
            except Exception:
                pass
        for path in dev_paths:
            try:
                fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                self.fds[fd] = path
            except Exception:
                pass

    def _initial_sync(self):
        state = {}
        if os.path.exists(self.ryzenadj_path):
            try:
                out = subprocess.check_output([self.ryzenadj_path, "-i"], text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    line_u = line.upper()
                    if "STAPM LIMIT " in line_u:
                        parts = line.split('|')
                        if len(parts) >= 3: state["tdp"] = int(float(parts[2].strip()))
                    if "THM LIMIT CORE " in line_u or "TCTL TEMP " in line_u:
                        parts = line.split('|')
                        if len(parts) >= 3: state["temp"] = int(float(parts[2].strip()))
            except: pass

        # Check Nvidia GPU and OC state
        nvidia_oc_path = "/usr/local/bin/nvidia-oc"
        if is_nvidia_gpu_connected() and os.path.exists(nvidia_oc_path):
            try:
                out = subprocess.check_output([nvidia_oc_path, "get", "--index", "0"], text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    line_l = line.lower()
                    if "core clock offset" in line_l:
                        state["nvidia_core"] = int(line_l.split(":")[-1].replace("mhz", "").strip())
                    elif "memory clock offset" in line_l:
                        state["nvidia_mem"] = int(line_l.split(":")[-1].replace("mhz", "").strip())
                    elif "power limit" in line_l and "range" not in line_l:
                        state["nvidia_power"] = int(line_l.split(":")[-1].replace("w", "").strip())
            except:
                pass

        try:
            with open("/sys/devices/system/cpu/cpufreq/boost") as f:
                state["cpu_boost"] = f.read().strip() == "1"
        except:
            try:
                with open("/sys/devices/system/cpu/amd_pstate/cpb_boost") as f:
                    state["cpu_boost"] = f.read().strip() == "1"
            except: pass
        
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq") as f:
                state["cpu_max_freq"] = int(f.read().strip()) // 1000
        except: pass

        try:
            with open("/sys/class/drm/card0/device/power_dpm_force_performance_level") as f:
                if f.read().strip() == "manual":
                    with open("/sys/class/drm/card0/device/pp_od_clk_voltage") as f2:
                        for line in f2.read().splitlines():
                            if line.startswith("1:"):
                                state["gpu_max_freq"] = int(line.split()[1].replace("Mhz",""))
        except: pass

        payload = "SYNC_INITIAL_JSON " + json.dumps(state)
        if self.sync_callback:
            GLib.idle_add(self.sync_callback, payload)

    # --- Persistent power/thermal settings ---
    def _load_persisted_settings(self):
        try:
            if SETTINGS_PATH.exists():
                with open(SETTINGS_PATH) as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            print(f"Backend: Failed to load persisted settings: {e}")
        return {}

    def _save_persisted_settings(self):
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_PATH.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(self.persisted_settings, f, indent=2)
            os.replace(tmp, SETTINGS_PATH)
        except Exception as e:
            print(f"Backend: Failed to save persisted settings: {e}")

    def _ensure_default_settings(self):
        """First-run defaults so the device boots into Custom @ 43W / 79C."""
        changed = False
        with self.settings_lock:
            for k, v in DEFAULT_SETTINGS.items():
                if k not in self.persisted_settings:
                    self.persisted_settings[k] = v
                    changed = True
            if changed:
                self._save_persisted_settings()

    def _persist_command(self, cmd, full_line):
        if cmd not in PERSISTENT_KEYS:
            return
        with self.settings_lock:
            for group in CONFLICT_GROUPS:
                if cmd in group:
                    for k in group:
                        if k != cmd and k in self.persisted_settings:
                            del self.persisted_settings[k]
            self.persisted_settings[cmd] = full_line
            self._save_persisted_settings()

    def _apply_persisted_settings(self, reason="startup"):
        """Re-issue every persisted command via the command queue, in order."""
        with self.settings_lock:
            snapshot = dict(self.persisted_settings)
        applied = []
        for cmd in APPLY_ORDER:
            if cmd in snapshot:
                self.send_command(snapshot[cmd])
                applied.append(cmd)
        if applied:
            print(f"Backend: Re-applied persisted settings ({reason}): {', '.join(applied)}")
            # Worker is debounced (0.1s) and each ryzenadj call is ~200-500ms.
            # Refresh the UI once the batch should be done so sliders catch up.
            threading.Timer(3.0, self._initial_sync).start()

    def _get_ac_online(self):
        """Return True if AC adapter is plugged in, False if on battery, None if unknown."""
        for p in glob.glob("/sys/class/power_supply/*"):
            try:
                with open(os.path.join(p, "type")) as f:
                    if f.read().strip() != "Mains":
                        continue
                with open(os.path.join(p, "online")) as f:
                    return f.read().strip() == "1"
            except Exception:
                pass
        return None

    def _command_worker(self):
        while self.running:
            self.command_event.wait(timeout=1.0)
            if not self.running: break
            
            # Debounce: wait for more commands to accumulate and overwrite each other
            time.sleep(0.1) 
            
            to_process = []
            with self.command_lock:
                if not self.pending_commands:
                    self.command_event.clear()
                    continue
                num_pending = len(self.pending_commands)
                to_process = list(self.pending_commands.values())
                self.pending_commands.clear()
                self.command_event.clear()
            
            print(f"Backend: Executing batch of {len(to_process)} commands.")
            for line in to_process:
                try:
                    parts = line.split()
                    if not parts: continue
                    cmd = parts[0]
                    self._handle_single_command(cmd, parts, line)
                    self._persist_command(cmd, line)
                except Exception as e:
                    print(f"Error handling backend command: {e}")
            
            # Check if any new ones arrived during execution
            with self.command_lock:
                if self.pending_commands:
                    print(f"Backend: {len(self.pending_commands)} items already queued for next batch.")

    # --- Uinput for SW_TABLET_MODE ---
    def _setup_uinput(self):
        """Create a virtual input device that emits SW_TABLET_MODE."""
        try:
            # uinput ioctl constants
            UI_SET_EVBIT  = 0x40045564  # _IOW('U', 100, int)
            UI_SET_SWBIT  = 0x4004556D  # _IOW('U', 109, int)
            UI_DEV_CREATE = 0x5501
            UI_DEV_DESTROY = 0x5502
            EV_SW = 0x05
            SW_TABLET_MODE = 0x01
            
            fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            
            # Set event bits
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SW)
            fcntl.ioctl(fd, UI_SET_SWBIT, SW_TABLET_MODE)
            
            # uinput_user_dev struct: name[80], id{bustype,vendor,product,version}, ff_effects_max, absmax[64], absmin[64], absfuzz[64], absflat[64]
            name = b"legion-go-tablet-switch" + b"\x00" * (80 - len(b"legion-go-tablet-switch"))
            # id: bustype=BUS_VIRTUAL(0x06), vendor=0x1234, product=0x5678, version=1
            dev_id = struct.pack("HHHH", 0x06, 0x1234, 0x5678, 0x01)
            ff_effects = struct.pack("i", 0)
            abs_arrays = b"\x00" * (4 * 64 * 4)  # 4 arrays of 64 ints
            
            setup = name + dev_id + ff_effects + abs_arrays
            os.write(fd, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
            
            self.uinput_fd = fd
            print("Backend: Created virtual SW_TABLET_MODE uinput device.")
        except Exception as e:
            print(f"Backend: Failed to create uinput device: {e}")
            print("Backend: Auto-rotation will not work. Ensure /dev/uinput is accessible.")
            self.uinput_fd = None

    def _emit_tablet_mode(self, tablet_mode_on):
        """Emit SW_TABLET_MODE event via uinput."""
        if self.uinput_fd is None:
            return
        try:
            EV_SW = 0x05
            EV_SYN = 0x00
            SW_TABLET_MODE = 0x01
            SYN_REPORT = 0x00
            
            now = time.time()
            sec = int(now)
            usec = int((now - sec) * 1e6)
            
            # input_event struct: time_sec, time_usec, type, code, value
            # On 64-bit: struct timeval is 2x long (8 bytes each), then 2x unsigned short, 1x int
            event = struct.pack("llHHi", sec, usec, EV_SW, SW_TABLET_MODE, 1 if tablet_mode_on else 0)
            os.write(self.uinput_fd, event)
            
            # SYN_REPORT
            syn = struct.pack("llHHi", sec, usec, EV_SYN, SYN_REPORT, 0)
            os.write(self.uinput_fd, syn)
            
            print(f"Backend: SW_TABLET_MODE = {1 if tablet_mode_on else 0}")
        except Exception as e:
            print(f"Backend: Failed to emit tablet mode: {e}")

    # --- Auto-brightness ---
    def _lux_to_brightness(self, lux):
        """Map lux reading to brightness percentage (3-100) with a snappy curve."""
        if lux <= 5:
            return 3
        elif lux >= 600:
            return 100
        else:
            # More sensitive log curve for low light
            normalized = (math.log(lux) - math.log(5)) / (math.log(600) - math.log(5))
            return max(3, min(100, int(3 + normalized * 97)))

    def _set_backlight_pct(self, pct):
        """Set backlight brightness as a percentage (0-100)."""
        backlights = glob.glob("/sys/class/backlight/*/brightness")
        if not backlights:
            print("Backend: No backlight devices found!")
            return
            
        for path in backlights:
            try:
                with open(path.replace("brightness", "max_brightness")) as f:
                    max_b = int(f.read().strip())
                min_b = max(1, int(max_b * 0.01))
                target = max(min_b, int(max_b * pct / 100))
                
                # Check current value to avoid redundant writes
                try:
                    with open(path, "r") as f_read:
                        if int(f_read.read().strip()) == target:
                            continue
                except: pass
                
                with open(path, "w") as f:
                    f.write(str(target))
                if self.sensor_debug:
                    print(f"Backend: Set {path} to {target} ({pct}%)")
            except Exception as e:
                print(f"Backend: Failed to set brightness for {path}: {e}")

    def _parse_mutter_modes(self, raw_output):
        """Parse mode IDs and their available scales from GetCurrentState output.
        Returns dict: { mode_id_str: [scale1, scale2, ...] }"""
        import re
        modes = {}
        # Pattern: ('mode_id', width, height, refresh, preferred_scale, [scale_list], {props})
        # Find each mode entry by matching the mode_id pattern and the scale list after it
        pattern = r"'(\d+x\d+@[\d.]+)',\s*\d+,\s*\d+,\s*[\d.]+,\s*[\d.]+,\s*\[([\d.,\s]+)\]"
        for m in re.finditer(pattern, raw_output):
            mode_id = m.group(1)
            scale_str = m.group(2)
            scales = [float(s.strip()) for s in scale_str.split(",") if s.strip()]
            modes[mode_id] = scales
        return modes

    def _apply_display_config(self, w, h, r, rot, scale=None):
        """Apply display config. w,h are user-facing landscape dimensions.
        Mutter uses native portrait mode IDs - we find the right one dynamically."""
        try:
            if scale is None:
                scale = self.current_scale
            
            # 1. Get current state from Mutter
            p = subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
                "-o", "/org/gnome/Mutter/DisplayConfig", "-m",
                "org.gnome.Mutter.DisplayConfig.GetCurrentState"],
                capture_output=True, text=True)
            if p.returncode != 0:
                print(f"DisplayConfig Error: GetCurrentState failed")
                return
            
            raw = p.stdout
            serial = raw.split("uint32 ")[1].split(",")[0].strip()
            
            # 2. Parse all available modes and their valid scales
            available_modes = self._parse_mutter_modes(raw)
            
            # 3. Find the right mode ID
            # Native 2560x1600 is landscape in Mutter, sub-modes are portrait (e.g. 900x1440).
            # Try both orderings: as-given (w x h) and portrait-swapped (min x max).
            dim_candidates = [
                (w, h),                          # as-is (works for native 2560x1600)
                (min(w, h), max(w, h)),           # portrait swap (works for sub-modes)
            ]
            
            target_mode = None
            target_scales = [1.0]
            print(available_modes)
            for dw, dh in dim_candidates:
                if target_mode:
                    break
                for rate_str in [f"{r:.3f}", "143.999", "60.000"]:
                    candidate = f"{dh}x{dw}@{rate_str}"
                    if candidate in available_modes:
                        target_mode = candidate
                        target_scales = available_modes[candidate]
                        break
            
            # Fallback: search all modes by pixel count
            if not target_mode:
                target_pixels = w * h
                for mode_id, scales in available_modes.items():
                    dims = mode_id.split("@")[0].split("x")
                    if int(dims[0]) * int(dims[1]) == target_pixels:
                        target_mode = mode_id
                        target_scales = scales
                        break
            
            if not target_mode:
                print(f"DisplayConfig Error: No mode found for {w}x{h}@{r}Hz")
                return
            
            # 4. Clamp scale to nearest valid value for this mode
            scale = min(target_scales, key=lambda s: abs(s - scale))
            
            # 5. Determine effective transform
            # Native 2560x1600 is landscape at transform=0 (GPU driver rotates internally).
            # Sub-modes (1200x1600, 900x1440, etc.) are portrait-format in Mutter.
            # For these, transform=3 (90° CW) makes them landscape-correct.
            mode_dims = target_mode.split("@")[0].split("x")
            mode_w, mode_h = int(mode_dims[0]), int(mode_dims[1])
            
            effective_rot = rot
            if mode_w < mode_h:
                # For portrait-native sub-modes (e.g. 800x1280), transform 3 is landscape
                # effective_rot = (3 + rot) % 4
                effective_rot = 0
            
            # 6. Apply
            cmd = f"gdbus call --session --dest org.gnome.Mutter.DisplayConfig -o /org/gnome/Mutter/DisplayConfig -m org.gnome.Mutter.DisplayConfig.ApplyMonitorsConfig {serial} 2 \"[(0, 0, {repr(scale)}, uint32 {effective_rot}, true, [('eDP-1', '{target_mode}', @a{{sv}} {{}})])]\" \"@a{{sv}} {{}}\""
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0 and result.stderr:
                print(f"DisplayConfig Error: {result.stderr.strip()}")
            
            # Save current state
            self.current_res_w = w
            self.current_res_h = h
            self.current_rate = r
            self.current_scale = scale
            self.current_rot = rot
            
            print(f"Backend: Applied {w}x{h}@{r}Hz Mode:{target_mode} Scale:{scale} Rot:{rot} T:{effective_rot}")
        except Exception as e:
            print(f"DisplayConfig Error: {e}")

    def _handle_single_command(self, cmd, parts, full_line):
        ryzenadj_path = self.ryzenadj_path
        if cmd == "SET_TDP" and len(parts) >= 2:
            mw = int(parts[1]) * 1000
            subprocess.call([ryzenadj_path, "--stapm-limit", str(mw), "--fast-limit", str(mw), "--slow-limit", str(mw)], stderr=subprocess.DEVNULL)
        elif cmd == "SET_TEMP" and len(parts) >= 2:
            temps = int(parts[1])
            subprocess.call([ryzenadj_path, "--tctl-temp", str(temps)], stderr=subprocess.DEVNULL)
        elif cmd == "SET_GPU_FREQ_MODE" and len(parts) >= 2:
            for hw in glob.glob("/sys/class/drm/card*"):
                try:
                    with open(f"{hw}/device/vendor") as f:
                        if "0x1002" in f.read():
                            with open(f"{hw}/device/power_dpm_force_performance_level", "w") as f_pow:
                                f_pow.write(parts[1])
                except: pass
        elif cmd == "SET_GPU_FREQ" and len(parts) >= 2:
            freq = int(parts[1])
            for hw in glob.glob("/sys/class/drm/card*"):
                try:
                    with open(f"{hw}/device/vendor") as f:
                        if "0x1002" in f.read():
                            with open(f"{hw}/device/power_dpm_force_performance_level", "w") as f_pow:
                                f_pow.write("manual")
                            for c in [f"s 0 {freq}\n", f"s 1 {freq}\n", "c\n"]:
                                with open(f"{hw}/device/pp_od_clk_voltage", "w") as f_od:
                                    f_od.write(c)
                except: pass
        elif cmd == "SET_CPU_BOOST" and len(parts) >= 2:
            val = parts[1]
            for p in ["/sys/devices/system/cpu/amd_pstate/cpb_boost", "/sys/devices/system/cpu/cpufreq/boost"]:
                if os.path.exists(p):
                    try:
                        with open(p, "w") as f: f.write(val)
                    except: pass
        elif cmd == "SET_CPU_MAX_FREQ" and len(parts) >= 2:
            freq_khz = int(parts[1]) * 1000
            for d in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq"):
                try:
                    with open(d, "w") as f: f.write(str(freq_khz))
                except: pass
        elif cmd == "SET_PROFILE" and len(parts) >= 2:
            profile = parts[1]
            mode_map = {
                "quiet": r"\_SB.GZFD.WMAA 0x00 0x2C 0x01", "balanced": r"\_SB.GZFD.WMAA 0x00 0x2C 0x02",
                "performance": r"\_SB.GZFD.WMAA 0x00 0x2C 0x03", "custom": r"\_SB.GZFD.WMAA 0x00 0x2C 0xFF"
            }
            if profile in mode_map and os.path.exists("/proc/acpi/call"):
                try:
                    with open("/proc/acpi/call", "w") as f: f.write(mode_map[profile])
                except: pass
        elif cmd == "SET_CTRL_RGB" and len(parts) >= 8:
            r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
            mode, br, sp, side = parts[4], int(parts[5]), int(parts[6]), parts[7].upper()
            targets = ["LEFT", "RIGHT"] if side == "BOTH" else [side]
            for t in targets: controller_hid.set_rgb(t, r, g, b, mode, br, sp)
        elif cmd == "SET_CTRL_RGB_OFF" and len(parts) >= 2:
            side = parts[1].upper()
            targets = ["LEFT", "RIGHT"] if side == "BOTH" else [side]
            for t in targets: controller_hid.set_rgb_off(t)
        elif cmd == "SET_FAN_CURVE" and len(parts) == 11:
            try:
                arr = [int(x) for x in parts[1:11]]
                payload = [
                    0x00, 0x00, 0x0A, 0x00, 0x00, 0x00, arr[0], 0x00, arr[1], 0x00, arr[2], 0x00, arr[3], 0x00, arr[4], 0x00,
                    arr[5], 0x00, arr[6], 0x00, arr[7], 0x00, arr[8], 0x00, arr[9], 0x00, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x0A,
                    0x00, 0x14, 0x00, 0x1E, 0x00, 0x28, 0x00, 0x32, 0x00, 0x3C, 0x00, 0x46, 0x00, 0x50, 0x00, 0x5A, 0x00, 0x64, 0x00, 0x00
                ]
                hex_str = "".join(f"{b:02x}" for b in payload)
                if os.path.exists("/proc/acpi/call"):
                    with open("/proc/acpi/call", "w") as f: f.write(f"\\_SB.GZFD.WMAB 0x00 0x06 b{hex_str}")
            except: pass
        elif cmd == "SET_FULL_FAN" and len(parts) >= 2:
            val = int(parts[1])
            cmd_acpi = r"\_SB.GZFD.WMAE 0x00 0x12 b0000020401000000" if val == 1 else r"\_SB.GZFD.WMAE 0x00 0x12 b0000020400000000"
            if os.path.exists("/proc/acpi/call"):
                try:
                    with open("/proc/acpi/call", "w") as f: f.write(cmd_acpi)
                except: pass
        elif cmd == "TOGGLE_LED" and len(parts) >= 2:
            val = int(parts[1])
            # Trying a more robust pattern for the power LED toggle
            # Some BIOS use WMAF 0x02 with b030100/b030000, others might use different offsets
            cmd_acpi = r"\_SB.GZFD.WMAF 0x00 0x02 b030100" if val == 1 else r"\_SB.GZFD.WMAF 0x00 0x02 b030000"
            if os.path.exists("/proc/acpi/call"):
                try:
                    with open("/proc/acpi/call", "w") as f: f.write(cmd_acpi)
                    # Also try the older/alternative offset just in case
                    alt_cmd = r"\_SB.GZFD.WMAA 0x00 0x2c 0x01" if val == 1 else r"\_SB.GZFD.WMAA 0x00 0x2c 0x00"
                    # wait, 0x2c is profile. 0x21 might be LED
                    # I'll stick to WMAF for now but maybe the bit mask is different.
                except: pass
        elif cmd == "SET_VIBRATION" and len(parts) >= 2:
            strength = int(parts[1]) # 1-4
            controller_hid.set_vibration(strength)
        elif cmd == "SET_GYRO_MAP" and len(parts) >= 2:
            payload_str = full_line.split(maxsplit=1)[1]
            try:
                configs = json.loads(payload_str)
                controller_hid.apply_gyro_mapping(configs)
            except Exception as e:
                print(f"Backend: Failed to parse SET_GYRO_MAP payload: {e}")
        elif cmd == "SET_CTRL_PROFILE" and len(parts) >= 2:
            prof_num = int(parts[1])
            for btn in ["Y1","Y2","Y3","M2","M3"]:
                controller_hid.remap_button_profile(prof_num, btn, "DISABLED")
        elif cmd == "REMAP_BTN" and len(parts) >= 4:
            prof, btn, act = int(parts[1]), parts[2].upper(), parts[3].upper()
            controller_hid.remap_button_profile(prof, btn, act)
        elif cmd == "SET_CTRL_MAP" and len(parts) >= 2:
            payload_str = full_line.split(maxsplit=1)[1]
            mappings = json.loads(payload_str)
            print(f"Backend: Received remapping for {len(mappings)} buttons.")
            controller_hid.apply_hardware_remapping(mappings)
        elif cmd == "SET_BATTERY_LIMIT" and len(parts) >= 2:
            val = int(parts[1])
            payload = "b0100010301000000" if val else "b0100010300000000"
            if os.path.exists("/proc/acpi/call"):
                try:
                    with open("/proc/acpi/call", "w") as f: f.write(f"\\_SB.GZFD.WMAE 0x00 0x12 {payload}")
                except: pass
        elif cmd == "SET_BRIGHTNESS" and len(parts) >= 2:
            val = int(parts[1]) # 0-100
            self._set_backlight_pct(val)
        elif cmd == "SET_AUTO_BRIGHTNESS" and len(parts) >= 2:
            val = int(parts[1])
            self.auto_brightness_enabled = (val == 1)
            self.sensor_debug = (val == 1)
            if not self.auto_brightness_enabled:
                self.last_auto_br_value = -1  # Reset so manual slider works immediately
        elif cmd == "SET_RESOLUTION" and len(parts) >= 3:
            w, h = int(parts[1]), int(parts[2])
            self._apply_display_config(w, h, self.current_rate, self.current_rot)
        elif cmd == "SET_REFRESH" and len(parts) >= 2:
            r = int(parts[1])
            self._apply_display_config(self.current_res_w, self.current_res_h, r, self.current_rot)
        elif cmd == "SET_SCALING" and len(parts) >= 2:
            scale = float(parts[1])
            self._apply_display_config(self.current_res_w, self.current_res_h, self.current_rate, self.current_rot, scale)
        elif cmd == "SET_ROTATION" and len(parts) >= 2:
            val = int(parts[1])
            rot_map = {0: 0, 90: 1, 180: 2, 270: 3}
            rot = rot_map.get(val, 0)
            # Apply first to make it current, then lock it
            self._apply_display_config(self.current_res_w, self.current_res_h, self.current_rate, rot)
            subprocess.run(["gsettings", "set", "org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock", "true"], check=False)
        elif cmd == "SET_AUTO_ROTATION" and len(parts) >= 2:
            enabled = int(parts[1]) == 1
            self.auto_rotation_enabled = enabled
            self.sensor_debug = enabled
            if enabled:
                # Enable: enter tablet mode, unlock orientation
                subprocess.run(["gsettings", "set", "org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock", "false"], check=False)
                self._emit_tablet_mode(True)
            else:
                # Disable: lock at CURRENT orientation. 
                # Avoid re-applying config here to prevent GNOME's "keep changes" dialog.
                subprocess.run(["gsettings", "set", "org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock", "true"], check=False)
        elif cmd == "SET_LEGION_SWAP" and len(parts) >= 2:
            val = int(parts[1])
            payload = bytes([0x05, 0x06, 0x69, 0x04, 0x01, 0x02 if val else 0x01, 0x01])
            for fd in list(self.fds.keys()):
                try: os.write(fd, payload)
                except: pass
        elif cmd == "SET_NVIDIA_OC" and len(parts) >= 4:
            power = int(parts[1])
            core = int(parts[2])
            mem = int(parts[3])
            nvidia_oc_path = "/usr/local/bin/nvidia-oc"
            if os.path.exists(nvidia_oc_path):
                try:
                    subprocess.call([
                        nvidia_oc_path, "set", "--index", "0",
                        "--power-limit", str(power * 1000),
                        "--freq-offset", str(core),
                        "--mem-offset", str(mem)
                    ], stderr=subprocess.DEVNULL)
                except Exception as e:
                    print(f"Backend: Failed to run nvidia-oc set: {e}")

    def _telemetry_loop(self):
        while self.running:
            try:
                hwmon_temps = {}
                for d in glob.glob("/sys/class/hwmon/hwmon*"):
                    try:
                        with open(f"{d}/name") as f: name = f.read().strip()
                        if name == "k10temp":
                            with open(f"{d}/temp1_input") as f: hwmon_temps["cpu_temp"] = int(f.read().strip()) // 1000
                        elif name == "amdgpu":
                            with open(f"{d}/temp1_input") as f: hwmon_temps["gpu_temp"] = int(f.read().strip()) // 1000
                            try:
                                with open(f"{d}/freq1_input") as f: hwmon_temps["gpu_freq"] = int(f.read().strip()) // 1000000
                            except: pass
                        elif name == "nvme":
                            with open(f"{d}/temp1_input") as f: hwmon_temps["ssd_temp"] = int(f.read().strip()) // 1000
                    except: pass
                
                if os.path.exists(self.ryzenadj_path):
                    try:
                        out = subprocess.check_output([self.ryzenadj_path, "-i"], text=True, stderr=subprocess.DEVNULL)
                        for line in out.splitlines():
                            line_u = line.upper()
                            if "SOCKET POWER" in line_u or "PACKAGE POWER" in line_u:
                                parts = line.split('|')
                                if len(parts) >= 3:
                                    hwmon_temps["apu_power"] = round(float(parts[2].strip()), 1)
                                    break
                    except: pass
                
                batt_stats = {}
                for b in glob.glob("/sys/class/power_supply/BATT*"):
                    try:
                        with open(f"{b}/capacity") as f: batt_stats["bat_level"] = int(f.read().strip())
                        with open(f"{b}/status") as f: batt_stats["bat_status"] = f.read().strip()
                        with open(f"{b}/energy_full") as f: energy_full = int(f.read().strip())
                        with open(f"{b}/energy_full_design") as f: energy_full_design = int(f.read().strip())
                        batt_stats["bat_health"] = int(100 * energy_full / energy_full_design)
                    except: pass
                
                cpu_freq = 0
                for d in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"):
                    try:
                        with open(d) as f: cpu_freq = max(cpu_freq, int(f.read().strip()) // 1000)
                    except: pass
                
                payload = {
                    "system": hwmon_temps, "battery": batt_stats, "cpu_freq": cpu_freq,
                    "controllers": {"l_bat": self.CONTROLLER_L_BAT, "l_status": self.CONTROLLER_L_STATUS, "r_bat": self.CONTROLLER_R_BAT, "r_status": self.CONTROLLER_R_STATUS}
                }
                
                if self.telemetry_callback:
                    GLib.idle_add(self.telemetry_callback, payload)

                # AC adapter state change → EC resets profile/TDP/temp.
                # Re-apply persisted settings whenever the plug state flips.
                ac_now = self._get_ac_online()
                if ac_now is not None and ac_now != self.last_ac_online:
                    prev = self.last_ac_online
                    self.last_ac_online = ac_now
                    if prev is not None:
                        reason = f"AC {'plugged' if ac_now else 'unplugged'}"
                        print(f"Backend: {reason}, scheduling re-apply.")
                        # Give the EC ~1.5s to settle before re-issuing.
                        threading.Timer(1.5, self._apply_persisted_settings, args=(reason,)).start()

                # Sensor Debug Logging & Auto-Brightness (1s interval)
                curr = time.time()
                if curr - self.last_sensor_log > 0.5:
                    try:
                        lx_val = None
                        if os.path.exists(self.lux_path):
                            with open(self.lux_path) as f:
                                lx_str = f.read().strip()
                                try: lx_val = int(lx_str)
                                except: pass
                        
                        if self.sensor_debug:
                            ax, ay, az = "N/A", "N/A", "N/A"
                            if os.path.exists(self.accel_x):
                                with open(self.accel_x) as f: ax = f.read().strip()
                            if os.path.exists(self.accel_y):
                                with open(self.accel_y) as f: ay = f.read().strip()
                            if os.path.exists(self.accel_z):
                                with open(self.accel_z) as f: az = f.read().strip()
                            print(f"DEBUG SENSORS: Lux={lx_val} (path: {self.lux_path}) | Accel X={ax} Y={ay} Z={az}")
                        
                        # Auto-brightness: smooth transition using EMA
                        if self.auto_brightness_enabled and lx_val is not None:
                            raw_target = self._lux_to_brightness(lx_val)
                            
                            if self.smoothed_brightness < 0:
                                self.smoothed_brightness = float(raw_target)
                            else:
                                # EMA alpha=0.6 for more responsiveness
                                self.smoothed_brightness = 0.6 * raw_target + 0.4 * self.smoothed_brightness
                            
                            # Apply in bolder steps (max 8% change per 0.5s)
                            final = int(self.smoothed_brightness)
                            if self.last_auto_br_value < 0:
                                self.last_auto_br_value = final
                            step = max(-100, min(100, final - self.last_auto_br_value))
                            if step != 0:
                                self.last_auto_br_value += step
                                if self.sensor_debug:
                                    print(f"DEBUG: Auto-Brightness Target={final} Current={self.last_auto_br_value}%")
                                self._set_backlight_pct(self.last_auto_br_value)
                        
                        self.last_sensor_log = curr
                    except: pass
            except Exception as e:
                print(f"Backend: Telemetry loop error: {e}")
            time.sleep(0.5 if self.auto_brightness_enabled else 2)

    def _hid_loop(self):
        last_1, last_2 = False, False
        while self.running:
            if not self.fds:
                self._find_hid_devices()
                if not self.fds:
                    time.sleep(2)
                    continue
                print(f"Backend: Found {len(self.fds)} HID devices.")
            
            try:
                # Filter out any closed FDs
                active_fds = list(self.fds.keys())
                if not active_fds:
                    continue
                    
                r, _, _ = select.select(active_fds, [], [], 1.0)
                for fd in r:
                    try:
                        data = os.read(fd, 64)
                        if len(data) >= 19:
                            b18 = data[18]
                            button1, button2 = bool(b18 & 0x40), bool(b18 & 0x80)
                            self.CONTROLLER_L_BAT, self.CONTROLLER_L_STATUS = data[5], data[6]
                            self.CONTROLLER_R_BAT, self.CONTROLLER_R_STATUS = data[7], data[8]
                            
                            if button1 and not last_1 and self.toggle_callback:
                                GLib.idle_add(self.toggle_callback)
                            if button2 and not last_2 and self.keyboard_callback:
                                GLib.idle_add(self.keyboard_callback)
                            last_1, last_2 = button1, button2
                    except BlockingIOError:
                        pass
                    except OSError:
                        print(f"Backend: Device {self.fds[fd]} disconnected.")
                        os.close(fd)
                        del self.fds[fd]
            except Exception as e:
                print(f"Backend: HID Loop error: {e}")
                time.sleep(1)

# Global Singleton
_backend = DeviceBackend()

def get_backend():
    return _backend

def send_command(cmd_str):
    _backend.send_command(cmd_str)

def listen_for_buttons(toggle_callback, keyboard_callback, sync_callback, telemetry_callback):
    _backend.set_callbacks(toggle_callback, keyboard_callback, sync_callback, telemetry_callback)
