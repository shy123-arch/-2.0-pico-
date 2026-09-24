# G1 original baseline

## What this snapshot is

- Source workspace: `F:\molospace\HoloTeleop-deploy\HoloTeleop`
- Snapshot date: 2026-09-24
- Target robot: Unitree G1
- XR device: PICO through XRoboToolkit
- Motion retargeting: GMR `xrobot -> unitree_g1`
- Robot transport: Unitree SDK 2 / CycloneDDS
- Purpose in this repository: immutable reference for the Tianyi 2.0 rewrite

The snapshot lives at [`legacy/g1_holoteleop`](legacy/g1_holoteleop). No file in
that directory is used as the Tianyi robot driver.

## Code-only archival policy

The source tree contained roughly 1.1 GB of generated data, policy checkpoints,
recordings and duplicated meshes. The public baseline keeps the source code,
configuration, shell scripts, documentation, URDF/XML descriptors and checkpoint
metadata, but excludes bulky or generated artifacts:

- `*.onnx`, `*.onnx.data`, `*.pt`, `*.npz`
- recordings and generated video
- runtime logs and output folders
- G1 mesh directories duplicated by the simulator and web viewer
- generated web motion sample JSON files
- virtual environments, caches and `node_modules`

The excluded files remain untouched in the original local workspace. Their
absence means this archived baseline is for source comparison and is not a
standalone runnable G1 release.

## Version marker

The first commit is tagged `g1-original-baseline`. Later Tianyi work must be
placed outside `legacy/g1_holoteleop` so the baseline remains reviewable.

