#!/usr/bin/env python3
"""
Native messaging host for the UEU dean extension.

Chrome extension → stdout/stdin → this script → rhizome graph.

Protocol: 4-byte little-endian length prefix + JSON body (Chrome native messaging spec).

Accepts:
  { "type": "observe", "subject": "...", "predicate": "...", "object": "...",
    "confidence": 0.7, "phase": "fluid", "note": "..." }
  { "type": "query", "subject": "..." }
  { "type": "ping" }

Responds with JSON.

Frame: a persistent "ueu-dean-extension" frame is established on first run
and reused across messages. Token stored in ~/.edge_frame_dean so it doesn't
collide with the interactive CLI frame.
"""

import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

# Add parent to path so this runs as a standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from rhizome_alkahest.db import connect
from rhizome_alkahest.edge import Edge
from rhizome_alkahest.frame import Frame
from rhizome_alkahest.graph import Graph

FRAME_FILE = Path.home() / ".edge_frame_dean"
WHO = "ueu-dean-extension"
TRUTHS = [
    ("ueu-dean-extension", "observes", "salesforce-case-pages"),
    ("ueu-dean-extension", "writes", "rhizome-alkahest"),
    ("ueu-dean-extension", "purpose", "pattern-learning-for-deans"),
]


def get_or_create_frame() -> Frame:
    conn = connect()

    if FRAME_FILE.exists():
        token = FRAME_FILE.read_text().strip()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT token, who, cwd, truths FROM frames WHERE token = %s",
                (token,),
            )
            row = cur.fetchone()
        if row:
            conn.close()
            return Frame(token=row[0], who=row[1], cwd=row[2], truths=row[3])

    # Create a new frame
    frame = Frame.establish(WHO, TRUTHS, conn=conn, cwd=str(Path.home()))
    FRAME_FILE.write_text(frame.token)
    conn.close()
    return frame


def read_message() -> dict | None:
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    length = struct.unpack("<I", raw_len)[0]
    raw = sys.stdin.buffer.read(length)
    return json.loads(raw.decode("utf-8"))


def write_message(msg: dict):
    encoded = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def handle(msg: dict, graph: Graph) -> dict:
    t = msg.get("type")

    if t == "ping":
        return {"ok": True, "who": WHO}

    if t == "observe":
        try:
            edge = graph.add(
                subject=msg["subject"],
                predicate=msg["predicate"],
                object=msg["object"],
                confidence=float(msg.get("confidence", 0.7)),
                phase=msg.get("phase", "fluid"),
                notes=msg.get("note", ""),
            )
            return {"ok": True, "edge": f"({edge.subject} --{edge.predicate}--> {edge.object})"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if t == "query":
        subject = msg.get("subject", "")
        try:
            edges = graph.about(subject)
            return {
                "ok": True,
                "edges": [
                    {
                        "subject": e.subject,
                        "predicate": e.predicate,
                        "object": e.object,
                        "confidence": e.confidence,
                        "phase": e.phase,
                        "note": e.notes,
                    }
                    for e in edges
                ],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"unknown type: {t}"}


def main():
    try:
        frame = get_or_create_frame()
        graph = Graph(frame)
    except Exception as e:
        write_message({"ok": False, "error": f"frame init failed: {e}"})
        sys.exit(1)

    while True:
        msg = read_message()
        if msg is None:
            break
        response = handle(msg, graph)
        write_message(response)


if __name__ == "__main__":
    main()
