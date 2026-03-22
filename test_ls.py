import gi
gi.require_version("Gtk", "4.0")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell
    print("Layer Shell OK")
except Exception as e:
    print("Layer Shell Bad", e)
