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

def get_config_paths():
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
    return paths

def send_command(command):
    return send_commands([command])

def send_commands(commands):
    paths = get_config_paths()
    if not paths:
        print("Controller HID configuration device not found.")
        return False
    
    success = False
    for path in paths:
        try:
            with Device(path=path) as device:
                for cmd in commands:
                    print(cmd)
                    device.write(pad_command(cmd))
                success = True
        except Exception as e:
            pass # Keep trying other paths
            
    if not success:
        print("Error: Could not write to ANY matching HID device endpoints.")
        
    return success

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
    if not mappings:
        return

    # Max 8 rows per 64-byte packet
    chunks = [mappings[i:i + 8] for i in range(0, len(mappings), 8)]
    total_chunks = len(chunks)

    # Base payload structure
    base_data = [0x00, 0x12, 0x0a]

    # We send configuration to BOTH Left (0x03) and Right (0x04) logical devices
    for ctrl_id in [0x04]:
        for chunk_idx, chunk in enumerate(chunks):
            current_chunk = chunk_idx + 1
            count = len(chunk)
            
            # The mystery XX byte is (total_chunks << 4) | current_chunk !
            # e.g., 1 of 1 -> 0x11, 1 of 2 -> 0x21, 2 of 2 -> 0x22
            xx = (total_chunks << 4) | current_chunk

            data = [0x05] + base_data + [ctrl_id, 0x01, xx, count]
            for m in chunk:
                # Each row: [btn_code, device, key0, key1, key2, key3, key4] = 7 bytes
                row = [m["btn"], m["device"]] + (list(m["keys"]) + [0]*5)[:5]
                data.extend(row)

            padded = pad_command(data)

            print(f"[HID-REMAP] Sending to Controller {ctrl_id:02x} (Chunk {current_chunk}/{total_chunks}, XX=0x{xx:02x}):")
            for i in range(0, 64, 16):
                hex_part = " ".join(f"{b:02x}" for b in padded[i:i+16])
                print(f"  {i:04x}  {hex_part}")

            send_command(padded)
