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
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SESSIONS_DIR = Path.home() / ".copilot" / "session-state"
VAULT_DIR = Path.home() / "Library" / "CloudStorage" / "OneDrive-EROAD" / "Documents" / "copilot-sessions" / "sessions"

NOTION_TOKEN = "YOUR_NOTION_TOKEN"
NOTION_VAULT_PAGE_ID = "33ff43d1-71ee-81fd-a2be-c733d2a4f837"
NOTION_LEARNINGS_TITLE = "Key Learnings & Findings"
NOTION_STATE_FILE = Path.home() / ".copilot" / "notion-vault-state.json"


def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _notion_request(url: str, payload: dict | None = None, method: str | None = None) -> dict:
    if method is None:
        method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=_notion_headers(),
        method=method,
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())


def get_or_create_learnings_page() -> str:
    """Return the Notion page ID for the central learnings page, creating it if needed."""
    if NOTION_STATE_FILE.exists():
        state = json.loads(NOTION_STATE_FILE.read_text())
        if page_id := state.get("learnings_page_id"):
            return page_id

    result = _notion_request(
        "https://api.notion.com/v1/pages",
        {
            "parent": {"page_id": NOTION_VAULT_PAGE_ID},
            "icon": {"emoji": "💡"},
            "properties": {
                "title": {"title": [{"type": "text", "text": {"content": NOTION_LEARNINGS_TITLE}}]}
            },
            "children": [{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {
                        "content": "Auto-synced key learnings and findings from Copilot sessions. Duplicates are skipped."
                    }}]
                },
            }],
        },
    )
    page_id = result["id"]
    NOTION_STATE_FILE.write_text(json.dumps({"learnings_page_id": page_id}))
    return page_id


def fetch_all_blocks(page_id: str) -> list[dict]:
    """Fetch all child blocks from a Notion page, handling pagination."""
    blocks = []
    cursor = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        req = urllib.request.Request(url, headers=_notion_headers())
        with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=15) as resp:
            data = json.loads(resp.read())
        blocks.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return blocks


def existing_bullets_from_blocks(blocks: list[dict]) -> set[str]:
    """Extract the text of all bulleted_list_item blocks."""
    existing: set[str] = set()
    for block in blocks:
        if block.get("type") == "bulleted_list_item":
            texts = block["bulleted_list_item"].get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in texts).strip()
            if text:
                existing.add(text)
    return existing


def find_todays_section(blocks: list[dict], date_str: str) -> tuple[str | None, str | None]:
    """
    Find an existing callout section whose text starts with date_str.
    Returns (callout_block_id, last_block_id_in_section) so new bullets can be
    appended after last_block_id_in_section using Notion's `after` parameter.
    Returns (None, None) if no section exists for today.
    """
    callout_idx = None
    callout_id = None
    for i, block in enumerate(blocks):
        if block.get("type") == "callout":
            texts = block["callout"].get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in texts)
            if text.startswith(date_str):
                callout_idx = i
                callout_id = block["id"]
                break

    if callout_idx is None:
        return None, None

    # Walk forward until the next divider (or end) to find the last block in this section.
    last_block_id = callout_id
    for block in blocks[callout_idx + 1:]:
        if block.get("type") == "divider":
            break
        last_block_id = block["id"]

    return callout_id, last_block_id


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
    replacement = new_section
    updated = re.sub(pattern, replacement, content, flags=re.DOTALL)
    file_path.write_text(updated)


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


def extract_learnings(messages: list[dict]) -> list[str]:
    """Extract key learnings from AI messages — bullet points, numbered items, and recommendations."""
    learnings = []
    for msg in messages:
        if msg["role"] != "assistant":
            continue
        for line in msg["content"].split("\n"):
            line = line.strip()
            if re.match(r'^[-*•]\s+.{20,}', line):
                learnings.append(re.sub(r'^[-*•]\s+', '', line))
            elif re.match(r'^\d+[.)]\s+.{20,}', line):
                learnings.append(re.sub(r'^\d+[.)]\s+', '', line))

    # Deduplicate, preserving order
    seen: set[str] = set()
    unique = []
    for item in learnings:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:25]


def post_to_notion_vault(title: str, learnings: list[str], date_str: str, session_id: str) -> None:
    """Sync learnings to the central Notion page.

    Same-day syncs are squashed: new bullets are appended inside the existing
    day's section rather than creating a duplicate header.
    """
    if not learnings:
        print("ℹ️  No learnings extracted — skipping Notion sync.")
        return

    try:
        page_id = get_or_create_learnings_page()
        blocks = fetch_all_blocks(page_id)
        existing = existing_bullets_from_blocks(blocks)
        new_items = [item for item in learnings if item not in existing]

        if not new_items:
            print(f"ℹ️  All {len(learnings)} learnings already in Notion vault — nothing to add.")
            return

        bullet_blocks = [
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": item[:2000]}}]
                },
            }
            for item in new_items
        ]

        _, last_block_id = find_todays_section(blocks, date_str)

        if last_block_id:
            # Squash into the existing today section — insert after the last block in it
            _notion_request(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                {"children": bullet_blocks, "after": last_block_id},
                method="PATCH",
            )
            print(f"💡 Added {len(new_items)} new learnings to today's Notion section (skipped {len(learnings) - len(new_items)} duplicates).")
        else:
            # First sync of the day — create a new dated section
            children = [
                {"object": "block", "type": "divider", "divider": {}},
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"type": "text", "text": {"content": f"{date_str} — {title}  (session: {session_id})"}}],
                        "icon": {"emoji": "🗓️"},
                        "color": "gray_background",
                    },
                },
                *bullet_blocks,
            ]
            _notion_request(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                {"children": children},
                method="PATCH",
            )
            print(f"💡 Synced {len(new_items)} new learnings to Notion vault (skipped {len(learnings) - len(new_items)} duplicates).")
    except urllib.error.HTTPError as e:
        print(f"⚠️  Notion API error {e.code}: {e.read().decode()}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️  Could not sync to Notion: {e}", file=sys.stderr)


def main():
    # Allow passing a specific session ID as argument
    if len(sys.argv) > 1:
        session_id = sys.argv[1]
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

    slug = slugify(raw_title)
    filename = f"{date_prefix}-{slug}.md"
    output_path = VAULT_DIR / filename

    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # Find previous note for bidirectional linking
    prev_note = find_prev_note(VAULT_DIR, filename)
    prev_stem = prev_note.stem if prev_note else None

    summary = build_summary(messages, workspace, session_id, prev_stem=prev_stem)
    output_path.write_text(summary)
    print(f"✅ Session saved: {output_path}")

    # Back-patch the → next link onto the previous note
    if prev_note:
        patch_next_link(prev_note, Path(filename).stem)

    # Extract learnings and post to Notion vault
    date_prefix_str = date_prefix  # already computed above
    learnings = extract_learnings(messages)
    post_to_notion_vault(raw_title, learnings, date_prefix_str, session_id)


if __name__ == "__main__":
    main()
