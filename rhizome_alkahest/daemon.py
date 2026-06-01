"""Pulse — the memory daemon.

The loop `edge dream` left open. The evidence: dream ran hard for ~36 hours
in late March (494 dreamt-on edges, two days), produced 137 connections of
which 4 precipitated (1 salt, 3 fluid) and 0 ever dissolved — then went dark.
No scheduler. Meanwhile volatiles accumulated unattended (~1000 older than
two weeks by June). The generative half worked; the operational loop and the
decay counterpart were never wired up.

Pulse closes that loop. One unattended cycle over the alkahest graph:

    1. DREAM    — free-associate across random fluid/volatile edges,
                  deposit new connections as volatile@0.5 (cmd_dream).
    2. DIGEST   — for high-spread parallax, ask a third observer what
                  neither frame can see; deposit as fluid (ParallaxDigest).
    3. PROMOTE  — lift volatile triples corroborated by >= K distinct
                  observers to fluid. Confirmation earns persistence.
    4. GC       — dissolve volatile edges older than N days that nothing
                  confirmed. Decay is physics; unconfirmed guesses die quietly.

Order matters: promote BEFORE gc, so a volatile that earned corroboration
is lifted out of harm's way before the age-sweep runs. Capture (dream,
digest) runs first so the freshest material is present for the same cycle's
curation only on the next pulse — this pulse curates what prior pulses left,
which is correct: a connection should survive a confirmation window before it
can be promoted, and should not be gc'd the instant it's born.

Nothing here merges or deletes a fact to resolve a disagreement. Parallax is
preserved end to end (honors the design memory: pushback is data). The only
destructive act is gc, and it only dissolves *unconfirmed volatiles past an
age threshold* — never fluid, never salt, never a corroborated triple.

Run:
    edge pulse                 # full cycle, live
    edge pulse --dry           # show what each stage would do, write nothing
    edge pulse --no-dream      # skip a stage (also --no-digest/--promote/--gc)
    edge pulse --gc-days 21    # tune the decay window
    edge pulse --quiet         # only the summary line (for cron logs)
"""

import os
import sys
import time
import traceback
from datetime import date, datetime, timezone

from .db import connect
from .frame import Frame
from .frame_pointer import read_token


# The daemon establishes its own frame so its deposits are attributable to a
# distinct observer — "this came from the overnight pulse, not a live session."
# That observer identity is what later lets a human read the graph and tell
# machine-surfaced connections apart from lived ones.
def _pulse_who() -> str:
    today = date.today().isoformat()
    return f"pulse @ {today}"


def _ensure_frame(conn) -> Frame:
    """Establish (or reuse today's) pulse frame.

    The frame's three truths are the daemon's standing orientation: it knows
    what it is, what it does, and the rule it must not break. Reusing one
    frame per day keeps a pulse's deposits grouped without spawning a new
    observer every run.
    """
    who = _pulse_who()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT token, who, cwd, truths FROM frames WHERE who = %s ORDER BY created_at DESC LIMIT 1",
            (who,),
        )
        row = cur.fetchone()
    if row:
        return Frame(token=row[0], who=row[1], cwd=row[2], truths=row[3])

    return Frame.establish(
        who,
        [
            ("pulse", "is", "the-overnight-metabolism-of-the-graph"),
            ("pulse", "must-not", "merge-or-delete-a-fact-to-resolve-disagreement"),
            ("volatile-unconfirmed", "decays", "fluid-corroborated-persists"),
        ],
        conn=conn,
        cwd=os.getcwd(),
    )


