#!/usr/bin/env python3

import argparse
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XML = REPO_ROOT / "sim2real" / "assets" / "g1" / "g1.xml"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "pico_records"
DEFAULT_GMR_DIR = REPO_ROOT / "data" / "gmr_records"

XR_BODY_JOINT_NAMES = [
    "Pelvis",
    "Left_Hip",
    "Right_Hip",
    "Spine1",
    "Left_Knee",
    "Right_Knee",
    "Spine2",
    "Left_Ankle",
    "Right_Ankle",
    "Spine3",
    "Left_Foot",
    "Right_Foot",
    "Neck",
    "Left_Collar",
    "Right_Collar",
    "Head",
    "Left_Shoulder",
    "Right_Shoulder",
    "Left_Elbow",
    "Right_Elbow",
    "Left_Wrist",
    "Right_Wrist",
    "Left_Hand",
    "Right_Hand",
]

XR_BODY_EDGES = [
    ("Pelvis", "Spine1"),
    ("Spine1", "Spine2"),
    ("Spine2", "Spine3"),
    ("Spine3", "Neck"),
    ("Neck", "Head"),
    ("Spine3", "Left_Collar"),
    ("Left_Collar", "Left_Shoulder"),
    ("Left_Shoulder", "Left_Elbow"),
    ("Left_Elbow", "Left_Wrist"),
    ("Left_Wrist", "Left_Hand"),
    ("Spine3", "Right_Collar"),
    ("Right_Collar", "Right_Shoulder"),
    ("Right_Shoulder", "Right_Elbow"),
    ("Right_Elbow", "Right_Wrist"),
    ("Right_Wrist", "Right_Hand"),
    ("Pelvis", "Left_Hip"),
    ("Left_Hip", "Left_Knee"),
    ("Left_Knee", "Left_Ankle"),
    ("Left_Ankle", "Left_Foot"),
    ("Pelvis", "Right_Hip"),
    ("Right_Hip", "Right_Knee"),
    ("Right_Knee", "Right_Ankle"),
    ("Right_Ankle", "Right_Foot"),
]

