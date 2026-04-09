import os
import ctypes
import atexit

hidapi = None
library_paths = (
    'libhidapi-hidraw.so',
    'libhidapi-hidraw.so.0',
    'libhidapi-libusb.so',
    'libhidapi-libusb.so.0',
    'libhidapi.so',
    'libhidapi.so.0',
)

for lib in library_paths:
    try:
        hidapi = ctypes.cdll.LoadLibrary(lib)
        break
    except OSError:
        pass
else:
    # Try finding it globally or silently fail if not used yet
    pass

if hidapi:
    try:
        hidapi.hid_init()
        atexit.register(hidapi.hid_exit)
        hidapi.hid_init.argtypes = []
        hidapi.hid_init.restype = ctypes.c_int
        hidapi.hid_exit.argtypes = []
        hidapi.hid_exit.restype = ctypes.c_int
        hidapi.hid_open_path.argtypes = [ctypes.c_char_p]
        hidapi.hid_open_path.restype = ctypes.c_void_p
        hidapi.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        hidapi.hid_write.restype = ctypes.c_int
        hidapi.hid_close.argtypes = [ctypes.c_void_p]
        hidapi.hid_close.restype = None
        hidapi.hid_error.argtypes = [ctypes.c_void_p]
        hidapi.hid_error.restype = ctypes.c_wchar_p
    except Exception as e:
        print(f"Failed to setup hidapi config: {e}")

class HIDException(Exception): pass

class Device(object):
    def __init__(self, path=None):
        if path:
            self.__dev = hidapi.hid_open_path(path)
        else:
            raise ValueError('specify path')
        if not self.__dev:
            raise HIDException('unable to open device')

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, exc_traceback): self.close()

    def write(self, data):
        ret = hidapi.hid_write(self.__dev, data, len(data))
        if ret == -1:
            err = hidapi.hid_error(self.__dev)
            raise HIDException(err)
        return ret

    def close(self):
        if self.__dev:
            hidapi.hid_close(self.__dev)
            self.__dev = None

# Lenovo Vendor ID
VENDOR_ID = 0x17EF

# Legion Go controller product IDs
PRODUCT_IDS = [0x6180, 0x61E0, 0x6182, 0x6183, 0x6184, 0x6185, 0x61EB, 0x61EC, 0x61ED, 0x61EE]
USAGE_PAGE = 0xFFA0

# Enums
Controllers = {"LEFT": 0x03, "RIGHT": 0x04}

RemappableButtons = {
    "Y1": 0x1c, "Y2": 0x1d, "Y3": 0x1e, "M2": 0x21, "M3": 0x22
}

RemapActions = {
    "DISABLED": 0x00,
    "L_STICK_CLICK": 0x03, "L_STICK_UP": 0x04, "L_STICK_DOWN": 0x05, "L_STICK_LEFT": 0x06, "L_STICK_RIGHT": 0x07,
    "R_STICK_CLICK": 0x08, "R_STICK_UP": 0x09, "R_STICK_DOWN": 0x0a, "R_STICK_LEFT": 0x0b, "R_STICK_RIGHT": 0x0c,
    "D_PAD_UP": 0x0d, "D_PAD_DOWN": 0x0e, "D_PAD_LEFT": 0x0f, "D_PAD_RIGHT": 0x10,
    "BUTTON_A": 0x12, "BUTTON_B": 0x13, "BUTTON_X": 0x14, "BUTTON_Y": 0x15,
    "L_BUMPER": 0x16, "L_TRIGGER": 0x17, "R_BUMPER": 0x18, "R_TRIGGER": 0x19,
    "VIEW": 0x23, "MENU": 0x24
}

# Device types for remapping
DEVICE_CONTROLLER = 0x01
DEVICE_KEYBOARD = 0x02
DEVICE_MOUSE = 0x03
RgbModes = {"SOLID": 0x01, "PULSE": 0x02, "DYNAMIC": 0x03, "SPIRAL": 0x04}

_cached_paths = []
_working_path = None

