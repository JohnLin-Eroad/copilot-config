#!/usr/bin/env python3
"""
john-brain: Personal idea clustering engine

Reads chat history, extracts idea atoms with an LLM, clusters them by theme,
and writes one Obsidian note per cluster with quotes from the original source.

Usage:
  python3 brain.py ingest [--source <path>] [--type copilot|chatgpt|claude]
  python3 brain.py compile
  python3 brain.py status
  python3 brain.py reset
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency: pip3 install openai")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH   = Path.home() / "john-brain"
STATE_DB     = VAULT_PATH / ".brain" / "state.db"
CLUSTERS_DIR = VAULT_PATH / "clusters"
INDEX_FILE   = VAULT_PATH / "index.md"

FAST_MODEL   = "gpt-4o-mini"   # extraction — many small calls
HEAVY_MODEL  = "gpt-4o"        # clustering — needs broad reasoning

CHUNK_SIZE   = 3500            # chars per extraction chunk (~900 tokens)
MAX_QUOTES   = 12              # quotes shown per cluster note
MAX_IDEAS_SINGLE_PASS = 180    # above this, use hierarchical clustering

def _get_gh_token() -> str:
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("gh auth token returned nothing. Are you logged in with 'gh auth login'?")
    return token

def _make_client() -> OpenAI:
    return OpenAI(
        api_key=_get_gh_token(),
        base_url="https://models.inference.ai.azure.com",
    )

# ── State DB ──────────────────────────────────────────────────────────────────

def init_db() -> sqlite3.Connection:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id           TEXT PRIMARY KEY,
            path         TEXT,
            type         TEXT,
            hash         TEXT,
            processed_at TEXT,
            idea_count   INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            text      TEXT,
            quote     TEXT,
            date      TEXT
        )
    """)
    conn.commit()
    return conn


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ── Text utilities ────────────────────────────────────────────────────────────

def chunk_text(text: str, size: int = CHUNK_SIZE) -> Iterator[str]:
    """Split on paragraph boundaries, targeting ~size chars per chunk."""
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > size and current:
            yield "\n\n".join(current)
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)
    if current:
        yield "\n\n".join(current)


def _is_worth_analyzing(text: str) -> bool:
    """Fast heuristic: skip chunks that are mostly code or too short to contain ideas."""
    if len(text.strip()) < 120:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    # Count lines that are inside code blocks or look like code
    code_lines = sum(
        1 for l in lines
        if l.startswith("    ") or l.startswith("\t") or l.strip().startswith("```")
    )
    # Count lines that look like prose sentences
    prose_lines = sum(1 for l in lines if len(l.strip()) > 40 and not l.strip().startswith(("```", "#", "|", "-", "*", ">")))
    # Skip if overwhelmingly code with no prose
    if code_lines > 0 and prose_lines == 0:
        return False
    if len(lines) > 5 and (code_lines / len(lines)) > 0.7:
        return False
    return True


def clean_markdown(text: str) -> str:
    """Strip frontmatter, metadata tables, and HTML comments from session markdown."""
    # Remove YAML frontmatter
    text = re.sub(r'^---.*?---\s*', '', text, flags=re.DOTALL)
    # Remove HTML comments (<!-- ... -->)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # Remove markdown tables
    text = re.sub(r'^\|.*\|$\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-|: ]+$\n?', '', text, flags=re.MULTILINE)
    # Condense blanks
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── LLM calls ────────────────────────────────────────────────────────────────

SYSTEM_EXTRACT = (
    "You are a precise knowledge analyst. Your job is to surface the genuine thoughts, "
    "values, and beliefs of a specific person from their conversation history. "
    "Be thorough and specific — surface nuanced opinions, not just surface-level topics. "
    "Never invent ideas; only extract what is actually present. "
    "Always respond with valid JSON."
)