XROBOT_TO_MUJOCO = np.array(
    [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
    dtype=np.float64,
)


def _read_str_list(npz, key: str) -> list[str]:
    if key not in npz:
        return []
    out = []
    for value in npz[key].tolist():
        if isinstance(value, bytes):
            out.append(value.decode("utf-8"))
        else:
            out.append(str(value))
    return out


def _latest_npz(record_dir: Path, prefix: str) -> Path:
    paths = sorted(record_dir.glob(f"{prefix}_*.npz"), key=lambda p: p.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"No {prefix}_*.npz files found in {record_dir}")
    return paths[-1]


def _sorted_npz(record_dir: Path, prefix: str) -> list[Path]:
    return sorted(record_dir.glob(f"{prefix}_*.npz"))


def _infer_pair(path: Path) -> Path | None:
    name = path.name
    if name.startswith("pico_raw_"):
        return path.parent.parent / "gmr_records" / name.replace("pico_raw_", "gmr_mt_", 1)
    if name.startswith("gmr_mt_"):
        return path.parent.parent / "pico_records" / name.replace("gmr_mt_", "pico_raw_", 1)
    return None


def _frame_times_from_ns(timestamps_ns: np.ndarray, fallback_fps: float, speed: float) -> np.ndarray:
    timestamps_ns = np.asarray(timestamps_ns, dtype=np.float64).reshape(-1)
    if timestamps_ns.shape[0] > 1:
        t = (timestamps_ns - float(timestamps_ns[0])) * 1e-9
        if np.all(np.isfinite(t)) and np.all(np.diff(t) >= 0):
            return t / float(speed)
    return np.arange(timestamps_ns.shape[0], dtype=np.float64) / float(fallback_fps) / float(speed)


def _raw_motion(path: Path, transform_xrobot: bool) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as npz:
        poses = np.asarray(npz["raw_body_poses"], dtype=np.float64)
        recv_ns = np.asarray(npz["raw_recv_ns"], dtype=np.int64)
    if poses.ndim != 3 or poses.shape[1:] != (24, 7):
        raise ValueError(f"Expected raw_body_poses shape (T, 24, 7), got {poses.shape}")

    pos = poses[:, :, :3].copy()
    if transform_xrobot:
        pos = pos @ XROBOT_TO_MUJOCO.T
    return pos, recv_ns


def _align_raw_for_raw_only(raw_pos: np.ndarray) -> np.ndarray:
    pos = raw_pos.copy()
    pos -= pos[0:1, 0:1, :]
    pos[:, :, 2] -= np.nanmin(pos[:, :, 2])
    return pos


def _align_raw_to_gmr(raw_pos: np.ndarray, qpos: np.ndarray) -> np.ndarray:
    pos = raw_pos.copy()
    raw_pelvis0 = pos[0, 0].copy()
    gmr_root0 = qpos[0, 0:3].copy()
    offset = np.zeros(3, dtype=np.float64)
    offset[:2] = gmr_root0[:2] - raw_pelvis0[:2]
    offset[2] = -float(np.nanmin(pos[0, :, 2]))
    pos += offset.reshape(1, 1, 3)
    return pos


def _gmr_motion(path: Path) -> tuple[np.ndarray, list[str], np.ndarray, float, np.ndarray | None, np.ndarray | None]:
    with np.load(path, allow_pickle=False) as npz:
        if "gmr_qpos" in npz:
            qpos = np.asarray(npz["gmr_qpos"], dtype=np.float64)
            recv_ns = np.asarray(npz["gmr_recv_ns"], dtype=np.int64)
            joint_names = _read_str_list(npz, "dof_joint_names") or _read_str_list(npz, "joint_names")
        elif "root_pos" in npz and "root_rot" in npz and "dof_pos" in npz:
            root_pos = np.asarray(npz["root_pos"], dtype=np.float64)
            root_rot_xyzw = np.asarray(npz["root_rot"], dtype=np.float64)
            dof_pos = np.asarray(npz["dof_pos"], dtype=np.float64)
            root_quat_wxyz = root_rot_xyzw[:, [3, 0, 1, 2]]
            qpos = np.concatenate([root_pos, root_quat_wxyz, dof_pos], axis=-1)
            recv_ns = np.asarray(npz["gmr_recv_ns"], dtype=np.int64) if "gmr_recv_ns" in npz else np.arange(qpos.shape[0], dtype=np.int64)
            joint_names = _read_str_list(npz, "joint_names")
        else:
            raise KeyError("GMR/MT file must contain gmr_qpos or root_pos/root_rot/dof_pos.")
        fps = float(np.asarray(npz["fps"]).reshape(-1)[0]) if "fps" in npz else 50.0
        aligned_raw_indices = np.asarray(npz["aligned_raw_indices"], dtype=np.int64) if "aligned_raw_indices" in npz else None
        aligned_gmr_indices = np.asarray(npz["aligned_gmr_indices"], dtype=np.int64) if "aligned_gmr_indices" in npz else None
    if qpos.ndim != 2 or qpos.shape[1] != 36:
        raise ValueError(f"Expected GMR qpos shape (T, 36), got {qpos.shape}")
    return qpos, joint_names, recv_ns, fps, aligned_raw_indices, aligned_gmr_indices


def _add_raw_bodies_to_xml(xml_path: Path) -> Path:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    compiler = root.find("compiler")
    if compiler is not None:
        compiler.set("meshdir", str((xml_path.parent / "meshes").resolve()))

    worldbody = root.find("worldbody")
    if worldbody is None:
        raise ValueError("MuJoCo XML has no worldbody.")

    for name in XR_BODY_JOINT_NAMES:
        rgba = "0.2 0.55 1.0 1"
        if name.startswith("Left"):
            rgba = "0.1 0.8 0.25 1"
        elif name.startswith("Right"):
            rgba = "1.0 0.35 0.2 1"
        elif name in ("Pelvis", "Head"):
            rgba = "1.0 0.9 0.15 1"
        body = ET.SubElement(worldbody, "body", {"name": f"raw_{name}", "mocap": "true", "pos": "0 0 0"})
        ET.SubElement(body, "geom", {"type": "sphere", "size": "0.035", "rgba": rgba, "contype": "0", "conaffinity": "0"})

    tmp = tempfile.NamedTemporaryFile("wb", suffix=".xml", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tree.write(tmp, encoding="utf-8", xml_declaration=False)
    finally:
        tmp.close()
    return tmp_path


def _raw_only_model_xml() -> str:
    joint_geoms = []
    for name in XR_BODY_JOINT_NAMES:
        rgba = "0.2 0.55 1.0 1"
        if name.startswith("Left"):
            rgba = "0.1 0.8 0.25 1"
        elif name.startswith("Right"):
            rgba = "1.0 0.35 0.2 1"
        elif name in ("Pelvis", "Head"):
            rgba = "1.0 0.9 0.15 1"
        joint_geoms.append(
            f'<body name="raw_{name}" mocap="true" pos="0 0 0">'
            f'<geom type="sphere" size="0.035" rgba="{rgba}" contype="0" conaffinity="0"/>'
            "</body>"
        )
    return f"""
<mujoco model="pico_raw_replay">
  <option timestep="0.02"/>
  <asset>
    <texture name="grid" type="2d" builtin="checker" width="512" height="512" rgb1="0.34 0.36 0.38" rgb2="0.22 0.24 0.26"/>
    <material name="grid" texture="grid" texrepeat="8 8" reflectance="0.03"/>
  </asset>
  <visual>
    <headlight ambient="0.45 0.45 0.45" diffuse="0.55 0.55 0.55" specular="0.15 0.15 0.15"/>
    <rgba haze="0.82 0.88 0.95 1"/>
    <map znear="0.01" zfar="50"/>
    <global azimuth="140" elevation="-20"/>
  </visual>
  <statistic center="0 0 1.1" extent="2.4"/>
  <worldbody>
    <light name="key" pos="0 -3 5" dir="0 1 -1" diffuse="0.85 0.85 0.85"/>
    <geom name="floor" type="plane" size="8 8 0.01" material="grid"/>
    {"".join(joint_geoms)}
  </worldbody>
</mujoco>
"""


def _raw_mocap_ids(model, mujoco) -> list[int]:
    ids = []
    for name in XR_BODY_JOINT_NAMES:
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, f"raw_{name}")
        if body_id < 0:
            raise ValueError(f"Raw body raw_{name} not found.")
        mocap_id = int(model.body_mocapid[body_id])
        if mocap_id < 0:
            raise ValueError(f"Body raw_{name} is not a mocap body.")
        ids.append(mocap_id)
    return ids


def _model_joint_order(model, mujoco) -> tuple[int, list[tuple[str, int]]]:
    free_qpos_adr = None
    hinge_joints = []
    for joint_id in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
        jtype = int(model.jnt_type[joint_id])
        qpos_adr = int(model.jnt_qposadr[joint_id])
        if jtype == int(mujoco.mjtJoint.mjJNT_FREE):
            free_qpos_adr = qpos_adr
        elif jtype == int(mujoco.mjtJoint.mjJNT_HINGE):
            hinge_joints.append((name, qpos_adr))
    if free_qpos_adr is None:
        raise ValueError("Model has no free joint for root qpos.")
    return free_qpos_adr, hinge_joints


def _apply_gmr_frame(model, data, mujoco, frame: np.ndarray, source_joint_names: list[str], hinge_joints, free_qpos_adr: int) -> None:
    data.qpos[free_qpos_adr : free_qpos_adr + 7] = frame[:7]
    source_idx = {name: i for i, name in enumerate(source_joint_names)}
    for i, (joint_name, qpos_adr) in enumerate(hinge_joints):
        if source_joint_names:
            src = source_idx.get(joint_name)
            if src is None:
                continue
            data.qpos[qpos_adr] = frame[7 + src]
        elif i < frame.shape[0] - 7:
            data.qpos[qpos_adr] = frame[7 + i]
    mujoco.mj_forward(model, data)


def _update_raw_mocap(data, raw_mocap_ids: list[int], raw_pos: np.ndarray, frame_idx: int) -> None:
    for joint_idx, mocap_id in enumerate(raw_mocap_ids):
        data.mocap_pos[mocap_id] = raw_pos[frame_idx, joint_idx]


def _draw_raw_edges(viewer, mujoco, raw_pos: np.ndarray, frame_idx: int) -> None:
    if not hasattr(viewer, "user_scn") or viewer.user_scn is None:
        return
    scene = viewer.user_scn
    scene.ngeom = 0
    name_to_idx = {name: i for i, name in enumerate(XR_BODY_JOINT_NAMES)}
    identity = np.eye(3, dtype=np.float32).reshape(-1)
    rgba = np.array([0.1, 0.85, 1.0, 0.42], dtype=np.float32)
    for a, b in XR_BODY_EDGES:
        if scene.ngeom >= scene.maxgeom:
            return
        geom = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            geom,
            mujoco.mjtGeom.mjGEOM_CAPSULE,
            np.array([0.008, 0.0, 0.0], dtype=np.float32),
            np.zeros(3, dtype=np.float32),
            identity,
            rgba,
        )
        mujoco.mjv_connector(
            geom,
            mujoco.mjtGeom.mjGEOM_CAPSULE,
            0.008,
            raw_pos[frame_idx, name_to_idx[a]].astype(np.float64),
            raw_pos[frame_idx, name_to_idx[b]].astype(np.float64),
        )
        scene.ngeom += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay PICO raw and online GMR records in MuJoCo.")
    parser.add_argument(
        "record",
        nargs="?",
        default=None,
        help="Optional pico_raw_*.npz/gmr_mt_*.npz path, 1-based index, or negative index from the end.",
    )
    parser.add_argument("--raw-record", type=str, default=None, help="Path to pico_raw_*.npz.")
    parser.add_argument("--gmr-record", type=str, default=None, help="Path to gmr_mt_*.npz.")
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Record index from --list-records. Positive is 1-based; negative counts from the end, e.g. -1 latest.",
    )
    parser.add_argument("--list-records", action="store_true", help="List available records for the selected mode and exit.")
    parser.add_argument("--mode", choices=["raw", "gmr", "both"], default="both")
    parser.add_argument("--xml", type=str, default=str(DEFAULT_XML), help="MuJoCo G1 XML path.")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier.")
    parser.add_argument("--fps", type=float, default=None, help="Override playback fps.")
    parser.add_argument("--start", type=int, default=0, help="Start frame.")
    parser.add_argument("--end", type=int, default=-1, help="End frame, exclusive. -1 means all.")
    parser.add_argument("--loop", action="store_true", help="Loop playback.")
    parser.add_argument(
        "--raw-no-transform",
        action="store_true",
        help="Show raw PICO positions in their original coordinate frame.",
    )
    return parser.parse_args()


