"""Recording commands: add."""

import sys

from .graph import Graph
from .cli_helpers import require_frame, fmt_edge, resolve_subject


def cmd_add(args):
    confidence = 0.7
    phase = "fluid"
    note = ""
    slug = None
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--confidence" and i + 1 < len(args):
            confidence = float(args[i + 1]); i += 2
        elif args[i] == "--phase" and i + 1 < len(args):
            phase = args[i + 1]; i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]; i += 2
        elif args[i] == "--slug" and i + 1 < len(args):
            slug = args[i + 1]; i += 2
        else:
            positional.append(args[i]); i += 1

    if len(positional) < 3:
        print("usage: edge add <s> <p> <o> [--confidence N] [--phase P] [--note 'text'] [--slug name]")
        sys.exit(1)

    frame = require_frame()
    g = Graph(frame)
    subject = resolve_subject(positional[0], g)
    predicate, obj = positional[1], positional[2]
    edge = g.add(subject, predicate, obj, confidence, phase, note, slug=slug)
    print(f"  + {fmt_edge(edge)}")
    print(f"    #{edge.hash}")
    if slug:
        print(f"    slug: {slug}")
    if note:
        print(f"    note: {note}")
