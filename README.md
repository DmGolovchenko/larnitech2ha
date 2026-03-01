# Larnitech Home Assistant Integration

This integration allows you to control Larnitech smart home devices through Home Assistant Core running in Docker.

## Larnitech Local Integration

### Larnitech device types
| Device Type         | Status  | Notes                 |
|---------------------|---------|-----------------------|
| switch              | OK      |                       |
| temperature-sensor  | OK      |                       |
| humidity-sensor     | OK      |                       |
| script              | OK      |                       |
| lamp                | OK      |                       |
| co2-sensor          | OK      |                       |
| motion-sensor       | OK      |                       |
| illumination-sensor | OK      |                       |
| dimmer-lamp         | OK      |                       |
| light-scheme        | OK      |                       |
| rgb-lamp            | OK      |                       |
| blinds              | PARTIAL |                       |
| valve               | OK      |                       |
| leak-sensor         | OK      |                       |
| valve-heating       | OK      |                       |
| conditioner         | OK      |                       |
| ir-transmitter      | IGNORED |                       |
| ir-receiver         | IGNORED |                       |
| door-sensor         | IGNORED |                       |
| virtual             | IGNORED |                       |
| remote-control      | IGNORED |                       |
| rtsp                | IGNORED | ONVIF Cameras ignored |
| com-port            | IGNORED |                       |
| current-sensor      | IGNORED | used for blinds       |

### HACS Installation

1. Navigate to **System** → **Devices & Services** → **Add Integration**
2. Search for "Larnitech" and select the integration
3. Provide the following configuration parameters:
  - **HOST**: IP address of the local Larnitech service (e.g., `192.168.1.100`)
  - **PORT**: Usually `2041`. You can find it in LT Server → General → Server mode → API → websocket port (ensure the
    API is enabled)
  - **API KEY**: You can find it in LT Server → Security → API Access (should be enabled) → Show API key
4. Submit the settings and wait while the integration retrieves the list of devices

### Developer: Local Testing

1. Clone the repository
2. Copy source files to HA config:
   ```bash
   cp -R custom_components/* config/custom_components/
   ```
3. Start the Docker container:
   ```bash
   docker compose up -d
   ```
4. Open http://localhost:8123
5. Complete the basic HA setup: provide home information, username, and password
6. Navigate to **System** → **Devices & Services** → **Add Integration** → Search for "Larnitech"
7. Provide the following configuration parameters:
  - **HOST**: IP address of the local Larnitech service (e.g., `192.168.1.100`)
  - **PORT**: Usually `2041`. You can find it in LT Server → General → Server mode → API → websocket port (ensure the
    API is enabled)
  - **API KEY**: You can find it in LT Server → Security → API Access (should be enabled) → Show API key
8. Submit the settings and wait while the integration retrieves the list of devices, then configure as needed
9. Enable debug logging: **System** → **Devices & Services** → Select "Larnitech" integration → Click the three-dot menu
   at the top right → Enable debug logging (logs will be available in HA UI and `config/home_assistant.log`)
10. You can now test the integration
11. After making code changes, copy the modified files back to the config folder to persist them across Docker container
    restarts:
   ```bash
   cp -R custom_components/* config/custom_components/
   ```

**Useful commands:**

- Restart the integration after file changes:
  ```bash
  docker restart ha_larnitech_dev
  ```
- Stop the integration when done with testing:
  ```bash
  docker stop ha_larnitech_dev
  ```