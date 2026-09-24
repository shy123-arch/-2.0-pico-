#!/usr/bin/env python3
"""
Offline evaluation of motion-tracking performance.

Usage
-----
  python eval/eval_metrics.py [--eval-dir data/eval] [--model examples/g1/g1.xml]
                               [--name punch] [--root-body 1] [--fall-thresh 0.3]

For each matched ref+tracking pair (e.g. punch-1.npz / punch-tracking-1.npz) inside
--eval-dir the script:
  1. Loads the reference motion (dof_pos, root_pos, root_rot) from the ref npz.
  2. Runs forward kinematics with Python MuJoCo to obtain reference body positions.
  3. Resamples the tracked body positions (stored at policy frequency) to the
     reference frame rate.
  4. Computes the three metrics per clip:
       Succ      – 1 if root z never drops below --fall-thresh the whole clip
       Eg-mpjpe  – global mean per-joint position error (mm), averaged over all
                   frames and non-world bodies
       Empjpe    – root-relative MPJPE (mm), same averaging

Outputs a per-clip table and per-name aggregate (mean ± std) to stdout,
and optionally saves a CSV to --csv.

Requirements: mujoco (pip install mujoco), numpy, scipy
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np

try:
    import mujoco
except ImportError:
    sys.exit("mujoco Python package not found.  pip install mujoco")

# ── MT joint order (must match bridge.py) ────────────────────────────────────
MT_JOINT_ORDER = [
    "left_hip_pitch_joint",  "left_hip_roll_joint",   "left_hip_yaw_joint",
    "left_knee_joint",        "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint",  "right_hip_yaw_joint",
    "right_knee_joint",       "right_ankle_pitch_joint","right_ankle_roll_joint",
    "waist_yaw_joint",        "waist_roll_joint",       "waist_pitch_joint",
    "left_shoulder_pitch_joint","left_shoulder_roll_joint","left_shoulder_yaw_joint",
    "left_elbow_joint","left_wrist_roll_joint","left_wrist_pitch_joint","left_wrist_yaw_joint",
    "right_shoulder_pitch_joint","right_shoulder_roll_joint","right_shoulder_yaw_joint",
    "right_elbow_joint","right_wrist_roll_joint","right_wrist_pitch_joint","right_wrist_yaw_joint",
]


def _build_joint_map(model) -> dict[str, int]:
    """Return {joint_name: qpos_adr} for all 1-dof joints in the model."""
    mapping = {}
    for j in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j)
        if name and model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE:
            mapping[name] = int(model.jnt_qposadr[j])
    return mapping


def _compute_ref_body_pos(model_path: str, dof_pos: np.ndarray,
                           root_pos: np.ndarray, root_xyzw: np.ndarray
                           ) -> np.ndarray:
    """
    Run forward kinematics for every frame in the reference motion.

    Parameters
    ----------
    model_path : path to the MuJoCo XML
    dof_pos    : (T, ndof) joint angles in MT order
    root_pos   : (T, 3)   root world position
    root_xyzw  : (T, 4)   root quaternion in xyzw

    Returns
    -------
    body_pos : (T, nbody, 3) world body positions
    """
    m = mujoco.MjModel.from_xml_path(model_path)
    d = mujoco.MjData(m)
    joint_map = _build_joint_map(m)

    T = dof_pos.shape[0]
    nbody = m.nbody
    body_pos = np.zeros((T, nbody, 3), dtype=np.float32)

    for t in range(T):
        d.qpos[:] = 0.0
        # Root position and orientation (MuJoCo uses wxyz)
        d.qpos[0:3] = root_pos[t]
        x, y, z, w = root_xyzw[t]
        d.qpos[3:7] = [w, x, y, z]
        # Joint angles
        for i, jname in enumerate(MT_JOINT_ORDER):
            if jname in joint_map:
                d.qpos[joint_map[jname]] = dof_pos[t, i]
        mujoco.mj_kinematics(m, d)
        body_pos[t] = d.xpos.reshape(nbody, 3).astype(np.float32)

    return body_pos


def _load_ref_npz(path: Path):
    """Load a reference motion npz (standard format with dof_pos etc.)."""
    d = np.load(str(path), allow_pickle=True)
    dof_pos   = d["dof_pos"].astype(np.float32)
    root_pos  = d["root_pos"].astype(np.float32)
    root_xyzw = d["root_rot"].astype(np.float32)   # stored as xyzw
    fps = int(d["fps"].item() if isinstance(d["fps"], np.ndarray) else d["fps"])
    return dof_pos, root_pos, root_xyzw, fps


def _load_tracking_npz(path: Path):
    """Load a tracking npz with body_pos (T, nbody, 3) and fps."""
    d = np.load(str(path), allow_pickle=True)
    body_pos = d["body_pos"].astype(np.float32)   # (T, nbody, 3)
    fps = int(d["fps"].item() if isinstance(d["fps"], np.ndarray) else d["fps"])
    return body_pos, fps


def _resample(arr: np.ndarray, src_fps: float, dst_fps: float) -> np.ndarray:
    """Resample (T, ...) array from src_fps to dst_fps via nearest-frame."""
    if src_fps == dst_fps:
        return arr
    T_src = arr.shape[0]
    T_dst = max(1, round(T_src * dst_fps / src_fps))
    src_idx = np.round(np.linspace(0, T_src - 1, T_dst)).astype(int)
    return arr[src_idx]


def _compute_metrics(ref_body_pos: np.ndarray, track_body_pos: np.ndarray,
                     root_body_id: int = 1, succ_thresh: float = 0.3
                     ) -> dict:
    """
    Compute Succ, Eg-mpjpe, Empjpe per paper formulas.

    ref_body_pos   : (T, nbody, 3) — from FK
    track_body_pos : (T, nbody, 3) — from tracking recording (resampled to T)

    Succ  : I(e_i <= theta), where e_i = max_t mean_j ||(track[j]-track[0])-(ref[j]-ref[0])||
            theta = 0.3 m  (eq. 18-19)
    Eg-mpjpe : 1000/(T*J) * sum_t sum_j ||track[j] - ref[j]||  (eq. 20)
    Empjpe   : 1000/(T*J) * sum_t sum_j ||(track[j]-track[0]) - (ref[j]-ref[0])||  (eq. 21)
    """
    T = min(ref_body_pos.shape[0], track_body_pos.shape[0])
    ref   = ref_body_pos[:T]    # (T, nbody, 3)
    track = track_body_pos[:T]

    # Only compare non-world bodies (body 0 is world in MuJoCo)
    ref_j   = ref[:, 1:, :]     # (T, J, 3)
    track_j = track[:, 1:, :]

    # Root position (pelvis = root_body_id; after slicing body 0, index shifts by 1)
    root_idx = root_body_id - 1  # index into *_j arrays
    ref_root   = ref_j[:, root_idx:root_idx+1, :]    # (T, 1, 3)
    track_root = track_j[:, root_idx:root_idx+1, :]

    # Root-relative positions
    ref_rel   = ref_j   - ref_root    # (T, J, 3)
    track_rel = track_j - track_root

    # Succ: max over frames of mean-per-joint root-relative error (eq. 18-19)
    per_frame_err = np.mean(np.linalg.norm(track_rel - ref_rel, axis=-1), axis=-1)  # (T,)
    e_i = per_frame_err.max()
    succ = float(e_i <= succ_thresh)

    # Eg-mpjpe: global MPJPE in mm (eq. 20)
    eg_mpjpe = np.mean(np.linalg.norm(track_j - ref_j, axis=-1)) * 1000.0

    # Empjpe: root-relative MPJPE in mm (eq. 21)
    empjpe = np.mean(np.linalg.norm(track_rel - ref_rel, axis=-1)) * 1000.0

    return {"succ": succ, "eg_mpjpe": eg_mpjpe, "empjpe": empjpe}


def _find_pairs(eval_dir: Path, name_filter: str | None):
    """
    Find all (ref_path, tracking_path) pairs in eval_dir.

    Pairs share the same base name and index, e.g.:
        punch-1.npz  ↔  punch-tracking-1.npz
    """
    pairs = []
    tracking_re = re.compile(r"^(.+)-tracking-(\d+)$")
    ref_re = re.compile(r"^(.+)-(\d+)$")

    tracking_files = {}
    for f in eval_dir.glob("*.npz"):
        m = tracking_re.match(f.stem)
        if m:
            tracking_files[(m.group(1), m.group(2))] = f

    for f in sorted(eval_dir.glob("*.npz")):
        m = ref_re.match(f.stem)
        if not m:
            continue
        base, idx = m.group(1), m.group(2)
        if name_filter and base != name_filter:
            continue
        key = (base, idx)
        if key in tracking_files:
            pairs.append((base, idx, f, tracking_files[key]))

    pairs.sort(key=lambda x: (x[0], int(x[1])))
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eval-dir",    default="data/eval",
                        help="Directory containing eval npz pairs (default: data/eval)")
    parser.add_argument("--model",       default="public/examples/scenes/g1/g1.xml",
                        help="Path to MuJoCo XML model (default: public/examples/scenes/g1/g1.xml)")
    parser.add_argument("--name",        default=None,
                        help="Filter to a specific base name (e.g. punch)")
    parser.add_argument("--root-body",   type=int, default=1,
                        help="Body index of the root/pelvis (default: 1)")
    parser.add_argument("--succ-thresh", type=float, default=0.3,
                        help="Max root-relative mean per-link error threshold for Succ (default: 0.3 m)")
    parser.add_argument("--csv",         default=None,
                        help="Output CSV path (default: data/eval/<name>_results.csv)")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    eval_dir   = (root / args.eval_dir).resolve()
    model_path = (root / args.model).resolve()

    if not eval_dir.is_dir():
        sys.exit(f"eval-dir not found: {eval_dir}")
    if not model_path.is_file():
        sys.exit(f"model not found: {model_path}")

    pairs = _find_pairs(eval_dir, args.name)
    if not pairs:
        sys.exit("No matching ref+tracking pairs found.")

    print(f"Model  : {model_path}")
    print(f"Pairs  : {len(pairs)}")
    print(f"{'Name':<30} {'#':>3}  {'Succ':>5}  {'Eg-mpjpe':>10}  {'Empjpe':>10}")
    print("-" * 65)

    rows = []
    per_name: dict[str, list] = {}

    for base, idx, ref_path, track_path in pairs:
        try:
            dof_pos, root_pos, root_xyzw, ref_fps = _load_ref_npz(ref_path)
            track_body_pos, track_fps = _load_tracking_npz(track_path)
        except Exception as e:
            print(f"  [skip] {base}-{idx}: {e}")
            continue

        # FK for reference
        try:
            ref_body_pos = _compute_ref_body_pos(str(model_path), dof_pos, root_pos, root_xyzw)
        except Exception as e:
            print(f"  [fk error] {base}-{idx}: {e}")
            continue

        # Resample tracking to ref fps
        track_body_resampled = _resample(track_body_pos, track_fps, ref_fps)

        metrics = _compute_metrics(ref_body_pos, track_body_resampled,
                                   root_body_id=args.root_body,
                                   succ_thresh=args.succ_thresh)

        print(f"  {base:<28} {idx:>3}  {metrics['succ']:>5.0f}  "
              f"{metrics['eg_mpjpe']:>10.1f}  {metrics['empjpe']:>10.1f}")

        rows.append({"name": base, "idx": idx,
                     "succ": metrics["succ"],
                     "eg_mpjpe": metrics["eg_mpjpe"],
                     "empjpe": metrics["empjpe"]})
        per_name.setdefault(base, []).append(metrics)

    # Per-name aggregates
    if per_name:
        print("-" * 65)
        print(f"{'Name (mean ± 95%CI)':<30} {'N':>3}  {'Succ':>5}  {'Eg-mpjpe':>10}  {'Empjpe':>10}")
        print("-" * 65)
        for name, mlist in sorted(per_name.items()):
            n      = len(mlist)
            succs  = np.array([m["succ"]     for m in mlist])
            eg_arr = np.array([m["eg_mpjpe"] for m in mlist])
            em_arr = np.array([m["empjpe"]   for m in mlist])
            eg_ci  = 1.96 * eg_arr.std() / np.sqrt(n)
            em_ci  = 1.96 * em_arr.std() / np.sqrt(n)
            print(f"  {name:<28} {n:>3}  "
                  f"{succs.mean():>5.2f}  "
                  f"{eg_arr.mean():>10.3f} (±{eg_ci:.3f})  "
                  f"{em_arr.mean():>10.3f} (±{em_ci:.3f})")

    # Save aggregate summary to eval/results.csv (one row per name)
    if per_name:
        import csv
        csv_path = Path(args.csv) if args.csv else Path(__file__).parent / "results.csv"

        # Load existing rows so we can update in-place
        existing: dict[str, dict] = {}
        if csv_path.exists():
            with csv_path.open(newline="") as f:
                for row in csv.DictReader(f):
                    existing[row["name"]] = row

        for name, mlist in per_name.items():
            n      = len(mlist)
            succs  = np.array([m["succ"]     for m in mlist])
            eg_arr = np.array([m["eg_mpjpe"] for m in mlist])
            em_arr = np.array([m["empjpe"]   for m in mlist])
            eg_ci  = 1.96 * eg_arr.std() / np.sqrt(n)
            em_ci  = 1.96 * em_arr.std() / np.sqrt(n)
            existing[name] = {
                "name":        name,
                "succ":        f"{int(succs.sum())}/{n}",
                "eg_mpjpe":    f"{eg_arr.mean():.3f}",
                "eg_mpjpe_ci": f"{eg_ci:.3f}",
                "empjpe":      f"{em_arr.mean():.3f}",
                "empjpe_ci":   f"{em_ci:.3f}",
            }

        fieldnames = ["name", "succ", "eg_mpjpe", "eg_mpjpe_ci", "empjpe", "empjpe_ci"]
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing.values())
        print(f"\nSummary saved to {csv_path}")


if __name__ == "__main__":
    main()
