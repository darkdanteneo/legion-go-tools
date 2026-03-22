#!/usr/bin/env python3
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from window import SidebarWindow
from ipc import listen_for_buttons

class SidebarApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.github.shubu.LegionSidebar", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if not self.win:
            self.win = SidebarWindow(application=self)
            listen_for_buttons(self.win.toggle_visibility, self.win.sync_sliders, self.win.update_telemetry)
        self.win.present()

def main():
    app = SidebarApp()
    return app.run(sys.argv)

if __name__ == '__main__':
    main()
