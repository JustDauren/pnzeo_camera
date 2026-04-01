# PNZEO Camera for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Local-only Home Assistant integration for PNZEO W8 cameras (and compatible PPPP/minicam cameras). No cloud, no Chinese servers, full local control.

## Features

- **Live View** — RTSP stream via HA WebRTC (zero latency)
- **PTZ Control** — pan, tilt, zoom, 16 presets, patrol modes
- **IR Night Vision** — toggle on/off
- **Motion Detection** — enable/disable from HA
- **SD Card Recording** — start/stop recording
- **Image Settings** — brightness, contrast sliders
- **Resolution** — switch between 640p/720p/1080p
- **Mirror/Flip** — normal, vertical, horizontal, both
- **Indicator LED** — toggle camera LED
- **Reboot** — restart camera remotely
- **Snapshot** — capture still image
- **Format SD** — format SD card (hidden by default)

## Installation

### HACS (recommended)
1. Open HACS in Home Assistant
2. Click "Custom repositories"
3. Add `https://github.com/JustDauren/pnzeo_camera` as "Integration"
4. Install "PNZEO Camera"
5. Restart Home Assistant

### Manual
Copy `custom_components/pnzeo_camera/` to your HA `config/custom_components/` directory.

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "PNZEO Camera"
3. Choose "Manual" or "Auto-discover"
4. Enter camera IP and credentials (default: admin / 8888)

## Services

| Service | Description |
|---------|-------------|
| `pnzeo_camera.ptz_control` | Pan/tilt/zoom (up, down, left, right, center, zoom_in, zoom_out, patrol_lr, patrol_ud) |
| `pnzeo_camera.goto_preset` | Go to saved position (0-15) |
| `pnzeo_camera.set_preset` | Save current position (0-15) |
| `pnzeo_camera.send_command` | Send raw PPPP command (advanced) |

## Security

This integration works **100% locally** via RTSP and PPPP LAN protocol. No cloud servers are contacted.

**Recommended:** Block all outbound traffic from camera IP on your router to prevent the camera from connecting to Chinese P2P relay servers.

## Compatibility

Tested with:
- PNZEO W8 (Model W8, MTC888 prefix)

Should work with any camera using MTCam HD, minicam, or iWFCam apps (PPPP protocol, MTC/CAM prefix).

## Credits

- Protocol research based on [devbis/pppp_camera](https://github.com/devbis/pppp_camera) and [devbis/aiopppp](https://github.com/devbis/aiopppp)
- PPPP protocol analysis by [Wladimir Palant](https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/) and [Paul Marrapese (DEF CON 28)](https://hacked.camera/)
