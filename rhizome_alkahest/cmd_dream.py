"""Dream commands: dream, resonance, embed."""

import json
import os
import random

from .db import connect
from .graph import Graph
from .cli_helpers import require_frame


def cmd_dream(args):
    """Pull random edges, free-associate across them, deposit a dream.

    The isle is full of noises, sounds and sweet airs, that give delight and hurt not.

    --n N: how many random edges to pull (default 5)
    --anti-orient: also pull edges far from current truths (requires frame)
    --dry: show the dream prompt without running it
    --model MODEL: which model to use (default claude-haiku-4-5-20251001)
    """
    n = 5
    anti_orient = "--anti-orient" in args
    dry = "--dry" in args
    model = "claude-haiku-4-5-20251001"
    i = 0
    while i < len(args):
        if args[i] == "--n" and i + 1 < len(args):
            n = int(args[i + 1]); i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]; i += 2
        elif args[i] in ("--anti-orient", "--dry"):
            i += 1
        else:
            i += 1

    conn = connect()
    edges = []      # display strings for the prompt
    triples = []    # (s, p, o) tuples for provenance links

    with conn.cursor() as cur:
        # Pull random knowledge edges — fluid and volatile only (salt has settled, doesn't dream)
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.notes, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.phase IN ('fluid', 'volatile')
            AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                      'needs-attention-from', 'records', 'completed-on',
                                      'decomposed-into', 'compressed-to', 'dreamt-on')
            AND e.subject NOT LIKE 'task:%%'
            ORDER BY random()
            LIMIT %s
        """, (n,))
        for row in cur.fetchall():
            s, p, o, notes, phase, who = row
            edge_str = f"({s} --{p}--> {o})"
            if notes:
                edge_str += f" [note: {notes}]"
            edges.append(edge_str)
            triples.append((s, p, o))

        # Salt anchor — one settled edge to ground the dream (the familiar house)
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.notes, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.phase = 'salt'
            AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                    'needs-attention-from', 'records', 'completed-on',
                                    'move-chosen', 'valuation', 'outcome')
            AND e.subject NOT LIKE 'task:%%'
            AND e.subject NOT LIKE 'go9:%%'
            AND e.subject NOT LIKE 'connect5:%%'
            ORDER BY random()
            LIMIT 1
        """)
        salt_row = cur.fetchone()
        if salt_row:
            s, p, o, notes, phase, who = salt_row
            edge_str = f"({s} --{p}--> {o}) [salt]"
            if notes:
                edge_str += f" [note: {notes}]"
            edges.append(edge_str)
            triples.append((s, p, o))

        # Anti-orient: pull edges far from current truths
        if anti_orient:
            try:
                frame = require_frame()
                # Get truth terms
                truth_terms = set()
                for t in frame.truths:
                    for val in [t.get("s", ""), t.get("p", ""), t.get("o", "")]:
                        truth_terms.update(val.replace("-", " ").split())

                if truth_terms:
                    # Pull edges that share NO terms with truths (fluid/volatile only)
                    cur.execute("""
                        SELECT e.subject, e.predicate, e.object, e.notes, e.phase
                        FROM live_edges e
                        WHERE e.phase IN ('fluid', 'volatile')
                        AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                                  'needs-attention-from', 'records', 'completed-on',
                                                  'dreamt-on')
                        AND e.subject NOT LIKE 'task:%%'
                        ORDER BY random()
                        LIMIT 50
                    """)
                    cold_edges = []
                    cold_triples = []
                    for row in cur.fetchall():
                        s, p, o, notes, phase = row
                        all_text = f"{s} {p} {o}".replace("-", " ")
                        overlap = sum(1 for t in truth_terms if t.lower() in all_text.lower())
                        if overlap == 0:
                            edge_str = f"({s} --{p}--> {o})"
                            if notes:
                                edge_str += f" [note: {notes}]"
                            cold_edges.append(edge_str)
                            cold_triples.append((s, p, o))
                    # Take up to 2 cold edges
                    edges.extend(cold_edges[:2])
                    triples.extend(cold_triples[:2])
            except SystemExit:
                pass  # No frame, skip anti-orient

    conn.close()

    if not edges:
        print("  no edges to dream on")
        return

    random.shuffle(edges)

    prompt_narrative = f"""You are dreaming.

Here are some things that were next to each other when you woke up:

{chr(10).join(f"  {e}" for e in edges)}

Let them be near each other. What do you notice? Not what they mean — what they *touch*.

Write a short paragraph — a few sentences — about what you see between them. Free-associate. Follow the heat. Don't name edges or triples, just write."""

    prompt_extract = """Here is a dream narrative:

{narrative}

What did it find? Pull out 1-3 relationships the dream made — connections between things, not descriptions of single things. Write them as short triples: subject predicate object (hyphenated names, 1-4 words each), one per line.

Then a blank line, then one sentence for the feeling."""

    if dry:
        print("  === dream prompt (pass 1: narrative) ===")
        print(prompt_narrative)
        print(f"\n  model: {model}")
        print(f"  edges: {len(edges)}")
        return

    # Call the model — prefer local Qwen, fall back to Anthropic API
    qwen_url = os.environ.get("QWEN_URL", "http://localhost:5052")
    use_local = model.startswith("qwen") or model == "local"
    if not use_local:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            use_local = True

    def _call_llm(prompt_text, max_tokens=300):
        if use_local:
            import urllib.request
            req_body = json.dumps({
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [{"role": "user", "content": prompt_text}],
                "max_tokens": max_tokens,
                "temperature": 0.9,
            }).encode()
            req = urllib.request.Request(
                f"{qwen_url}/v1/chat/completions",
                data=req_body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
        else:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt_text}],
            )
            return response.content[0].text.strip()

    try:
        # Pass 1: free-associate a narrative
        narrative = _call_llm(prompt_narrative, max_tokens=400)
        print(f"  === dream narrative ===")
        print(f"  {narrative}")
        print()

        # Pass 2: extract edges from the narrative
        dream_text = _call_llm(prompt_extract.format(narrative=narrative), max_tokens=200)
    except Exception as e:
        print(f"  dream failed: {e}")
        return

    # Parse the response: lines with 3+ words are edges, blank line separates, rest is dream-note
    lines = dream_text.strip().split("\n")
    found_edges = []
    dream_note = ""
    past_blank = False
    for line in lines:
        line = line.strip()
        if not line:
            past_blank = True
            continue
        if past_blank:
            dream_note = (dream_note + " " + line).strip() if dream_note else line
        else:
            parts = line.split(None, 2)
            if len(parts) >= 3:
                found_edges.append((parts[0], parts[1], parts[2]))
            elif len(parts) == 2:
                found_edges.append((parts[0], "touches", parts[1]))

    # Print the dream
    print(f"  === dream ({len(edges)} edges pulled, {len(found_edges)} edges found) ===")
    for s, p, o in found_edges:
        print(f"  ({s} --{p}--> {o})")
    if dream_note:
        print(f"  note: {dream_note}")
    print()
    print(f"  dreamt on:")
    for e in edges:
        print(f"    {e}")

    # Deposit found edges as volatile with dreamt-on provenance
    try:
        frame = require_frame()
        g = Graph(frame)
        for ds, dp, do_ in found_edges:
            edge = g.add(ds, dp, do_, 0.5, "volatile", dream_note)
            print(f"  + ({ds} --{dp}--> {do_}) #{edge.hash} [volatile]")
            # Link each found edge to its source edges
            dream_node = f"e:{ds}/{dp}/{do_}"
            for src_s, src_p, src_o in triples:
                source_node = f"e:{src_s}/{src_p}/{src_o}"
                g.add(dream_node, "dreamt-on", source_node, 0.5, "volatile", "")
    except (SystemExit, Exception) as e:
        print(f"  (dream not deposited — {e})")


