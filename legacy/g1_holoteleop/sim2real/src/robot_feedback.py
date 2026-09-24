import subprocess
from pathlib import Path
from typing import Optional


class RobotAudioFeedback:
    def __init__(
        self,
        enabled: bool = True,
        net: Optional[str] = None,
        unitree_tool: Optional[str] = None,
    ):
        self.enabled = bool(enabled)
        self.net = str(net or "")
        self.unitree_tool = Path(unitree_tool).expanduser() if unitree_tool else None

    def record_start(self):
        return self._run_unitree_tool("start")

    def record_stop(self):
        return self._run_unitree_tool("stop")

    def say(self, text: str) -> bool:
        text = str(text or "").strip()
        if not text:
            return False
        return self._run_unitree_tool("say", text)

    def _unitree_tool_available(self) -> bool:
        return bool(self.net) and self.unitree_tool is not None and self.unitree_tool.exists()

    def _run_unitree_tool(self, mode: str, *args: str) -> bool:
        if not self.enabled or not self._unitree_tool_available():
            return False
        try:
            subprocess.Popen(
                [str(self.unitree_tool), self.net, mode, *[str(arg) for arg in args]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False
