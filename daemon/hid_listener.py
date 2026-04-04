#!/usr/bin/env python3
import os
import glob
import time
import socket
import select
import sys
import subprocess
import threading
import json
import controller_hid
# import input_mapper

LEGION_PIDS = [0x6182, 0x6183, 0x6184, 0x6185, 0x61EB, 0x61EC, 0x61ED, 0x61EE]
VID = 0x17EF
SOCK_PATH = "/tmp/legion_sidebar.sock"

clients = []

CONTROLLER_L_BAT = -1
CONTROLLER_L_STATUS = -1
CONTROLLER_R_BAT = -1
CONTROLLER_R_STATUS = -1

# Initialize telemetry poller
def poll_telemetry():
    while True:
        try:
            hwmon_temps = {}
            for d in glob.glob("/sys/class/hwmon/hwmon*"):
                try:
                    with open(f"{d}/name") as f:
                        name = f.read().strip()
                    if name in ["k10temp", "amdgpu", "nvme", "BATT"]:
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
            
            # Read APU power via RyzenAdj
            ryzenadj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../bin/ryzenadj")
            if os.path.exists(ryzenadj_path):
                try:
                    out = subprocess.check_output([ryzenadj_path, "-i"], text=True, stderr=subprocess.DEVNULL)
                    for line in out.splitlines():
                        line_u = line.upper()
                        if "SOCKET POWER" in line_u or "PACKAGE POWER" in line_u:
                            parts = line.split('|')
                            if len(parts) >= 3:
                                hwmon_temps["apu_power"] = round(float(parts[2].strip()), 1)
                                break
                except: pass
            
            batt_stats = {}
            try:
                for b in glob.glob("/sys/class/power_supply/BATT*"):
                    with open(f"{b}/capacity") as f: batt_stats["bat_level"] = int(f.read().strip())
                    with open(f"{b}/status") as f: batt_stats["bat_status"] = f.read().strip()
                    with open(f"{b}/energy_full") as f: energy_full = int(f.read().strip())
                    with open(f"{b}/energy_full_design") as f: energy_full_design = int(f.read().strip())
                    batt_stats["bat_health"] = int(100 * energy_full / energy_full_design)
            except: pass
            
            cpu_freq = 0
            try:
                for d in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"):
                    with open(d) as f:
                        cpu_freq = max(cpu_freq, int(f.read().strip()) // 1000)
            except: pass
            
            payload = {
                "system": hwmon_temps,
                "battery": batt_stats,
                "cpu_freq": cpu_freq,
                "controllers": {
                    "l_bat": CONTROLLER_L_BAT,
                    "l_status": CONTROLLER_L_STATUS,
                    "r_bat": CONTROLLER_R_BAT,
                    "r_status": CONTROLLER_R_STATUS,
                }
            }
            
            broadcast_event("TELEMETRY_DATA " + json.dumps(payload))
        except Exception as e:
            print(f"Telemetry poll error: {e}")
            
        time.sleep(2)

def start_poller():
    t = threading.Thread(target=poll_telemetry, daemon=True)
    t.start()

def setup_server():
    if os.path.exists(SOCK_PATH):
        os.unlink(SOCK_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK_PATH)
    server.listen(5)
    os.chmod(SOCK_PATH, 0o666)  # allow user app to connect
    server.setblocking(False)
    return server

def broadcast_event(event_str):
    dead_clients = []
    for c in clients:
        try:
            c.sendall((event_str + "\n").encode())
        except Exception:
            dead_clients.append(c)
    for c in dead_clients:
        clients.remove(c)

def get_ryzenadj_status(ryzenadj_path):
    state = {}
    if os.path.exists(ryzenadj_path):
        try:
            out = subprocess.check_output([ryzenadj_path, "-i"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                line_u = line.upper()
                if "STAPM LIMIT " in line_u:
                    parts = line.split('|')
                    if len(parts) >= 3: state["tdp"] = int(float(parts[2].strip()))
                if "THM LIMIT CORE " in line_u or "TCTL TEMP " in line_u:
                    parts = line.split('|')
                    if len(parts) >= 3: state["temp"] = int(float(parts[2].strip()))
        except: pass

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

    return "SYNC_INITIAL_JSON " + json.dumps(state)

def handle_ipc_command(data_bytes, ryzenadj_path, fds):
    try:
        cmd_str = data_bytes.decode('utf-8').strip()
        for line in cmd_str.split('\n'):
            line = line.strip()
            if not line: continue
            print(f"Received UI Command: {line}")
            parts = line.split()
            cmd = parts[0]
            
            if not os.path.exists(ryzenadj_path):
                print(f"Error: Bundled RyzenAdj not found at {ryzenadj_path}")
                continue
                
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
                                print(f"Set GPU freq mode to {parts[1]}")
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
                                print(f"Set GPU freq to {freq} MHz")
                    except: pass
            elif cmd == "SET_CPU_BOOST" and len(parts) >= 2:
                val = parts[1]
                paths = [
                    "/sys/devices/system/cpu/amd_pstate/cpb_boost",
                    "/sys/devices/system/cpu/cpufreq/boost"
                ]
                success = False
                for p in paths:
                    try:
                        if os.path.exists(p):
                            with open(p, "w") as f:
                                f.write(val)
                            print(f"Set CPU boost to {val} via {p}")
                            success = True
                            break
                    except Exception as e:
                        print(f"Failed to set CPU boost on {p}: {e}")
                if not success:
                    print(f"Could not find a writable boost path for {val}")
            elif cmd == "SET_CPU_MAX_FREQ" and len(parts) >= 2:
                freq_khz = int(parts[1]) * 1000
                for d in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq"):
                    try:
                        with open(d, "w") as f:
                            f.write(str(freq_khz))
                    except: pass
                print(f"Set CPU max freq to {parts[1]} MHz")
            elif cmd == "SET_PROFILE" and len(parts) >= 2:
                profile = parts[1]
                mode_map = {
                    "quiet": r"\_SB.GZFD.WMAA 0x00 0x2C 0x01",
                    "balanced": r"\_SB.GZFD.WMAA 0x00 0x2C 0x02",
                    "performance": r"\_SB.GZFD.WMAA 0x00 0x2C 0x03",
                    "custom": r"\_SB.GZFD.WMAA 0x00 0x2C 0xFF",
                }
                if profile in mode_map:
                    cmd_acpi = mode_map[profile]
                    if os.path.exists("/proc/acpi/call"):
                        with open("/proc/acpi/call", "w") as f:
                            f.write(cmd_acpi)
                        
                        try:
                            with open("/proc/acpi/call", "r") as f:
                                acpi_result = f.read().strip()
                        except Exception as e:
                            acpi_result = f"Failed to read result: {e}"
                        
                        print(f"Sent Profile '{profile}': {cmd_acpi} | Result: {acpi_result}")
                    else:
                        print("Error: /proc/acpi/call not found. Ensure 'acpi_call' is loaded.")
            elif cmd == "SET_CTRL_RGB" and len(parts) >= 8:
                r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                mode, br, sp, side = parts[4], int(parts[5]), int(parts[6]), parts[7]
                targets = ["LEFT", "RIGHT"] if side == "BOTH" else [side]
                for t in targets:
                    controller_hid.set_rgb(t, r, g, b, mode, br, sp)
                print(f"Set RGB {side}: {mode} rgb({r},{g},{b}) br={br} sp={sp}")
            elif cmd == "SET_CTRL_RGB_OFF" and len(parts) >= 2:
                side = parts[1]
                targets = ["LEFT", "RIGHT"] if side == "BOTH" else [side]
                for t in targets:
                    controller_hid.set_rgb_off(t)
                print(f"Turned OFF RGB {side}")
            
            elif cmd == "SET_FAN_CURVE" and len(parts) == 11:
                try:
                    arr = [int(x) for x in parts[1:11]]
                    payload = [
                        0x00, 0x00, 0x0A, 0x00, 0x00, 0x00,
                        arr[0], 0x00, arr[1], 0x00, arr[2], 0x00, arr[3], 0x00, arr[4], 0x00,
                        arr[5], 0x00, arr[6], 0x00, arr[7], 0x00, arr[8], 0x00, arr[9], 0x00,
                        0x00, 0x0A, 0x00, 0x00, 0x00, 0x0A,
                        0x00, 0x14, 0x00, 0x1E, 0x00, 0x28, 0x00, 0x32, 0x00, 0x3C,
                        0x00, 0x46, 0x00, 0x50, 0x00, 0x5A, 0x00, 0x64, 0x00, 0x00
                    ]
                    hex_str = "".join(f"{b:02x}" for b in payload)
                    cmd_acpi = f"\\_SB.GZFD.WMAB 0x00 0x06 b{hex_str}"
                    if os.path.exists("/proc/acpi/call"):
                        with open("/proc/acpi/call", "w") as f:
                            f.write(cmd_acpi)
                        try:
                            with open("/proc/acpi/call", "r") as f:
                                acpi_res = f.read().strip()
                        except: acpi_res = "ok"
                        print(f"Sent Fan Curve: {cmd_acpi} | Result: {acpi_res}")
                    else:
                        print("Error: /proc/acpi/call not found.")
                except Exception as ex:
                    print(f"Failed to set Fan Curve: {ex}")
            
            elif cmd == "SET_FULL_FAN" and len(parts) >= 2:
                try:
                    val = int(parts[1])
                    cmd_acpi = r"\_SB.GZFD.WMAE 0x00 0x12 b0000020401000000" if val == 1 else r"\_SB.GZFD.WMAE 0x00 0x12 b0000020400000000"
                    
                    if os.path.exists("/proc/acpi/call"):
                        with open("/proc/acpi/call", "w") as f:
                            f.write(cmd_acpi)
                        
                        try:
                            with open("/proc/acpi/call", "r") as f:
                                acpi_result = f.read().strip()
                        except Exception:
                            acpi_result = "ok"
                            
                        print(f"Sent FULL FAN ACPI command: {cmd_acpi} | Result: {acpi_result}")
                    else:
                        print("Error: /proc/acpi/call not found.")
                except Exception as ex:
                    print(f"Failed to set Full Fan via ACPI: {ex}")
            
            elif cmd == "TOGGLE_LED" and len(parts) >= 2:
                try:
                    val = int(parts[1])
                    cmd_acpi = r"\_SB.GZFD.WMAF 0x00 0x02 b030100" if val == 1 else r"\_SB.GZFD.WMAF 0x00 0x02 b030000"
                    
                    if os.path.exists("/proc/acpi/call"):
                        with open("/proc/acpi/call", "w") as f:
                            f.write(cmd_acpi)
                        
                        try:
                            with open("/proc/acpi/call", "r") as f:
                                acpi_result = f.read().strip()
                        except Exception as e:
                            acpi_result = f"Failed to read result: {e}"
                        
                        print(f"Sent ACPI command: {cmd_acpi} | Result: {acpi_result}")
                    else:
                        print("Error: /proc/acpi/call not found. Ensure 'acpi_call' is loaded.")
                except Exception as ex:
                    print(f"Failed to set Power LED via ACPI: {ex}")

            elif cmd == "SET_BATTERY_LIMIT" and len(parts) >= 2:
                try:
                    val = int(parts[1])
                    payload = "b0100010301000000" if val else "b0100010300000000"
                    cmd_acpi = f"\\_SB.GZFD.WMAE 0x00 0x12 {payload}"
                    if os.path.exists("/proc/acpi/call"):
                        with open("/proc/acpi/call", "w") as f:
                            f.write(cmd_acpi)
                        try:
                            with open("/proc/acpi/call", "r") as f:
                                acpi_result = f.read().strip()
                        except Exception:
                            acpi_result = "ok"
                        print(f"Sent SET BATTERY LIMIT ACPI command: {cmd_acpi} | Result: {acpi_result}")
                    else:
                        print("Error: /proc/acpi/call not found. Ensure 'acpi_call' is loaded.")
                except Exception as ex:
                    print(f"Failed to set Battery limit via ACPI: {ex}")

            elif cmd == "SET_LEGION_SWAP" and len(parts) >= 2:
                try:
                    val = int(parts[1])
                    payload = bytes([0x05, 0x06, 0x69, 0x04, 0x01, 0x02 if val else 0x01, 0x01])
                    for fd in list(fds.keys()):
                        try:
                            os.write(fd, payload)
                        except Exception as e:
                            print(f"Failed to write swap command to {fds[fd]}: {e}")
                    print(f"Successfully sent Legion swap command {val}")
                except Exception as e:
                    print(f"Error swapping: {e}")

            elif cmd == "SET_CTRL_PROFILE" and len(parts) >= 2:
                try:
                    prof_num = int(parts[1])
                    # No global switch known, but we can set built-in profile state for remapped buttons
                    # Apply remaps per profile. For now, just a placeholder.
                    # As a simpler initial implementation, let's just use the profile commands from remapper.
                    for btn, act in controller_hid.RemappableButtons.items():
                        # Resend remap command to profile N
                        if btn in ["Y3", "M2", "M3"]:
                            controller_hid.remap_button_profile(prof_num, btn, "DISABLED")
                        else:
                            controller_hid.remap_button_profile(prof_num, btn, "DISABLED")
                    print(f"Set controller profile {prof_num}")
                except Exception as e:
                    print(f"Failed to set profile: {e}")

            elif cmd == "SET_CTRL_RGB" and len(parts) >= 8:
                try:
                    # SET_CTRL_RGB r g b mode brightness speed both/left/right
                    r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                    mode, brightness, speed = parts[4], int(parts[5]), int(parts[6])
                    side = parts[7].upper()
                    
                    if side in ["BOTH", "LEFT"]:
                        controller_hid.set_rgb("LEFT", r, g, b, mode, brightness, speed)
                    if side in ["BOTH", "RIGHT"]:
                        controller_hid.set_rgb("RIGHT", r, g, b, mode, brightness, speed)
                    print(f"Set RGB {side} to {mode} {r},{g},{b}")
                except Exception as e:
                    print(f"Failed to set RGB: {e}")

            elif cmd == "SET_CTRL_RGB_OFF" and len(parts) >= 2:
                try:
                    side = parts[1].upper()
                    if side in ["BOTH", "LEFT"]: controller_hid.set_rgb_off("LEFT")
                    if side in ["BOTH", "RIGHT"]: controller_hid.set_rgb_off("RIGHT")
                    print(f"Set RGB OFF {side}")
                except Exception as e:
                    print(f"Failed to turn off RGB: {e}")

            elif cmd == "REMAP_BTN" and len(parts) >= 4:
                try:
                    # REMAP_BTN prof_num button action
                    prof = int(parts[1])
                    btn = parts[2].upper()
                    act = parts[3].upper()
                    controller_hid.remap_button_profile(prof, btn, act)
                    print(f"Remapped profile {prof} {btn} -> {act}")
                except Exception as e:
                    print(f"Failed to remap button: {e}")

            elif cmd == "SET_CTRL_MAP" and len(parts) >= 2:
                try:
                    # SET_CTRL_MAP [{"btn":0x16, "device":0x01, "keys":[0x16,0,0,0,0]}, ...]
                    mappings_json = line.split(maxsplit=1)[1]
                    mappings = json.loads(mappings_json)
                    controller_hid.apply_hardware_remapping(mappings)
                    print(f"Applied {len(mappings)} hardware mappings.")
                except Exception as e:
                    print(f"Failed to apply hardware mapping: {e}")

    except Exception as e:
        print(f"Error handling IPC command: {e}")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ryzenadj_path = os.path.join(script_dir, "../bin/ryzenadj")

    print("Searching for Legion Go HID device...")
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

    if not dev_paths:
        print("No Legion Go controller hidraw devices found. Are they connected?")
        sys.exit(1)
        
    fds = {}
    for path in dev_paths:
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            fds[fd] = path
        except Exception:
            pass
            
    if not fds:
        sys.exit(1)

    server = setup_server()
    poll_list = list(fds.keys()) + [server]

    print("Daemon active! Listening for raw inputs... press Legion L or R.")
    
    start_poller()
    
    # # Start input virtualization mapping
    # try:
    #     mapper = input_mapper.InputMapper()
    #     mapper.start()
    # except Exception as e:
    #     print(f"Failed to start InputMapper: {e}")
        
    last_1 = False
    last_2 = False

    try:
        while True:
            r, _, _ = select.select(poll_list + clients, [], [], 1.0)
            
            for fd in r:
                if fd == server:
                    # New IPC connection
                    client, _ = server.accept()
                    client.setblocking(False)
                    clients.append(client)
                    print("New UI client connected.")
                    
                    # Sync current state to the new client
                    sync_str = get_ryzenadj_status(ryzenadj_path)
                    if sync_str:
                        try:
                            client.sendall((sync_str + "\n").encode())
                        except:
                            clients.remove(client)
                            
                elif fd in clients:
                    # Client disconnected / Received command
                    try:
                        data = fd.recv(1024)
                        if not data:
                            clients.remove(fd)
                        else:
                            handle_ipc_command(data, ryzenadj_path, fds)
                    except:
                        if fd in clients: clients.remove(fd)
                else:
                    # Raw HID input
                    try:
                        data = os.read(fd, 64)
                        if len(data) >= 19:
                            b18 = data[18]
                            # Bit 6 (0x40) and Bit 7 (0x80)
                            button1 = bool(b18 & 0x40)
                            button2 = bool(b18 & 0x80)
                            
                            global CONTROLLER_L_BAT, CONTROLLER_L_STATUS, CONTROLLER_R_BAT, CONTROLLER_R_STATUS
                            CONTROLLER_L_BAT = data[5]
                            CONTROLLER_L_STATUS = data[6]
                            CONTROLLER_R_BAT = data[7]
                            CONTROLLER_R_STATUS = data[8]
                            
                            if button1 and not last_1:
                                print(f"[HIT] Legion Button L Pressed! Broadcasting TOGGLE_SIDEBAR")
                                broadcast_event("TOGGLE_SIDEBAR")
                            if button2 and not last_2:
                                print(f"[HIT] Legion Button R Pressed! Broadcasting TOGGLE_KEYBOARD")
                                broadcast_event("TOGGLE_KEYBOARD")
                                
                            last_1 = button1
                            last_2 = button2
                    except BlockingIOError:
                        pass
                    except OSError as e:
                        print(f"Read error on {fds[fd]}: {e}")
                        poll_list.remove(fd)
                        del fds[fd]
    except KeyboardInterrupt:
        print("\nExiting listener daemon...")
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)

if __name__ == '__main__':
    main()
