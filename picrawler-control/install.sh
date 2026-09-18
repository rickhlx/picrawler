#!/bin/bash
# PiCrawler Control Skill — One-click install script
# Install all dependencies and deploy the skill on Raspberry Pi

set -e

# Everything is cloned under ~ and the service unit points at ~/picrawler, so
# under sudo it would all land in /root. The steps that need root use sudo.
if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, not with sudo." >&2
    exit 1
fi

echo "============================================"
echo " PiCrawler Control Skill Installation"
echo "============================================"

# 1. Update system
echo "[1/5] Updating system packages..."
sudo apt update && sudo apt upgrade -y

# 2. Install Python dependencies
echo "[2/5] Installing Python tools..."
sudo apt install -y git python3-pip python3-setuptools python3-smbus

# 3. Install robot-hat
echo "[3/5] Installing robot-hat..."
cd ~
if [ ! -d "robot-hat" ]; then
    git clone -b 2.5.x https://github.com/rickhlx/robot-hat.git
    cd robot-hat && sudo python3 install.py
else
    echo "   robot-hat already exists, skipping"
fi

# 4. Install vilib
echo "[4/5] Installing vilib..."
cd ~
if [ ! -d "vilib" ]; then
    git clone https://github.com/sunfounder/vilib.git --depth 1
    cd vilib && sudo python3 install.py
else
    echo "   vilib already exists, skipping"
fi

# 5. Install picrawler
echo "[5/5] Installing picrawler..."
cd ~
if [ ! -d "picrawler" ]; then
    git clone https://github.com/rickhlx/picrawler.git
    sudo pip3 install ~/picrawler --break-system-packages
else
    echo "   picrawler already exists, skipping"
fi

# Restore the servo calibration saved in the repo (make cali-pull), unless this
# Pi already has offsets of its own. The examples run under sudo, so robot_hat
# reads them from root's home.
CALI_PI=/root/.config/.picrawler.config
CALI_REPO="$HOME/picrawler/calibration/picrawler.config"
if sudo grep -qs picrawler_servo_offset_list "$CALI_PI"; then
    echo "   Servo calibration already present, keeping it"
elif [ -f "$CALI_REPO" ]; then
    sudo mkdir -p "$(dirname "$CALI_PI")"
    sudo cp "$CALI_REPO" "$CALI_PI"
    echo "   Restored servo calibration from $CALI_REPO"
fi

# 6. Enable speaker (I2S)
echo "[Optional] Enabling I2S speaker..."
cd ~/robot-hat
sudo bash i2samp.sh 2>/dev/null || echo "   Skipped (can be run manually later)"

# 7. Install the Petronilo voice assistant as a systemd service
echo "[Service] Installing petronilo.service..."
PICRAWLER_DIR="$HOME/picrawler"
# the unit file hardcodes the author's checkout path; point it at this one
sed "s#/home/ricardo/picrawler#${PICRAWLER_DIR}#g" \
    "$PICRAWLER_DIR/examples/petronilo.service" \
    | sudo tee /etc/systemd/system/petronilo.service > /dev/null
# the service runs as root with HOME=/root, so the Piper/Vosk models must be there
for models in .piper_models .vosk_models; do
    if [ -d "$HOME/$models" ]; then
        sudo cp -r "$HOME/$models" /root/
    fi
done
sudo systemctl daemon-reload
if [ -f "$PICRAWLER_DIR/examples/secret.py" ]; then
    sudo systemctl enable --now petronilo
else
    # starting without API keys would just crash-loop until they exist
    sudo systemctl enable petronilo
    echo "   examples/secret.py not found: service enabled but not started."
    echo "   Add your API keys, then: sudo systemctl start petronilo"
fi

echo ""
echo "============================================"
echo " Installation complete!"
echo ""
echo "Usage:"
echo "  python3 ~/picrawler-control/scripts/pc.py --help"
echo ""
echo "Voice assistant service:"
echo "  journalctl -u petronilo -f"
echo "  sudo systemctl restart petronilo"
echo ""
echo "Deploy to OpenClaw:"
echo "  cp -r ~/picrawler-control ~/.npm-global/lib/node_modules/openclaw/skills/"
echo "============================================"