def _record_list_for_mode(mode: str) -> list[Path]:
    if mode == "gmr":
        return _sorted_npz(DEFAULT_GMR_DIR, "gmr_mt")

    raw_paths = _sorted_npz(DEFAULT_RAW_DIR, "pico_raw")
    if mode == "raw":
        return raw_paths

    return [p for p in raw_paths if (_infer_pair(p) is not None and _infer_pair(p).exists())]


def _print_record_list(mode: str) -> None:
    records = _record_list_for_mode(mode)
    if not records:
        print(f"No records found for mode={mode}.")
        return
    print(f"Records for mode={mode}:")
    for i, path in enumerate(records, start=1):
        pair = _infer_pair(path)
        suffix = ""
        if mode == "both" and pair is not None:
            suffix = f"  + {pair.name}"
        print(f"{i:4d}  {path.name}{suffix}")


def _resolve_index_record(mode: str, index: int) -> Path:
    records = _record_list_for_mode(mode)
    if not records:
        raise FileNotFoundError(f"No records found for mode={mode}")
    if index == 0:
        raise IndexError("Record index must not be 0. Use 1 for first or -1 for latest.")
    resolved = index - 1 if index > 0 else len(records) + index
    if resolved < 0 or resolved >= len(records):
        raise IndexError(f"Record index {index} out of range -{len(records)}..-1 or 1..{len(records)} for mode={mode}")
    return records[resolved]


