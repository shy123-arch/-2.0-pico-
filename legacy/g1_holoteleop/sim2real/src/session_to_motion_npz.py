import argparse
from pathlib import Path

import numpy as np


def _as_str_array(values) -> np.ndarray:
    names = []
    for value in np.asarray(values).tolist():
        if isinstance(value, (bytes, np.bytes_)):
            names.append(value.decode("utf-8"))
        else:
            names.append(str(value))
    return np.asarray(names)


def _quat_wxyz_to_xyzw(quat_wxyz: np.ndarray) -> np.ndarray:
    quat_wxyz = np.asarray(quat_wxyz, dtype=np.float32)
    if quat_wxyz.ndim != 2 or quat_wxyz.shape[1] != 4:
        raise ValueError(f"Expected quaternion shape [T, 4], got {quat_wxyz.shape}")
    return quat_wxyz[:, [1, 2, 3, 0]].astype(np.float32)


def _infer_fps(timestamp_ns: np.ndarray | None) -> np.int32:
    if timestamp_ns is None or len(timestamp_ns) < 2:
        return np.int32(50)
    timestamp_ns = np.asarray(timestamp_ns, dtype=np.int64)
    dt = np.diff(timestamp_ns).astype(np.float64) * 1e-9
    dt = dt[np.isfinite(dt) & (dt > 0.0)]
    if dt.size == 0:
        return np.int32(50)
    return np.int32(round(1.0 / float(np.median(dt))))


def _load_source(session_dir: Path, source: str) -> dict[str, np.ndarray]:
    if source == "reference":
        path = session_dir / "reference.npz"
        with np.load(path, allow_pickle=False) as data:
            required = ("root_pos", "root_quat_wxyz", "dof_pos", "joint_names")
            missing = [key for key in required if key not in data]
            if missing:
                raise KeyError(f"{path} missing required keys: {missing}")
            timestamp_ns = data["timestamp_ns"] if "timestamp_ns" in data else None
            return {
                "root_pos": np.asarray(data["root_pos"], dtype=np.float32),
                "root_rot": _quat_wxyz_to_xyzw(data["root_quat_wxyz"]),
                "dof_pos": np.asarray(data["dof_pos"], dtype=np.float32),
                "joint_names": _as_str_array(data["joint_names"]),
                "timestamp_ns": timestamp_ns,
                "source_file": np.asarray(str(path)),
            }

    if source == "state":
        path = session_dir / "state.npz"
        with np.load(path, allow_pickle=False) as data:
            required = ("root_pos", "root_quat_wxyz", "qj_isaac", "isaac_joint_names")
            missing = [key for key in required if key not in data]
            if missing:
                raise KeyError(f"{path} missing required keys: {missing}")
            timestamp_ns = data["timestamp_ns"] if "timestamp_ns" in data else None
            return {
                "root_pos": np.asarray(data["root_pos"], dtype=np.float32),
                "root_rot": _quat_wxyz_to_xyzw(data["root_quat_wxyz"]),
                "dof_pos": np.asarray(data["qj_isaac"], dtype=np.float32),
                "joint_names": _as_str_array(data["isaac_joint_names"]),
                "timestamp_ns": timestamp_ns,
                "source_file": np.asarray(str(path)),
            }

    raise ValueError(f"Unsupported source: {source}")


def convert_session(session_dir: Path, source: str, output: Path | None, output_is_dir: bool = False) -> Path:
    session_dir = session_dir.expanduser().resolve()
    if not session_dir.is_dir():
        raise NotADirectoryError(session_dir)

    motion = _load_source(session_dir, source)
    frame_count = motion["root_pos"].shape[0]
    if motion["root_rot"].shape[0] != frame_count or motion["dof_pos"].shape[0] != frame_count:
        raise ValueError(
            "Frame count mismatch: "
            f"root_pos={motion['root_pos'].shape[0]}, "
            f"root_rot={motion['root_rot'].shape[0]}, "
            f"dof_pos={motion['dof_pos'].shape[0]}"
        )

    if output is None:
        output = session_dir / f"{source}_motion.npz"
    else:
        output = output.expanduser()
        if output_is_dir or output.is_dir():
            output = output / f"{source}_motion.npz"
    output.parent.mkdir(parents=True, exist_ok=True)

    timestamp_ns = motion["timestamp_ns"]
    fps = _infer_fps(timestamp_ns)
    save_kwargs = {
        "fps": fps,
        "root_pos": motion["root_pos"].astype(np.float32),
        "root_rot": motion["root_rot"].astype(np.float32),
        "dof_pos": motion["dof_pos"].astype(np.float32),
        "joint_names": motion["joint_names"],
        "source_session": np.asarray(str(session_dir)),
        "source_file": motion["source_file"],
    }
    if timestamp_ns is not None:
        save_kwargs["timestamp_ns"] = np.asarray(timestamp_ns, dtype=np.int64)

    np.savez(output, **save_kwargs)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a HoloTeleop VLA session reference/state npz to motion_select-compatible mt npz."
    )
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--source", choices=("reference", "state", "both"), default="reference")
    parser.add_argument("--output", type=Path, default=None, help="Output .npz path, or output directory for --source both.")
    args = parser.parse_args()

    sources = ("reference", "state") if args.source == "both" else (args.source,)
    for source in sources:
        output = convert_session(args.session_dir, source, args.output, output_is_dir=args.source == "both")
        with np.load(output, allow_pickle=False) as data:
            frames = int(data["root_pos"].shape[0])
            fps = int(np.asarray(data["fps"]).reshape(-1)[0])
        print(f"[session_to_motion_npz] {source}: {output} | frames={frames}, fps={fps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