SYSTEM_CLUSTER = (
    "You are a cognitive cartographer building a detailed map of one person's mind. "
    "Your clusters should reveal patterns in how this person thinks — their recurring concerns, "
    "their values, their aesthetic preferences, and their intellectual interests. "
    "Be specific and insightful. Prefer depth over breadth. "
    "Always respond with valid JSON."
)


def _llm_json(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int = 1200,
    retries: int = 3,
    system: str = SYSTEM_EXTRACT,
) -> dict | list:
    """Call LLM and parse JSON, with retry on rate limit."""
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
            )
            raw = resp.choices[0].message.content
            data = json.loads(raw)
            return data
        except Exception as e:
            if "rate" in str(e).lower() and attempt < retries - 1:
                wait = 20 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    return {}


def extract_ideas_from_chunk(client: OpenAI, chunk: str, source_context: str) -> list[dict]:
    """Extract discrete idea atoms from a text chunk."""
    prompt = f"""You are reading a conversation between John (a software engineer at EROAD) and an AI assistant.

Extract discrete ideas, opinions, preferences, and insights that John *himself* expresses.

Rules:
- Only extract what JOHN says or implies — not the AI's suggestions
- Each idea should be 1-2 sentences, self-contained
- Include a short verbatim or near-verbatim quote (≤25 words) from John's messages
- Skip pure task/command turns ("do X", "run Y", "create Z")
- Focus on: opinions, values, preferences, plans, concerns, recurring interests, decisions and the reasoning behind them
- Return an empty list if nothing meaningful is present

Source: {source_context}

Conversation excerpt:
{chunk}

Respond with JSON: {{"ideas": [{{"idea": "...", "quote": "..."}}]}}"""

    data = _llm_json(client, FAST_MODEL, prompt, max_tokens=900)
    if isinstance(data, list):
        return data
    return data.get("ideas", [])


# ── Ingesters ─────────────────────────────────────────────────────────────────

def ingest_copilot_sessions(conn: sqlite3.Connection, client: OpenAI, source_dir: Path):
    """Ingest Copilot session markdown files from a directory."""
    md_files = sorted(source_dir.glob("**/*.md"))
    print(f"Found {len(md_files)} session files in {source_dir}")

    new_count = skipped_count = 0

    for path in md_files:
        source_id = f"copilot:{path.name}"
        fhash = file_hash(path)

        existing = conn.execute("SELECT hash FROM sources WHERE id = ?", (source_id,)).fetchone()
        if existing and existing[0] == fhash:
            skipped_count += 1
            continue

        print(f"\n  ▶ {path.name}")
        content = path.read_text(encoding="utf-8", errors="ignore")

        date_match = re.search(r'^date:\s*"?(\d{4}-\d{2}-\d{2})', content, re.MULTILINE)
        date = date_match.group(1) if date_match else path.stem[:10]

        clean = clean_markdown(content)
        all_ideas: list[dict] = []

        chunks = list(chunk_text(clean))
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 100:
                continue
            if not _is_worth_analyzing(chunk):
                continue
            ideas = extract_ideas_from_chunk(client, chunk, f"Copilot session {date}")
            all_ideas.extend(ideas)
            if ideas:
                print(f"    chunk {i+1}/{len(chunks)}: {len(ideas)} ideas")

        # Persist
        if existing:
            conn.execute("DELETE FROM ideas WHERE source_id = ?", (source_id,))
            conn.execute(
                "UPDATE sources SET hash=?, processed_at=?, idea_count=? WHERE id=?",
                (fhash, datetime.now().isoformat(), len(all_ideas), source_id),
            )
        else:
            conn.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?)",
                (source_id, str(path), "copilot", fhash, datetime.now().isoformat(), len(all_ideas)),
            )

        for idea in all_ideas:
            conn.execute(
                "INSERT INTO ideas (source_id, text, quote, date) VALUES (?,?,?,?)",
                (source_id, idea.get("idea", ""), idea.get("quote", ""), date),
            )

        conn.commit()
        print(f"    → {len(all_ideas)} ideas extracted")
        new_count += 1

    print(f"\nIngest done: {new_count} processed, {skipped_count} unchanged (already up to date)")


