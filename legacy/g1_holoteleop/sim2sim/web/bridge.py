#!/usr/bin/env python3
from __future__ import annotations
"""
web_viewer bridge — serves npz motion data to the browser viewer.

HTTP http://127.0.0.1:8766
  POST /motion  — push npz clip (path or inline)
  POST /load    — load npz from data/ by name
  GET  /list    — list available npz files
  POST /clear   — delete gen_*.npz in data/generated/

WS   ws://127.0.0.1:8765
  ← web viewer connects here; receives "motion" messages
"""

import asyncio
import io
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np

try:
    import websockets
except ImportError:
    raise SystemExit("websockets not found.  pip install websockets")

# ── config ────────────────────────────────────────────────────────────────
WS_HOST   = "127.0.0.1"
WS_PORT   = 8765
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8766

_HERE = Path(__file__).parent
_SIM2REAL_CKPTS = (_HERE / ".." / ".." / "sim2real" / "assets" / "ckpts").resolve()
_WEB_CKPT_TEMPLATE = _HERE / "public" / "examples" / "checkpoints" / "g1" / "tracking_policy_latest.json"
_onnx_cache: dict[str, bytes] = {}
DATA_DIR = _HERE / "data"
for _sub in ("saved", "generated", "dataset", "eval"):
    (DATA_DIR / _sub).mkdir(parents=True, exist_ok=True)
GENERATED_DIR = DATA_DIR / "generated"
SAVED_DIR = DATA_DIR / "saved"

def _data_subdirs():
    return [d for d in DATA_DIR.iterdir() if d.is_dir()]