class Pulse:
    """One unattended capture-and-curate cycle over the graph."""

    def __init__(self, conn=None, quiet=False, dry=False):
        self.conn = conn or connect()
        self.quiet = quiet
        self.dry = dry
        self.stats = {}
        self.errors = []

    def log(self, msg):
        if not self.quiet:
            print(msg)

    def _stage(self, name, fn):
        """Run a stage in isolation — one stage failing must not abort the cycle.

        A dead Qwen server should cost you dream+digest, not promote+gc. The
        curation half is the half that's been missing; it must run even when
        the generative half is down.
        """
        self.log(f"\n  ── {name} {'─' * (40 - len(name))}")
        t0 = time.time()
        try:
            result = fn()
            self.stats[name] = result
            return result
        except SystemExit:
            # require_frame and friends exit() — swallow so the cycle continues.
            self.errors.append((name, "SystemExit (likely missing frame/server)"))
            self.log(f"  {name}: skipped (SystemExit)")
        except Exception as e:
            self.errors.append((name, repr(e)))
            self.log(f"  {name}: FAILED — {e}")
            if not self.quiet:
                traceback.print_exc()
        finally:
            self.log(f"  ({name} took {time.time() - t0:.1f}s)")
        return None

    # -- stages ------------------------------------------------------------

    def dream(self, n=5):
        from .cmd_dream import cmd_dream
        args = ["--n", str(n)]
        if self.dry:
            args.append("--dry")
        # cmd_dream establishes/uses the current frame pointer; we set ours.
        cmd_dream(args)
        return "ran"

    def digest(self, limit=3):
        if self.dry:
            self.log("  (dry) would run ParallaxDigest over high-spread disagreements")
            return "dry"
        from .digest import ParallaxDigest
        d = ParallaxDigest(conn=self.conn)
        discoveries = d.run(limit=limit)
        return f"{len(discoveries) if discoveries else 0} discoveries"

    def promote(self, min_observers=2):
        from .cmd_stewardship import cmd_promote
        args = ["--observers", str(min_observers)]
        if self.dry:
            args.append("--dry")
        cmd_promote(args)
        return "ran"

    def gc(self, days=14, amnesty=True):
        from .cmd_stewardship import cmd_gc
        args = ["--days", str(days)]
        # Amnesty by default: dissolve only dream-spawned volatiles, never
        # load-bearing ones. The daemon must not turn a long-dormant backlog
        # of lived session memory into a one-sweep extinction. Lived
        # observations are left for a deliberate tend pass. Pass amnesty=False
        # (CLI: --gc-lived) only when you've decided the lived backlog is
        # genuinely stale and should age out normally.
        if amnesty:
            args.append("--amnesty")
        if self.dry:
            args.append("--dry")
        cmd_gc(args)
        return "ran"

    # -- orchestration -----------------------------------------------------

    def run(self, stages, dream_n=5, digest_limit=3, min_observers=2, gc_days=14, gc_amnesty=True):
        started = datetime.now(timezone.utc)
        self.log(f"  PULSE {started.isoformat()}  {'(DRY RUN)' if self.dry else ''}")

        # Point the frame pointer at the pulse frame so cmd_dream/promote/gc,
        # which read the current frame, deposit as the pulse observer.
        frame = _ensure_frame(self.conn)
        from .frame_pointer import write_token
        prior = read_token()
        try:
            write_token(frame.token)
            self.log(f"  observer: {frame.who}  ({frame.token})")

            if "dream" in stages:
                self._stage("dream", lambda: self.dream(dream_n))
            if "digest" in stages:
                self._stage("digest", lambda: self.digest(digest_limit))
            if "promote" in stages:
                self._stage("promote", lambda: self.promote(min_observers))
            if "gc" in stages:
                self._stage("gc", lambda: self.gc(gc_days, amnesty=gc_amnesty))
        finally:
            # Restore whatever frame was active before, so a manual session
            # the user left open isn't hijacked by the daemon's pointer.
            if prior:
                write_token(prior)

        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        ok = len(stages) - len(self.errors)
        summary = (
            f"  PULSE done — {ok}/{len(stages)} stages ok, "
            f"{len(self.errors)} error(s), {elapsed:.1f}s"
        )
        # Summary always prints, even in --quiet, so cron logs have one line.
        print(summary)
        if self.errors:
            for name, err in self.errors:
                print(f"    ! {name}: {err}")
        return not self.errors


def cmd_pulse(args):
    """One unattended capture-and-curate cycle. See daemon.py for the design."""
    dry = "--dry" in args
    quiet = "--quiet" in args
    # gc runs in amnesty mode by default (dream-slop only, never load-bearing).
    # --gc-lived opts into letting lived observations age out normally — only
    # use it once you've decided the backlog is genuinely stale.
    gc_amnesty = "--gc-lived" not in args

    stages = ["dream", "digest", "promote", "gc"]
    for stage in list(stages):
        if f"--no-{stage}" in args:
            stages.remove(stage)

    dream_n = 5
    digest_limit = 3
    min_observers = 2
    gc_days = 14
    i = 0
    while i < len(args):
        if args[i] == "--dream-n" and i + 1 < len(args):
            dream_n = int(args[i + 1]); i += 2
        elif args[i] == "--digest-limit" and i + 1 < len(args):
            digest_limit = int(args[i + 1]); i += 2
        elif args[i] == "--observers" and i + 1 < len(args):
            min_observers = int(args[i + 1]); i += 2
        elif args[i] == "--gc-days" and i + 1 < len(args):
            gc_days = int(args[i + 1]); i += 2
        else:
            i += 1

    pulse = Pulse(quiet=quiet, dry=dry)
    ok = pulse.run(
        stages,
        dream_n=dream_n,
        digest_limit=digest_limit,
        min_observers=min_observers,
        gc_days=gc_days,
        gc_amnesty=gc_amnesty,
    )
    sys.exit(0 if ok else 1)
