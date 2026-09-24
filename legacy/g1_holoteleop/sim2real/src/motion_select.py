# interactive_motion_sender.py
import argparse
import json
import socket
import sys
import time
from typing import List, Tuple, Dict, Any
import yaml
import os
from pathlib import Path
from paths import REAL_G1_ROOT

BANNER = """\
Motion Sender
  - type a number or a name to send
  - press Enter to resend the last choice
  - 'list' : show all options
  - 'r'    : reload YAML
  - '?'    : help
  - 'q'    : quit
"""

def load_yaml_options(path: str) -> Tuple[List[str], Dict[str, Any]]:
    """
    Load YAML and extract unique motion names in display order.
    - motions[].name
    - motion_clips[].name  (ensures 'default' is present if defined here)
    Returns (options, raw_dict)
    """
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    opts: List[str] = []
    seen = set()

    # motion_clips first so 'default' appears at the top if provided there
    for arr_key in ("motion_clips", "motions"):
        arr = data.get(arr_key, []) or []
        for item in arr:
            name = str(item.get("name", "")).strip()
            if name and name not in seen:
                opts.append(name)
                seen.add(name)

    # If neither section provided default, still ensure it shows (optional)
    if "default" not in seen:
        # Not strictly necessary, but many flows expect it
        opts.insert(0, "default")
        seen.add("default")

    return opts, data

def add_runtime_motions(options: List[str], raw: Dict[str, Any], specs: List[str]) -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}
    if not specs:
        return payloads
    motions = raw.setdefault("motions", [])
    seen = set(options)
    for spec in specs:
        if "=" in spec:
            name, path = spec.split("=", 1)
            name = name.strip()
            path = path.strip()
        else:
            path = spec.strip()
            name = Path(path).stem
        if not name or not path:
            raise ValueError(f"Invalid --add-motion value: {spec!r}. Use name=/path/to/file.npz")
        item = {"name": name, "path": path, "start": 0, "end": -1}
        motions.append(item)
        payloads[name] = item
        if name not in seen:
            options.append(name)
            seen.add(name)
    return payloads

def print_menu(options: List[str]):
    print("\n=== Available motions ===")
    width = len(str(len(options)))
    for i, name in enumerate(options, 1):
        print(f"  {str(i).rjust(width)}. {name}")
    print("=========================\n")

def resolve_choice(user_in: str, options: List[str]) -> Tuple[bool, str, str]:
    """
    Resolve user input to a motion name.
    Returns (ok, resolved_name, msg)
    """
    s = user_in.strip()
    if not s:
        return False, "", "empty"

    # direct number
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= len(options):
            return True, options[idx - 1], ""
        return False, "", f"index out of range: {idx}"

    # exact match
    for name in options:
        if s == name:
            return True, name, ""

    # substring match
    matches = [n for n in options if s.lower() in n.lower()]
    if len(matches) == 1:
        return True, matches[0], ""
    elif len(matches) > 1:
        return False, "", f"ambiguous: {matches}"

    return False, "", f"unknown: '{s}'"

def send_udp(name: str, host: str, port: int, sock: socket.socket) -> bool:
    try:
        sock.sendto(name.encode("utf-8"), (host, port))
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] Sent motion '{name}' to udp://{host}:{port}")
        return True
    except Exception as e:
        print(f"[ERROR] send failed: {e}")
        return False

def send_udp_payload(payload: str | Dict[str, Any], host: str, port: int, sock: socket.socket) -> bool:
    text = json.dumps(payload, separators=(",", ":")) if isinstance(payload, dict) else payload
    try:
        sock.sendto(text.encode("utf-8"), (host, port))
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] Sent {text} to udp://{host}:{port}")
        return True
    except Exception as e:
        print(f"[ERROR] send failed: {e}")
        return False

