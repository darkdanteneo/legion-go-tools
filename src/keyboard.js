/* -*- mode: js; js-indent-level: 4; indent-tabs-mode: nil -*- */
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

// ─── DBus interface ───────────────────────────────────────────────────────────
const LegionOSKInterface = `<node>
  <interface name="com.shubu.LegionOSK">
    <method name="Toggle"/>
  </interface>
</node>`;

// ─── Linux evdev keycodes ─────────────────────────────────────────────────────
const KC = {
    SHIFT_L: 42, BACKSPACE: 14, ENTER: 28, SPACE: 57,
    TAB: 15, CAPSLOCK: 58, CTRL_L: 29,
    UP: 103, DOWN: 108, LEFT: 105, RIGHT: 106,
    q: 16, w: 17, e: 18, r: 19, t: 20, y: 21, u: 22, i: 23, o: 24, p: 25,
    a: 30, s: 31, d: 32, f: 33, g: 34, h: 35, j: 36, k: 37, l: 38,
    z: 44, x: 45, c: 46, v: 47, b: 48, n: 49, m: 50,
    N1: 2, N2: 3, N3: 4, N4: 5, N5: 6, N6: 7, N7: 8, N8: 9, N9: 10, N0: 11,
    MINUS: 12, EQUALS: 13, SEMI: 39, QUOTE: 40, COMMA: 51, DOT: 52, SLASH: 53,
    GRAVE: 41, LEFTBRACE: 26, RIGHTBRACE: 27, BACKSLASH: 43,
    F1: 59, F2: 60, F3: 61, F4: 62, F5: 63, F6: 64, F7: 65, F8: 66, F9: 67, F10: 68, F11: 87, F12: 88,
    ALT_L: 56,
};

// ─── Key definition helpers ───────────────────────────────────────────────────
const L = ch => ({ type: 'letter', lower: ch, upper: ch.toUpperCase(), code: KC[ch], flex: 1 });
const S = (label, codes, flex = 1) => ({ type: 'symbol', label, codes, flex });
const K = (type, label, flex = 1) => ({ type, label, flex });

// Number row (shared)
const NUM_ROW = [
    S('1', [KC.N1]), S('2', [KC.N2]), S('3', [KC.N3]), S('4', [KC.N4]), S('5', [KC.N5]),
    S('6', [KC.N6]), S('7', [KC.N7]), S('8', [KC.N8]), S('9', [KC.N9]), S('0', [KC.N0]),
];

// ─── Layouts ──────────────────────────────────────────────────────────────────
const LETTERS_ROWS = [
    NUM_ROW,
    [K('tab', '⇥', 1.5), ...[...'qwertyuiop'].map(L), K('backspace', '⌫', 1.5)],
    [K('caps', '⇪', 1.7), ...[...'asdfghjkl'].map(L), K('enter', '↵', 2.3)],
    [K('shift', '⇧', 1.3), K('view-sym', '?123', 1), ...[...'zxcvbnm'].map(L), K('emoji', '😀', 0.5), K('up', '↑', 1), K('close', '✕', 1)],
    [K('ctrl', 'Ctrl', 1.1), K('fn', 'Fn', 0.6), K('alt', 'Alt', 0.6), S(',', [KC.COMMA], 0.6), K('space', '', 5.3), S('.', [KC.DOT], 0.6), K('left', '←', 1), K('down', '↓', 1), K('right', '→', 1)],
];

