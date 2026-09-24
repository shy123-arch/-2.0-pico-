# PICO Temperature Telemetry

Robot deploy can send motor temperature telemetry to the PICO app over UDP.
The PICO app should make its own warning decision from the raw temperatures.

## Transport

- Protocol: UDP JSON
- Default port: `13601`
- Default rate: `5 Hz`
- Sender: robot deploy process
- Receiver: PICO app

Example deploy args:

```bash
--pico-telemetry-host 192.168.31.85 \
--pico-telemetry-port 13601 \
--pico-telemetry-rate-hz 5
```

## Payload

```json
{
  "type": "robot_thermal",
  "version": 1,
  "time_ns": 1234567890,
  "step": 123,
  "temperature": {
    "max": 82,
    "joint": "left_knee_joint",
    "index": 3,
    "sensor": 0,
    "pair": [82, 80],
    "top": [
      {
        "index": 0,
        "name": "left_hip_pitch_joint",
        "max": 55,
        "pair": [55, 54]
      }
    ]
  }
}
```

`temperature.max` is the highest value among all reported motor temperature sensors.
Each joint currently reports `pair`, because Unitree low state exposes two temperature values per motor.
`temperature.top` contains only the five hottest joints in descending order.

## Suggested PICO Warning Policy

- `< 80 C`: normal, no visible warning.
- `80-89 C`: passive yellow indicator.
- `90-104 C`: visible warning and short haptic pulse.
- `105-114 C`: strong warning, repeated haptic pulse, tell operator to stop low-posture/high-load motion.
- `>= 115 C`: critical warning, persistent overlay and audio/haptic alert.

Use hysteresis so the UI does not flicker:

- Enter warning at the threshold.
- Clear only after temperature drops at least `5 C` below the threshold.
- Require the condition to last `0.5-1.0 s` before escalating the UI.

For kneeling, squatting, crawling, or deep bending tests, treat knee and ankle motors more conservatively. If a knee motor stays above `100 C` for more than a few seconds, stop the current trial and let the robot cool.

## Current Defaults

`sim2real.sh` sends telemetry to:

```bash
192.168.31.85:13601
```

Override the PICO IP before starting deploy:

```bash
PICO_TELEMETRY_HOST=192.168.31.85 bash sim2real.sh
```