def get_config_paths():
    global _cached_paths
    if _cached_paths:
        return _cached_paths
    # ... (no changes to the glob logic)
    
    import glob
    paths = []
    for sys_path in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            with open(os.path.join(sys_path, "device/uevent"), "r") as f:
                uevent = f.read()
            for pid in PRODUCT_IDS:
                if f"0003:{VENDOR_ID:08X}:" in uevent.upper() and f"{pid:04X}" in uevent.upper():
                    paths.append( ("/dev/" + os.path.basename(sys_path)).encode('utf-8') )
        except Exception:
            pass
    _cached_paths = paths
    return paths

def clear_path_cache():
    global _cached_paths
    _cached_paths = []

def send_command(command):
    return send_commands([command])

def send_commands(commands):
    global _working_path
    paths = get_config_paths()
    if not paths:
        print("Controller HID configuration device not found.")
        return False
    
    # Prioritize the last confirmed working path
    if _working_path and _working_path in paths:
        paths = [_working_path] + [p for p in paths if p != _working_path]

    for path in paths:
        try:
            with Device(path=path) as device:
                for cmd in commands:
                    device.write(pad_command(cmd))
                # If we successfully wrote a batch, this is the right device
                _working_path = path
                return True 
        except Exception:
            continue # Try next path if this one failed
            
    print("Error: Could not write to ANY matching HID device endpoints.")
    _working_path = None # Reset if all failed
    return False

def pad_command(command):
    return bytes(command) + bytes([0x00] * (64 - len(command)))

def set_rgb(controller_name, r, g, b, mode_name="SOLID", brightness=100, speed=50):
    controller = Controllers[controller_name]
    mode = RgbModes.get(mode_name, 0x01)
    
    # Scale brightness and speed
    r_brightness = min(max(int(64 * (brightness / 100.0)), 0), 63)
    r_period = min(max(int(64 * (1.0 - (speed / 100.0))), 0), 63)
    prof = 0x03
    
    cmd_set = [0x05, 0x0c, 0x72, 0x01, controller, mode, r, g, b, r_brightness, r_period, prof, 0x01]
    cmd_load = [0x05, 0x06, 0x73, 0x02, controller, prof, 0x01]
    cmd_en = [0x05, 0x06, 0x70, 0x02, controller, 0x01, 0x01]
    
    send_commands([cmd_set, cmd_load, cmd_en])

def set_rgb_off(controller_name):
    controller = Controllers[controller_name]
    cmd_off = [0x05, 0x06, 0x70, 0x02, controller, 0x00, 0x01]
    send_commands([cmd_off])

def set_vibration(strength_idx):
    """
    strength_idx: 1 (Off), 2 (Weak), 3 (Mid), 4 (Strong)
    """
    # Global vibration strength command seen in decode.md
    cmd = [0x05, 0x00, 0x06, 0x02, 0x00, strength_idx]
    send_command(cmd)

def apply_gyro_mapping(configs):
    """
    configs: list of dicts like:
    {
        "controller": 0x03 or 0x04,
        "mode": 0x01 (Disable), 0x02 (L-Stick), 0x03 (R-Stick), 0x04 (Mouse),
        "mapping_type": 0x01 (Instant), 0x02 (Continuous) - joystick only,
        "sensitivity": 1-100,
        "invert_x": bool,
        "invert_y": bool,
        "activation_mode": 0x01 (Always), 0x02 (Hold), 0x03 (Toggle),
        "activation_buttons": [0x18, 0x19] # list of keys holding/toggling
    }
    """
    packets = []
    for cfg in configs:
        ctrl = cfg.get("controller", 0x04)
        mode = cfg.get("mode", 0x01)
        mtype = cfg.get("mapping_type", 0x01)
        sens = int(min(max(cfg.get("sensitivity", 50), 1), 100))
        inv_x = 0x02 if cfg.get("invert_x", False) else 0x01
        inv_y = 0x02 if cfg.get("invert_y", False) else 0x01
        act_mode = cfg.get("activation_mode", 0x01)
        act_btns = cfg.get("activation_buttons", [])
        
        # 1. Turn on/off mapping for the controller
        packets.append(pad_command([0x05, 0x00, 0x0e, 0x02, ctrl, mode]))
        
        if mode > 1: # If not disabled
            if mode == 0x04: # Mouse mode
                # 0x0e 04 04 00 00 SS SS 01 02
                pkt = [0x05, 0x00, 0x0e, 0x04, ctrl, 0x00, 0x00, sens, sens, inv_x, inv_y]
                packets.append(pad_command(pkt))
            else: # Joystick mode (L-stick or R-stick)
                # 0x0e 03 04 00 00 01 32 32 ff ff ff ff 01 01 
                pkt = [0x05, 0x00, 0x0e, 0x03, ctrl, 0x00, 0x00, mtype, sens, sens, 0xff, 0xff, 0xff, 0xff, inv_x, inv_y]
                packets.append(pad_command(pkt))
                
            # Activation buttons
            # 0x0e 05 04 02 18
            pkt_act = [0x05, 0x00, 0x0e, 0x05, ctrl, act_mode] + act_btns
            packets.append(pad_command(pkt_act))
            
    if packets:
        send_commands(packets)

