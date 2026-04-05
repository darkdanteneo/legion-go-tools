#!/usr/bin/env python3
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

import subprocess
import os
import sys
import time
import socket

from window import SidebarWindow
from ipc import listen_for_buttons

# TODO: Make proper Init
# def ensure_dependencies():
#     # 1. Ensure acpi_call is loaded
#     if not os.path.exists("/proc/acpi/call"):
#         print("Loading acpi_call module...")
#         subprocess.run(["sudo", "modprobe", "acpi_call"], check=False)
    
#     # 2. Ensure hid_listener daemon is running
#     sock_path = "/tmp/legion_sidebar.sock"
#     daemon_running = False
#     if os.path.exists(sock_path):
#         try:
#             with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
#                 s.settimeout(0.5)
#                 s.connect(sock_path)
#                 daemon_running = True
#         except:
#             os.remove(sock_path)
            
#     if not daemon_running:
#         print("Starting HID listener daemon...")
#         script_dir = os.path.dirname(os.path.abspath(__file__))
#         daemon_path = os.path.abspath(os.path.join(script_dir, "../daemon/hid_listener.py"))
#         daemon_dir = os.path.dirname(daemon_path)

#         # Spawn detached sudo process with cwd set to daemon/ so local imports work.
#         # Keep stderr visible so we can see errors (e.g. sudo password prompts, import failures).
#         # Redirect output to log file for debugging
#         log_file = open("/tmp/legion_daemon.log", "w")
#         # subprocess.Popen(
#         #     ["sudo", "-n", sys.executable, daemon_path],
#         #     cwd=daemon_dir,
#         #     stdout=log_file,
#         #     stderr=subprocess.STDOUT,  # merge stderr into stdout
#         #     stdin=subprocess.DEVNULL,
#         #     start_new_session=True,
#         # )
#         # # Give it a moment to bind the socket
#         # time.sleep(1.5)
        
#         # Verify daemon actually started
#         if os.path.exists(sock_path):
#             try:
#                 with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
#                     s.settimeout(0.5)
#                     s.connect(sock_path)
#                     print("HID listener daemon started successfully.")
#             except:
#                 print("WARNING: Daemon socket exists but not accepting connections.")
#         else:
#             print("WARNING: HID listener daemon did not start.")
#             print("  You may need to run it manually with:")
#             print(f"  sudo {sys.executable} {daemon_path}")

class SidebarApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.github.shubu.LegionSidebar", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None
        self.ensure_deps_done = False

    def do_activate(self):
        if not self.ensure_deps_done and False: # TODO: Make proper Init
            ensure_dependencies()
            self.ensure_deps_done = True
            
        if not self.win:
            self.win = SidebarWindow(application=self)
            listen_for_buttons(self.win.toggle_visibility, self.win.toggle_keyboard, self.win.sync_sliders, self.win.update_telemetry)
        # self.win.present() # default hidden

def main():
    app = SidebarApp()
    return app.run(sys.argv)

if __name__ == '__main__':
    main()
