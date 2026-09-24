import shlex
import os
import signal
import time
from dataclasses import dataclass

from .qt_compat import QProcess, QPushButton


@dataclass
class Runner:
    name: str
    process: QProcess
    stop_button: QPushButton | None = None
    terminal: bool = False
    pid_file: str | None = None


class ProcessManager:
    def __init__(self, owner, log_callback):
        self.owner = owner
        self.log = log_callback
        self.runners: dict[str, Runner] = {}

    def run_once(self, title: str, program: str, args: list[str], cwd: str | None = None) -> None:
        proc = QProcess(self.owner)
        if cwd:
            proc.setWorkingDirectory(cwd)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda p=proc: self._read_process(title, p))
        proc.finished.connect(lambda code, status, p=proc: self._finished(title, p, code, status))
        self.log(title, "")
        self.log(title, f"$ {program} {' '.join(shlex.quote(a) for a in args)}")
        proc.start(program, args)
        if not proc.waitForStarted(3000):
            self.log(title, f"failed to start: {proc.errorString()}")

    def run_long(
        self,
        key: str,
        title: str,
        program: str,
        args: list[str],
        stop_button: QPushButton | None = None,
        cwd: str | None = None,
    ) -> None:
        if key in self.runners:
            self.log(title, "already running.")
            return
        proc = QProcess(self.owner)
        if cwd:
            proc.setWorkingDirectory(cwd)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda p=proc: self._read_process(title, p))
        proc.finished.connect(lambda code, status, p=proc, k=key: self._long_finished(k, title, p, code, status))
        self.runners[key] = Runner(title, proc, stop_button)
        if stop_button is not None:
            stop_button.setEnabled(True)
        self.log(title, "")
        self.log(title, f"$ {program} {' '.join(shlex.quote(a) for a in args)}")
        proc.start(program, args)
        if not proc.waitForStarted(3000):
            self.log(title, f"failed to start: {proc.errorString()}")
            if stop_button is not None:
                stop_button.setEnabled(False)
            self.runners.pop(key, None)

    def run_long_terminal(
        self,
        key: str,
        title: str,
        program: str,
        args: list[str],
        stop_button: QPushButton | None = None,
        cwd: str | None = None,
    ) -> None:
        if key in self.runners:
            self.log(title, "already running.")
            return
        proc = QProcess(self.owner)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda p=proc: self._read_process(title, p))
        proc.finished.connect(lambda code, status, p=proc, k=key: self._long_finished(k, title, p, code, status))
        pid_file = f"/tmp/holoteleop_app_{os.getpid()}_{key}.pid"
        self.runners[key] = Runner(title, proc, stop_button, terminal=True, pid_file=pid_file)
        if stop_button is not None:
            stop_button.setEnabled(True)

        command = self._shell_command(program, args, cwd)
        script = (
            f"echo $$ > {shlex.quote(pid_file)}; "
            f"trap 'rm -f {shlex.quote(pid_file)}' EXIT; "
            f"printf '\\033]0;HoloTeleop {title}\\007'; "
            f"{command}; "
            "code=$?; "
            "echo; "
            f"echo '[HoloTeleop {title}] exited with code' $code; "
            "echo 'Press Enter to close this terminal.'; "
            "read _; "
            "exit $code"
        )
        terminal_args = [
            "-e",
            "bash",
            "-lc",
            script,
        ]
        self.log(title, "")
        self.log(title, "$ x-terminal-emulator " + " ".join(shlex.quote(a) for a in terminal_args))
        proc.start("x-terminal-emulator", terminal_args)
        if not proc.waitForStarted(3000):
            self.log(title, f"failed to start terminal: {proc.errorString()}")
            if stop_button is not None:
                stop_button.setEnabled(False)
            self.runners.pop(key, None)

    def stop(self, key: str) -> None:
        runner = self.runners.get(key)
        if runner is None:
            return
        if runner.terminal:
            self._stop_terminal_runner(runner)
            return
        self.log(runner.name, "stopping with Ctrl+C...")
        runner.process.write(b"\x03")
        runner.process.waitForBytesWritten(500)
        if runner.process.waitForFinished(7000):
            return
        self.log(runner.name, "Ctrl+C timeout; terminating process...")
        runner.process.terminate()
        if not runner.process.waitForFinished(3000):
            self.log(runner.name, "terminate timeout; killing process...")
            runner.process.kill()

    def stop_all(self) -> list[str]:
        names = [runner.name for runner in self.runners.values()]
        for key in list(self.runners):
            self.stop(key)
        return names

    def running_names(self) -> list[str]:
        return [runner.name for runner in self.runners.values()]

    def _read_process(self, title: str, proc: QProcess) -> None:
        data = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        if data:
            for line in data.splitlines():
                self.log(title, line)

    def _shell_command(self, program: str, args: list[str], cwd: str | None = None) -> str:
        parts = []
        if cwd:
            parts.append(f"cd {shlex.quote(cwd)}")
        parts.append(" ".join([shlex.quote(program)] + [shlex.quote(arg) for arg in args]))
        return " && ".join(parts)

    def _stop_terminal_runner(self, runner: Runner) -> None:
        self.log(runner.name, "closing terminal window...")
        pid = self._read_pid_file(runner.pid_file)
        if pid is not None:
            for sig, delay in ((signal.SIGINT, 0.8), (signal.SIGTERM, 0.8), (signal.SIGKILL, 0.0)):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    break
                except PermissionError as exc:
                    self.log(runner.name, f"failed to signal terminal shell pid {pid}: {exc}")
                    break
                if delay:
                    deadline = time.monotonic() + delay
                    while time.monotonic() < deadline:
                        if runner.process.state() == QProcess.ProcessState.NotRunning:
                            return
                        time.sleep(0.05)
            if runner.process.waitForFinished(500):
                return

        runner.process.terminate()
        if runner.process.waitForFinished(1000):
            return
        self.log(runner.name, "terminal close timeout; killing terminal launcher...")
        runner.process.kill()

    def _read_pid_file(self, pid_file: str | None) -> int | None:
        if not pid_file:
            return None
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _finished(self, title: str, proc: QProcess, code: int, status) -> None:
        self._read_process(title, proc)
        status_name = status.name if hasattr(status, "name") else str(int(status))
        self.log(title, f"exited code={code} status={status_name}")
        proc.deleteLater()

    def _long_finished(self, key: str, title: str, proc: QProcess, code: int, status) -> None:
        self._read_process(title, proc)
        runner = self.runners.pop(key, None)
        if runner and runner.stop_button is not None:
            runner.stop_button.setEnabled(False)
        status_name = status.name if hasattr(status, "name") else str(int(status))
        self.log(title, f"exited code={code} status={status_name}")
        proc.deleteLater()
