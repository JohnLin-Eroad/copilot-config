#!/usr/bin/env python3
"""
Copilot Session Summarizer
Reads the most recently modified Copilot session and writes a summary
to the Obsidian copilot-sessions vault.

Called automatically by the zsh copilot() wrapper after gh copilot exits.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SESSIONS_DIR = Path.home() / ".copilot" / "session-state"
VAULT_DIR = Path.home() / "copilot-sessions" / "sessions"



def find_latest_session() -> Path | None:
    """Return the session directory most recently written to."""
    candidates = []
    for d in SESSIONS_DIR.iterdir():
        events = d / "events.jsonl"
        if events.exists():
            candidates.append((events.stat().st_mtime, d))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def load_workspace(session_dir: Path) -> dict:
    ws = session_dir / "workspace.yaml"
    if not ws.exists():
        return {}
    data = {}
    for line in ws.read_text().splitlines():
        if ": " in line:
            k, _, v = line.partition(": ")
            data[k.strip()] = v.strip()
    return data


def extract_messages(events_path: Path) -> list[dict]:
    """Extract user and assistant messages from events.jsonl."""
    messages = []
    seen_message_ids: set[str] = set()

    with events_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            data = event.get("data", {})

            if etype == "user.message":
                content = data.get("content", "").strip()
                if content:
                    messages.append({"role": "user", "content": content})

            elif etype == "assistant.message":
                content = data.get("content", "").strip()
                message_id = data.get("messageId", "")
                if content and message_id not in seen_message_ids:
                    seen_message_ids.add(message_id)
                    messages.append({"role": "assistant", "content": content})

    return messages


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:60]


def build_session_section(messages: list[dict], workspace: dict, session_id: str, section_num: int) -> str:
    """Build a single session block (no frontmatter). Used for both new and updated sections."""
    title = workspace.get("summary", "Copilot Session")
    cwd = workspace.get("cwd", "~")
    repo = workspace.get("repository", "")
    branch = workspace.get("branch", "")
    created_at = workspace.get("created_at", "")

    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            created_display = dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            created_display = created_at
    else:
        created_display = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    user_messages = [m for m in messages if m["role"] == "user"]
    ai_messages = [m for m in messages if m["role"] == "assistant"]

    lines = [
        f"## Session {section_num}: {title}",
        f"<!-- session_id: {session_id} -->",
        "",
        "### Metadata",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Date | {created_display} |",
        f"| Working Directory | `{cwd}` |",
    ]
    if repo:
        lines.append(f"| Repository | `{repo}` |")
    if branch:
        lines.append(f"| Branch | `{branch}` |")
    lines += [
        f"| Messages | {len(user_messages)} user / {len(ai_messages)} AI turns |",
        f"| Session ID | `{session_id}` |",
        "",
        "### Conversation",
        "",
    ]

    for msg in messages:
        if msg["role"] == "user":
            lines.append(f"**🧑 You:** {msg['content']}")
            lines.append("")
        else:
            content = msg["content"]
            snippet = (content[:300].rstrip() + "…") if len(content) > 300 else content
            lines.append(f"**🤖 Copilot:** {snippet}")
            lines.append("")

    return "\n".join(lines)


def build_daily_file(messages: list[dict], workspace: dict, session_id: str, date_prefix: str, prev_stem: str | None = None) -> str:
    """Build a new daily file with the first session."""
    nav = f"**← [[{prev_stem}]]** | → *(next)*" if prev_stem else "← *(first)* | → *(next)*"
    section = build_session_section(messages, workspace, session_id, 1)
    lines = [
        "---",
        f'title: "{date_prefix}"',
        f'date: "{date_prefix}"',
        "tags:",
        "  - copilot-session",
        "  - ai",
        "---",
        "",
        nav,
        "",
        f"# {date_prefix}",
        "",
        section,
        "",
        "---",
        "*Auto-generated by `~/.copilot/scripts/summarize-session.py`*",
    ]
    return "\n".join(lines)


_FOOTER = "---\n*Auto-generated by `~/.copilot/scripts/summarize-session.py`*"


def rebuild_daily_summary(file_path: Path, prose: str | None = None) -> None:
    """Regenerate the ## Summary block after the # heading in a daily file.

    If prose is provided, it replaces any existing prose section.
    If prose is None, any existing prose between the markers is preserved.
    """
    content = file_path.read_text()

    # Parse all session blocks
    sessions = []
    for m in re.finditer(
        r"^## Session (\d+): (.+)\n<!-- session_id: ([a-f0-9-]+) -->",
        content, re.MULTILINE,
    ):
        num, title, sid = m.group(1), m.group(2), m.group(3)
        after = content[m.end():]
        time_m = re.search(r"\| Date \| (.+?) \|", after)
        msgs_m = re.search(r"\| Messages \| (.+?) \|", after)
        first_q_m = re.search(r"\*\*🧑 You:\*\* (.+)", after)

        raw_time = time_m.group(1).strip() if time_m else ""
        ts = re.search(r"(\d{2}:\d{2} UTC)", raw_time)
        time_short = ts.group(1) if ts else raw_time

        msgs = msgs_m.group(1).strip() if msgs_m else ""
        first_q = (first_q_m.group(1).strip()[:80] + "…") if first_q_m and len(first_q_m.group(1).strip()) > 80 else (first_q_m.group(1).strip() if first_q_m else "")

        sessions.append({"num": num, "title": title, "time": time_short, "msgs": msgs, "first_q": first_q})

    if not sessions:
        return

    # Preserve existing prose if no new prose provided
    existing_prose = ""
    prose_m = re.search(r"<!-- prose_start -->\n(.*?)\n<!-- prose_end -->", content, re.DOTALL)
    if prose is None:
        existing_prose = prose_m.group(1).strip() if prose_m else ""
    else:
        existing_prose = prose.strip()

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n = len(sessions)

    lines = [
        "## Summary",
        "",
        f"> *{n} session{'s' if n != 1 else ''} · updated {updated_at}*",
        "",
        "| # | Session | Time | Turns | Opening question |",
        "|---|---|---|---|---|",
    ]
    for s in sessions:
        lines.append(f"| {s['num']} | {s['title']} | {s['time']} | {s['msgs']} | {s['first_q']} |")

    if existing_prose:
        lines += [
            "",
            "<!-- prose_start -->",
            existing_prose,
            "<!-- prose_end -->",
        ]

    summary_block = "\n".join(lines)

    if "## Summary" in content:
        # Replace existing summary block (up to the next ## Session heading)
        updated = re.sub(
            r"## Summary\n.*?(?=\n## Session \d+:)",
            summary_block + "\n",
            content,
            flags=re.DOTALL,
        )
    else:
        # Insert after "# YYYY-MM-DD\n\n"
        updated = re.sub(
            r"(# \d{4}-\d{2}-\d{2}\n\n)",
            rf"\1{summary_block}\n\n",
            content,
        )

    file_path.write_text(updated)


def append_session_to_daily(file_path: Path, messages: list[dict], workspace: dict, session_id: str) -> None:
    """Append a new session section to an existing daily file."""
    content = file_path.read_text()
    section_num = len(re.findall(r"^## Session \d+:", content, re.MULTILINE)) + 1
    section = build_session_section(messages, workspace, session_id, section_num)
    new_content = content.replace(_FOOTER, f"---\n\n{section}\n\n{_FOOTER}")
    if new_content == content:
        file_path.write_text(content.rstrip() + f"\n\n---\n\n{section}\n\n{_FOOTER}\n")
    else:
        file_path.write_text(new_content)
    rebuild_daily_summary(file_path)


def update_session_in_daily(file_path: Path, messages: list[dict], workspace: dict, session_id: str) -> None:
    """Replace the existing section for session_id in a daily file."""
    content = file_path.read_text()
    # Find section number from the existing marker
    match = re.search(rf"^(## Session (\d+): .+)\n<!-- session_id: {re.escape(session_id)} -->", content, re.MULTILINE)
    if not match:
        # Marker not found — fall back to append
        append_session_to_daily(file_path, messages, workspace, session_id)
        return
    section_num = int(match.group(2))
    new_section = build_session_section(messages, workspace, session_id, section_num)
    # Replace from the ## Session line up to (but not including) the next ## Session or footer
    pattern = rf"## Session {section_num}: .+\n<!-- session_id: {re.escape(session_id)} -->.*?(?=\n## Session \d+:|\n{re.escape('---')})"
    updated = re.sub(pattern, new_section, content, flags=re.DOTALL)
    file_path.write_text(updated)
    rebuild_daily_summary(file_path)


def find_prev_note(vault_dir: Path, current_filename: str) -> Path | None:
    """Return the most recent existing note that sorts before current_filename."""
    notes = sorted(p for p in vault_dir.glob("*.md") if p.name != current_filename)
    if not notes:
        return None
    # Notes sort chronologically by filename (YYYY-MM-DD-slug.md)
    candidates = [n for n in notes if n.name < current_filename]
    return candidates[-1] if candidates else None


def patch_next_link(prev_path: Path, next_stem: str) -> None:
    """Append a → next link to the bottom of the previous note if not already there."""
    content = prev_path.read_text()
    marker = f"→ [[{next_stem}]]"
    if marker in content:
        return
    # Replace the footer line so nav stays at the very bottom
    footer = "---\n*Auto-generated by `~/.copilot/scripts/summarize-session.py`*"
    new_footer = f"---\n← prev | **→ [[{next_stem}]]**\n\n*Auto-generated by `~/.copilot/scripts/summarize-session.py`*"
    if footer in content:
        prev_path.write_text(content.replace(footer, new_footer))
    else:
        prev_path.write_text(content.rstrip() + f"\n\n→ [[{next_stem}]]\n")



def _git_commit_session(file_path: Path) -> None:
    """Commit and push the session summary to the copilot-sessions git repo."""
    import subprocess
    repo_dir = file_path.parent.parent  # sessions/ -> repo root
    try:
        subprocess.run(["git", "add", str(file_path)], cwd=repo_dir, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir, capture_output=True
        )
        if result.returncode != 0:  # there are staged changes
            subprocess.run(
                ["git", "commit", "-m", f"session: add {file_path.stem}"],
                cwd=repo_dir, check=True, capture_output=True
            )
            print(f"✅ Session committed to git (push handled by fswatch)")
    except Exception as e:
        print(f"⚠️  Could not git-commit session summary: {e}", file=sys.stderr)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id", nargs="?", help="Session ID to summarise")
    parser.add_argument("--prose", help="Human prose summary to embed below the summary table")
    parser.add_argument(
        "--learnings",
        help="Newline-separated explicit learning statements to sync to Notion (skips auto-extraction)",
    )
    args = parser.parse_args()

    if args.session_id:
        session_id = args.session_id
        session_dir = SESSIONS_DIR / session_id
        if not session_dir.exists():
            print(f"Session not found: {session_id}", file=sys.stderr)
            sys.exit(1)
    else:
        session_dir = find_latest_session()
        if not session_dir:
            print("No sessions found.", file=sys.stderr)
            sys.exit(1)
        session_id = session_dir.name

    workspace = load_workspace(session_dir)
    events_path = session_dir / "events.jsonl"

    if not events_path.exists():
        print(f"No events found for session {session_id}", file=sys.stderr)
        sys.exit(1)

    messages = extract_messages(events_path)
    if not messages:
        print(f"No messages in session {session_id}", file=sys.stderr)
        sys.exit(0)

    # Determine output filename
    # Determine output filename — date-only for same-day squashing
    raw_title = workspace.get("summary", "session")
    date_prefix = ""
    created_at = workspace.get("created_at", "")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            date_prefix = dt.strftime("%Y-%m-%d")
        except ValueError:
            date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    filename = f"{date_prefix}.md"
    output_path = VAULT_DIR / filename

    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        content = output_path.read_text()
        if session_id in content:
            update_session_in_daily(output_path, messages, workspace, session_id)
            print(f"✅ Session updated in: {output_path}")
        else:
            append_session_to_daily(output_path, messages, workspace, session_id)
            print(f"✅ Session appended to: {output_path}")
        if args.prose:
            rebuild_daily_summary(output_path, prose=args.prose)
            print(f"📝 Prose summary updated.")
    else:
        # New daily file — find prev for nav links
        prev_note = find_prev_note(VAULT_DIR, filename)
        prev_stem = prev_note.stem if prev_note else None
        output_path.write_text(build_daily_file(messages, workspace, session_id, date_prefix, prev_stem=prev_stem))
        rebuild_daily_summary(output_path, prose=args.prose)
        print(f"✅ Session saved: {output_path}")
        if prev_note:
            patch_next_link(prev_note, date_prefix)

    # Auto-commit the session summary to git
    _git_commit_session(output_path)

    # Extract learnings and post to Notion vault
    date_prefix_str = date_prefix  # already computed above
    explicit_learnings = (
        [l.strip() for l in args.learnings.splitlines() if l.strip()]
        if args.learnings
        else None
    )
    learnings = extract_learnings(messages, explicit=explicit_learnings)
    post_to_notion_vault(raw_title, learnings, date_prefix_str, session_id)


if __name__ == "__main__":
    main()