const SYMBOLS_ROWS = [
    NUM_ROW,
    [S('!', [KC.SHIFT_L, KC.N1]), S('@', [KC.SHIFT_L, KC.N2]), S('#', [KC.SHIFT_L, KC.N3]),
    S('$', [KC.SHIFT_L, KC.N4]), S('%', [KC.SHIFT_L, KC.N5]), S('^', [KC.SHIFT_L, KC.N6]),
    S('&', [KC.SHIFT_L, KC.N7]), S('*', [KC.SHIFT_L, KC.N8]),
    S('(', [KC.SHIFT_L, KC.N9]), S(')', [KC.SHIFT_L, KC.N0])],
    [S('"', [KC.SHIFT_L, KC.QUOTE]), S("'", [KC.QUOTE]), S(':', [KC.SHIFT_L, KC.SEMI]),
    S(';', [KC.SEMI]), S('?', [KC.SHIFT_L, KC.SLASH]), S('/', [KC.SLASH]),
    S('-', [KC.MINUS]), S('+', [KC.SHIFT_L, KC.EQUALS]),
    S('=', [KC.EQUALS]), K('backspace', '⌫', 1.5)],
    [S('<', [KC.SHIFT_L, KC.COMMA]), S('{', [KC.SHIFT_L, KC.LEFTBRACE]),
    S('[', [KC.LEFTBRACE]), S(']', [KC.RIGHTBRACE]),
    S('}', [KC.SHIFT_L, KC.RIGHTBRACE]), S('>', [KC.SHIFT_L, KC.DOT]),
    S('|', [KC.SHIFT_L, KC.BACKSLASH]), S('\\', [KC.BACKSLASH]),
    S('~', [KC.SHIFT_L, KC.GRAVE]), S('`', [KC.GRAVE])],
    [K('view-abc', 'ABC', 1.5), S(',', [KC.COMMA]), S('_', [KC.SHIFT_L, KC.MINUS]),
    K('space', '', 4),
    S('.', [KC.DOT]), K('enter', '↵', 1.5)],
];

// ─── Colours / sizes ──────────────────────────────────────────────────────────
const C = {
    bg: 'rgba(18,18,20,0.97)',
    key: 'rgba(52,52,58,0.95)',
    mod: 'rgba(75,75,82,0.95)',
    accent: 'rgba(220,65,0,0.88)',
    shiftOn: 'rgba(220,95,0,0.95)',
    capsOn: 'rgba(230,160,0,0.95)',
    ctrlOn: 'rgba(90,160,255,0.90)',
    border: 'rgba(100,100,110,0.25)',
    dragBar: 'rgba(40,40,46,0.98)',
    dragGrip: 'rgba(100,100,110,0.6)',
};

function keyStyle(bg, fg = '#fff', extra = '') {
    return `background-color:${bg};color:${fg};border:1px solid ${C.border};` +
        `border-radius:8px;padding:0;margin:0;${extra}`;
}

// ─── Floating mode constants ──────────────────────────────────────────────────
const FLOAT_WIDTH_RATIO = 0.55;   // 55% of monitor width
const FLOAT_HEIGHT_PCT = 0.36;    // 36% of monitor height
const DOCK_HEIGHT_PCT = 0.42;     // 42% of monitor height (normal/docked)
const DRAG_BAR_H = 28;           // drag handle height in floating mode
const EMOJI_HOLD_MS = 2000;       // hold emoji for 2s to toggle float

// ─── Main Extension ───────────────────────────────────────────────────────────
export default class LegionOSKExtension extends Extension {

    enable() {
        this._visible = false;
        this._view = 'letters';
        this._capsLock = false;
        this._shiftActive = false;
        this._ctrlActive = false;
        this._altActive = false;
        this._fnActive = false;
        this._letterBtns = [];
        this._shiftBtn = null;
        this._capsBtn = null;
        this._ctrlBtn = null;
        this._altBtn = null;
        this._monitorsChangedId = 0;

        // Floating mode state
        this._floatingMode = false;
        this._floatX = -1;  // -1 = not positioned yet (center on first show)
        this._floatY = -1;
        this._dragging = false;
        this._dragOffsetX = 0;
        this._dragOffsetY = 0;
        this._grab = null;

        this._inputDevice = Clutter.get_default_backend()
            .get_default_seat()
            .create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);

        this._setupDBus();
        this._oldShowKeyboard = null;

        // ── Disable Built-in Keyboard ───────────────────────────────────────
        // This prevents GNOME from popping up its own keyboard when auto-rotate
        // triggers tablet mode.
        if (Main.keyboard) {
            this._oldShowKeyboard = Main.keyboard.show;
            Main.keyboard.show = () => {
                console.log("[LegionOSK] Suppressing built-in GNOME OSK");
            };
        }

