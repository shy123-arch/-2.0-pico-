import socket
from pathlib import Path


class VideoRecordControlClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 13600):
        self.addr = (str(host), int(port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def send_start(self, session_dir: str | Path) -> None:
        self._send(f"START {Path(session_dir)}")

    def send_stop(self) -> None:
        self._send("STOP")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, msg: str) -> None:
        try:
            self.sock.sendto(msg.encode("utf-8"), self.addr)
        except OSError as exc:
            print(f"[VideoRecordControl][Warning] send failed: {exc}")
