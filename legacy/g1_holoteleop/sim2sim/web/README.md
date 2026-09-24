# Web Viewer

Browser-based MuJoCo + ONNX viewer for G1 tracking policy.

## Quick start

```bash
cd HoloTeleop/sim2sim/web
npm install
```

### Terminal 1 — bridge (serves sim2real checkpoints & motion data)

```bash
conda activate mview
python bridge.py
```

### Terminal 2 — dev server

```bash
npm run dev
```

Open `http://localhost:3000`.

## Checkpoints

The bridge auto-discovers checkpoints from `../../sim2real/assets/ckpts/`.
Select one from the Policy dropdown — the bridge serves the ONNX model
(merging external data on-the-fly) and generates the matching obs_config.

## Load motion

- **With bridge**: files from `data/` directory appear in the Load dropdown.
- **Without bridge**: upload `.npz` directly or use the built-in motion presets.

## Architecture

- `bridge.py` — HTTP/WS server, checkpoint serving, npz format conversion
- `src/simulation/main.js` — MuJoCo WASM + Three.js renderer + policy loop
- `src/simulation/policyRunner.js` — ONNX inference + observation pipeline
- `src/simulation/observationHelpers.js` — observation modules (matches sim2real)
- `public/examples/` — G1 scene, built-in checkpoint, motion clips
