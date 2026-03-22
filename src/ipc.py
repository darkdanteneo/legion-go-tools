import socket
import threading
import time
import json
from gi.repository import GLib

SOCK_PATH = "/tmp/legion_sidebar.sock"

_ipc_client = None

def send_command(cmd_str):
    global _ipc_client
    if _ipc_client:
        try:
            _ipc_client.sendall((cmd_str + "\n").encode())
        except Exception as e:
            print(f"Failed to send IPC command: {e}")

def listen_for_buttons(toggle_callback, sync_callback, telemetry_callback):
    def _thread():
        global _ipc_client
        while True:
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(SOCK_PATH)
                _ipc_client = client
                print("Connected to root HID daemon.")
                
                # Keep reading lines
                f = client.makefile('r')
                while True:
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line == "TOGGLE_SIDEBAR":
                        # Invoke GTK UI code back on the main GLib loop
                        GLib.idle_add(toggle_callback)
                    elif line.startswith("SYNC_INITIAL_JSON "):
                        GLib.idle_add(sync_callback, line)
                    elif line.startswith("TELEMETRY_DATA "):
                        payload_str = line[len("TELEMETRY_DATA "):].strip()
                        try:
                            payload = json.loads(payload_str)
                            GLib.idle_add(telemetry_callback, payload)
                        except Exception as e:
                            print(f"Failed to parse telemetry: {e}")
            except Exception as e:
                print(f"IPC Error: Daemon not running? Retrying in 2s...")
                _ipc_client = None
                time.sleep(2)
                
    t = threading.Thread(target=_thread, daemon=True)
    t.start()
