#!/usr/bin/env bash
# scripts/setup-mosquitto.sh
# Install mosquitto and configure as a systemd service.
set -euo pipefail

echo "[agentbus] Installing mosquitto..."
sudo apt-get update -qq
sudo apt-get install -y mosquitto mosquitto-clients

echo "[agentbus] Enabling mosquitto systemd service..."
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
sudo systemctl status mosquitto --no-pager

echo "[agentbus] mosquitto broker running on port 1883"
echo "[agentbus] Test: mosquitto_pub -t test -m hello & mosquitto_sub -t test"
