#!/bin/bash

# 0. Cleanup Old Versions
echo "Cleaning up old service versions (if any)..."
for svc in legion-buttons.service legion-go-sidebar.service legion-daemon.service; do
    sudo systemctl stop "$svc" 2>/dev/null
    sudo systemctl disable "$svc" 2>/dev/null
    sudo rm -f "/etc/systemd/system/$svc" "/usr/lib/systemd/system/$svc"
done

# 1. Install System Dependencies
echo "Installing system dependencies..."
sudo dnf install -y python3-gobject python3-pip gtk4 libadwaita hidapi kernel-devel akmod-acpi_call acpi_call || true

# 2. Load acpi_call module permanently
echo "Configuring acpi_call module..."
sudo modprobe acpi_call 2>/dev/null
echo "acpi_call" | sudo tee /etc/modules-load.d/acpi_call.conf > /dev/null

# 3. Copy System Files (REQUIRED for Fedora/SELinux)
# Using symlinks to /home/ is blocked by SELinux for system services.
# We MUST delete existing symlinks first or 'cp' will follow them incorrectly!
echo "Setting up system files..."
PROJECT_DIR=$(pwd)
HOME_DIR="$HOME"

# Ensure traversal permissions for the app later (for desktop autostart)
echo "Ensuring system access to project path..."
sudo chmod +x "$HOME_DIR"
sudo chmod +x "$HOME_DIR/code" 2>/dev/null || true
sudo chmod +x "$PROJECT_DIR"

# COPY the setup script
sudo rm -f /usr/local/bin/legion-go-setup.sh
sudo cp -f "$PROJECT_DIR/setup_permissions.sh" /usr/local/bin/legion-go-setup.sh
sudo chmod +x /usr/local/bin/legion-go-setup.sh

# COPY ryzenadj
sudo rm -f /usr/local/bin/ryzenadj
sudo cp -f "$PROJECT_DIR/bin/ryzenadj" /usr/local/bin/ryzenadj
sudo chmod +x /usr/local/bin/ryzenadj

# CRITICAL: Use a REAL FILE for the service unit.
echo "Configuring systemd service..."
sudo rm -f /etc/systemd/system/legion-go-setup.service
sudo cp -f "$PROJECT_DIR/legion-go-setup.service" /etc/systemd/system/legion-go-setup.service
sudo chmod 644 /etc/systemd/system/legion-go-setup.service

# Update the Exec= path in the desktop file for autostart
sed -i "s|Exec=python3 .*|Exec=python3 $PROJECT_DIR/src/main.py|" "$PROJECT_DIR/legion-go-app.desktop"

# Link Autostart (User level)
mkdir -p ~/.config/autostart
ln -sf "$PROJECT_DIR/legion-go-app.desktop" ~/.config/autostart/legion-go-app.desktop

# 4. Install GNOME Shell Extension (System-wide for Lock Screen support)
echo "Installing GNOME Shell extension..."
EXT_UUID="legion-osk@shubu.com"
EXT_PATH="/usr/share/gnome-shell/extensions/$EXT_UUID"
sudo mkdir -p "$EXT_PATH"
sudo cp -f "$PROJECT_DIR/src/keyboard.js" "$EXT_PATH/extension.js"
sudo cp -f "$PROJECT_DIR/src/metadata.json" "$EXT_PATH/metadata.json"
sudo chmod -R 755 "$EXT_PATH"

# 5. Reload and Enable Service
echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable legion-go-setup.service
sudo systemctl restart legion-go-setup.service

# 6. Enable Extension
echo "Enabling extension..."
# We try to enable it for the current user, but system-wide it's already there
gnome-extensions enable "$EXT_UUID" 2>/dev/null || true
# For GDM/Lock screen, being in /usr/share and having session-modes is usually enough if enabled.

echo "--------------------------------------------------"
echo "Installation Complete!"
echo "Permissions and acpi_call are now PERMANENT."
echo "--------------------------------------------------"
echo "Live Dev Workflow:"
echo "1. Change your .py files"
echo "2. Restart the app: pkill -f main.py && python3 src/main.py"
echo "3. If you change setup_permissions.sh: sudo systemctl restart legion-go-setup.service"
