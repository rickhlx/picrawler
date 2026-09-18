#!/bin/bash
# PiCrawler Control Skill — One-click install script
# Install all dependencies and deploy the skill on Raspberry Pi

set -e

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

# 6. Enable speaker (I2S)
echo "[Optional] Enabling I2S speaker..."
cd ~/robot-hat
sudo bash i2samp.sh 2>/dev/null || echo "   Skipped (can be run manually later)"

echo ""
echo "============================================"
echo " Installation complete!"
echo ""
echo "Usage:"
echo "  python3 ~/picrawler-control/scripts/pc.py --help"
echo ""
echo "Deploy to OpenClaw:"
echo "  cp -r ~/picrawler-control ~/.npm-global/lib/node_modules/openclaw/skills/"
echo "============================================"