def remap_button_profile(profile_idx, button_name, action_name):
    """
    profile_idx: 1-4
    """
    controller = Controllers["RIGHT"] if button_name in ["Y3", "M2", "M3"] else Controllers["LEFT"]
    btn = RemappableButtons[button_name]
    act = RemapActions.get(action_name, 0x00)
    
    cmd = [0x05, 0x08, 0x6c, 0x04, controller, profile_idx, btn, act, 0x01]
    send_command(pad_command(cmd))

def apply_hardware_remapping(mappings):
    """
    mappings: list of dicts like:
    {
        "btn": 0x16,        # physical button code
        "device": 0x01,     # 0x01: controller, 0x02: kbd, 0x03: mouse
        "keys": [0x16, 0, 0, 0, 0] # up to 5 keys/buttons
    }
    """
    # Button Ownership Maps
    LEFT_BTNS = {0x16, 0x17, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0d, 0x0e, 0x0f, 0x10, 0x1c, 0x1d, 0x23}
    RIGHT_BTNS = {0x12, 0x13, 0x14, 0x15, 0x18, 0x19, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x1e, 0x21, 0x22, 0x24}

    # Split mappings by controller ownership
    for ctrl_id in [0x03, 0x04]:
        target_btns = LEFT_BTNS if ctrl_id == 0x03 else RIGHT_BTNS
        ctrl_mappings = [m for m in mappings if m["btn"] in target_btns]
        
        packets = []
        if not ctrl_mappings:
            # Send a clear/empty mapping list (count=0) to this controller
            clear_data = [0x05, 0x00, 0x12, 0x0a, ctrl_id, 0x01, 0x11, 0x00]
            packets.append(clear_data)
        else:
            # Max 8 rows per 64-byte packet
            chunks = [ctrl_mappings[i:i + 8] for i in range(0, len(ctrl_mappings), 8)]
            total_chunks = len(chunks)
            base_data = [0x00, 0x12, 0x0a]
            for chunk_idx, chunk in enumerate(chunks):
                current_chunk = chunk_idx + 1
                xx = (total_chunks << 4) | current_chunk
                data = [0x05] + base_data + [ctrl_id, 0x01, xx, len(chunk)]
                for m in chunk:
                    row = [m["btn"], m["device"]] + (list(m["keys"]) + [0]*5)[:5]
                    data.extend(row)
                
                # Explicitly pad to 64 bytes as requested (0x05 header + 63 body)
                data = (data + [0]*64)[:64]
                packets.append(data)

        if packets:
            print(f"[HID-REMAP] Sending batch of {len(packets)} packets to Controller {ctrl_id:02x}")
            for midx, p in enumerate(packets):
                print(f"  Packet {midx+1}:")
                for i in range(0, 64, 16):
                    hex_part = " ".join(f"{b:02x}" for b in p[i:i+16])
                    print(f"    {i:04x}  {hex_part}")
            send_commands(packets)

