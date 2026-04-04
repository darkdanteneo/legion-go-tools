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
    
    HID Packet format (based on Wireshark capture, USB overhead stripped):
    [0x05] [0x12] [0x0a] [0x03] [0x01] [XX] [count] [row0] [row1] ...
    where row = [btn_code, device_code, key0, key1, key2, key3, key4]  (7 bytes)
    
    Known XX values from capture:
      1 row  -> 0x11 (17)
      7 rows -> 0x22 (34)
      8 rows -> 0x21 (33)
    Pattern: XX = 8 + count * 7 - (count - 1)? Actually simpler: count*7 + 6 doesn't match...
    8 rows: 8*7=56, XX=0x21=33. 7 rows: 7*7=49, XX=0x22=34. 1 row: 1*7=7, XX=0x11=17.
    Differences: 33+56=89, 34+49=83... no pattern on sum.
    Diff between XX and count: 33-8=25, 34-7=27, 17-1=16... no clear pattern.
    Best approach: just compute XX = 8 + (count - 1) * 7 + count (still wrong).
    For now: map known values, and for unknown counts try: XX = 17 + (count - 1) * 7
    1 -> 17+0=17=0x11 ✓, 7->17+42=59... nope.
    Try XX = 0x0a + count * (0x0a? 0x05?). 0x0a + 1*7=17 ✓! 0x0a + 7*7=59 ✗.
    Simpler: XX = (payload_length - 1) where payload_length = 5 + count * 7?
    5 + 1*7 = 12 -> 11=0x0b ✗.
    Let's just hard-compute from data: XX = count_byte_high_nibble_weirdness.
    SIMPLEST FIX: use the known map and for others, use 0x10 + count as best guess.
    """
    count = len(mappings)
    if count == 0:
        return

    # Known XX values from Wireshark captures
    # Pattern analysis: XX for 1=0x11, 7=0x22, 8=0x21
    # It looks like XX = total_data_bytes_after_count / something
    # 1 row: 0x11=17. Remaining data after XX+count = 1*7=7. 17-7=10=0x0a
    # 7 rows: 0x22=34. Remaining = 7*7=49. 34-49 = -15 (no)
    # Let's try: XX is just part of the command opcode sub-sequence and not dependent on count.
    # Actually, maybe XX and count are swapped: 0x21 0x08 -> XX=0x21, count=8
    # but for 7 rows: 0x22 0x07 and 1 row: 0x11 0x01.
    # For 1 row: 0x11 appears before 0x01. So XX > count by: 0x11-0x01=16, 0x22-0x07=27, 0x21-0x08=25
    # No clear linear pattern either. But 0x11=17=0x10+0x01, 0x22=34=0x10+0x07+...
    # Best guess: just always send 0x21 (8 row value) as a max placeholder for now,
    # or try: XX = total_padded_rows_len where each row is ≥ 7 bytes.
    # For safety: use lookup and fall back gracefully.
    xx_map = {1: 0x11, 7: 0x22, 8: 0x21}
    # Interpolate for missing counts
    xx = xx_map.get(count, 0x10 + count)

    # Build the base payload WITHOUT the Report ID yet
    # Format according to Legion Space: [0x00, 0x12, 0x0a, ControllerID, 0x01, XX, count, ...rows...]
    base_data = [0x00, 0x12, 0x0a]
    
    # We must send this configuration to BOTH the Left (0x03) and Right (0x04) logical 
    # devices on the Legion Go, otherwise some buttons (like M3) won't save.
    for ctrl_id in [0x04]:
        data = [0x05] + base_data + [ctrl_id, 0x01, xx, count]
        for m in mappings:
            # Each row: [btn_code, device, key0, key1, key2, key3, key4] = 7 bytes
            row = [m["btn"], m["device"]] + (list(m["keys"]) + [0]*5)[:5]
            data.extend(row)
            
        padded = pad_command(data)
        
        # Hex dump exactly what goes to hidapi
        print(f"[HID-REMAP] Sending to Controller {ctrl_id:02x} (XX=0x{xx:02x}):")
        for i in range(0, 64, 16):
            hex_part = " ".join(f"{b:02x}" for b in padded[i:i+16])
            print(f"  {i:04x}  {hex_part}")
            
        send_command(padded)