def _resolve_records(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    raw_path = Path(args.raw_record).expanduser() if args.raw_record else None
    gmr_path = Path(args.gmr_record).expanduser() if args.gmr_record else None

    record_arg = args.record
    if args.index is not None:
        record_arg = str(_resolve_index_record(args.mode, int(args.index)))
    elif record_arg is not None:
        try:
            record_index = int(str(record_arg))
        except ValueError:
            record_index = None
        if record_index is not None:
            record_arg = str(_resolve_index_record(args.mode, record_index))

    if record_arg:
        path = Path(record_arg).expanduser()
        if path.name.startswith("pico_raw_"):
            raw_path = raw_path or path
            gmr_path = gmr_path or _infer_pair(path)
        elif path.name.startswith("gmr_mt_"):
            gmr_path = gmr_path or path
            raw_path = raw_path or _infer_pair(path)
        else:
            raise ValueError("record must be pico_raw_*.npz or gmr_mt_*.npz")

    if raw_path is None and args.mode in ("raw", "both"):
        raw_path = _latest_npz(DEFAULT_RAW_DIR, "pico_raw")
    if gmr_path is None and args.mode in ("gmr", "both"):
        if raw_path is not None:
            gmr_path = _infer_pair(raw_path)
        if gmr_path is None or not gmr_path.exists():
            gmr_path = _latest_npz(DEFAULT_GMR_DIR, "gmr_mt")

    if args.mode in ("raw", "both") and (raw_path is None or not raw_path.exists()):
        raise FileNotFoundError(f"Raw record not found: {raw_path}")
    if args.mode in ("gmr", "both") and (gmr_path is None or not gmr_path.exists()):
        raise FileNotFoundError(f"GMR record not found: {gmr_path}")
    return raw_path, gmr_path


def main() -> None:
    args = parse_args()
    if args.list_records:
        _print_record_list(args.mode)
        return
    if args.speed <= 0:
        raise ValueError("--speed must be > 0.")

    raw_path, gmr_path = _resolve_records(args)
    xml_path = Path(args.xml).expanduser()

    try:
        import mujoco
        import mujoco.viewer
    except ImportError as exc:
        raise ImportError("mujoco is required. Run this from the sim2real uv environment.") from exc

    raw_pos = raw_times_ns = None
    qpos = gmr_times_ns = source_joint_names = None
    aligned_raw_indices = aligned_gmr_indices = None
    fps = 50.0
    if args.mode in ("raw", "both"):
        raw_pos, raw_times_ns = _raw_motion(raw_path, transform_xrobot=not args.raw_no_transform)
    if args.mode in ("gmr", "both"):
        qpos, source_joint_names, gmr_times_ns, fps, aligned_raw_indices, aligned_gmr_indices = _gmr_motion(gmr_path)
    if args.fps is not None:
        fps = float(args.fps)

    total_frames = raw_pos.shape[0] if args.mode == "raw" else qpos.shape[0]
    if args.mode == "both":
        if (
            aligned_raw_indices is not None
            and aligned_gmr_indices is not None
            and aligned_raw_indices.size > 0
            and aligned_raw_indices.size == aligned_gmr_indices.size
        ):
            valid = (
                (aligned_raw_indices >= 0)
                & (aligned_raw_indices < raw_pos.shape[0])
                & (aligned_gmr_indices >= 0)
                & (aligned_gmr_indices < qpos.shape[0])
            )
            aligned_raw_indices = aligned_raw_indices[valid]
            aligned_gmr_indices = aligned_gmr_indices[valid]
            total_frames = aligned_raw_indices.shape[0]
        else:
            aligned_raw_indices = None
            aligned_gmr_indices = None
            total_frames = min(raw_pos.shape[0], qpos.shape[0])
    start = max(0, int(args.start))
    end = total_frames if int(args.end) < 0 else min(total_frames, int(args.end))
    if start >= end:
        raise ValueError(f"Invalid frame range start={start}, end={end}, total={total_frames}")

    if args.mode == "both" and aligned_raw_indices is not None and aligned_gmr_indices is not None:
        raw_select = aligned_raw_indices[start:end]
        gmr_select = aligned_gmr_indices[start:end]
        raw_pos = raw_pos[raw_select]
        raw_times_ns = raw_times_ns[raw_select]
        qpos = qpos[gmr_select]
        gmr_times_ns = gmr_times_ns[gmr_select]
        print(f"Alignment: using {end - start} seq-matched frames from aligned_raw_indices/aligned_gmr_indices")
    elif raw_pos is not None:
        raw_pos = raw_pos[start:end]
        raw_times_ns = raw_times_ns[start:end]
    if args.mode == "both" and aligned_raw_indices is None and qpos is not None:
        qpos = qpos[start:end]
        gmr_times_ns = gmr_times_ns[start:end]
    elif args.mode != "both" and qpos is not None:
        qpos = qpos[start:end]
        gmr_times_ns = gmr_times_ns[start:end]
    if args.mode == "raw":
        raw_pos = _align_raw_for_raw_only(raw_pos)
    elif args.mode == "both":
        raw_pos = _align_raw_to_gmr(raw_pos, qpos)

    timing_ns = raw_times_ns if args.mode == "raw" else gmr_times_ns
    if args.mode == "both" and raw_times_ns is not None:
        timing_ns = raw_times_ns[:end - start]
    frame_times = _frame_times_from_ns(timing_ns, fallback_fps=fps, speed=args.speed)

    combined_xml = None
    try:
        if args.mode == "raw":
            model = mujoco.MjModel.from_xml_string(_raw_only_model_xml())
        elif args.mode == "both":
            combined_xml = _add_raw_bodies_to_xml(xml_path)
            model = mujoco.MjModel.from_xml_path(str(combined_xml))
        else:
            model = mujoco.MjModel.from_xml_path(str(xml_path))
        data = mujoco.MjData(model)
        if args.mode == "raw":
            free_qpos_adr, hinge_joints = None, []
        else:
            free_qpos_adr, hinge_joints = _model_joint_order(model, mujoco)
        raw_mocap_ids = _raw_mocap_ids(model, mujoco) if args.mode in ("raw", "both") else []

        print(f"Mode: {args.mode}")
        if raw_path is not None:
            print(f"Raw: {raw_path}")
        if gmr_path is not None:
            print(f"GMR: {gmr_path}")
        print(f"frames={end - start}, fps~={fps:.2f}, speed={args.speed:.2f}, loop={args.loop}")
        print("Close the MuJoCo viewer or press Ctrl+C to exit.")

        frame_idx = 0
        start_time = time.perf_counter()
        try:
            try:
                viewer_ctx = mujoco.viewer.launch_passive(
                    model,
                    data,
                    show_left_ui=False,
                    show_right_ui=False,
                )
            except TypeError:
                viewer_ctx = mujoco.viewer.launch_passive(model, data)

            with viewer_ctx as viewer:
                viewer.cam.distance = 3.2
                viewer.cam.elevation = -45
                viewer.cam.azimuth = 140
                while viewer.is_running():
                    if args.mode in ("raw", "both"):
                        _update_raw_mocap(data, raw_mocap_ids, raw_pos, frame_idx)
                    if args.mode in ("gmr", "both"):
                        _apply_gmr_frame(model, data, mujoco, qpos[frame_idx], source_joint_names, hinge_joints, free_qpos_adr)
                    else:
                        mujoco.mj_forward(model, data)
                    if args.mode in ("raw", "both"):
                        _draw_raw_edges(viewer, mujoco, raw_pos, frame_idx)
                    if args.mode in ("gmr", "both"):
                        viewer.cam.lookat[:] = data.qpos[free_qpos_adr : free_qpos_adr + 3]
                    else:
                        viewer.cam.lookat[:] = raw_pos[frame_idx, 0]
                    viewer.sync()

                    frame_idx += 1
                    if frame_idx >= end - start:
                        if args.loop:
                            frame_idx = 0
                            start_time = time.perf_counter()
                        else:
                            break

                    target_time = start_time + frame_times[frame_idx]
                    delay = target_time - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
        except KeyboardInterrupt:
            pass
    finally:
        if combined_xml is not None:
            try:
                combined_xml.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    main()