logging.basicConfig(level=logging.INFO, format="[bridge] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── shared state ──────────────────────────────────────────────────────────
_ws_clients: set = set()
_loop: asyncio.AbstractEventLoop | None = None

# ── joint mapping (Isaac → MT order) ──────────────────────────────────────
ISAAC_JOINT_ORDER = [
    "left_hip_pitch_joint", "right_hip_pitch_joint", "waist_yaw_joint",
    "left_hip_roll_joint",  "right_hip_roll_joint",  "waist_roll_joint",
    "left_hip_yaw_joint",   "right_hip_yaw_joint",   "waist_pitch_joint",
    "left_knee_joint",      "right_knee_joint",
    "left_shoulder_pitch_joint",  "right_shoulder_pitch_joint",
    "left_ankle_pitch_joint",     "right_ankle_pitch_joint",
    "left_shoulder_roll_joint",   "right_shoulder_roll_joint",
    "left_ankle_roll_joint",      "right_ankle_roll_joint",
    "left_shoulder_yaw_joint",    "right_shoulder_yaw_joint",
    "left_elbow_joint",           "right_elbow_joint",
    "left_wrist_roll_joint",      "right_wrist_roll_joint",
    "left_wrist_pitch_joint",     "right_wrist_pitch_joint",
    "left_wrist_yaw_joint",       "right_wrist_yaw_joint",
]
MT_JOINT_ORDER = [
    "left_hip_pitch_joint",  "left_hip_roll_joint",  "left_hip_yaw_joint",
    "left_knee_joint",       "left_ankle_pitch_joint","left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint",  "right_hip_yaw_joint",
    "right_knee_joint",      "right_ankle_pitch_joint","right_ankle_roll_joint",
    "waist_yaw_joint",       "waist_roll_joint",      "waist_pitch_joint",
    "left_shoulder_pitch_joint","left_shoulder_roll_joint","left_shoulder_yaw_joint",
    "left_elbow_joint","left_wrist_roll_joint","left_wrist_pitch_joint","left_wrist_yaw_joint",
    "right_shoulder_pitch_joint","right_shoulder_roll_joint","right_shoulder_yaw_joint",
    "right_elbow_joint","right_wrist_roll_joint","right_wrist_pitch_joint","right_wrist_yaw_joint",
]
_ISAAC_TO_MT = np.array([ISAAC_JOINT_ORDER.index(j) for j in MT_JOINT_ORDER])

# ── data conversion ───────────────────────────────────────────────────────
def _npz_to_standard(data) -> tuple:
    keys = set(data.keys())
    if "dof_pos" in keys:
        dof_pos   = data["dof_pos"].astype(np.float32)
        root_pos  = data["root_pos"].astype(np.float32)
        root_xyzw = data["root_rot"].astype(np.float32)
    elif "joint_pos" in keys and "body_pos_w" in keys:
        joint_pos_isaac = data["joint_pos"].astype(np.float32)
        dof_pos         = joint_pos_isaac[:, _ISAAC_TO_MT]
        root_pos        = data["body_pos_w"][:, 0, :].astype(np.float32)
        root_xyzw       = data["body_quat_w"][:, 0, :].astype(np.float32)
        root_xyzw       = np.concatenate([root_xyzw[:, 1:], root_xyzw[:, :1]], axis=-1)
    elif "joint_pos" in keys and "root_pos" in keys:
        joint_pos_isaac = data["joint_pos"].astype(np.float32)
        root_pos        = data["root_pos"].astype(np.float32)
        root_wxyz       = data["root_rot"].astype(np.float32)
        root_xyzw       = np.concatenate([root_wxyz[:, 1:], root_wxyz[:, :1]], axis=-1)
        dof_pos         = joint_pos_isaac[:, _ISAAC_TO_MT]
    else:
        raise ValueError(f"Unsupported npz format. Keys: {list(keys)}")
    fps = int(data["fps"].item() if isinstance(data["fps"], np.ndarray) else data["fps"])
    return dof_pos, root_pos, root_xyzw, fps

def _npz_file_to_clip(path: str) -> dict:
    d = np.load(path, allow_pickle=True)
    dof_pos, root_pos, root_xyzw, _ = _npz_to_standard(d)
    wxyz = np.concatenate([root_xyzw[:, 3:4], root_xyzw[:, :3]], axis=-1)
    return {"joint_pos": dof_pos.tolist(), "root_pos": root_pos.tolist(), "root_quat": wxyz.tolist()}

# ── WebSocket broadcast ───────────────────────────────────────────────────
async def _broadcast(msg: str):
    if not _ws_clients:
        return
    await asyncio.gather(*[c.send(msg) for c in list(_ws_clients)], return_exceptions=True)

def _push_motion_threadsafe(name: str, clip: dict):
    if _loop:
        asyncio.run_coroutine_threadsafe(
            _broadcast(json.dumps({"type": "motion", "name": name, "clip": clip})), _loop
        )

async def _ws_handler(ws):
    _ws_clients.add(ws)
    log.info(f"Viewer connected ({len(_ws_clients)} total)")
    try:
        await ws.wait_closed()
    finally:
        _ws_clients.discard(ws)
        log.info(f"Viewer disconnected ({len(_ws_clients)} remaining)")

# ── HTTP handler ──────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # /ckpt/<name>/tracking_policy.json
        if self.path.startswith("/ckpt/") and self.path.endswith("/tracking_policy.json"):
            name = self.path[len("/ckpt/"):-len("/tracking_policy.json")]
            self._serve_ckpt_config(name)
            return
        # /ckpt/<name>/policy.onnx
        if self.path.startswith("/ckpt/") and self.path.endswith("/policy.onnx"):
            name = self.path[len("/ckpt/"):-len("/policy.onnx")]
            self._serve_ckpt_onnx(name)
            return
        # /ckpts
        if self.path == "/ckpts":
            self._serve_ckpts_list()
            return
        if self.path == "/list":
            import re
            result = []
            for subdir in _data_subdirs():
                tag = subdir.name
                files = list(subdir.glob("*.npz"))
                if tag == "eval":
                    files = [f for f in files if not re.search(r"-tracking-\d+$", f.stem)]
                files.sort(key=lambda f: f.stem)
                for f in files:
                    result.append({"name": f.stem, "folder": tag})
            body = json.dumps(result).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self._reply(404, b"not found")

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except Exception:
            return self._reply(400, b"invalid json")

        if self.path == "/load":
            name   = body.get("name", "").strip()
            folder = body.get("folder", "generated")
            if not name:
                return self._reply(400, b"name required")
            _folder_map = {d.name: d for d in _data_subdirs()}
            base = _folder_map.get(folder, GENERATED_DIR)
            path = base / f"{name}.npz"
            if not path.exists():
                return self._reply(404, f"not found: {name}".encode())
            try:
                clip = _npz_file_to_clip(str(path))
            except Exception as e:
                return self._reply(500, str(e).encode())
            _push_motion_threadsafe(f"[LOAD] {name}", clip)
            log.info(f"Loaded '{folder}/{name}' via /load")
            self._reply(200, b"ok")

        elif self.path == "/motion":
            name = body.get("name", "loaded")
            if "path" in body:
                try:
                    clip = _npz_file_to_clip(body["path"])
                except Exception as e:
                    return self._reply(500, str(e).encode())
            elif "clip" in body:
                clip = body["clip"]
            else:
                return self._reply(400, b"need 'path' or 'clip'")
            _push_motion_threadsafe(name, clip)
            self._reply(200, b"ok")

        elif self.path == "/save":
            name      = body.get("name", "").strip().rstrip(".").strip()
            source    = body.get("source", "").strip()
            overwrite = bool(body.get("overwrite", False))
            if not name or not source:
                return self._reply(400, b"need 'name' and 'source'")
            src_path  = GENERATED_DIR / f"{source}.npz"
            if not src_path.exists():
                return self._reply(404, f"source not found: {source}".encode())
            safe_name = "".join(c for c in name if c not in r'\/:*?"<>|').strip()
            if not safe_name:
                return self._reply(400, b"invalid name")
            dst_path = SAVED_DIR / f"{safe_name}.npz"
            if dst_path.exists() and not overwrite:
                return self._reply(409, b"exists")
            import shutil
            shutil.copy2(src_path, dst_path)
            log.info(f"Saved '{safe_name}.npz' to data/saved/")
            self._reply(200, json.dumps({"saved": safe_name}).encode())

        elif self.path == "/clear":
            files = list(GENERATED_DIR.glob("gen_*.npz"))
            for f in files:
                try:
                    f.unlink()
                except Exception:
                    pass
            log.info(f"Cleared {len(files)} gen_*.npz files")
            self._reply(200, json.dumps({"deleted": len(files)}).encode())

        else:
            self._reply(404, b"not found")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── checkpoint serving ────────────────────────────────────────────
    def _serve_ckpts_list(self):
        if not _SIM2REAL_CKPTS.exists():
            self._reply(404, b"sim2real checkpoints not found")
            return
        dirs = sorted(
            [d.name for d in _SIM2REAL_CKPTS.iterdir() if d.is_dir() and (d / "policy.onnx").exists()],
            reverse=True,
        )
        body = json.dumps([{"name": n} for n in dirs]).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _serve_ckpt_config(self, name: str):
        ckpt_dir = _SIM2REAL_CKPTS / name
        if not (ckpt_dir / "policy.onnx").exists():
            self._reply(404, f"checkpoint {name} not found".encode())
            return
        try:
            with open(_WEB_CKPT_TEMPLATE) as f:
                config = json.load(f)
        except Exception as e:
            self._reply(500, str(e).encode())
            return

        # Override ONNX path
        if "onnx" not in config or not isinstance(config["onnx"], dict):
            config["onnx"] = {}
        config["onnx"]["path"] = f"http://127.0.0.1:8766/ckpt/{name}/policy.onnx"

        # Override obs_config for sim2real checkpoint (1590-dim)
        FS = [0, 1, 2, 3, 4, -1, -2, -4, -8, -12, -16]  # future_steps
        HS = [0, 1, 2, 3, 4, 8, 12, 16, 20]             # history/pos/vel steps
        config["obs_config"] = {
            "policy": [
                {"name": "BootIndicator"},
                {"name": "TrackingCommandObsRaw", "future_steps": FS},
                {"name": "ComplianceFlagObs"},
                {"name": "TargetJointPosObs", "future_steps": FS},
                {"name": "TargetRootZObs", "future_steps": FS},
                {"name": "TargetProjectedGravityBObs", "future_steps": FS},
                {"name": "RootAngVelBHistory", "history_steps": HS},
                {"name": "ProjectedGravityBHistory", "history_steps": HS},
                {"name": "JointPos", "pos_steps": HS},
                {"name": "JointVel", "vel_steps": HS},
                {"name": "PrevActions", "history_steps": 8},
            ]
        }

        body = json.dumps(config).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _serve_ckpt_onnx(self, name: str):
        if name in _onnx_cache:
            data = _onnx_cache[name]
        else:
            path = _SIM2REAL_CKPTS / name / "policy.onnx"
            if not path.exists():
                self._reply(404, b"not found")
                return
            data = path.read_bytes()
            if (path.parent / "policy.onnx.data").exists():
                try:
                    import onnx
                    model = onnx.load(str(path))
                    data = model.SerializeToString()
                except ImportError:
                    log.warning("onnx not available, serving un-merged model")
            _onnx_cache[name] = data
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _reply(self, code: int, body: bytes):
        self.send_response(code)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def log_message(self, *_):
        pass

def _run_http():
    srv = HTTPServer((HTTP_HOST, HTTP_PORT), _Handler)
    log.info(f"HTTP  http://{HTTP_HOST}:{HTTP_PORT}  (/load /motion /list)")
    srv.serve_forever()

# ── main ──────────────────────────────────────────────────────────────────
async def main():
    global _loop
    _loop = asyncio.get_running_loop()
    threading.Thread(target=_run_http, daemon=True).start()
    try:
        async with websockets.serve(_ws_handler, WS_HOST, WS_PORT):
            log.info(f"WS    ws://{WS_HOST}:{WS_PORT}")
            log.info("Ready.")
            await asyncio.Future()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    asyncio.run(main())