        // ── Top Bar Indicators ──────────────────────────────────────────────
        // 1. Keyboard Toggle
        // NOTE: dontCreateMenu MUST be `true` on GNOME 50+. PanelMenu.Button
        // now uses Clutter.ClickGesture (a ClutterAction) to toggle its menu,
        // and that gesture eats press/touch events before any signal handler
        // runs. Passing `true` disables the gesture so our `button-press-event`
        // / `touch-event` connects fire normally.
        this._indicator = new PanelMenu.Button(0.0, "Legion OSK Indicator", true);
        const icon = new St.Icon({
            gicon: new Gio.ThemedIcon({ name: 'input-keyboard-symbolic' }),
            style_class: 'system-status-icon'
        });
        this._indicator.add_child(icon);
        this._indicator.connect("button-press-event", () => { this.Toggle(); return Clutter.EVENT_STOP; });
        this._indicator.connect("touch-event", (_actor, event) => {
            if (event.type() === Clutter.EventType.TOUCH_END) this.Toggle();
            return Clutter.EVENT_STOP;
        });
        Main.panel.addToStatusArea("LegionOSK", this._indicator);

        // 2. Sidebar Toggle (same dontCreateMenu=true rationale as above)
        this._sidebarIndicator = new PanelMenu.Button(0.0, "Legion Sidebar Indicator", true);
        const sIcon = new St.Icon({
            gicon: new Gio.ThemedIcon({ name: 'emblem-system-symbolic' }),
            style_class: 'system-status-icon'
        });
        this._sidebarIndicator.add_child(sIcon);
        const toggleSidebar = () => {
            Gio.DBus.session.call(
                'com.github.shubu.LegionSidebar',
                '/com/github/shubu/LegionSidebar',
                'org.gtk.Actions',
                'Activate',
                new GLib.Variant('(sava{sv})', ['toggle-sidebar', [], {}]),
                null, Gio.DBusCallFlags.NONE, -1, null, null
            );
        };
        this._sidebarIndicator.connect("button-press-event", () => { toggleSidebar(); return Clutter.EVENT_STOP; });
        this._sidebarIndicator.connect("touch-event", (_actor, event) => {
            if (event.type() === Clutter.EventType.TOUCH_END) toggleSidebar();
            return Clutter.EVENT_STOP;
        });
        Main.panel.addToStatusArea("LegionSidebar", this._sidebarIndicator);

        // ── Lock Screen Touch Detection ─────────────────────────────────────
        this._stageEventId = global.stage.connect('event', (_actor, event) => {
            const mode = Main.sessionMode.currentMode;
            if (mode === 'unlock-dialog' && (event.type() === Clutter.EventType.TOUCH_END || event.type() === Clutter.EventType.BUTTON_RELEASE)) {
                let source = event.get_source();
                let isEntry = false;
                while (source) {
                    const name = source.constructor ? source.constructor.name : '';
                    if (source instanceof St.Entry || source instanceof Clutter.Text || name.includes('Entry') || name.includes('Password')) {
                        isEntry = true;
                        break;
                    }
                    source = source.get_parent();
                }
                if (isEntry && !this._visible) {
                    this._show();
                }
            }
            return Clutter.EVENT_PROPAGATE;
        });

