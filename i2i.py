"""
I2I — Instance-to-Instance Protocol (Python client)

Implements the I2I/1.0 wire format for plato-tui to communicate with
plato-kernel or other Plato instances. Mirrors the Rust I2I module.

Wire format:
    I2I/1.0 <VERB> <target>
    From: <kind>/<name>@<host>
    To:   <kind>/<name>@<host>
    Nonce: <uuid>
    Timestamp: <iso8601>

    <json-payload>
"""

from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

I2I_VERSION = "I2I/1.0"
I2I_DEFAULT_PORT = 7272  # Default I2I listener port (distinct from MUD port 4040)


class I2IVerb(str, Enum):
    ANNOUNCE = "ANNOUNCE"
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    NOTIFY = "NOTIFY"
    CONSTRAINT_CHECK = "CONSTRAINT_CHECK"
    CONSTRAINT_RESULT = "CONSTRAINT_RESULT"
    TUTOR_JUMP = "TUTOR_JUMP"
    EPISODE_PUSH = "EPISODE_PUSH"
    DISCONNECT = "DISCONNECT"


@dataclass
class InstanceId:
    kind: str          # "kernel" | "tui" | "os" | "agent"
    name: str
    host: str = "localhost"

    def __str__(self) -> str:
        return f"{self.kind}/{self.name}@{self.host}"

    @classmethod
    def parse(cls, s: str) -> "InstanceId":
        """Parse 'kind/name@host' string."""
        host = "localhost"
        if "@" in s:
            kind_name, host = s.rsplit("@", 1)
        else:
            kind_name = s
        if "/" in kind_name:
            kind, name = kind_name.split("/", 1)
        else:
            kind, name = "unknown", kind_name
        return cls(kind=kind, name=name, host=host)

    @classmethod
    def local_tui(cls, name: str) -> "InstanceId":
        return cls(kind="tui", name=name)

    @classmethod
    def local_kernel(cls, name: str) -> "InstanceId":
        return cls(kind="kernel", name=name)


@dataclass
class I2IMessage:
    verb: I2IVerb
    target: str
    from_id: InstanceId
    to_id: InstanceId
    payload: dict = field(default_factory=dict)
    nonce: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    in_reply_to: Optional[str] = None
    version: str = I2I_VERSION

    def to_wire(self) -> str:
        """Serialize to I2I wire format."""
        lines = [
            f"{self.version} {self.verb.value} {self.target}",
            f"From: {self.from_id}",
            f"To: {self.to_id}",
            f"Nonce: {self.nonce}",
            f"Timestamp: {self.timestamp}",
            "",
            json.dumps(self.payload, indent=2),
            "",
        ]
        return "\n".join(lines)

    @classmethod
    def from_wire(cls, s: str) -> "I2IMessage":
        """Parse I2I wire format."""
        lines = s.split("\n")
        it = iter(lines)

        # First line: I2I/1.0 VERB target
        first = next(it, "").strip()
        parts = first.split(" ", 2)
        if len(parts) < 3:
            raise ValueError(f"Malformed I2I header: {first!r}")
        _version, verb_str, target = parts
        verb = I2IVerb(verb_str)

        from_id = InstanceId("unknown", "unknown")
        to_id = InstanceId("unknown", "unknown")
        nonce = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        in_reply_to = None

        # Header fields
        for line in it:
            if line.strip() == "":
                break
            if line.startswith("From: "):
                from_id = InstanceId.parse(line[6:].strip())
            elif line.startswith("To: "):
                to_id = InstanceId.parse(line[4:].strip())
            elif line.startswith("Nonce: "):
                nonce = line[7:].strip()
            elif line.startswith("Timestamp: "):
                timestamp = line[11:].strip()
            elif line.startswith("InReplyTo: "):
                in_reply_to = line[11:].strip()

        # Remaining = JSON payload
        body = "\n".join(it).strip()
        payload = json.loads(body) if body else {}

        return cls(
            verb=verb,
            target=target,
            from_id=from_id,
            to_id=to_id,
            payload=payload,
            nonce=nonce,
            timestamp=timestamp,
            in_reply_to=in_reply_to,
        )

    @classmethod
    def reply(cls, original: "I2IMessage", verb: I2IVerb, payload: dict) -> "I2IMessage":
        """Construct a reply correlated to the original message."""
        return cls(
            verb=verb,
            target=str(original.from_id),
            from_id=original.to_id,
            to_id=original.from_id,
            payload=payload,
            in_reply_to=original.nonce,
        )


