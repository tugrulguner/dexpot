"""Parent-owned connection turns; no worker-held shared lock or request handoff."""

from __future__ import annotations

import socket
import threading
from time import monotonic, sleep
from typing import Any


class GILAcceptTurns:
    def __init__(self, context: Any, workers: int) -> None:
        self.context = context
        self.workers = workers
        self.parents: dict[int, Any] = {}
        self.peers: dict[int, Any] = {}
        self.cursor = 0
        self.pending: tuple[int, Any] | None = None
        self.pending_since = 0.0
        self.outstanding: dict[int, Any] = {}

    def drop(self, slot: int) -> None:
        self.outstanding.pop(slot, None)
        if self.pending is not None and self.pending[0] == slot:
            self.pending = None
            self.cursor = (slot + 1) % self.workers
        for channels in (self.parents, self.peers):
            channel = channels.pop(slot, None)
            if channel is not None:
                channel.close()

    def new_channel(self, slot: int) -> Any:
        self.drop(slot)
        parent, peer = self.context.Pipe(duplex=True)
        try:
            self.parents[slot] = parent
            self.peers[slot] = peer
        except BaseException:
            self.drop(slot)
            parent.close()
            peer.close()
            raise
        return peer

    def parent_started(self, slot: int) -> None:
        self.peers[slot].close()

    def child_started(self, keep: Any) -> None:
        # Forked siblings must not keep each other's channel endpoints alive.
        for channel in (*self.parents.values(), *self.peers.values()):
            if channel is not keep:
                channel.close()

    def _acknowledge(self, slot: int, channel: Any) -> bool:
        try:
            message = channel.recv_bytes(maxlength=1)
        except (EOFError, OSError):
            self.drop(slot)
            return False
        if message not in (b"D", b"T"):
            self.drop(slot)
            return False
        self.outstanding.pop(slot, None)
        return True

    def step(self, processes: list[Any]) -> None:
        for slot, channel in tuple(self.outstanding.items()):
            if self.pending is not None and self.pending[0] == slot:
                continue
            if channel is not self.parents.get(slot) or not processes[slot].is_alive():
                self.drop(slot)
            elif channel.poll():
                self._acknowledge(slot, channel)
        if self.pending is not None:
            slot, channel = self.pending
            if channel is not self.parents.get(slot) or not processes[slot].is_alive():
                self.drop(slot)
            elif channel.poll(0.05):
                if self._acknowledge(slot, channel):
                    self.pending = None
                    self.cursor = (slot + 1) % self.workers
            elif monotonic() - self.pending_since >= 1.0:
                # A living but unresponsive worker must not freeze its peers.
                # Keep its single outstanding grant until acknowledgement;
                # never build an unbounded command backlog behind it.
                self.pending = None
                self.cursor = (slot + 1) % self.workers
            return
        for offset in range(self.workers):
            slot = (self.cursor + offset) % self.workers
            process = processes[slot]
            channel = self.parents.get(slot)
            if (
                channel is None
                or slot in self.outstanding
                or not process.is_alive()
                or not process._dexpot_ready.is_set()
            ):
                continue
            try:
                channel.send_bytes(b"A")
            except (EOFError, OSError):
                self.drop(slot)
                continue
            self.outstanding[slot] = channel
            self.pending = (slot, channel)
            self.pending_since = monotonic()
            return
        sleep(0.05)

    @staticmethod
    def accept(
        listener: socket.socket, channel: Any, stopping: threading.Event
    ) -> tuple[socket.socket, Any]:
        while not stopping.is_set():
            if not channel.poll(0.1):
                continue
            try:
                if channel.recv_bytes(maxlength=1) != b"A":
                    break
                try:
                    connection = listener.accept()
                except TimeoutError:
                    channel.send_bytes(b"T")
                    raise
                try:
                    channel.send_bytes(b"D")
                except (EOFError, OSError):
                    connection[0].close()
                    break
                return connection
            except (EOFError, OSError) as exc:
                if isinstance(exc, TimeoutError):
                    raise
                break
        stopping.set()
        raise TimeoutError("accept coordinator stopped")

    def close(self) -> None:
        for slot in list(self.parents):
            self.drop(slot)
