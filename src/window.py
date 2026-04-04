import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk
import json
import time
import os
import subprocess

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell
    HAS_LAYER_SHELL = True
except (ValueError, ImportError):
    HAS_LAYER_SHELL = False

from ipc import send_command

class FanCurveWidget(Gtk.DrawingArea):
    def __init__(self, callback, hover_callback=None):
        super().__init__()
        self.set_size_request(-1, 140)
        self.min_points = [44, 48, 55, 60, 71, 79, 87, 87, 100, 100]
        self.points = list(self.min_points)
        self.saved_custom_points = list(self.min_points)
        self.current_temp = -1.0
        self.callback = callback
        self.hover_callback = hover_callback
        self.set_draw_func(self.on_draw)
        self.active_point = -1

    def set_current_temp(self, temp):
        try:
            self.current_temp = float(temp)
        except (ValueError, TypeError):
            self.current_temp = -1.0
        self.queue_draw()

    def set_points(self, points):
        if len(points) == len(self.points):
            self.points = list(points)
            self.queue_draw()
        
        self.drag = Gtk.GestureDrag.new()
        self.drag.connect("drag-begin", self.on_drag_begin)
        self.drag.connect("drag-update", self.on_drag_update)
        self.drag.connect("drag-end", self.on_drag_end)
        self.add_controller(self.drag)
        self.old_y = 0

    def get_point_coords(self, pts_array, width, height, pad_x, pad_y, usable_w, usable_h):
        coords = []
        for i, val in enumerate(pts_array):
            x = pad_x + (i / 9.0) * usable_w
            pct = (val - 40.0) / 60.0
            y = pad_y + (1.0 - pct) * usable_h
            coords.append((x, y))
        return coords

    def on_draw(self, area, cr, width, height):
        pad_x = 15
        pad_y = 15
        usable_w = width - 2*pad_x
        usable_h = height - 2*pad_y
        
        coords = self.get_point_coords(self.points, width, height, pad_x, pad_y, usable_w, usable_h)
        min_coords = self.get_point_coords(self.min_points, width, height, pad_x, pad_y, usable_w, usable_h)
        
        # Background
        cr.set_source_rgba(1, 1, 1, 0.05)
        cr.rectangle(pad_x, pad_y, usable_w, usable_h)
        cr.fill()
        
        # Grid/Temp Line
        temp = getattr(self, "current_temp", -1.0)
        if temp > 0.0:
            pct_x = (temp - 10.0) / 90.0
            if pct_x < 0.0: pct_x = 0.0
            if pct_x > 1.0: pct_x = 1.0
            
            cx = pad_x + pct_x * usable_w
            cr.set_source_rgba(1, 0, 0, 0.4) # Red line
            cr.set_line_width(2)
            cr.move_to(cx, pad_y)
            cr.line_to(cx, height - pad_y)
            cr.stroke()

            # Circle on the curve intersection
            idx = pct_x * 9
            i1 = int(idx)
            i2 = min(9, i1 + 1)
            f = idx - i1
            if i1 < len(self.points):
                v = self.points[i1] * (1 - f) + self.points[i2] * f
                cy = pad_y + (1.0 - (v - 40.0) / 60.0) * usable_h
                cr.set_source_rgba(1, 0, 0, 0.8)
                cr.arc(cx, cy, 4, 0, 2 * 3.14159)
                cr.fill()
        
        # Grid lines
        cr.set_source_rgba(1, 1, 1, 0.1)
        cr.set_line_width(1)
        for i in range(10):
            x = pad_x + (i / 9.0) * usable_w
            cr.move_to(x, pad_y)
            cr.line_to(x, pad_y + usable_h)
        for i in range(7): # 40 to 100 by 10s
            y_val = pad_y + (1.0 - i/6.0) * usable_h
            cr.move_to(pad_x, y_val)
            cr.line_to(pad_x + usable_w, y_val)
        cr.stroke()
        
        # Temp texts
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.set_font_size(10)
        for i in range(10):
            txt = f"{(i+1)*10}"
            te = cr.text_extents(txt)
            x = pad_x + (i / 9.0) * usable_w - te.width/2
            cr.move_to(x, height - 2)
            cr.show_text(txt)
            
        # Draw min line limits
        cr.set_source_rgba(1, 0.2, 0.2, 0.5)
        cr.set_line_width(1.5)
        cr.set_dash([4.0, 4.0])
        for i, (x, y) in enumerate(min_coords):
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()
        cr.set_dash([])
            
        # Draw connected user line
        cr.set_source_rgb(0.2, 0.6, 1.0)
        cr.set_line_width(2)
        for i, (x, y) in enumerate(coords):
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()
        
        # Draw point nodes
        for i, (x, y) in enumerate(coords):
            cr.arc(x, y, 4, 0, 6.28)
            cr.set_source_rgb(0.2, 0.6, 1.0)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.arc(x, y, 4, 0, 6.28)
            cr.stroke()

    def update_point_from_y(self, y, height):
        if self.active_point < 0 or self.active_point > 9: return
        pad_y = 15
        usable_h = height - 2*pad_y
        val = 40.0 + 60.0 * (1 - (y - pad_y) / usable_h)
        idx = self.active_point
        val = max(self.min_points[idx], min(100, val))
        self.points[idx] = int(val)
        if self.hover_callback:
            self.hover_callback((idx+1)*10, self.points[idx])
        
        # Monotonicity check
        for i in range(1, 10):
            if self.points[i] < self.points[i-1]:
                if i <= idx: self.points[i-1] = max(self.min_points[i-1], self.points[i])
                else: self.points[i] = max(self.min_points[i], self.points[i-1])
        self.queue_draw()

    def on_drag_begin(self, gesture, start_x, start_y):
        if not self.get_sensitive(): return
        width = self.get_width()
        height = self.get_height()
        pad_x, pad_y = 10, 10
        usable_w = width - 2*pad_x
        usable_h = height - 2*pad_y
        coords = self.get_point_coords(self.points, width, height, pad_x, pad_y, usable_w, usable_h)
        closest = -1
        min_dist = 600 # Approx squared distance radius limit
        for i, (px, py) in enumerate(coords):
            dist = (px - start_x)**2 + (py - start_y)**2
            if dist < min_dist:
                min_dist = dist
                closest = i
        if min_dist < 600:
            self.active_point = closest
            self.old_y = start_y
            if self.hover_callback:
                self.hover_callback((closest+1)*10, self.points[closest])
        else:
            self.active_point = -1

    def on_drag_update(self, gesture, offset_x, offset_y):
        if self.active_point >= 0 and self.get_sensitive():
            new_y = self.old_y + offset_y
            self.update_point_from_y(new_y, self.get_height())

    def on_drag_end(self, gesture, offset_x, offset_y):
        if self.active_point >= 0 and self.get_sensitive():
            self.saved_custom_points = list(self.points)
            self.callback(self.points)
            self.active_point = -1
            if self.hover_callback:
                self.hover_callback(None, None)