class I2IClient:
    """
    Simple synchronous I2I client for plato-tui.

    Sends I2I messages to a plato-kernel over a TCP connection.
    Non-blocking: if the kernel is unreachable, messages are queued in memory
    and the TUI continues running — I2I is advisory, not required.
    """

    def __init__(self, identity: str, kernel_host: str = "localhost", kernel_port: int = I2I_DEFAULT_PORT):
        self.identity = InstanceId.local_tui(identity)
        self.kernel = InstanceId.local_kernel("plato-kernel")
        self.kernel_host = kernel_host
        self.kernel_port = kernel_port
        self._sock: Optional[socket.socket] = None
        self._pending: list[I2IMessage] = []

    def connect(self) -> bool:
        """Attempt to connect to the kernel's I2I listener."""
        try:
            self._sock = socket.create_connection(
                (self.kernel_host, self.kernel_port), timeout=2.0
            )
            self._announce()
            return True
        except OSError:
            self._sock = None
            return False

    def _announce(self):
        """Send ANNOUNCE on connect."""
        msg = I2IMessage(
            verb=I2IVerb.ANNOUNCE,
            target="kernel",
            from_id=self.identity,
            to_id=self.kernel,
            payload={"identity": str(self.identity), "version": I2I_VERSION},
        )
        self._send(msg)

    def send(self, msg: I2IMessage) -> bool:
        """Send a message, queuing it if not connected."""
        if self._sock is None:
            self._pending.append(msg)
            return False
        return self._send(msg)

    def _send(self, msg: I2IMessage) -> bool:
        try:
            wire = msg.to_wire().encode()
            # Prefix with 4-byte length for framing
            length = len(wire).to_bytes(4, "big")
            self._sock.sendall(length + wire)
            return True
        except OSError:
            self._sock = None
            self._pending.append(msg)
            return False

    def flush_pending(self) -> int:
        """Retry sending queued messages. Returns number sent."""
        if not self._pending:
            return 0
        if self._sock is None and not self.connect():
            return 0
        sent = 0
        remaining = []
        for msg in self._pending:
            if self._send(msg):
                sent += 1
            else:
                remaining.append(msg)
        self._pending = remaining
        return sent

    def notify_command(self, command: str, room: str):
        """Notify kernel of a user command (for episode recording, constraint checks)."""
        msg = I2IMessage(
            verb=I2IVerb.NOTIFY,
            target="kernel",
            from_id=self.identity,
            to_id=self.kernel,
            payload={"command": command, "room": room},
        )
        self.send(msg)

    def request_constraint_check(self, command: str, room: str) -> Optional[str]:
        """
        Request a constraint check from the kernel.
        Returns the audit result string, or None if kernel unreachable.
        Blocks briefly for a response; falls back gracefully.
        """
        msg = I2IMessage(
            verb=I2IVerb.CONSTRAINT_CHECK,
            target="constraint-engine",
            from_id=self.identity,
            to_id=self.kernel,
            payload={"command": command, "room": room},
        )
        if not self.send(msg):
            return None
        # Wait up to 1s for response
        try:
            if self._sock:
                self._sock.settimeout(1.0)
                length_bytes = self._sock.recv(4)
                if len(length_bytes) == 4:
                    length = int.from_bytes(length_bytes, "big")
                    data = self._recv_exact(length)
                    resp = I2IMessage.from_wire(data.decode())
                    return resp.payload.get("result", "Allow")
        except OSError:
            pass
        return None

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                break
            buf += chunk
        return buf

    def tutor_jump(self, anchor: str):
        """Request a TUTOR context jump in the kernel for the given anchor."""
        msg = I2IMessage(
            verb=I2IVerb.TUTOR_JUMP,
            target="tutor",
            from_id=self.identity,
            to_id=self.kernel,
            payload={"anchor": anchor},
        )
        self.send(msg)

    def disconnect(self):
        """Send DISCONNECT and close."""
        if self._sock:
            try:
                msg = I2IMessage(
                    verb=I2IVerb.DISCONNECT,
                    target="kernel",
                    from_id=self.identity,
                    to_id=self.kernel,
                    payload={},
                )
                self._send(msg)
                self._sock.close()
            except OSError:
                pass
            finally:
                self._sock = None