def ingest_chatgpt(conn: sqlite3.Connection, client: OpenAI, export_path: Path):
    """
    Ingest ChatGPT conversations.json export.

    To export: chatgpt.com → Settings → Data Controls → Export Data
    You'll receive an email with a zip. Extract it and point --source at conversations.json
    """
    if not export_path.exists():
        print(f"File not found: {export_path}")
        print("Export your ChatGPT data: Settings → Data Controls → Export Data")
        return

    print(f"Loading ChatGPT export: {export_path}")
    conversations = json.loads(export_path.read_text(encoding="utf-8"))
    print(f"Found {len(conversations)} conversations")

    new_count = skipped_count = 0

    for conv in conversations:
        conv_id = conv.get("id", "unknown")
        source_id = f"chatgpt:{conv_id}"
        title = conv.get("title", "Untitled")

        # Build a text representation from user messages only
        messages = conv.get("mapping", {})
        user_texts: list[str] = []
        for node in messages.values():
            msg = node.get("message")
            if not msg:
                continue
            if msg.get("author", {}).get("role") != "user":
                continue
            parts = msg.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, str) and len(part.strip()) > 20:
                    user_texts.append(part.strip())

        if not user_texts:
            continue

        combined = "\n\n".join(user_texts)
        fhash = hashlib.sha256(combined.encode()).hexdigest()[:16]

        existing = conn.execute("SELECT hash FROM sources WHERE id = ?", (source_id,)).fetchone()
        if existing and existing[0] == fhash:
            skipped_count += 1
            continue

        # Date from create_time
        create_time = conv.get("create_time")
        date = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d") if create_time else "unknown"

        print(f"\n  ▶ {title[:60]} ({date})")
        all_ideas: list[dict] = []

        chunks = list(chunk_text(combined))
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 80:
                continue
            if not _is_worth_analyzing(chunk):
                continue
            ideas = extract_ideas_from_chunk(client, chunk, f"ChatGPT conversation '{title}' ({date})")
            all_ideas.extend(ideas)
            if ideas:
                print(f"    chunk {i+1}/{len(chunks)}: {len(ideas)} ideas")

        if existing:
            conn.execute("DELETE FROM ideas WHERE source_id = ?", (source_id,))
            conn.execute(
                "UPDATE sources SET hash=?, processed_at=?, idea_count=? WHERE id=?",
                (fhash, datetime.now().isoformat(), len(all_ideas), source_id),
            )
        else:
            conn.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?)",
                (source_id, str(export_path), "chatgpt", fhash, datetime.now().isoformat(), len(all_ideas)),
            )

        for idea in all_ideas:
            conn.execute(
                "INSERT INTO ideas (source_id, text, quote, date) VALUES (?,?,?,?)",
                (source_id, idea.get("idea", ""), idea.get("quote", ""), date),
            )

        conn.commit()
        print(f"    → {len(all_ideas)} ideas extracted")
        new_count += 1

    print(f"\nChatGPT ingest done: {new_count} processed, {skipped_count} unchanged")