        const mon = Main.layoutManager.primaryMonitor;
        if (mon) {
            this._initUI();
        } else {
            this._monitorsChangedId = Main.layoutManager.connect('monitors-changed', () => {
                if (Main.layoutManager.primaryMonitor) {
                    this._onGeometryChanged();
                }
            });
        }
    }

    _onGeometryChanged() {
        if (!this._visible) {
            this._initUI();
            return;
        }
        this._hide();
        this._initUI();
        this._show();
    }

    _initUI() {
        const mon = Main.layoutManager.primaryMonitor;
        if (!mon) return;
        this._buildChrome();
        this._buildKeyboard();
    }

    disable() {
        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = 0;
        }
        if (this._stageEventId) {
            global.stage.disconnect(this._stageEventId);
            this._stageEventId = 0;
        }
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        if (this._sidebarIndicator) {
            this._sidebarIndicator.destroy();
            this._sidebarIndicator = null;
        }
        if (this._oldShowKeyboard && Main.keyboard) {
            Main.keyboard.show = this._oldShowKeyboard;
            this._oldShowKeyboard = null;
        }
        this._endDrag();
        this._teardownDBus();
        if (this._chrome) {
            Main.layoutManager.removeChrome(this._chrome);
            this._chrome.destroy();
            this._chrome = null;
        }
    }

    // ── DBus ──────────────────────────────────────────────────────────────────
    _setupDBus() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(LegionOSKInterface, this);
        this._dbus.export(Gio.DBus.session, '/com/shubu/LegionOSK');
        this._nameId = Gio.DBus.session.own_name(
            'com.shubu.LegionOSK', Gio.BusNameOwnerFlags.NONE, null, null);
    }

    _teardownDBus() {
        if (this._nameId) { Gio.DBus.session.unown_name(this._nameId); this._nameId = null; }
        if (this._dbus) { this._dbus.unexport(); this._dbus = null; }
    }

    Toggle() { if (!this._chrome) return; this._visible ? this._hide() : this._show(); }

    // ── Show / Hide ───────────────────────────────────────────────────────────
    _show() {
        if (!this._chrome) return;
        const mon = Main.layoutManager.primaryMonitor;
        if (!mon) return;

        if (this._floatingMode) {
            // Center on first show, otherwise use saved position
            if (this._floatX < 0 || this._floatY < 0) {
                this._floatX = mon.x + Math.round((mon.width - this._kbW) / 2);
                this._floatY = mon.y + Math.round((mon.height - this._kbH) / 2);
            }
            this._chrome.set_position(this._floatX, this._floatY);
        } else {
            this._chrome.set_position(mon.x, mon.y + mon.height - this._kbH);
        }

        this._chrome.show();
        this._chrome.set_opacity(0);
        this._chrome.ease({ opacity: 255, duration: 160, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
        const parent = this._chrome.get_parent();
        if (parent) parent.set_child_above_sibling(this._chrome, null);
        this._visible = true;
    }

    _hide() {
        this._endDrag();
        this._chrome.ease({
            opacity: 0, duration: 120, mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                this._chrome.hide();
                if (!this._floatingMode) {
                    this._chrome.set_position(-this._monW, -this._kbH);
                }
            },
        });
        this._visible = false;
        // Always reopen to letters view
        if (this._view !== 'letters') {
            this._view = 'letters';
            this._resetModifiers();
            this._buildKeyboard();
        }
    }

    // ── Chrome container ──────────────────────────────────────────────────────
    _buildChrome() {
        // Destroy old chrome if exists
        if (this._chrome) {
            Main.layoutManager.removeChrome(this._chrome);
            this._chrome.destroy();
            this._chrome = null;
        }

        const mon = Main.layoutManager.primaryMonitor;
        this._monW = mon.width;

        if (this._floatingMode) {
            this._kbW = Math.round(mon.width * FLOAT_WIDTH_RATIO);
            this._kbH = Math.round(mon.height * FLOAT_HEIGHT_PCT);
            this._rowH = Math.round((this._kbH - DRAG_BAR_H - 28) / 5);
        } else {
            this._kbW = mon.width;
            this._kbH = Math.round(mon.height * DOCK_HEIGHT_PCT);
            this._rowH = Math.round((this._kbH - 28) / 5);
        }

        this._chrome = new St.BoxLayout({
            name: 'legion-osk-chrome',
            vertical: true,
            reactive: true,
            width: this._kbW,
            height: this._kbH,
            style: `background-color:${C.bg};` +
                `border:1px solid rgba(80,80,90,0.5);` +
                `border-radius:${this._floatingMode ? '12' : '0'}px;` +
                `padding:6px 6px 10px 6px;`,
        });

        // Position off-screen initially
        this._chrome.set_position(-this._kbW, -this._kbH);

        // GNOME 50 removed `affectsInputRegion`: input region is now derived
        // automatically from the actor's reactivity.
        Main.layoutManager.addChrome(this._chrome, {
            affectsStruts: false,
            trackFullscreen: true,
        });
        this._chrome.hide();
    }

    // ── Build keyboard rows ───────────────────────────────────────────────────
    _buildKeyboard() {
        this._chrome.get_children().forEach(c => c.destroy());
        this._letterBtns = [];
        this._shiftBtn = null;
        this._capsBtn = null;
        this._ctrlBtn = null;

        const GAP = this._floatingMode ? 3 : 4;
        const contentW = this._kbW - 12; // 2×6 padding

        // ── Drag handle (floating mode only) ─────────────────────────────────
        if (this._floatingMode) {
            const dragBar = new St.BoxLayout({
                vertical: false, x_expand: true, reactive: true,
                height: DRAG_BAR_H,
                style: `background-color:${C.dragBar};border-radius:8px 8px 0 0;` +
                    `margin-bottom:${GAP}px;`,
            });

            // Left spacer
            dragBar.add_child(new St.Widget({ x_expand: true }));

            // Grip dots (visual indicator)
            const grip = new St.Label({
                text: '⠿⠿⠿',
                y_align: Clutter.ActorAlign.CENTER,
                style: `color:${C.dragGrip};font-size:14px;letter-spacing:4px;`,
            });
            dragBar.add_child(grip);

            // Right spacer
            dragBar.add_child(new St.Widget({ x_expand: true }));

            // Wire drag events on the bar
            this._wireDrag(dragBar);
            this._chrome.add_child(dragBar);
        }

        // ── Key rows ─────────────────────────────────────────────────────────
        const layout = this._view === 'letters' ? LETTERS_ROWS : SYMBOLS_ROWS;
        const fontSize = this._floatingMode ? 0.82 : 1.0; // scale factor

        for (const rowDef of layout) {
            const totalFlex = rowDef.reduce((s, k) => s + (k.flex ?? 1), 0);
            const totalGap = (rowDef.length - 1) * GAP;
            const flexUnit = (contentW - totalGap) / totalFlex;

            const row = new St.BoxLayout({
                vertical: false, x_expand: true, reactive: true,
                style: `spacing:${GAP}px;margin-bottom:${GAP}px;`,
                height: this._rowH,
            });

            for (const kd of rowDef) {
                const w = Math.round(flexUnit * (kd.flex ?? 1));
                const btn = this._makeKey(kd, w, this._rowH, fontSize);
                row.add_child(btn);
            }
            this._chrome.add_child(row);
        }
    }

    // ── Key factory ───────────────────────────────────────────────────────────
    _makeKey(kd, w, h, fontScale = 1.0) {
        let label, bg, fg = '#fff', fontSize = 16 * fontScale;

        switch (kd.type) {
            case 'letter':
                label = (this._capsLock !== this._shiftActive) ? kd.upper : kd.lower;
                bg = C.key; fontSize = 17 * fontScale; break;
            case 'symbol':
                if (this._fnActive) {
                    if (kd.label >= '1' && kd.label <= '9') label = `F${kd.label}`;
                    else if (kd.label === '0') label = 'F10';
                    else if (kd.label === '-') label = 'F11';
                    else if (kd.label === '=') label = 'F12';
                    else label = kd.label;
                } else {
                    label = kd.label;
                }
                bg = C.key; break;
            case 'tab':
                label = '⇥'; bg = C.mod; break;
            case 'caps':
                label = '⇪'; bg = this._capsLock ? C.capsOn : C.mod;
                fg = this._capsLock ? '#000' : '#fff'; break;
            case 'shift':
                label = '⇧'; bg = this._shiftActive ? C.shiftOn : C.mod; break;
            case 'ctrl':
                label = 'Ctrl'; bg = this._ctrlActive ? C.ctrlOn : C.mod;
                fontSize = 13 * fontScale; break;
            case 'alt':
                label = 'Alt'; bg = this._altActive ? C.ctrlOn : C.mod;
                fontSize = 13 * fontScale; break;
            case 'fn':
                label = 'Fn'; bg = this._fnActive ? C.accent : C.mod;
                fontSize = 13 * fontScale; break;
            case 'backspace':
                label = '⌫'; bg = C.mod; break;
            case 'space':
                label = ''; bg = C.mod; break;
            case 'enter':
                label = '↵'; bg = C.accent; fontSize = 18 * fontScale; break;
            case 'emoji':
                label = '😀'; bg = C.mod; break;
            case 'up': label = '↑'; bg = C.mod; break;
            case 'down': label = '↓'; bg = C.mod; break;
            case 'left': label = '←'; bg = C.mod; break;
            case 'right': label = '→'; bg = C.mod; break;
            case 'close': label = '✕'; bg = 'rgba(180,50,50,0.85)'; fontSize = 14 * fontScale; break;
            case 'view-sym':
                label = '?123'; bg = C.mod; fontSize = 13 * fontScale; break;
            case 'view-abc':
                label = 'ABC'; bg = C.mod; fontSize = 13 * fontScale; break;
            default:
                label = kd.label ?? ''; bg = C.mod;
        }

        const btn = new St.Button({
            label, width: w, height: h,
            style: keyStyle(bg, fg, `font-size:${Math.round(fontSize)}px;font-weight:500;`),
        });

        if (kd.type === 'letter') { btn._kd = kd; this._letterBtns.push(btn); }
        if (kd.type === 'shift') { this._shiftBtn = btn; }
        if (kd.type === 'caps') { this._capsBtn = btn; }
        if (kd.type === 'ctrl') { this._ctrlBtn = btn; }
        if (kd.type === 'alt') { this._altBtn = btn; }

        this._wire(btn, kd);
        return btn;
    }

    // ── Event wiring ──────────────────────────────────────────────────────────
    _wire(btn, kd) {
        let holdT = null, repT = null;
        // For emoji long-press detection
        let emojiHoldT = null, emojiLongPressed = false;

        const cancelTimers = () => {
            if (holdT) { clearTimeout(holdT); holdT = null; }
            if (repT) { clearInterval(repT); repT = null; }
        };

        const press = () => {
            btn.add_style_pseudo_class('active');
            if (kd.type === 'backspace') {
                cancelTimers();
                this._act(kd);
                holdT = setTimeout(() => {
                    holdT = null;
                    repT = setInterval(() => this._act(kd), 80);
                }, 500);
            }
            if (kd.type === 'emoji') {
                emojiLongPressed = false;
                emojiHoldT = setTimeout(() => {
                    emojiHoldT = null;
                    emojiLongPressed = true;
                    this._toggleFloatingMode();
                }, EMOJI_HOLD_MS);
            }
        };

        const release = () => {
            btn.remove_style_pseudo_class('active');
            cancelTimers();
            if (kd.type === 'emoji') {
                if (emojiHoldT) { clearTimeout(emojiHoldT); emojiHoldT = null; }
                // Only fire emoji if it wasn't a long press
                if (!emojiLongPressed) this._act(kd);
                emojiLongPressed = false;
                return;
            }
            if (kd.type === 'backspace') {
                this._releaseKey([KC.BACKSPACE]);
            } else {
                this._act(kd);
            }
        };

        btn.connect('button-press-event', () => { press(); return Clutter.EVENT_STOP; });
        btn.connect('button-release-event', () => { release(); return Clutter.EVENT_STOP; });
        btn.connect('touch-event', () => {
            const ev = Clutter.get_current_event();
            if (ev.type() === Clutter.EventType.TOUCH_BEGIN) press();
            else if (ev.type() === Clutter.EventType.TOUCH_END ||
                ev.type() === Clutter.EventType.TOUCH_CANCEL) release();
            return Clutter.EVENT_STOP;
        });
    }

    // ── Drag handling (floating mode) ─────────────────────────────────────────
    _wireDrag(actor) {
        actor.connect('button-press-event', (_a, event) => {
            this._startDrag(event);
            return Clutter.EVENT_STOP;
        });

        actor.connect('touch-event', (_a, event) => {
            const ev = Clutter.get_current_event();
            if (ev.type() === Clutter.EventType.TOUCH_BEGIN) {
                this._startDrag(ev);
            } else if (ev.type() === Clutter.EventType.TOUCH_END ||
                ev.type() === Clutter.EventType.TOUCH_CANCEL) {
                this._endDrag();
            } else if (ev.type() === Clutter.EventType.TOUCH_UPDATE && this._dragging) {
                const [absX, absY] = ev.get_coords();
                this._moveDrag(absX, absY);
            }
            return Clutter.EVENT_STOP;
        });
    }

    _startDrag(event) {
        if (this._dragging) return;
        const [absX, absY] = event.get_coords();
        const [chromeX, chromeY] = this._chrome.get_position();
        this._dragOffsetX = absX - chromeX;
        this._dragOffsetY = absY - chromeY;
        this._dragging = true;

        // Grab the stage to receive motion/release events everywhere
        this._grab = global.stage.grab(this._chrome);

        // Connect stage events for mouse drag
        this._dragMotionId = this._chrome.connect('event', (_actor, event) => {
            const t = event.type();
            if (t === Clutter.EventType.MOTION) {
                const [mx, my] = event.get_coords();
                this._moveDrag(mx, my);
                return Clutter.EVENT_STOP;
            }
            if (t === Clutter.EventType.BUTTON_RELEASE ||
                t === Clutter.EventType.TOUCH_END ||
                t === Clutter.EventType.TOUCH_CANCEL) {
                this._endDrag();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        // Visual feedback
        this._chrome.ease({ opacity: 220, duration: 100, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
    }

    _moveDrag(absX, absY) {
        if (!this._dragging) return;
        const mon = Main.layoutManager.primaryMonitor;
        if (!mon) return;
        // Clamp to monitor bounds
        const nx = Math.max(mon.x, Math.min(absX - this._dragOffsetX, mon.x + mon.width - this._kbW));
        const ny = Math.max(mon.y, Math.min(absY - this._dragOffsetY, mon.y + mon.height - this._kbH));
        this._chrome.set_position(nx, ny);
        this._floatX = nx;
        this._floatY = ny;
    }

    _endDrag() {
        if (!this._dragging) return;
        this._dragging = false;
        if (this._dragMotionId) {
            this._chrome.disconnect(this._dragMotionId);
            this._dragMotionId = 0;
        }
        if (this._grab) {
            this._grab.dismiss();
            this._grab = null;
        }
        if (this._chrome) {
            this._chrome.ease({ opacity: 255, duration: 100, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
        }
    }

    // ── Toggle floating mode ──────────────────────────────────────────────────
    _toggleFloatingMode() {
        const wasVisible = this._visible;
        this._floatingMode = !this._floatingMode;

        // Reset float position so it re-centers
        if (this._floatingMode) {
            this._floatX = -1;
            this._floatY = -1;
        }

        // Rebuild chrome with new dimensions
        this._buildChrome();
        this._buildKeyboard();

        if (wasVisible) {
            this._show();
        }

        console.log(`[LegionOSK] Floating mode: ${this._floatingMode ? 'ON' : 'OFF'}`);
    }

    // ── Actions ───────────────────────────────────────────────────────────────
    _act(kd) {
        switch (kd.type) {
            case 'letter': {
                const upper = this._capsLock !== this._shiftActive;
                let codes = upper ? [KC.SHIFT_L, kd.code] : [kd.code];
                if (this._ctrlActive) { codes = [KC.CTRL_L, ...codes]; this._setCtrl(false); }
                if (this._altActive) { codes = [KC.ALT_L, ...codes]; this._setAlt(false); }
                this._sendKey(codes);
                if (this._shiftActive) this._setShift(false);
                break;
            }
            case 'symbol': {
                let codes = [...kd.codes];
                if (this._fnActive) {
                    if (kd.label >= '1' && kd.label <= '9') codes = [KC[`F${kd.label}`]];
                    else if (kd.label === '0') codes = [KC.F10];
                    else if (kd.label === '-') codes = [KC.F11];
                    else if (kd.label === '=') codes = [KC.F12];
                }
                if (this._ctrlActive) {
                    codes = [KC.CTRL_L, ...codes];
                    this._setCtrl(false);
                }
                if (this._altActive) {
                    codes = [KC.ALT_L, ...codes];
                    this._setAlt(false);
                }
                this._sendKey(codes);
                if (this._shiftActive) this._setShift(false);
                break;
            }
            case 'backspace': this._sendKey([KC.BACKSPACE]); break;
            case 'enter': this._sendKey([KC.ENTER]); break;
            case 'space': this._sendKey([KC.SPACE]); break;
            case 'tab': this._sendKey([KC.TAB]); break;
            case 'up': this._sendKey([KC.UP]); break;
            case 'down': this._sendKey([KC.DOWN]); break;
            case 'left': this._sendKey([KC.LEFT]); break;
            case 'right': this._sendKey([KC.RIGHT]); break;
            case 'emoji':
                this._sendKey([KC.CTRL_L, KC.DOT]);
                break;
            case 'caps':
                this._capsLock = !this._capsLock;
                this._updateLetterDisplay();
                this._updateModifierStyles();
                break;
            case 'shift':
                this._setShift(!this._shiftActive);
                break;
            case 'ctrl':
                this._setCtrl(!this._ctrlActive);
                break;
            case 'alt':
                this._setAlt(!this._altActive);
                break;
            case 'fn':
                this._fnActive = !this._fnActive;
                this._buildKeyboard();
                break;
            case 'view-sym':
                this._view = 'symbols'; this._resetModifiers(); this._buildKeyboard(); break;
            case 'view-abc':
                this._view = 'letters'; this._resetModifiers(); this._buildKeyboard(); break;
            case 'close':
                this._hide(); break;
        }
    }

    // ── Modifier state helpers ────────────────────────────────────────────────
    _setShift(active) {
        this._shiftActive = active;
        this._updateLetterDisplay();
        this._updateModifierStyles();
    }

    _setCtrl(active) {
        this._ctrlActive = active;
        this._updateModifierStyles();
    }

    _resetModifiers() {
        this._shiftActive = false;
        this._ctrlActive = false;
        this._altActive = false;
    }

    _updateLetterDisplay() {
        const upper = this._capsLock !== this._shiftActive;
        for (const b of this._letterBtns)
            b.label = upper ? b._kd.upper : b._kd.lower;
    }

    _updateModifierStyles() {
        const fs = this._floatingMode ? 0.82 : 1.0;
        if (this._shiftBtn) {
            this._shiftBtn.style = keyStyle(
                this._shiftActive ? C.shiftOn : C.mod,
                '#fff', `font-size:${Math.round(16 * fs)}px;font-weight:500;`);
        }
        if (this._capsBtn) {
            this._capsBtn.style = keyStyle(
                this._capsLock ? C.capsOn : C.mod,
                this._capsLock ? '#000' : '#fff', `font-size:${Math.round(16 * fs)}px;font-weight:500;`);
        }
        if (this._ctrlBtn) {
            this._ctrlBtn.style = keyStyle(
                this._ctrlActive ? C.ctrlOn : C.mod,
                '#fff', `font-size:${Math.round(13 * fs)}px;font-weight:500;`);
        }
        if (this._altBtn) {
            this._altBtn.style = keyStyle(
                this._altActive ? C.ctrlOn : C.mod,
                '#fff', `font-size:${Math.round(13 * fs)}px;font-weight:500;`);
        }
    }

    // ── Key injection ─────────────────────────────────────────────────────────
    _sendKey(codes) {
        try {
            const tPress = GLib.get_monotonic_time();
            codes.forEach(c => this._inputDevice.notify_key(tPress, c, Clutter.KeyState.PRESSED));
            setTimeout(() => {
                try {
                    const tRelease = GLib.get_monotonic_time();
                    [...codes].reverse().forEach(c =>
                        this._inputDevice.notify_key(tRelease, c, Clutter.KeyState.RELEASED));
                } catch (e) {
                    console.error('[LegionOSK] sendKey release error:', e.message);
                }
            }, 50);
        } catch (e) {
            console.error('[LegionOSK] sendKey error:', e.message);
        }
    }

    _releaseKey(codes) {
        try {
            const t = GLib.get_monotonic_time();
            [...codes].reverse().forEach(c =>
                this._inputDevice.notify_key(t, c, Clutter.KeyState.RELEASED));
        } catch (e) {
            console.error('[LegionOSK] releaseKey error:', e.message);
        }
    }

    _setAlt(active) {
        this._altActive = active;
        this._updateModifierStyles();
    }
}
