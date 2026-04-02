#!/bin/bash
# =============================================================================
# PNZEO Camera — Local Relay Setup Script
# =============================================================================
# Run this ONCE on Pi5 (via SSH addon) to make the camera work without internet.
#
# What it does:
# 1. Makes Pi5 intercept camera's cloud traffic via iptables DNAT
# 2. Blocks camera's internet access (all other outbound traffic dropped)
# 3. Camera thinks it talks to cloud — but everything stays on Pi5
#
# Prerequisites:
# - Camera and Pi5 on the same LAN
# - Camera's default gateway changed to Pi5 IP (via app or DHCP)
# - SSH addon installed (a0d7b954_ssh)
#
# Usage:
#   ./setup_local_relay.sh CAMERA_IP PI5_IP
#   Example: ./setup_local_relay.sh 192.168.31.132 192.168.31.100
# =============================================================================

set -e

CAMERA_IP="${1:?Usage: $0 CAMERA_IP PI5_IP}"
PI5_IP="${2:?Usage: $0 CAMERA_IP PI5_IP}"

# Cloud P2P servers that the camera tries to reach (hardcoded in firmware)
CLOUD_SERVERS=(
    "182.92.131.196"
    "54.191.3.239"
    "54.186.48.247"
)
CLOUD_PORT=32100

# Proprietary server
PROP_SERVER="113.46.133.13"
PROP_PORT=19000

echo "=== PNZEO Local Relay Setup ==="
echo "Camera IP:  $CAMERA_IP"
echo "Pi5 IP:     $PI5_IP"
echo ""

# Step 1: Enable IP forwarding (needed for DNAT to work)
echo "[1/4] Enabling IP forwarding..."
sysctl -w net.ipv4.ip_forward=1
# Make persistent
if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf 2>/dev/null; then
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi

# Step 2: DNAT — redirect camera's cloud traffic to Pi5 local relay
echo "[2/4] Setting up iptables DNAT rules..."
for SERVER in "${CLOUD_SERVERS[@]}"; do
    # Remove old rule if exists
    iptables -t nat -D PREROUTING -s "$CAMERA_IP" -d "$SERVER" -p udp --dport "$CLOUD_PORT" \
        -j DNAT --to-destination "$PI5_IP:$CLOUD_PORT" 2>/dev/null || true
    # Add rule
    iptables -t nat -A PREROUTING -s "$CAMERA_IP" -d "$SERVER" -p udp --dport "$CLOUD_PORT" \
        -j DNAT --to-destination "$PI5_IP:$CLOUD_PORT"
    echo "  DNAT $SERVER:$CLOUD_PORT -> $PI5_IP:$CLOUD_PORT"
done

# Proprietary server redirect
iptables -t nat -D PREROUTING -s "$CAMERA_IP" -d "$PROP_SERVER" -p udp --dport "$PROP_PORT" \
    -j DNAT --to-destination "$PI5_IP:$PROP_PORT" 2>/dev/null || true
iptables -t nat -A PREROUTING -s "$CAMERA_IP" -d "$PROP_SERVER" -p udp --dport "$PROP_PORT" \
    -j DNAT --to-destination "$PI5_IP:$PROP_PORT"
echo "  DNAT $PROP_SERVER:$PROP_PORT -> $PI5_IP:$PROP_PORT"

# Step 3: Allow DNAT'ed traffic, block everything else from camera
echo "[3/4] Blocking camera internet access..."
# Allow established connections (for DNAT return traffic)
iptables -D FORWARD -s "$CAMERA_IP" -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
iptables -A FORWARD -s "$CAMERA_IP" -m state --state ESTABLISHED,RELATED -j ACCEPT
# Allow traffic to Pi5 (local)
iptables -D FORWARD -s "$CAMERA_IP" -d "$PI5_IP" -j ACCEPT 2>/dev/null || true
iptables -A FORWARD -s "$CAMERA_IP" -d "$PI5_IP" -j ACCEPT
# Drop all other forwarded traffic from camera
iptables -D FORWARD -s "$CAMERA_IP" -j DROP 2>/dev/null || true
iptables -A FORWARD -s "$CAMERA_IP" -j DROP
echo "  Camera internet BLOCKED (only local relay allowed)"

# Step 4: Verify
echo "[4/4] Verifying..."
echo ""
echo "Active DNAT rules for camera:"
iptables -t nat -L PREROUTING -n | grep "$CAMERA_IP" || echo "  (none found — check manually)"
echo ""
echo "Forward rules for camera:"
iptables -L FORWARD -n | grep "$CAMERA_IP" || echo "  (none found — check manually)"
echo ""

echo "=== Setup Complete ==="
echo ""
echo "NEXT STEPS:"
echo "1. Change camera's default gateway to $PI5_IP"
echo "   (via MTCam HD app → Camera Settings → Network → Gateway)"
echo "   OR set up DHCP on Pi5 for camera's MAC address"
echo ""
echo "2. Reboot the camera (power cycle or via app)"
echo ""
echo "3. Camera will register with local relay on Pi5"
echo "   Check HA logs for: 'Camera registered: uid=...'"
echo ""
echo "4. All controls (IR, brightness, etc.) will work through local relay"
echo "   No internet required for camera anymore!"
echo ""
echo "To UNDO: iptables -t nat -F && iptables -F FORWARD"
