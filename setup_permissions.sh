#!/bin/bash

# 1. Create udev rule for Legion Go Controllers to allow non-root HID access
# Also adds the SDL_GAMECONTROLLERCONFIG for these devices
UDEV_RULE_FILE="/etc/udev/rules.d/99-legion-go.rules"
SDL_STR="03008665ef170000eb61000000010000,Generic X-Box pad,platform:Linux,crc:6586,a:b0,b:b1,x:b2,y:b3,back:b6,start:b7,leftstick:b9,rightstick:b10,leftshoulder:b4,rightshoulder:b5,dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,"

echo "Creating udev rules for Legion Go HID devices with SDL2 config..."
cat <<EOF | sudo tee $UDEV_RULE_FILE
# Legion Go Controller HID devices (include various PIDs)
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6180", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61e0", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6182", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6183", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6184", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6185", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61eb", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61ec", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61ed", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61ee", MODE="0666", ENV{SDL_GAMECONTROLLERCONFIG}="$SDL_STR"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

# 2. Handle ACPI permissions (acpi_call)
echo "Setting permissions for /proc/acpi/call..."
if [ -e "/proc/acpi/call" ]; then
    sudo chmod 666 /proc/acpi/call
else
    # Try loading the module
    sudo modprobe acpi_call 2>/dev/null
    if [ -e "/proc/acpi/call" ]; then
        sudo chmod 666 /proc/acpi/call
    else
        echo "Warning: /proc/acpi/call not found. acpi_call module might be missing."
    fi
fi

# 3. RyzenAdj permissions
RYZENADJ_PATH="/usr/local/bin/ryzenadj"
if [ -f "$RYZENADJ_PATH" ]; then
    echo "Setting SUID bit on $RYZENADJ_PATH..."
    sudo chown root:root "$RYZENADJ_PATH"
    sudo chmod +s "$RYZENADJ_PATH"
fi

# 3b. Nvidia-OC permissions
NVIDIAOC_PATH="/usr/local/bin/nvidia-oc"
if [ -f "$NVIDIAOC_PATH" ]; then
    echo "Setting SUID bit on $NVIDIAOC_PATH..."
    sudo chown root:root "$NVIDIAOC_PATH" /usr/local/bin/nvidia-oc-bin
    sudo chmod +s "$NVIDIAOC_PATH"
    sudo chmod +x /usr/local/bin/nvidia-oc-bin
fi

# 4. CPU/GPU/Display Frequency & Brightness Control Permissions
echo "Setting permissions for hardware control..."
# GPU
for f in /sys/class/drm/card*/device/power_dpm_force_performance_level /sys/class/drm/card*/device/pp_od_clk_voltage; do
    [ -e "$f" ] && sudo chmod 666 "$f"
done

# Backlight
for f in /sys/class/backlight/*/brightness; do
    [ -e "$f" ] && sudo chmod 666 "$f"
done

# CPU Boost
for f in /sys/devices/system/cpu/amd_pstate/cpb_boost /sys/devices/system/cpu/cpufreq/boost; do
    [ -e "$f" ] && sudo chmod 666 "$f"
done

# CPU Max Freq
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq; do
    [ -e "$f" ] && sudo chmod 666 "$f"
done

# 4a. Create PERSISTENT udev rules for the above
SYSFS_RULE_FILE="/etc/udev/rules.d/98-legion-go-sysfs.rules"
echo "Creating persistent udev rules for sysfs nodes..."
cat <<EOF | sudo tee $SYSFS_RULE_FILE
# Backlight
SUBSYSTEM=="backlight", RUN+="/bin/chmod 666 /sys/class/backlight/%k/brightness"

# Uinput (for tablet mode emulation)
KERNEL=="uinput", MODE="0666"

# GPU (amdgpu)
KERNEL=="card*", SUBSYSTEM=="drm", RUN+="/bin/chmod 666 /sys/class/drm/%k/device/power_dpm_force_performance_level /sys/class/drm/%k/device/pp_od_clk_voltage"

# CPU
SUBSYSTEM=="cpu", RUN+="/bin/chmod 666 /sys/devices/system/cpu/amd_pstate/cpb_boost /sys/devices/system/cpu/cpufreq/boost /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu1/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu2/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu3/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu4/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu5/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu6/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu7/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu8/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu9/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu10/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu11/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu12/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu13/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu14/cpufreq/scaling_max_freq /sys/devices/system/cpu/cpu15/cpufreq/scaling_max_freq"
EOF

# 5. Set SDL2 Controller String system-wide (for non-udev apps)
if ! grep -q "SDL_GAMECONTROLLERCONFIG" /etc/environment; then
    echo "Adding SDL_GAMECONTROLLERCONFIG to /etc/environment..."
    echo "SDL_GAMECONTROLLERCONFIG=\"$SDL_STR\"" | sudo tee -a /etc/environment
fi

# 6. Legion Go Accelerometer Orientation Fix (required for auto-rotation)
echo "Setting up accelerometer hwdb rule..."
sudo mkdir -p /etc/udev/hwdb.d
#  ACCEL_MOUNT_MATRIX=0, -1, 0; 1, 0, 0; 0, 0, 1
#  ACCEL_MOUNT_MATRIX=0, 1, 0; -1, 0, 0; 0, 0, 1
cat <<EOF | sudo tee /etc/udev/hwdb.d/99-legion-go-accel.hwdb
sensor:modalias:platform:HID-SENSOR-200073:dmi:*svnLENOVO:pn83E1:*
 ACCEL_MOUNT_MATRIX=1, 0, 0; 0, 1, 0; 0, 0, 1
EOF
sudo systemd-hwdb update
sudo udevadm trigger -v /sys/bus/iio/devices/iio:device0

# 7. Libinput Quirks (prevent input suppression in tablet mode)
echo "Setting up libinput quirks for tablet mode..."
QUIRKS_DIR="/etc/libinput"
sudo mkdir -p "$QUIRKS_DIR"
cat <<EOF | sudo tee "$QUIRKS_DIR/local-overrides.quirks"
# Prevent these input devices from being disabled by libinput when entering tablet mode.

[Volume Keys]
MatchBus=ps2
MatchVendor=0x0001
MatchProduct=0x0001
ModelTabletModeNoSuspend=1

[Legion Controller]
MatchBus=usb
MatchVendor=0x17EF
ModelTabletModeNoSuspend=1
EOF

# 8. Uinput permissions (for virtual SW_TABLET_MODE device)
echo "Setting permissions for /dev/uinput..."
if [ -e "/dev/uinput" ]; then
    sudo chmod 666 /dev/uinput
fi

echo "Permissions and hardware fixes setup complete!"
