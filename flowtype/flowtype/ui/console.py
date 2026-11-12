"""Phase 1 UI: one status line in the terminal. (Phase 2 replaces this with a PySide6 overlay near the cursor.)"""

import sys
import time


class Console:
    def __init__(self, stream=sys.stdout):
        self.stream = stream

    def status(self, msg: str) -> None:
        self.stream.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.stream.flush()

    def recording(self, handsfree: bool = False) -> None:
        self.status("● recording (hands-free: tap again to stop, Esc to cancel)" if handsfree else "● recording")

    def cancelled(self) -> None:
        self.status("○ cancelled")