def ingest_claude(conn: sqlite3.Connection, client: OpenAI, export_path: Path):
    """
    Ingest Claude conversation export.

    To export: claude.ai → Settings → Export Data
    You'll get a JSON file. Point --source at it.
    """
    if not export_path.exists():
        print(f"File not found: {export_path}")
        print("Export your Claude data: claude.ai → Settings → Export Data")
        return

    print(f"Loading Claude export: {export_path}")
    data = json.loads(export_path.read_text(encoding="utf-8"))

    # Claude export is a list of conversations
    if isinstance(data, dict):
        conversations = data.get("conversations", [data])
    else:
        conversations = data

    print(f"Found {len(conversations)} conversations")

    new_count = skipped_count = 0

    for conv in conversations:
        conv_id = conv.get("uuid", conv.get("id", "unknown"))
        source_id = f"claude:{conv_id}"
        title = conv.get("name", conv.get("title", "Untitled"))

        # Extract human turns
        chat_messages = conv.get("chat_messages", conv.get("messages", []))
        user_texts: list[str] = []
        for msg in chat_messages:
            role = msg.get("sender", msg.get("role", ""))
            if role not in ("human", "user"):
                continue
            content = msg.get("text", msg.get("content", ""))
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            if isinstance(content, str) and len(content.strip()) > 20:
                user_texts.append(content.strip())

        if not user_texts:
            continue

        combined = "\n\n".join(user_texts)
        fhash = hashlib.sha256(combined.encode()).hexdigest()[:16]

        existing = conn.execute("SELECT hash FROM sources WHERE id = ?", (source_id,)).fetchone()
        if existing and existing[0] == fhash:
            skipped_count += 1
            continue

        created = conv.get("created_at", "")
        date = created[:10] if created else "unknown"

        print(f"\n  ▶ {title[:60]} ({date})")
        all_ideas: list[dict] = []

        chunks = list(chunk_text(combined))
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 80:
                continue
            if not _is_worth_analyzing(chunk):
                continue
            ideas = extract_ideas_from_chunk(client, chunk, f"Claude conversation '{title}' ({date})")
            all_ideas.extend(ideas)
            if ideas:
                print(f"    chunk {i+1}/{len(chunks)}: {len(ideas)} ideas")

        if existing:
            conn.execute("DELETE FROM ideas WHERE source_id = ?", (source_id,))
            conn.execute(
                "UPDATE sources SET hash=?, processed_at=?, idea_count=? WHERE id=?",
                (fhash, datetime.now().isoformat(), len(all_ideas), source_id),
            )
        else:
            conn.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?)",
                (source_id, str(export_path), "claude", fhash, datetime.now().isoformat(), len(all_ideas)),
            )

        for idea in all_ideas:
            conn.execute(
                "INSERT INTO ideas (source_id, text, quote, date) VALUES (?,?,?,?)",
                (source_id, idea.get("idea", ""), idea.get("quote", ""), date),
            )

        conn.commit()
        print(f"    → {len(all_ideas)} ideas extracted")
        new_count += 1

    print(f"\nClaude ingest done: {new_count} processed, {skipped_count} unchanged")


# ── Clustering ────────────────────────────────────────────────────────────────

def _cluster_batch(client: OpenAI, ideas: list[tuple], label: str = "") -> list[dict]:
    """Cluster a list of (id, text, quote, date, source_id) idea rows."""
    numbered = "\n".join(
        f"[{i+1}] ({row[3]}) {row[1]}"
        for i, row in enumerate(ideas)
    )

    prompt = f"""You are mapping the mental landscape of John, a software engineer.
Below are ideas and opinions extracted from his conversations with AI assistants.{(' ' + label) if label else ''}

Group these into 8–20 meaningful thematic clusters. Each cluster should represent
a genuine recurring interest, concern, value, or opinion of John's.

Ideas:
{numbered}

For each cluster provide:
- name: 2–5 word descriptive title
- summary: 2–3 sentences capturing what John thinks/feels about this theme
- idea_indices: list of 1-based numbers from the ideas above that belong here
- related: list of other cluster names this naturally connects to

Aim for specificity — "Hexagonal Architecture" beats "Software Design".
Every idea should belong to exactly one cluster.

Respond with JSON: {{"clusters": [{{"name": "...", "summary": "...", "idea_indices": [...], "related": [...]}}]}}"""

    data = _llm_json(client, HEAVY_MODEL, prompt, max_tokens=4000, system=SYSTEM_CLUSTER)
    raw = data.get("clusters", [])

    result = []
    for c in raw:
        cluster_ideas = [ideas[i - 1] for i in c.get("idea_indices", []) if 0 < i <= len(ideas)]
        result.append({
            "name": c.get("name", "Unnamed"),
            "summary": c.get("summary", ""),
            "ideas": cluster_ideas,
            "related": c.get("related", []),
        })
    return result


