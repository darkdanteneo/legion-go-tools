Legion Go Sidebar - Walkthrough
I have implemented the Legion Go Sidebar application using a Python GTK4 application coupled with a background evdev driver listening daemon. Since GNOME Wayland restricts arbitrary key bindings from reading hardware buttons natively, the background daemon solves this by reading your controller limits directly.

Directory Structure
In /home/shubu/.gemini/antigravity/scratch/legion_sidebar_app:

sidebar/app.py: The Python GTK4 + libadwaita graphical interface.
daemon/input_listener.py: The background daemon that listens for the hardware button.
utils/find_button.py: A utility to help you configure the correct button code.
1. Finding Your Lenovo Button Code
Because the exact button codes emitted by the Legion Controller can vary depending on driver patches (e.g. if you are using Handheld Daemon or vanilla xpad), you should first find exactly what your system sees when you press the Legion L or R button.

Open a terminal and run the diagnostic utility as root (you need this to read raw input events):
bash
cd /home/shubu/.gemini/antigravity/scratch/legion_sidebar_app
sudo python3 utils/find_button.py
Press the physical Legion L or Legion R button on your controller.
The terminal will output something like:
text
[DEVICE MAPPING HIT]
Device: Microsoft X-Box 360 pad
Evdev Path: /dev/input/eventX
Button Keycode: 'KEY_PROG1'
Raw Scancode: XXXXXX
Stop the script with Ctrl+C. Note the Button Keycode (e.g. KEY_PROG1 or KEY_MACRO).
Open daemon/input_listener.py and ensure the TARGET_KEYCODES array contains your keycode.
2. Using The App
You can test the components individually:

Test the UI:

bash
python3 sidebar/app.py
The window should appear. Keep it open, and running this in another terminal tab will toggle it off:

bash
python3 sidebar/app.py --toggle
Starting the setup: Since the input listener must be able to read /dev/input/, you should add your user to the input group. This is standard practice for Linux handhelds:

bash
sudo usermod -aG input $USER
Note: You may need to log out and log back in for the group change to take effect.

Once your user is in the input group, you can launch the listener daemon in the background on startup:

bash
python3 daemon/input_listener.py &
Now, whenever you press the mapped physical Lenovo Button, the GTK4 sidebar will instantly pop up on your screen. Pressing it again will cleanly hide it.

Future Improvements
True Edge Docking: To get a native "edge swipe-in" sidebar look like Windows, Wayland GNOME does not allow native window placing. The current app is a floating window. Converting this into a GNOME Shell Extension would be the next step if you want to dock it exactly to the right edge of the display and bypass Wayland windowing.
Start on Boot: You can easily add input_listener.py to your ~/.config/autostart/ so it starts up ready every time you turn on your Legion Go.