def build_direct_payload(target: str, name: str | None, start: int, end: int) -> str | Dict[str, Any]:
    path = Path(target).expanduser()
    if target.endswith(".npz") or path.exists():
        return {
            "name": name or path.stem,
            "path": str(path),
            "start": int(start),
            "end": int(end),
        }
    return target

def main():
    parser = argparse.ArgumentParser(description="Interactive UDP motion sender")
    parser.add_argument(
        "target",
        nargs="?",
        help="Motion name or .npz path to send immediately, then exit.",
    )
    parser.add_argument("--yaml", required=False, default="config/tracking.yaml",
                        help="YAML config file containing motions & motion_clips. If omitted, built-in example is used.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=28562)
    parser.add_argument("--name", default=None, help="Runtime motion name when target is a .npz path.")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=-1)
    parser.add_argument(
        "--add-motion",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Add a runtime motion path without editing tracking.yaml. Can be repeated.",
    )
    args = parser.parse_args()

    if args.target:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = build_direct_payload(args.target, args.name, args.start, args.end)
        ok = send_udp_payload(payload, args.host, args.port, sock)
        return 0 if ok else 1

    # If no YAML path provided, allow pasting inline later; but we still try to load if present
    yaml_path = args.yaml

    # Load options (with simple retry if file missing)
    options: List[str] = []
    raw: Dict[str, Any] = {}
    runtime_payloads: Dict[str, Dict[str, Any]] = {}
    last_mtime = None
    yp = None

    def try_load():
        nonlocal options, raw, runtime_payloads, last_mtime, yp
        if yaml_path is None:
            # No file provided: fall back to just 'default'
            options = ["default"]
            raw = {}
            runtime_payloads = {}
            last_mtime = None
            print("[INFO] No YAML provided. Only 'default' is available.")
            return

        yp = Path(yaml_path)
        if not yp.is_absolute():
            yp = REAL_G1_ROOT / yp
        if not os.path.exists(yp):
            print(f"[WARN] YAML not found: {yaml_path} — using only 'default'")
            options = ["default"]
            raw = {}
            runtime_payloads = {}
            last_mtime = None
            return

        options, raw = load_yaml_options(str(yp))
        runtime_payloads = add_runtime_motions(options, raw, args.add_motion)
        try:
            last_mtime = os.path.getmtime(yp)
        except Exception:
            last_mtime = None
        print(f"[INFO] Loaded {len(options)} options from {yaml_path}")
        print_menu(options)

    try_load()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(BANNER)

    last_choice = None

    while True:
        try:
            # auto-reload on file change
            if yp and os.path.exists(yp):
                try:
                    mtime = os.path.getmtime(yp)
                    if last_mtime is not None and mtime > last_mtime:
                        try_load()
                except Exception:
                    pass

            prompt = f"Select motion [number/name | Enter:{last_choice or '-'} | list | r | ? | q]: "
            user_in = input(prompt).strip()

            if user_in == "":
                if last_choice:
                    send_udp_payload(runtime_payloads.get(last_choice, last_choice), args.host, args.port, sock)
                else:
                    print("Nothing to resend yet.")
                continue

            if user_in.lower() in ("q", "quit", "exit"):
                print("Bye.")
                break

            if user_in.lower() in ("?", "h", "help"):
                print(BANNER)
                continue

            if user_in.lower() in ("l", "list"):
                print_menu(options)
                continue

            if user_in.lower() == "r":
                try_load()
                continue

            ok, name, msg = resolve_choice(user_in, options)
            if not ok:
                if msg.startswith("ambiguous:"):
                    print(msg)
                else:
                    print(f"[WARN] {msg}. Type 'list' to see options.")
                continue

            if send_udp_payload(runtime_payloads.get(name, name), args.host, args.port, sock):
                last_choice = name

        except KeyboardInterrupt:
            print("\nCtrl-C — quitting.")
            break
        except EOFError:
            print("\nEOF — quitting.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

if __name__ == "__main__":
    main()
