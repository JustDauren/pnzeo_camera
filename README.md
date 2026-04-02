# PNZEO Camera for Home Assistant

Full local control of PNZEO/MTC cameras via PPPP protocol.

## Features

- Auto-discovery of cameras on LAN
- Live video stream (RTSP)
- IR LED / Night vision control
- Indicator LED control
- Motion detection toggle
- SD card recording control
- Brightness & contrast adjustment
- Resolution & mirror mode selection
- Camera reboot & factory reset
- Password change

## How it works

Camera control uses the PPPP protocol (CGI commands over DRW packets).
Cloud P2P server is used **only for port discovery** (one UDP query) —
all actual data stays on your local network.

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click "Integrations" > "+" > "Custom repositories"
3. Add `https://github.com/JustDauren/pnzeo_camera` as "Integration"
4. Install "PNZEO Camera"
5. Restart Home Assistant
6. Go to Settings > Devices > Add Integration > "PNZEO Camera"

### Manual

Copy `custom_components/pnzeo_camera/` to your HA `config/custom_components/` directory.

## Configuration

1. The integration auto-discovers cameras on your network
2. Enter the camera password (default: `8888`)
3. All controls appear automatically

## Supported cameras

- PNZEO W8 (MTC888 prefix)
- Other cameras using libRtMain.so with PPPP protocol

## Security

**Change the default password!** Cameras with default passwords
are accessible to anyone on the internet via cloud relay.
Use the integration's options to change the password.