def compile_clusters(conn: sqlite3.Connection, client: OpenAI):
    """Cluster all extracted ideas and write Obsidian notes."""
    rows = conn.execute(
        "SELECT id, text, quote, date, source_id FROM ideas WHERE length(trim(text)) > 0"
    ).fetchall()

    if not rows:
        print("No ideas found. Run 'ingest' first.")
        return

    total = len(rows)
    print(f"Clustering {total} ideas...")

    if total <= MAX_IDEAS_SINGLE_PASS:
        clusters = _cluster_batch(client, rows)
    else:
        # Hierarchical: cluster in batches, then meta-cluster
        batch_size = MAX_IDEAS_SINGLE_PASS
        all_clusters: list[dict] = []
        for i in range(0, total, batch_size):
            batch = rows[i:i + batch_size]
            print(f"  Batch {i // batch_size + 1}: clustering {len(batch)} ideas...")
            all_clusters.extend(_cluster_batch(client, batch, f"(batch {i // batch_size + 1})"))

        # If still many clusters, meta-cluster them
        if len(all_clusters) > 30:
            print(f"  Meta-clustering {len(all_clusters)} initial clusters...")
            # Flatten into pseudo-ideas for meta pass
            meta_rows = [
                (None, c["name"] + ": " + c["summary"], "", "", "")
                for c in all_clusters
            ]
            meta_clusters = _cluster_batch(client, meta_rows, "(meta-cluster pass)")
            # Re-attach original ideas to meta clusters by name matching
            for meta in meta_clusters:
                for cluster_name_idea in meta["ideas"]:
                    orig_name = cluster_name_idea[1].split(":")[0].strip()
                    match = next((c for c in all_clusters if c["name"] == orig_name), None)
                    if match:
                        meta["ideas"] = meta.get("raw_ideas", []) + match["ideas"]
            clusters = meta_clusters
        else:
            clusters = all_clusters

    CLUSTERS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nGenerating {len(clusters)} cluster notes...")
    for cluster in clusters:
        _write_cluster_note(cluster)

    _write_index(clusters)
    print(f"\n✓ Brain compiled. Open {VAULT_PATH} in Obsidian.")
    print(f"  {len(clusters)} clusters · {total} total ideas")


# ── Note writing ──────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\n]', '', name).strip()


def _source_label(source_id: str) -> str:
    parts = source_id.split(":", 1)
    return parts[0].title() if parts else "Unknown"


def _write_cluster_note(cluster: dict):
    name = cluster["name"]
    safe = _safe_name(name)
    path = CLUSTERS_DIR / f"{safe}.md"

    quotes_section = ""
    for idea in cluster["ideas"][:MAX_QUOTES]:
        _id, text, quote, date, source_id = idea
        label = _source_label(source_id)
        if quote and len(quote.strip()) > 5:
            quotes_section += f'\n> "{quote.strip()}"\n> — *{label}, {date}*\n'
        else:
            quotes_section += f"\n- {text}  \n  *({label}, {date})*\n"

    extra = len(cluster["ideas"]) - MAX_QUOTES
    if extra > 0:
        quotes_section += f"\n*…and {extra} more ideas in this cluster.*\n"

    related_links = " · ".join(f"[[{_safe_name(r)}]]" for r in cluster.get("related", []))

    content = f"""---
tags: [brain-cluster]
updated: {datetime.now().strftime('%Y-%m-%d')}
idea_count: {len(cluster['ideas'])}
---

# {name}

{cluster['summary']}

## Ideas & Quotes
{quotes_section}
## Related

{related_links if related_links else '*None identified*'}
"""
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ {safe}.md  ({len(cluster['ideas'])} ideas)")