def cmd_resonance(args):
    """Semantic search — find edges by meaning, not keywords."""
    from .embed import embed
    if not args:
        print("Usage: edge resonance <query> [--limit N]")
        return
    limit = 10
    query_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            query_parts.append(args[i]); i += 1
    query = " ".join(query_parts)
    if not query:
        print("Usage: edge resonance <query> [--limit N]")
        return
    vec = embed(query)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT subject, predicate, object, notes,
                      1 - (embedding <=> %s::vector) AS similarity,
                      phase, observer
               FROM live_edges
               WHERE embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (vec, vec, limit),
        )
        rows = cur.fetchall()
    if not rows:
        print("  No edges with embeddings found.")
        return
    print(f"\n  RESONANCE  —  \"{query}\"")
    print(f"  {'─' * 60}\n")
    for s, p, o, notes, sim, phase, obs in rows:
        sim_pct = f"{sim:.3f}"
        triple = f"({s} --{p}--> {o})"
        print(f"  {sim_pct}  {triple}  [{phase}]")
        if notes:
            note_preview = notes[:80] + ("..." if len(notes) > 80 else "")
            print(f"         {note_preview}")
    print()


def cmd_embed(args):
    """Backfill embeddings for edges missing them."""
    from .embed import embed_batch, edge_text
    batch_size = 256
    dry_run = False
    for i, arg in enumerate(args):
        if arg == "--batch-size" and i + 1 < len(args):
            batch_size = int(args[i + 1])
        elif arg == "--dry-run":
            dry_run = True
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, subject, predicate, object, notes FROM live_edges WHERE embedding IS NULL"
        )
        rows = cur.fetchall()
    if not rows:
        print("All edges already have embeddings.")
        return
    print(f"  {len(rows)} edges missing embeddings. Embedding in batches of {batch_size}...")
    if dry_run:
        print("  (dry run — not writing)")
        return
    texts = [edge_text(r[1], r[2], r[3], r[4] or "") for r in rows]
    vectors = embed_batch(texts, batch_size=batch_size)
    with conn.cursor() as cur:
        for (row, vec) in zip(rows, vectors):
            cur.execute("UPDATE edges SET embedding = %s WHERE id = %s", (vec, row[0]))
    conn.commit()
    print(f"  {len(rows)} embeddings written.")
