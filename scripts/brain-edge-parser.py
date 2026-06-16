#!/usr/bin/env python3
"""
brain-edge-parser.py — Edge extraction and wiki-link resolution for the brain graph.

Imported by brain-graph-sync.py and brain-graph-query.py.
Vault: ~/eroad-brain/ (~823 .md files, ~6K wiki-links).
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

EDGE_WEIGHTS: dict[str, float] = {
    "wiki_link": 1.0,
    "yaml_dep": 1.5,
    "folder_sibling": 0.3,
}

# ---------------------------------------------------------------------------
# Wiki-link extraction
# ---------------------------------------------------------------------------

_WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)")


def extract_wiki_links(content: str) -> list[tuple[str, str]]:
    """Return [(raw_target, target_basename), ...] for all wiki-links in content."""
    results: list[tuple[str, str]] = []
    for m in _WIKI_LINK_RE.finditer(content):
        raw = m.group(1).strip()
        if not raw:
            continue
        basename = Path(raw).name
        if basename.lower().endswith(".md"):
            basename = basename[:-3]
        results.append((raw, basename))
    return results


# ---------------------------------------------------------------------------
# Wiki-link resolution
# ---------------------------------------------------------------------------

def resolve_wiki_link(
    raw_target: str,
    basename_lookup: dict[str, list[str]],
) -> str:
    """Resolve a raw wiki-link target to a node ID.

    Resolution order:
      1. Exact basename match (case-insensitive).
      2. Path-hint disambiguation when multiple candidates exist.
      3. First candidate (deterministic fallback).
      4. _unresolved/<raw_target> placeholder if no match.
    """
    # Derive basename from link (handles [[path/to/page]] form)
    raw_stripped = raw_target.strip()
    basename = Path(raw_stripped).name
    if basename.lower().endswith(".md"):
        basename = basename[:-3]

    key = basename.lower()
    candidates = basename_lookup.get(key)

    if not candidates:
        return f"_unresolved/{raw_stripped}"

    if len(candidates) == 1:
        return candidates[0]

    # --- Path-hint disambiguation ---
    # If the link contained a directory component, use it to prefer a matching node.
    parts = Path(raw_stripped).parts
    if len(parts) > 1:
        path_hint = str(Path(*parts[:-1])).lower()
        for node_id in candidates:
            if path_hint in node_id.lower():
                return node_id

    # Deterministic fallback: first candidate
    return candidates[0]


# ---------------------------------------------------------------------------
# YAML frontmatter dependency extraction
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL
)
_DEP_KEY_RE = re.compile(r"^depends[_-]on\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.+)$", re.MULTILINE)


def extract_yaml_deps(content: str) -> list[str]:
    """Return list of dependency names declared in YAML frontmatter.

    Supports:
      depends_on: [a, b]   (inline list)
      depends-on:          (block list)
        - a
        - b
    """
    fm_match = _FRONTMATTER_RE.match(content)
    if not fm_match:
        return []

    frontmatter = fm_match.group(1)
    dep_match = _DEP_KEY_RE.search(frontmatter)
    if not dep_match:
        return []

    value = dep_match.group(1).strip()

    # Inline list: [a, b, c]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]

    # Block list: value is empty or has items on following lines
    # Grab everything after the key until the next non-indented key
    dep_key_pos = dep_match.start()
    after_key = frontmatter[dep_key_pos:]
    # Collect consecutive list items
    items = _LIST_ITEM_RE.findall(after_key)
    return [item.strip().strip("'\"") for item in items]


# ---------------------------------------------------------------------------
# Folder sibling computation
# ---------------------------------------------------------------------------

def compute_folder_siblings(
    nodes: list[tuple[str, str]],
    max_dir_size: int = 20,
) -> list[tuple[str, str]]:
    """Return [(node_id_a, node_id_b), ...] for files sharing the same parent dir.

    Skips directories with more than max_dir_size files (too noisy).
    Edges are undirected — each pair appears once (a < b lexicographically).
    """
    dir_map: dict[str, list[str]] = defaultdict(list)
    for node_id, rel_path in nodes:
        parent = str(Path(rel_path).parent)
        dir_map[parent].append(node_id)

    pairs: list[tuple[str, str]] = []
    for siblings in dir_map.values():
        if len(siblings) > max_dir_size:
            continue
        for i, a in enumerate(siblings):
            for b in siblings[i + 1 :]:
                pairs.append((a, b) if a <= b else (b, a))

    return pairs


# ---------------------------------------------------------------------------
# Composite edge extractor
# ---------------------------------------------------------------------------

def extract_all_edges(
    content: str,
    source_id: str,
    basename_lookup: dict[str, list[str]],
    rel_path: str,
    all_nodes: list[tuple[str, str]],
) -> list[dict]:
    """Return all edges originating from source_id.

    Edge dict: {'source': str, 'target': str, 'type': str, 'weight': float}
    Includes wiki_link, yaml_dep edges.
    Folder sibling edges are computed separately via compute_folder_siblings().
    """
    edges: list[dict] = []
    seen: set[str] = set()

    def _add(target: str, edge_type: str) -> None:
        key = f"{edge_type}:{target}"
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "source": source_id,
                "target": target,
                "type": edge_type,
                "weight": EDGE_WEIGHTS[edge_type],
            }
        )

    # Wiki-link edges
    for raw_target, _basename in extract_wiki_links(content):
        resolved = resolve_wiki_link(raw_target, basename_lookup)
        if resolved != source_id:  # no self-loops
            _add(resolved, "wiki_link")

    # YAML dep edges
    for dep in extract_yaml_deps(content):
        resolved = resolve_wiki_link(dep, basename_lookup)
        if resolved != source_id:
            _add(resolved, "yaml_dep")

    return edges


# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------

def _run_tests() -> int:
    """Run built-in test suite. Returns number of failures."""
    failures = 0

    def check(label: str, condition: bool) -> None:
        nonlocal failures
        status = "PASS" if condition else "FAIL"
        if not condition:
            failures += 1
        print(f"  [{status}] {label}")

    # Build a sample basename_lookup
    sample_nodes: dict[str, list[str]] = {
        "media-service": [
            "eroad/01 - Services/media-service",
        ],
        "configuration-core": [
            "eroad/01 - Services/configuration-core",
            "eroad/02 - Libraries/configuration-core",
        ],
    }

    print("=== Test 1: Simple wiki-link resolution ===")
    result = resolve_wiki_link("media-service", sample_nodes)
    check(
        "[[media-service]] → eroad/01 - Services/media-service",
        result == "eroad/01 - Services/media-service",
    )

    print("=== Test 2: Path-qualified link ===")
    result = resolve_wiki_link("01 - Services/media-service", sample_nodes)
    check(
        "[[01 - Services/media-service]] → eroad/01 - Services/media-service",
        result == "eroad/01 - Services/media-service",
    )

    print("=== Test 3: Case-insensitive match ===")
    result = resolve_wiki_link("Media-Service", sample_nodes)
    check(
        "[[Media-Service]] resolves (case-insensitive)",
        result == "eroad/01 - Services/media-service",
    )

    print("=== Test 4: Unresolved link ===")
    result = resolve_wiki_link("nonexistent-thing", sample_nodes)
    check(
        "[[nonexistent-thing]] → _unresolved/nonexistent-thing",
        result == "_unresolved/nonexistent-thing",
    )

    print("=== Test 5: Disambiguation by path hint ===")
    result = resolve_wiki_link("02 - Libraries/configuration-core", sample_nodes)
    check(
        "[[02 - Libraries/configuration-core]] → eroad/02 - Libraries/configuration-core",
        result == "eroad/02 - Libraries/configuration-core",
    )

    print("=== Test 6: Wiki-link extraction from mixed markdown ===")
    sample_md = textwrap.dedent(
        """\
        See [[media-service]] for details.
        Also [[01 - Services/media-service|Media Service]] and [[configuration-core#setup]].
        Not a link: [regular link](http://example.com)
        """
    )
    links = extract_wiki_links(sample_md)
    raw_targets = [r for r, _ in links]
    basenames = [b for _, b in links]
    check("3 wiki-links found", len(links) == 3)
    check("first raw_target is 'media-service'", raw_targets[0] == "media-service")
    check(
        "second raw_target is '01 - Services/media-service'",
        raw_targets[1] == "01 - Services/media-service",
    )
    check("third basename is 'configuration-core'", basenames[2] == "configuration-core")

    print("=== Test 7: YAML frontmatter extraction ===")
    inline_yaml = textwrap.dedent(
        """\
        ---
        title: Test Page
        depends_on: [service-a, service-b, service-c]
        tags: [test]
        ---
        Body content.
        """
    )
    deps = extract_yaml_deps(inline_yaml)
    check("inline list: 3 deps found", len(deps) == 3)
    check("inline list: service-b present", "service-b" in deps)

    block_yaml = textwrap.dedent(
        """\
        ---
        title: Block Deps
        depends-on:
          - alpha
          - beta
        ---
        """
    )
    deps2 = extract_yaml_deps(block_yaml)
    check("block list: 2 deps found", len(deps2) == 2)
    check("block list: alpha present", "alpha" in deps2)

    no_fm = "No frontmatter here.\n[[some-link]]"
    check("no frontmatter → empty list", extract_yaml_deps(no_fm) == [])

    print("=== Test 8: Folder sibling computation ===")
    # 3 files in same dir → 3 pairs; 1 file alone → 0 extra pairs
    test_nodes: list[tuple[str, str]] = [
        ("a", "docs/a.md"),
        ("b", "docs/b.md"),
        ("c", "docs/c.md"),
        ("d", "other/d.md"),
    ]
    pairs = compute_folder_siblings(test_nodes, max_dir_size=20)
    check("3 sibling pairs for 3-file dir", len(pairs) == 3)
    check("lone file contributes no pairs", ("d", "other/d.md") not in pairs)

    # Directory exceeding max_dir_size is skipped
    big_dir_nodes: list[tuple[str, str]] = [
        (f"node-{i}", f"big/{i}.md") for i in range(25)
    ]
    big_pairs = compute_folder_siblings(big_dir_nodes, max_dir_size=20)
    check("dir >20 files skipped (0 pairs)", len(big_pairs) == 0)

    return failures


if __name__ == "__main__":
    import textwrap

    args = sys.argv[1:]
    if "--test" in args:
        print("Running brain-edge-parser self-tests…\n")
        failed = _run_tests()
        print(f"\n{'All tests passed.' if failed == 0 else f'{failed} test(s) FAILED.'}")
        sys.exit(0 if failed == 0 else 1)
    else:
        print(
            "brain-edge-parser.py — importable module. Run with --test for self-tests.",
            file=sys.stderr,
        )
        sys.exit(0)
else:
    # When imported, textwrap is not guaranteed — import lazily where needed.
    import textwrap  # noqa: E402 (used in _run_tests only)
