"""macOS-compatible Timer class.

Uses time.monotonic() fallback instead of linuxfd.timerfd().
Drop-in replacement for sim2real's common.utils.Timer.
"""

import select
import time

try:
    import linuxfd
except ImportError:
    linuxfd = None


class Timer:
    """Accurate loop rate control.

    Uses Linux timerfd when available, falls back to monotonic sleep
    scheduling on macOS / non-Linux platforms.
    """

    def __init__(self, interval: float) -> None:
        self._interval = float(interval)
        self._next_tick = time.monotonic() + self._interval
        self.__epl = None
        self.__tfd = None
        if linuxfd is not None and hasattr(select, "epoll"):
            self.__epl, self.__tfd = self._create_timerfd(self._interval)

    @staticmethod
    def _create_timerfd(interval: float):
        tfd = linuxfd.timerfd(rtc=True, nonBlocking=True)
        tfd.settime(interval, interval)
        epl = select.epoll()
        epl.register(tfd.fileno(), select.EPOLLIN)
        return epl, tfd

    def sleep(self) -> None:
        if self.__epl is None or self.__tfd is None:
            now = time.monotonic()
            remaining = self._next_tick - now
            if remaining > 0:
                time.sleep(remaining)
                self._next_tick += self._interval
            else:
                missed = int(max(-remaining, 0.0) / self._interval) + 1
                self._next_tick += missed * self._interval
            return
        events = self.__epl.poll(-1)
        for fd, event in events:
            if fd == self.__tfd.fileno() and event & select.EPOLLIN:
                self.__tfd.read()
