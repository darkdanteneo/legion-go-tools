#!/usr/bin/env python3
import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gio', '2.0')

from gi.repository import Gtk, Adw, Gio, GLib

class SidebarWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Legion Quick Settings")
        
        # Approximate sidebar dimensions. GNOME Wayland compositor 
        # manages actual window placement.
        self.set_default_size(360, 800)
        
        # Do not destroy the window on close so we can toggle it back rapidly
        self.connect("close-request", self.on_close_request)
        
        # Create Main layout container
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Header bar
        header = Adw.HeaderBar()
        self.set_content(header) # Temporarily just header, wait, header should be top
        
        # Use Adw.ToolbarView is standard in newer libadwaita
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(box)
        
        self.set_content(toolbar_view)
        
        # Add a title label
        label = Gtk.Label(label="Quick Settings", halign=Gtk.Align.START)
        label.add_css_class("title-1")
        box.append(label)

        # Build a Settings section (ActionRow with listbox) 
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        box.append(listbox)
        
        # Performance Mode Toggle
        perf_row = Adw.ActionRow(title="Performance Mode", subtitle="Enable maximum performance profile")
        self.perf_switch = Gtk.Switch()
        self.perf_switch.set_valign(Gtk.Align.CENTER)
        perf_row.add_suffix(self.perf_switch)
        listbox.append(perf_row)

        # Controller LED Toggle
        led_row = Adw.ActionRow(title="Controller LEDs", subtitle="Toggle RGB lights")
        self.led_switch = Gtk.Switch()
        self.led_switch.set_active(True)
        self.led_switch.set_valign(Gtk.Align.CENTER)
        led_row.add_suffix(self.led_switch)
        listbox.append(led_row)

    def on_close_request(self, *args):
        # Hide the window instead of destroying it
        self.set_visible(False)
        return True

class LegionSidebarApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.legion.SidebarApp',
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = SidebarWindow(application=self)
        self.window.present()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        
        if options.contains("toggle"):
            if self.window and self.window.get_visible():
                print("Toggling visibility to OFF.")
                self.window.set_visible(False)
            else:
                print("Toggling visibility to ON.")
                self.do_activate()
        else:
            self.do_activate()
        
        return 0

def main():
    app = LegionSidebarApp()
    
    # Register `--toggle` CLI option. This triggers D-Bus mechanism if already running!
    app.add_main_option("toggle", ord("t"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Toggle the sidebar visibility", None)
    
    return app.run(sys.argv)

if __name__ == '__main__':
    sys.exit(main())
