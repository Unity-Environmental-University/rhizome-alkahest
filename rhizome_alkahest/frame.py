"""Frame — celestial navigation for observers."""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

import psycopg


@dataclass
class Frame:
    token: str
    who: str
    cwd: str
    truths: list[dict] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return len(self.truths) >= 3

    @staticmethod
    def establish(
        who: str,
        truths: list[tuple[str, str, str]],
        conn: psycopg.Connection | None = None,
        cwd: str | None = None,
    ) -> "Frame":
        """Create a reference frame. Requires three truths to triangulate."""
        if len(truths) < 3:
            raise ValueError(f"Need 3 truths to establish a frame, got {len(truths)}")

        cwd = cwd or os.getcwd()
        short = hashlib.sha1(f"{who}:{time.time()}".encode()).hexdigest()[:8]
        token = f"{who}:{short}"
        truth_dicts = [{"s": s, "p": p, "o": o} for s, p, o in truths]

        frame = Frame(token=token, who=who, cwd=cwd, truths=truth_dicts)

        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO frames (token, who, cwd, truths) VALUES (%s, %s, %s, %s)",
                    (token, who, cwd, json.dumps(truth_dicts)),
                )
            conn.commit()

        return frame

    def __repr__(self):
        status = "ready" if self.ready else f"{len(self.truths)}/3 truths"
        return f"Frame({self.who}:{self.token[-8:]}, {status})"
