#!/bin/bash

# 1. Create udev rule for Legion Go Controllers to allow non-root HID access
UDEV_RULE_FILE="/etc/udev/rules.d/99-legion-go.rules"

echo "Creating udev rules for Legion Go HID devices..."
cat <<EOF | sudo tee $UDEV_RULE_FILE
# Legion Go Controller HID devices
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6182", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6183", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6184", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6185", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61eb", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61ec", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61ed", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="61ee", MODE="0666"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

# 2. Handle ACPI permissions (acpi_call)
# Note: This needs to be done every boot, or we can use a systemd-tmpfiles rule
echo "Setting permissions for /proc/acpi/call..."
if [ -e "/proc/acpi/call" ]; then
    sudo chmod 666 /proc/acpi/call
else
    echo "Warning: /proc/acpi/call not found. Is acpi_call loaded?"
fi

# 3. RyzenAdj permissions
RYZENADJ_PATH=$(realpath "$(dirname "$0")/bin/ryzenadj")
if [ -f "$RYZENADJ_PATH" ]; then
    echo "Setting SUID bit on ryzenadj..."
    sudo chown root:root "$RYZENADJ_PATH"
    sudo chmod +s "$RYZENADJ_PATH"
fi

echo "Permissions setup complete! You should now be able to run as a normal user."
