#!/usr/bin/env bash
# deploy_pi.sh
#
# Week 4 "Hardware Deployment": configures a Raspberry Pi (or similar
# dual-NIC edge device) as a transparent bump-in-the-wire, then installs
# and starts the VoltGuard IPS engine as a systemd service.
#
# ASSUMPTIONS (adjust to your hardware):
#   - Pi has two ethernet interfaces: eth0 (toward the PLC/field network)
#     and eth1 (toward the SCADA/upstream network). A single onboard NIC
#     Pi needs a USB-ethernet adapter for the second port.
#   - The VoltGuard binary has already been cross-compiled for ARM (see
#     the "Cross-compiling" section below) and is at ./voltguard-ips.
#
# Run this ON THE PI, as root:
#   sudo ./deploy_pi.sh

set -euo pipefail

IFACE_A="eth0"
IFACE_B="eth1"
BRIDGE="br0"
BINARY_SRC="./voltguard-ips"
INSTALL_PATH="/opt/voltguard/voltguard-ips"

echo "[deploy] --- Cross-compiling reminder ---"
echo "  On your build machine (not the Pi):"
echo "    rustup target add armv7-unknown-linux-gnueabihf"
echo "    cargo install cross --git https://github.com/cross-rs/cross"
echo "    cross build --release --target armv7-unknown-linux-gnueabihf"
echo "  Then scp target/armv7-unknown-linux-gnueabihf/release/voltguard-ips to the Pi."
echo ""

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./deploy_pi.sh)"
  exit 1
fi

echo "[deploy] Installing bridge utilities..."
apt-get update -qq
apt-get install -y -qq bridge-utils ebtables iptables-persistent

echo "[deploy] Creating transparent bridge $BRIDGE from $IFACE_A + $IFACE_B..."
ip link add name "$BRIDGE" type bridge
ip link set "$IFACE_A" master "$BRIDGE"
ip link set "$IFACE_B" master "$BRIDGE"

# No IP address on the bridge itself -- a true bump-in-the-wire is invisible
# at Layer 3. Management should happen over a separate dedicated interface
# if you need one.
ip link set "$IFACE_A" up
ip link set "$IFACE_B" up
ip link set "$BRIDGE" up

# Disable STP so the bridge doesn't introduce negotiation delay on an
# industrial link that expects to just be a wire.
brctl stp "$BRIDGE" off

echo "[deploy] Enabling IP forwarding (needed for the bridge's netfilter hooks)..."
sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

echo "[deploy] Redirecting bridged Modbus/TCP traffic (port 502) to the IPS engine..."
# This is what actually makes traffic flow THROUGH voltguard-ips instead of
# just passing straight across the bridge. Adjust the port/protocol to
# match your Week 1 parser's target (502 = standard Modbus/TCP).
ebtables -t broute -A BROUTING -p ipv4 --ip-proto tcp --ip-destination-port 502 -j redirect --redirect-target DROP
iptables -t nat -A PREROUTING -p tcp --dport 502 -j REDIRECT --to-port 8090

echo "[deploy] Installing VoltGuard binary..."
mkdir -p /opt/voltguard
cp "$BINARY_SRC" "$INSTALL_PATH"
chmod +x "$INSTALL_PATH"

echo "[deploy] Installing systemd service..."
cp ./voltguard.service /etc/systemd/system/voltguard.service
systemctl daemon-reload
systemctl enable voltguard.service
systemctl restart voltguard.service

echo "[deploy] Done. Check status with: systemctl status voltguard.service"
echo "[deploy] Check bridge with:        bridge link show"
echo "[deploy] Tail logs with:           journalctl -u voltguard -f"