def _write_index(clusters: list[dict]):
    sorted_clusters = sorted(clusters, key=lambda c: -len(c["ideas"]))
    rows = "\n".join(
        f"| [[{_safe_name(c['name'])}]] | {len(c['ideas'])} | {c['summary'][:90]}… |"
        for c in sorted_clusters
    )
    content = f"""---
tags: [brain-index]
updated: {datetime.now().strftime('%Y-%m-%d')}
---

# John's Brain — Idea Map

*{len(clusters)} clusters · last compiled {datetime.now().strftime('%Y-%m-%d %H:%M')}*

| Cluster | Ideas | Theme |
|---|---|---|
{rows}
"""
    INDEX_FILE.write_text(content, encoding="utf-8")
    print(f"  ✓ index.md")


# ── Status ────────────────────────────────────────────────────────────────────

def show_status(conn: sqlite3.Connection):
    sources = conn.execute(
        "SELECT type, COUNT(*), SUM(idea_count) FROM sources GROUP BY type"
    ).fetchall()
    total_ideas = conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0]
    cluster_notes = len(list(CLUSTERS_DIR.glob("*.md"))) if CLUSTERS_DIR.exists() else 0

    print("\nBrain Status")
    print("─" * 40)
    if sources:
        for stype, count, idea_sum in sources:
            print(f"  {stype:12s}  {count} file(s)   {idea_sum or 0} ideas extracted")
    else:
        print("  No sources ingested yet.")
    print(f"  {'total ideas':12s}  {total_ideas}")
    print(f"  {'clusters':12s}  {cluster_notes} notes in vault")

    recent = conn.execute(
        "SELECT path, idea_count, processed_at FROM sources ORDER BY processed_at DESC LIMIT 5"
    ).fetchall()
    if recent:
        print("\nRecently processed:")
        for p, ic, ts in recent:
            print(f"  {Path(p).name:40s}  {ic:3d} ideas  ({ts[:10]})")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="john-brain: cluster your ideas from chat history into an Obsidian vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  ingest   Extract idea atoms from a source (can be run multiple times, incrementally)
  compile  Cluster all ideas and (re)generate Obsidian notes
  status   Show what's been ingested and compiled
  reset    Wipe all extracted data and start fresh

Examples:
  python3 brain.py ingest                                  # Copilot sessions (default)
  python3 brain.py ingest --source ~/Downloads/conversations.json --type chatgpt
  python3 brain.py ingest --source ~/Downloads/claude_export.json  --type claude
  python3 brain.py compile
  python3 brain.py status
""",
    )
    sub = parser.add_subparsers(dest="command")

    ingest_p = sub.add_parser("ingest", help="Extract ideas from a source")
    ingest_p.add_argument(
        "--source",
        default=str(Path.home() / "Documents/copilot-sessions/sessions"),
        help="Path to source directory (copilot) or file (chatgpt/claude)",
    )
    ingest_p.add_argument(
        "--type",
        choices=["copilot", "chatgpt", "claude"],
        default="copilot",
        help="Source type",
    )

    sub.add_parser("compile", help="Cluster ideas and generate notes")
    sub.add_parser("status",  help="Show brain status")
    sub.add_parser("reset",   help="Clear all state and vault notes")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    conn = init_db()
    client = _make_client()

    if args.command == "ingest":
        source = Path(args.source).expanduser()
        if args.type == "copilot":
            ingest_copilot_sessions(conn, client, source)
        elif args.type == "chatgpt":
            ingest_chatgpt(conn, client, source)
        elif args.type == "claude":
            ingest_claude(conn, client, source)

    elif args.command == "compile":
        compile_clusters(conn, client)

    elif args.command == "status":
        show_status(conn)

    elif args.command == "reset":
        confirm = input("This will erase all extracted ideas and cluster notes. Type 'yes' to confirm: ")
        if confirm.strip().lower() == "yes":
            conn.execute("DELETE FROM ideas")
            conn.execute("DELETE FROM sources")
            conn.commit()
            if CLUSTERS_DIR.exists():
                shutil.rmtree(CLUSTERS_DIR)
            if INDEX_FILE.exists():
                INDEX_FILE.unlink()
            print("Reset complete.")
        else:
            print("Cancelled.")

    conn.close()


if __name__ == "__main__":
    main()
