"""Frame commands: iam, true."""

import hashlib
import json
import os
import sys
import time

from .db import connect
from .frame_pointer import frame_dir, read_token, write_token, git_context


def cmd_iam(args):
    speaks_as = []
    speaks_for = []
    in_for = False
    for a in args:
        if a == "--for":
            in_for = True
        elif a == "--as":
            in_for = False
        elif in_for:
            speaks_for.append(a)
        else:
            speaks_as.append(a)

    if speaks_as and speaks_for:
        who = "+".join(speaks_as) + "-reading-" + "+".join(speaks_for)
    elif speaks_as:
        who = "+".join(speaks_as)
    else:
        print("usage: edge iam <who>")
        print("       edge iam <self> [<self2> ...] --for <other> [<other2> ...]")
        sys.exit(1)

    cwd = os.getcwd()
    ctx = git_context()
    short = hashlib.sha1(f"{who}:{time.time()}".encode()).hexdigest()[:8]
    token = f"{who}:{short}"

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO frames (token, who, cwd, context) VALUES (%s, %s, %s, %s)",
            (token, who, cwd, json.dumps(ctx)),
        )
    conn.commit()
    conn.close()

    write_token(token)
    print(f"  I am {who}. Frame: {token}")
    print("  Establish your reference frame. Say three true things:")
    print("    edge true <subject> <predicate> <object>")

    # Store composite lists for post-truth registration
    composite_file = frame_dir() / "frame.composite"
    if speaks_for:
        composite_file.write_text(f"as:{' '.join(speaks_as)}\nfor:{' '.join(speaks_for)}\n")
    else:
        composite_file.unlink(missing_ok=True)


def cmd_true(args):
    if len(args) < 3:
        print("usage: edge true <subject> <predicate> <object>")
        sys.exit(1)

    token = read_token()
    if not token:
        print("  no frame started. run: edge iam <who>")
        sys.exit(1)

    subject, predicate, obj = args[0], args[1], args[2]
    truth = {"s": subject, "p": predicate, "o": obj}

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE frames SET truths = truths || %s::jsonb WHERE token = %s",
            (json.dumps(truth), token),
        )
        cur.execute("SELECT jsonb_array_length(truths), who FROM frames WHERE token = %s", (token,))
        n, who = cur.fetchone()
    conn.commit()

    print(f"  truth {n}/3: ({subject} --{predicate}--> {obj})")

    if n >= 3:
        print("  Reference frame established. You can now record edges.")
        from .cmd_discovery import _starmap_inner
        _starmap_inner(quiet=True)
        starmap_path = frame_dir() / "starmap"
        if starmap_path.exists():
            print(f"  Starmap ready: {starmap_path}  (run: edge starmap)")
        # Auto-register composite speaks-as/speaks-for
        composite_file = frame_dir() / "frame.composite"
        if composite_file.exists():
            text = composite_file.read_text()
            as_line = ""
            for_line = ""
            for line in text.strip().split("\n"):
                if line.startswith("as:"):
                    as_line = line[3:]
                elif line.startswith("for:"):
                    for_line = line[4:]
            for sa in as_line.split():
                if sa:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes)
                               VALUES (%s, 'speaks-as', %s, 1.0, 'salt', %s, 'auto-registered on frame creation')
                               ON CONFLICT DO NOTHING""",
                            (who, sa, token),
                        )
                    print(f"  + ({who} --speaks-as--> {sa}) [1.0, salt]")
            for sf in for_line.split():
                if sf:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes)
                               VALUES (%s, 'speaks-for', %s, 0.7, 'fluid', %s, 'auto-registered on frame creation')
                               ON CONFLICT DO NOTHING""",
                            (who, sf, token),
                        )
                    print(f"  + ({who} --speaks-for--> {sf}) [0.7, fluid]")
            conn.commit()
            composite_file.unlink(missing_ok=True)
    conn.close()
