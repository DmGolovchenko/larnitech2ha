## Larnitech local integration dev sandbox (Home Assistant Core in Docker)

### Run
1) Copy repo
2) docker compose up -d
3) Open http://localhost:8123

### Custom integration path
config/custom_components/larnitech

### Logs
In HA UI:
Settings → System → Logs
Or docker logs:
docker logs -f ha_larnitech_dev

### Add integration
Settings → Devices & services → Add integration → "Larnitech (Local API2)"

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

Testing:
docker compose up -d
docker restart ha_larnitech_dev
docker stop ha_larnitech_dev