class ControllerPanel(Gtk.Box):
    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15, margin_top=10, margin_start=12, margin_end=12, **kwargs)
        
        # --- 1. Input Profile ---
        prof_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        prof_lbl = Gtk.Label(label="Input Profile", halign=Gtk.Align.START)
        prof_lbl.add_css_class("heading")
        prof_box.append(prof_lbl)

        grid = Gtk.Grid(row_spacing=5, column_spacing=5, halign=Gtk.Align.CENTER)
        self.prof_btns = []
        for i in range(1, 5):
            btn = Gtk.Button(label=f"Profile {i}")
            btn.connect("clicked", self.on_profile_clicked, i)
            self.prof_btns.append(btn)
            grid.attach(btn, (i-1)%2, (i-1)//2, 1, 1)
        prof_box.append(grid)
        self.append(prof_box)

        # --- 2. Controller LED ---
        led_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        led_lbl = Gtk.Label(label="Controller LED", halign=Gtk.Align.START)
        led_lbl.add_css_class("heading")
        led_box.append(led_lbl)

        # Mode
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_box.append(Gtk.Label(label="Mode", halign=Gtk.Align.START))
        self.led_mode = Gtk.DropDown.new_from_strings(["Solid", "Pulse", "Dynamic", "Spiral"])
        self.led_mode.set_selected(0)
        self.led_mode.connect("notify::selected", self.on_led_changed)
        mode_box.append(self.led_mode)
        
        self.led_off_btn = Gtk.Button(label="Turn OFF LEDs")
        self.led_off_btn.connect("clicked", self.on_led_off)
        mode_box.append(self.led_off_btn)
        led_box.append(mode_box)

        # RGB Sliders
        color_grid = Gtk.Grid(row_spacing=2, column_spacing=10)
        self.sl_r = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self.sl_g = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self.sl_b = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        
        # Set values before connecting to avoid early signals
        self.sl_r.set_value(255) # default red
        
        for s in [self.sl_r, self.sl_g, self.sl_b]:
            s.set_draw_value(False)
            s.set_hexpand(True)
            s.connect("value-changed", self.on_led_changed)
        
        lbl_r = Gtk.Label(label="R")
        lbl_r.add_css_class("caption")
        color_grid.attach(lbl_r, 0, 0, 1, 1)
        color_grid.attach(self.sl_r, 1, 0, 1, 1)
        
        lbl_g = Gtk.Label(label="G")
        lbl_g.add_css_class("caption")
        color_grid.attach(lbl_g, 0, 1, 1, 1)
        color_grid.attach(self.sl_g, 1, 1, 1, 1)
        
        lbl_b = Gtk.Label(label="B")
        lbl_b.add_css_class("caption")
        color_grid.attach(lbl_b, 0, 2, 1, 1)
        color_grid.attach(self.sl_b, 1, 2, 1, 1)
        led_box.append(color_grid)

        # Brightness & Speed
        bs_grid = Gtk.Grid(row_spacing=2, column_spacing=10)
        self.sl_br = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.sl_sp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        
        for s in [self.sl_br, self.sl_sp]:
            s.set_draw_value(False)
            s.set_value(100)
            s.set_hexpand(True)
            s.connect("value-changed", self.on_led_changed)

        lbl_br = Gtk.Label(label="Brightness")
        lbl_br.add_css_class("caption")
        bs_grid.attach(lbl_br, 0, 0, 1, 1)
        bs_grid.attach(self.sl_br, 1, 0, 1, 1)
        
        lbl_sp = Gtk.Label(label="Speed")
        lbl_sp.add_css_class("caption")
        bs_grid.attach(lbl_sp, 0, 1, 1, 1)
        bs_grid.attach(self.sl_sp, 1, 1, 1, 1)
        led_box.append(bs_grid)

        self.append(led_box)

        # --- 3. Button Remap ---
        remap_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        remap_lbl = Gtk.Label(label="Button Remap (Current Profile)", halign=Gtk.Align.START)
        remap_lbl.add_css_class("heading")
        remap_box.append(remap_lbl)

        actions = [
            "DISABLED", "L_STICK_CLICK", "R_STICK_CLICK",
            "D_PAD_UP", "D_PAD_DOWN", "D_PAD_LEFT", "D_PAD_RIGHT",
            "BUTTON_A", "BUTTON_B", "BUTTON_X", "BUTTON_Y",
            "L_BUMPER", "L_TRIGGER", "R_BUMPER", "R_TRIGGER",
            "VIEW", "MENU"
        ]
        self.remap_drops = {}
        self.active_profile = 1

        rg = Gtk.Grid(row_spacing=5, column_spacing=10)
        for i, btn in enumerate(["Y1", "Y2", "Y3", "M2", "M3"]):
            rg.attach(Gtk.Label(label=btn), 0, i, 1, 1)
            drop = Gtk.DropDown.new_from_strings(actions)
            drop.connect("notify::selected", self.on_remap_changed, btn, actions)
            self.remap_drops[btn] = drop
            rg.attach(drop, 1, i, 1, 1)
        remap_box.append(rg)
        
        self.append(remap_box)

    def on_profile_clicked(self, btn, prof_num):
        self.active_profile = prof_num
        send_command(f"SET_CTRL_PROFILE {prof_num}")
        # Color the active button
        for b in self.prof_btns:
            b.remove_css_class("suggested-action")
        btn.add_css_class("suggested-action")

    def on_led_changed(self, *args):
        if not hasattr(self, 'sl_br'): return
        modes = ["SOLID", "PULSE", "DYNAMIC", "SPIRAL"]
        mode = modes[self.led_mode.get_selected()]
        r, g, b = int(self.sl_r.get_value()), int(self.sl_g.get_value()), int(self.sl_b.get_value())
        br, sp = int(self.sl_br.get_value()), int(self.sl_sp.get_value())
        send_command(f"SET_CTRL_RGB {r} {g} {b} {mode} {br} {sp} BOTH")

    def on_led_off(self, btn):
        send_command("SET_CTRL_RGB_OFF BOTH")

    def on_remap_changed(self, dropdown, pspec, btn_name, actions):
        act = actions[dropdown.get_selected()]
        send_command(f"REMAP_BTN {self.active_profile} {btn_name} {act}")

class RemappingPanel(Gtk.Box):
    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10, margin_start=12, margin_end=12, **kwargs)
        
        # Hardware key database from user
        self.HW_BUTTONS = {
            "L-Stick Click": 0x03, "L-Stick Up": 0x04, "L-Stick Down": 0x05, "L-Stick Left": 0x06, "L-Stick Right": 0x07,
            "R-Stick Click": 0x08, "R-Stick Up": 0x09, "R-Stick Down": 0x0a, "R-Stick Left": 0x0b, "R-Stick Right": 0x0c,
            "D-Pad Up": 0x0d, "D-Pad Down": 0x0e, "D-Pad Left": 0x0f, "D-Pad Right": 0x10,
            "A": 0x12, "B": 0x13, "X": 0x14, "Y": 0x15,
            "LB": 0x16, "LT": 0x17, "RB": 0x18, "RT": 0x19,
            "Y1": 0x1c, "Y2": 0x1d, "Y3": 0x1e, "M2": 0x21, "M3": 0x22,
            "View": 0x23, "Menu": 0x24
        }
        
        self.KEYBOARD_KEYS = {
            "None": 0x00, "Enter": 0x28, "Esc": 0x29, "Backspace": 0x2a, "Tab": 0x2b, "Space": 0x2c,
            "A": 0x04, "B": 0x05, "C": 0x06, "D": 0x07, "E": 0x08, "F": 0x09, "G": 0x0a, "H": 0x0b,
            "I": 0x0c, "J": 0x0d, "K": 0x0e, "L": 0x0f, "M": 0x10, "N": 0x11, "O": 0x12, "P": 0x13,
            "Q": 0x14, "R": 0x15, "S": 0x16, "T": 0x17, "U": 0x18, "V": 0x19, "W": 0x1a, "X": 0x1b,
            "Y": 0x1c, "Z": 0x1d, "1": 0x1e, "2": 0x1f, "3": 0x20, "4": 0x21, "5": 0x22, "6": 0x23,
            "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
            "L-Ctrl": 0xe0, "L-Shift": 0xe1, "L-Alt": 0xe2, "Win": 0xe3,
            "R-Ctrl": 0xe4, "R-Shift": 0xe5, "R-Alt": 0xe6
        }
        
        self.MOUSE_BTNS = {
            "L-Click": 0x01, "R-Click": 0x02, "Mid-Click": 0x03, "Scroll-Up": 0x04, "Scroll-Dn": 0x05,
            "Btn 4": 0x06, "Btn 5": 0x07
        }
        
        self.staged_mappings = []
        
        lbl = Gtk.Label(label="Hardware Remapping", halign=Gtk.Align.START)
        lbl.add_css_class("heading")
        self.append(lbl)
        
        # --- Selector UI ---
        entry_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # Source Button
        src_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        src_box.append(Gtk.Label(label="Physical Button", hexpand=True, halign=Gtk.Align.START))
        self.src_drop = Gtk.DropDown.new_from_strings(sorted(list(self.HW_BUTTONS.keys())))
        src_box.append(self.src_drop)
        entry_box.append(src_box)
        
        # Target Mode
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_box.append(Gtk.Label(label="Map To", hexpand=True, halign=Gtk.Align.START))
        self.mode_drop = Gtk.DropDown.new_from_strings(["Controller", "Keyboard", "Mouse"])
        self.mode_drop.connect("notify::selected", self.on_mode_changed)
        mode_box.append(self.mode_drop)
        entry_box.append(mode_box)
        
        # Target Key (Dynamic)
        self.target_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.target_lbl = Gtk.Label(label="Value", hexpand=True, halign=Gtk.Align.START)
        self.target_box.append(self.target_lbl)
        self.target_drop = Gtk.DropDown.new_from_strings(sorted(list(self.HW_BUTTONS.keys())))
        self.target_box.append(self.target_drop)
        entry_box.append(self.target_box)
        
        # Multi-key for keyboard
        self.keys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.selected_keys = []
        self.keys_lbl = Gtk.Label(label="Keys: None", halign=Gtk.Align.START)
        self.keys_lbl.add_css_class("caption")
        self.keys_box.append(self.keys_lbl)
        
        kb_ctrls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.add_key_btn = Gtk.Button(label="Add Key")
        self.add_key_btn.connect("clicked", self.on_add_key_to_list)
        kb_ctrls.append(self.add_key_btn)
        
        self.clear_keys_btn = Gtk.Button(label="Clear Keys")
        self.clear_keys_btn.connect("clicked", self.on_clear_keys_list)
        kb_ctrls.append(self.clear_keys_btn)
        self.keys_box.append(kb_ctrls)
        
        entry_box.append(self.keys_box)
        
        add_btn = Gtk.Button(label="Add Mapping", halign=Gtk.Align.END)
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self.on_add_mapping)
        entry_box.append(add_btn)
        
        self.append(entry_box)
        
        # --- List View ---
        self.list_lbl = Gtk.Label(label="Current Staged Mappings", halign=Gtk.Align.START, margin_top=10)
        self.list_lbl.add_css_class("caption")
        self.append(self.list_lbl)
        
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        
        scroll = Gtk.ScrolledWindow(min_content_height=150, vexpand=True)
        scroll.set_child(self.list_box)
        self.append(scroll)
        
        # Apply/Clear
        bb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        clear_btn = Gtk.Button(label="Clear All", hexpand=True)
        clear_btn.connect("clicked", self.on_clear_all)
        bb.append(clear_btn)
        
        apply_btn = Gtk.Button(label="Apply to Hardware", hexpand=True)
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self.on_apply)
        bb.append(apply_btn)
        self.append(bb)
        
        # Initial fix
        self.on_mode_changed(None, None)

    def on_mode_changed(self, dropdown, pspec):
        mode = self.mode_drop.get_selected()
        if mode == 0: # Controller
            items = sorted(list(self.HW_BUTTONS.keys()))
            self.keys_box.set_visible(False)
        elif mode == 1: # Keyboard
            items = sorted(list(self.KEYBOARD_KEYS.keys()))
            self.keys_box.set_visible(True)
        else: # Mouse
            items = sorted(list(self.MOUSE_BTNS.keys()))
            self.keys_box.set_visible(False)
            
        # Replace dropdown content
        old = self.target_drop
        self.target_box.remove(old)
        self.target_drop = Gtk.DropDown.new_from_strings(items)
        self.target_box.append(self.target_drop)
        self.on_clear_keys_list(None)

    def on_add_key_to_list(self, btn):
        items = sorted(list(self.KEYBOARD_KEYS.keys()))
        name = items[self.target_drop.get_selected()]
        code = self.KEYBOARD_KEYS[name]
        if len(self.selected_keys) < 5:
            self.selected_keys.append({"name": name, "code": code})
            self.update_keys_label()

    def on_clear_keys_list(self, btn):
        self.selected_keys = []
        self.update_keys_label()

    def update_keys_label(self):
        if not self.selected_keys:
            self.keys_lbl.set_label("Keys: None")
        else:
            names = [k["name"] for k in self.selected_keys]
            self.keys_lbl.set_label("Keys: " + " + ".join(names))

    def on_add_mapping(self, btn):
        src_name = sorted(list(self.HW_BUTTONS.keys()))[self.src_drop.get_selected()]
        src_code = self.HW_BUTTONS[src_name]
        
        mode = self.mode_drop.get_selected()
        if mode == 0:
            target_list = sorted(list(self.HW_BUTTONS.keys()))
            target_name = target_list[self.target_drop.get_selected()]
            target_code = self.HW_BUTTONS[target_name]
            device = 1
            keys = [target_code, 0, 0, 0, 0]
            display = f"{src_name} → {target_name}"
        elif mode == 1:
            if not self.selected_keys: return
            device = 2
            codes = [k["code"] for k in self.selected_keys]
            keys = (codes + [0]*5)[:5]
            display = f"{src_name} → " + " + ".join([k["name"] for k in self.selected_keys])
        else:
            target_list = sorted(list(self.MOUSE_BTNS.keys()))
            target_name = target_list[self.target_drop.get_selected()]
            target_code = self.MOUSE_BTNS[target_name]
            device = 3
            keys = [target_code, 0, 0, 0, 0]
            display = f"{src_name} → {target_name}"
            
        mapping = {
            "btn": src_code,
            "device": device,
            "keys": keys,
            "display": display
        }
        
        # Check for duplicates on same src
        self.staged_mappings = [m for m in self.staged_mappings if m["btn"] != src_code]
        self.staged_mappings.append(mapping)
        self.refresh_listview()

    def refresh_listview(self):
        while (row := self.list_box.get_first_child()):
            self.list_box.remove(row)
            
        for m in self.staged_mappings:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)
            row.append(Gtk.Label(label=m["display"], hexpand=True, halign=Gtk.Align.START))
            del_btn = Gtk.Button(icon_name="edit-delete-symbolic")
            del_btn.add_css_class("flat")
            del_btn.connect("clicked", self.on_delete_mapping, m)
            row.append(del_btn)
            self.list_box.append(row)

    def on_delete_mapping(self, btn, mapping):
        self.staged_mappings.remove(mapping)
        self.refresh_listview()

    def on_clear_all(self, btn):
        self.staged_mappings = []
        self.refresh_listview()

    def on_apply(self, btn):
        # Format for IPC
        payload = []
        for m in self.staged_mappings:
            payload.append({
                "btn": m["btn"],
                "device": m["device"],
                "keys": m["keys"]
            })
        send_command("SET_CTRL_MAP " + json.dumps(payload))

class SidebarWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Legion Quick Settings")
        
        # True Sidebar styling: borderless, full height
        self.set_decorated(False)
        self.set_default_size(350, 1080)
        self.add_css_class("sidebar")

        if HAS_LAYER_SHELL:
            Gtk4LayerShell.init_for_window(self)
            Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.TOP)
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
            Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)

        # Inject some custom CSS to tighten everything up
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data("""
            .micro-caption { font-size: 11px; font-weight: bold; margin: 0; padding: 0; }
            .dim-label { font-size: 10px; }
            .caption { font-size: 11px; margin: 0; padding: 0; }
            scale contents { min-height: 4px; padding: 0; margin: 0; }
            scale slider { min-height: 12px; min-width: 12px; margin: -2px 0; }
            switch { margin: 0; padding: 0; }
        """.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Reduced padding and margins 
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, margin_top=5, margin_start=12, margin_end=12)

        # Top Split: Telemetry (Left) and Profile (Right)
        top_split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        # Left: Telemetry Dashboard
        tele_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tele_box.set_hexpand(True)
        
        self.lbl_temps = Gtk.Label(halign=Gtk.Align.START)
        self.lbl_freqs = Gtk.Label(halign=Gtk.Align.START)
        self.lbl_legion_bat = Gtk.Label(halign=Gtk.Align.START)
        self.lbl_ctrl_bat = Gtk.Label(halign=Gtk.Align.START)
        
        self._set_tele_text(self.lbl_temps, "Cpu - | Gpu - | Ssd - | APU - W")
        self._set_tele_text(self.lbl_freqs, "Cpu - MHz | Gpu - MHz")
        self._set_tele_text(self.lbl_legion_bat, "Bat: -% (H: -%)")
        self._set_tele_text(self.lbl_ctrl_bat, "Ctrl L -% | R -%")
        
        for lbl in [self.lbl_temps, self.lbl_freqs, self.lbl_legion_bat, self.lbl_ctrl_bat]:
            lbl.set_use_markup(True)
            lbl.add_css_class("dim-label")
            tele_box.append(lbl)
            
        top_split.append(tele_box)

        # Right: Performance Profile Dropdown
        profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        prof_lbl = Gtk.Label(label="Profile", halign=Gtk.Align.START)
        prof_lbl.add_css_class("caption")
        profile_box.append(prof_lbl)
        
        self.profile_drop = Gtk.DropDown.new_from_strings(["Quiet", "Balanced", "Performance", "Custom"])
        self.profile_drop.set_selected(3) # Default Custom
        self.profile_drop.connect("notify::selected", self.on_profile_changed)
        profile_box.append(self.profile_drop)
        
        top_split.append(profile_box)
        content.append(top_split)
        
        # 2. TDP Limit Slider
        tdp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.tdp_label = Gtk.Label(label="TDP Limit: 30 W", halign=Gtk.Align.START)
        self.tdp_label.add_css_class("caption")
        tdp_box.append(self.tdp_label)
        
        self.tdp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 43, 1)
        self.tdp_scale.set_draw_value(False)
        self.tdp_scale.set_value(30)
        self.tdp_scale.connect("value-changed", self.on_tdp_changed)
        tdp_box.append(self.tdp_scale)
        content.append(tdp_box)
        
        # 3. Temp Limit Slider
        temp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.temp_label = Gtk.Label(label="Temperature Limit: 80 °C", halign=Gtk.Align.START)
        self.temp_label.add_css_class("caption")
        temp_box.append(self.temp_label)
        
        self.temp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 60, 95, 1)
        self.temp_scale.set_draw_value(False)
        self.temp_scale.set_value(80)
        self.temp_scale.connect("value-changed", self.on_temp_changed)
        temp_box.append(self.temp_scale)
        content.append(temp_box)

        # 3a. Custom GPU Freq Box
        gpu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        gpu_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.gpu_label = Gtk.Label(label="Custom GPU Freq: 1500 MHz", hexpand=True, halign=Gtk.Align.START)
        self.gpu_label.add_css_class("caption")
        self.gpu_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.gpu_switch.add_css_class("small")
        self.gpu_switch.connect("state-set", self.on_gpu_switch_toggled)
        gpu_header.append(self.gpu_label)
        gpu_header.append(self.gpu_switch)
        gpu_box.append(gpu_header)
        
        self.gpu_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 800, 2700, 50)
        self.gpu_scale.set_draw_value(False)
        self.gpu_scale.set_value(1500)
        self.gpu_scale.set_sensitive(False)
        self.gpu_scale.connect("value-changed", self.on_gpu_freq_changed)
        gpu_box.append(self.gpu_scale)
        content.append(gpu_box)

        # 3b. Custom CPU Freq Box
        cpu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        cpu_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.cpu_label = Gtk.Label(label="CPU Boost (Max: 3300 MHz)", hexpand=True, halign=Gtk.Align.START)
        self.cpu_label.add_css_class("caption")
        self.cpu_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.cpu_switch.add_css_class("small")
        self.cpu_switch.set_active(True)
        self.cpu_switch.connect("state-set", self.on_cpu_switch_toggled)
        cpu_header.append(self.cpu_label)
        cpu_header.append(self.cpu_switch)
        cpu_box.append(cpu_header)
        
        self.cpu_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1200, 5100, 100)
        self.cpu_scale.set_draw_value(False)
        self.cpu_scale.set_value(3300)
        self.cpu_scale.connect("value-changed", self.on_cpu_freq_changed)
        cpu_box.append(self.cpu_scale)
        content.append(cpu_box)
        
        # 4. Custom Fan Curve
        self.fan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        
        fan_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        fan_label = Gtk.Label(label="Custom Fan Curve", hexpand=True, halign=Gtk.Align.START)
        fan_label.add_css_class("caption")
        
        self.max_fan_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.max_fan_switch.add_css_class("small")
        self.max_fan_switch.connect("state-set", self.on_max_fan_toggled)
        max_fan_lbl = Gtk.Label(label="Max", margin_end=5)
        max_fan_lbl.add_css_class("caption")
        
        fan_header.append(fan_label)
        fan_header.append(max_fan_lbl)
        fan_header.append(self.max_fan_switch)
        self.fan_box.append(fan_header)
        
        self.fan_hover_lbl = Gtk.Label(label="Hold a point to view stats", halign=Gtk.Align.START)
        self.fan_hover_lbl.add_css_class("caption")
        self.fan_box.append(self.fan_hover_lbl)
        
        self.fan_curve = FanCurveWidget(self.on_fan_curve_changed, hover_callback=self.on_fan_hover)
        self.fan_box.append(self.fan_curve)
        content.append(self.fan_box)

        # 5. Hardware Toggles (LED, Swap, Battery)
        hw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hw_label = Gtk.Label(label="Hardware Toggles", halign=Gtk.Align.START)
        hw_label.add_css_class("heading")
        hw_box.append(hw_label)

        # Single row for toggles (centered)
        sw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=60, halign=Gtk.Align.CENTER)
        
        def create_toggle_item(label_text, switch):
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            lbl = Gtk.Label(label=label_text, xalign=0.5)
            lbl.add_css_class("micro-caption")
            vbox.append(lbl)
            vbox.append(switch)
            return vbox

        self.led_switch = Gtk.Switch(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.led_switch.set_active(True)
        self.led_switch.connect("state-set", self.on_led_toggled)
        
        self.swap_switch = Gtk.Switch(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.swap_switch.connect("state-set", self.on_swap_toggled)
        
        self.batt_switch = Gtk.Switch(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.batt_switch.connect("state-set", self.on_batt_toggled)

        sw_row.append(create_toggle_item("LED", self.led_switch))
        sw_row.append(create_toggle_item("Swap", self.swap_switch))
        sw_row.append(create_toggle_item("Battery", self.batt_switch))
        
        hw_box.append(sw_row)
        content.append(hw_box)
        
        # --- Stack Setup ---
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_vexpand(True)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(content)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.stack.add_titled(scrolled, "system", "⚙ System")
        
        self.ctrl_panel = ControllerPanel()
        ctrl_scrolled = Gtk.ScrolledWindow()
        ctrl_scrolled.set_child(self.ctrl_panel)
        ctrl_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.stack.add_titled(ctrl_scrolled, "controller", "🎮 Controller")
        
        self.remap_panel = RemappingPanel()
        remap_scrolled = Gtk.ScrolledWindow()
        remap_scrolled.set_child(self.remap_panel)
        remap_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.stack.add_titled(remap_scrolled, "remapping", "🔄 Remap")
        
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(10)
        switcher.set_margin_bottom(5)
        
        box.append(switcher)
        box.append(self.stack)
        
        self.set_content(box)

    def _set_tele_text(self, lbl, txt):
        lbl.set_markup(f"<span size='x-small'>{txt}</span>")

    def on_tdp_changed(self, scale):
        val = int(scale.get_value())
        self.tdp_label.set_label(f"TDP Limit: {val} W")
        if getattr(self, '_syncing', False): return
        send_command(f"SET_TDP {val}")

    def on_temp_changed(self, scale):
        val = int(scale.get_value())
        self.temp_label.set_label(f"Temperature Limit: {val} °C")
        if getattr(self, '_syncing', False): return
        send_command(f"SET_TEMP {val}")

    def on_profile_changed(self, dropdown, obj):
        if getattr(self, '_syncing', False): return
        idx = dropdown.get_selected()
        mapping = {0: "quiet", 1: "balanced", 2: "performance", 3: "custom"}
        profile_name = mapping.get(idx, "custom")
        send_command(f"SET_PROFILE {profile_name}")
        
        # Sync graph with HHD derived defaults based on DEFAULT_TCTL
        quiet_pts = [30, 30, 30, 40, 45, 50, 60, 70, 80, 100]
        bal_pts = [40, 40, 40, 45, 50, 80, 90, 100, 100, 100]
        perf_pts = [50, 50, 60, 70, 80, 90, 100, 100, 100, 100]
        
        if profile_name == "quiet":
            self.fan_curve.set_points(quiet_pts)
            self.fan_box.set_sensitive(False)
        elif profile_name == "balanced":
            self.fan_curve.set_points(bal_pts)
            self.fan_box.set_sensitive(False)
        elif profile_name == "performance":
            self.fan_curve.set_points(perf_pts)
            self.fan_box.set_sensitive(False)
        else:
            self.fan_curve.set_points(self.fan_curve.saved_custom_points)
            self.fan_box.set_sensitive(True)
            
    def on_max_fan_toggled(self, switch, state):
        if getattr(self, '_syncing', False): return
        val = 1 if state else 0
        send_command(f"SET_FULL_FAN {val}")

    def on_fan_curve_changed(self, points):
        if getattr(self, '_syncing', False): return
        vals = [str(p) for p in points]
        send_command("SET_FAN_CURVE " + " ".join(vals))

    def on_led_toggled(self, switch, state):
        if getattr(self, '_syncing', False): return
        val = 1 if state else 0
        send_command(f"TOGGLE_LED {val}")
        return False

    def on_swap_toggled(self, switch, state):
        if getattr(self, '_syncing', False): return
        val = 1 if state else 0
        send_command(f"SET_LEGION_SWAP {val}")
        return False

    def on_batt_toggled(self, switch, state):
        if getattr(self, '_syncing', False): return
        val = 1 if state else 0
        send_command(f"SET_BATTERY_LIMIT {val}")
        return False
        
    def on_gpu_switch_toggled(self, switch, state):
        self.gpu_scale.set_sensitive(state)
        if state:
            send_command(f"SET_GPU_FREQ {int(self.gpu_scale.get_value())}")
        else:
            send_command("SET_GPU_FREQ_MODE auto")

    def on_gpu_freq_changed(self, scale):
        val = int(scale.get_value())
        self.gpu_label.set_label(f"Custom GPU Freq: {val} MHz")
        if self.gpu_switch.get_active():
            send_command(f"SET_GPU_FREQ {val}")

    def on_cpu_switch_toggled(self, switch, state):
        # State True = Boost On, False = Boost Off
        send_command(f"SET_CPU_BOOST {1 if state else 0}")
        if not state:
            # Reclamp scale max to base clock (3300)
            self.cpu_scale.set_range(1200, 3300)
            self.cpu_label.set_label(f"CPU Boost Off (Max: {int(self.cpu_scale.get_value())} MHz)")
        else:
            self.cpu_scale.set_range(1200, 5100)
            self.cpu_label.set_label(f"CPU Boost On (Max: {int(self.cpu_scale.get_value())} MHz)")

    def on_cpu_freq_changed(self, scale):
        val = int(scale.get_value())
        boost_str = "On" if self.cpu_switch.get_active() else "Off"
        self.cpu_label.set_label(f"CPU Boost {boost_str} (Max: {val} MHz)")
        send_command(f"SET_CPU_MAX_FREQ {val}")

    def on_fan_hover(self, temp, pct):
        if temp is None:
            self.fan_hover_lbl.set_label("Hold a point to view stats")
        else:
            self.fan_hover_lbl.set_label(f"Current Point: {temp}°C at {pct}% speed")

    def sync_sliders(self, data_str):
        try:
            parts = data_str.strip().split(maxsplit=1)
            if parts[0] == "SYNC_INITIAL_JSON" and len(parts) >= 2:
                self._syncing = True
                state = json.loads(parts[1])
                tdp = state.get("tdp")
                
                if tdp and not getattr(self, '_tdp_synced', False):
                    if tdp == 8:
                        self.profile_drop.set_selected(0) # quiet
                    elif tdp == 15:
                        self.profile_drop.set_selected(1) # balanced
                    elif tdp == 20 or tdp == 30: # Example default perf
                        self.profile_drop.set_selected(2) # performance
                    else:
                        self.profile_drop.set_selected(3) # custom
                        self.tdp_scale.set_value(tdp)
                    self._tdp_synced = True
                
                temp_lim = state.get("temp")
                if temp_lim and not getattr(self, '_temp_synced', False):
                    self.temp_scale.set_value(temp_lim)
                    self._temp_synced = True

                if "cpu_max_freq" in state and not getattr(self, '_cpu_f_synced', False):
                    self.cpu_scale.set_value(state["cpu_max_freq"])
                    self._cpu_f_synced = True
                if "cpu_boost" in state and not getattr(self, '_cpu_b_synced', False):
                    self.cpu_switch.set_active(state["cpu_boost"])
                    self._cpu_b_synced = True
                if "gpu_max_freq" in state and not getattr(self, '_gpu_f_synced', False):
                    self.gpu_scale.set_value(state["gpu_max_freq"])
                    self.gpu_switch.set_active(True)
                    self._gpu_f_synced = True
                
                self._syncing = False
        except Exception as e:
            print(f"Failed to sync sliders: {e}")
            self._syncing = False
        
    def toggle_keyboard(self):
        # Trigger the seamless GNOME Shell Extension via DBus
        cmd = [
            "dbus-send", "--session", "--type=method_call",
            "--dest=com.shubu.LegionOSK", "/com/shubu/LegionOSK",
            "com.shubu.LegionOSK.Toggle"
        ]
        try:
            subprocess.run(cmd, check=False)
            print("Toggled Legion OSK via DBus (Seamless)")
        except Exception as e:
            print(f"Failed to toggle OSK extension: {e}")

    def toggle_visibility(self):
        if self.get_visible():
            self.set_visible(False)
        else:
            self.set_visible(True)
            self.present()

    def update_telemetry(self, payload):
        sys = payload.get("system", {})
        bat = payload.get("battery", {})
        ctrl = payload.get("controllers", {})
        
        cpu_t = sys.get("cpu_temp", "-")
        gpu_t = sys.get("gpu_temp", "-")
        ssd_t = sys.get("ssd_temp", "-")
        apu_p = sys.get("apu_power", "-")
        self._set_tele_text(self.lbl_temps, f"Cpu {cpu_t}° | Gpu {gpu_t}° | Ssd {ssd_t}° | APU {apu_p} W")
        
        if cpu_t != "-":
            self.fan_curve.set_current_temp(cpu_t)
        
        cpu_f = payload.get("cpu_freq", "-")
        gpu_f = sys.get("gpu_freq", "-")
        self._set_tele_text(self.lbl_freqs, f"Cpu {cpu_f} MHz | Gpu {gpu_f} MHz")
        
        b_lvl = bat.get("bat_level", "-")
        b_hlth = bat.get("bat_health", "-")
        b_stat = bat.get("bat_status", "-")
        self._set_tele_text(self.lbl_legion_bat, f"Bat: {b_lvl}% ({b_stat}, H: {b_hlth}%)")
        
        def fmt_ctrl(b, s):
            if b == -1: return ""
            status = "Chg" if s == 4 else "Bat"
            return f"{b}% ({status})"
            
        l_str = fmt_ctrl(ctrl.get("l_bat", -1), ctrl.get("l_status", -1))
        r_str = fmt_ctrl(ctrl.get("r_bat", -1), ctrl.get("r_status", -1))
        self._set_tele_text(self.lbl_ctrl_bat, f"Ctrl: L {l_str} | R {r_str}")
