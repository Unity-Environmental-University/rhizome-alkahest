"""
edge CLI — single implementation for both CLI and MCP.

Usage: python -m rhizome_alkahest.cli <command> [args...]
"""

import sys

from .cmd_stewardship import cmd_garden, cmd_name, cmd_words, cmd_gc, cmd_decompose, cmd_promote
from .daemon import cmd_pulse
from .cmd_query import (cmd_find, cmd_about, cmd_from, cmd_parallax,
                        cmd_parallax_token, cmd_frames, cmd_whoami,
                        cmd_ls, cmd_dissolve, cmd_count)
from .cmd_grammar import cmd_say, cmd_alias
from .cmd_frames import cmd_iam, cmd_true
from .cmd_dream import cmd_dream, cmd_resonance, cmd_embed
from .cmd_recording import cmd_add
from .cmd_discovery import (cmd_orient, cmd_ran, cmd_starmap, cmd_raw,
                            cmd_digest, cmd_overlap, cmd_attend,
                            cmd_polarity, cmd_help)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

COMMANDS = {
    "iam": cmd_iam,
    "true": cmd_true,
    "add": cmd_add,
    "find": cmd_find,
    "about": cmd_about,
    "from": cmd_from,
    "parallax": cmd_parallax,
    "parallax-token": cmd_parallax_token,
    "frames": cmd_frames,
    "whoami": cmd_whoami,
    "ls": cmd_ls,
    "dissolve": cmd_dissolve,
    "count": cmd_count,
    "orient": cmd_orient,
    "ran": cmd_ran,
    "starmap": cmd_starmap,
    "raw": cmd_raw,
    "digest": cmd_digest,
    "overlap": cmd_overlap,
    "attend": cmd_attend,
    "polarity": cmd_polarity,
    "garden": cmd_garden,
    "name": cmd_name,
    "decompose": cmd_decompose,
    "words": cmd_words,
    "say": cmd_say,
    "alias": cmd_alias,
    "dream": cmd_dream,
    "gc": cmd_gc,
    "promote": cmd_promote,
    "pulse": cmd_pulse,
    "embed": cmd_embed,
    "resonance": cmd_resonance,
    "help": cmd_help,
    "-h": cmd_help,
    "--help": cmd_help,
}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ls"
    args = sys.argv[2:]

    handler = COMMANDS.get(cmd)
    if handler:
        handler(args)
    else:
        print(f"unknown command: {cmd}")
        print("try: edge help")
        sys.exit(1)


if __name__ == "__main__":
    main()
