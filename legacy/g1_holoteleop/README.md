# HoloTeleop

Local workspace for PICO/GMR teleoperation, sim2sim validation, and robot deploy helpers.

Main folders:

```text
app/       Qt helper app
sim2real/  runtime code
sim2sim/   macOS & web deployment
  macos/   Python macOS compat layer
  web/     browser-based MuJoCo + ONNX viewer
training/  policy training, evaluation, and export code
teleop_ws/ external GitHub dependencies, ignored by this repo
```

Start with [`SETUP.md`](SETUP.md) for environment setup and runtime commands.

Useful notes:

- [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md): high-level technical report for the G1 teleoperation tracking approach
- [`docs/current_plan.md`](docs/current_plan.md): current G1 teleoperation and motion-tracking plan
- [`docs/DATA_COLLECTION_AND_EXPORT.md`](docs/DATA_COLLECTION_AND_EXPORT.md): PICO/GMR data collection and motion export
- [`benchmarks/g1_tracking/docs/EVALUATION.md`](benchmarks/g1_tracking/docs/EVALUATION.md):
  tracker and dataset evaluation commands
- [`docs/MODEL_CONFIG.md`](docs/MODEL_CONFIG.md): current tracker model size and parameter count
- [`docs/NETWORK_IP_SWITCHING.md`](docs/NETWORK_IP_SWITCHING.md): router/hotspot IP switching checklist
- [`docs/OBSBOT_TINY2.md`](docs/OBSBOT_TINY2.md): OBSBOT Tiny2 gimbal camera integration
- [`docs/PICO_TEMPERATURE_TELEMETRY.md`](docs/PICO_TEMPERATURE_TELEMETRY.md): motor-temperature telemetry sent to the PICO app
