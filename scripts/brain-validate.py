#!/usr/bin/env python3
"""
Brain Validation Pipeline
Cross-validates eroad-brain nodes against actual GitHub code.

Phases:
  1. Match brain service nodes → GitHub repos
  2. For matched repos, fetch key files (pom.xml, build.gradle, package.json, application.yml)
  3. Extract claims from brain nodes (tech stack, language, framework, DB, integrations)
  4. Compare claims vs code reality
  5. Output structured validation report (JSON)

Usage:
  python3 brain-validate.py --db ~/.copilot/brain-graph.db --repos /tmp/eroad-repo-names.txt --output /tmp/brain-validation.json
  python3 brain-validate.py --db ~/.copilot/brain-graph.db --repos /tmp/eroad-repo-names.txt --output /tmp/brain-validation.json --limit 10
  python3 brain-validate.py --db ~/.copilot/brain-graph.db --repos /tmp/eroad-repo-names.txt --output /tmp/brain-validation.json --node "media-service"
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Claim extraction from brain markdown ─────────────────────────────────

def extract_section(content: str, heading: str) -> str:
    """Extract content under a ## heading until the next ## heading."""
    pattern = rf'^## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)'
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_tech_stack(content: str) -> dict:
    """Parse ## Tech Stack section into structured claims."""
    section = extract_section(content, "Tech Stack")
    if not section:
        # Try "## Architecture" as fallback
        section = extract_section(content, "Architecture")
    if not section:
        return {}

    claims = {}
    for line in section.split('\n'):
        line = line.strip()
        if not line.startswith('- '):
            continue
        line = line[2:]

        # Parse **Key:** Value pattern
        m = re.match(r'\*\*(.+?)\*\*:?\s*(.*)', line)
        if m:
            key = m.group(1).strip().rstrip(':').lower()
            val = m.group(2).strip()
            claims[key] = val

    return claims


def extract_language_claim(tech_stack: dict, content: str) -> Optional[str]:
    """Extract primary language from tech stack or content."""
    if 'language' in tech_stack:
        return tech_stack['language']
    # Search content for common patterns
    for lang in ['Java', 'Kotlin', 'TypeScript', 'JavaScript', 'Python', 'Go', 'C#', '.NET']:
        if re.search(rf'\b{lang}\b', content[:2000]):
            return lang
    return None


def extract_java_version(tech_stack: dict) -> Optional[str]:
    """Extract Java version number from tech stack."""
    lang = tech_stack.get('language', '')
    m = re.search(r'Java\s+(\d+)', lang)
    return m.group(1) if m else None


def extract_framework_claim(tech_stack: dict) -> Optional[str]:
    """Extract framework from tech stack."""
    fw = tech_stack.get('framework', '')
    if 'Spring Boot' in fw:
        m = re.search(r'Spring Boot\s+([\d.x]+)', fw)
        return f"Spring Boot {m.group(1)}" if m else "Spring Boot"
    if 'Next.js' in fw or 'React' in fw:
        return fw.split('(')[0].strip()
    return fw if fw else None


def extract_build_tool(tech_stack: dict) -> Optional[str]:
    """Extract build tool."""
    build = tech_stack.get('build', '')
    for tool in ['Maven', 'Gradle', 'npm', 'yarn', 'pnpm', 'dotnet', 'MSBuild']:
        if tool.lower() in build.lower():
            return tool
    return build if build else None


def extract_database_claim(tech_stack: dict) -> Optional[str]:
    """Extract database type."""
    db = tech_stack.get('database', '')
    for dbtype in ['PostgreSQL', 'MySQL', 'DynamoDB', 'MongoDB', 'SQL Server', 'Redis', 'Elasticsearch']:
        if dbtype.lower() in db.lower():
            return dbtype
    return db if db else None


def extract_integrations(content: str) -> list[dict]:
    """Extract integration table entries from brain node."""
    section = extract_section(content, "Integrations")
    if not section:
        return []

    integrations = []
    for line in section.split('\n'):
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 3 and cells[0].upper() in ('IN', 'OUT', 'INBOUND', 'OUTBOUND', 'IN/OUT', 'BIDIRECTIONAL'):
            integrations.append({
                'direction': cells[0].upper(),
                'type': cells[1],
                'target': cells[2],
                'notes': cells[3] if len(cells) > 3 else ''
            })
    return integrations


def extract_related_services(content: str) -> list[str]:
    """Extract [[linked]] service names from Related Services section."""
    section = extract_section(content, "Related Services")
    if not section:
        return []
    return re.findall(r'\[\[.*?/([^\]/]+?)(?:\.md)?\]\]', section)


# ── GitHub code checks ──────────────────────────────────────────────────

def gh_api(endpoint: str, timeout: int = 15) -> Optional[dict]:
    """Call GitHub API via gh CLI."""
    try:
        result = subprocess.run(
            ['gh', 'api', endpoint, '--jq', '.'],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def gh_file_content(owner: str, repo: str, path: str) -> Optional[str]:
    """Fetch file content from GitHub."""
    try:
        result = subprocess.run(
            ['gh', 'api', f'/repos/{owner}/{repo}/contents/{path}',
             '--jq', '.content', '-H', 'Accept: application/vnd.github.v3+json'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            import base64
            return base64.b64decode(result.stdout.strip()).decode('utf-8', errors='replace')
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def detect_language_from_repo(owner: str, repo: str) -> Optional[str]:
    """Get primary language from GitHub repo metadata."""
    data = gh_api(f'/repos/{owner}/{repo}')
    if data and 'language' in data:
        return data['language']
    return None


def check_pom_xml(owner: str, repo: str) -> dict:
    """Extract facts from pom.xml."""
    content = gh_file_content(owner, repo, 'pom.xml')
    if not content:
        return {}

    facts = {'build_tool': 'Maven'}

    # Java version
    for pattern in [
        r'<java\.version>([\d.]+)</java\.version>',
        r'<maven\.compiler\.source>([\d.]+)',
        r'<release>(\d+)</release>',
        r'<source>([\d.]+)</source>',
    ]:
        m = re.search(pattern, content)
        if m:
            ver = m.group(1)
            # Normalize: 1.8 → 8, 1.11 → 11, 17 → 17
            if ver.startswith('1.'):
                ver = ver[2:]
            facts['java_version'] = ver
            break

    # Spring Boot version
    m = re.search(r'<spring-boot\.version>([\d.]+)', content)
    if not m:
        m = re.search(r'spring-boot-starter-parent.*?<version>([\d.]+)', content, re.DOTALL)
    if m:
        facts['spring_boot_version'] = m.group(1)

    # Database dependencies — check actual dependency artifacts, not just any mention
    dep_section = re.findall(r'<dependency>.*?</dependency>', content, re.DOTALL)
    dep_text = '\n'.join(dep_section).lower()
    if 'org.postgresql' in dep_text or 'postgresql</artifactid>' in dep_text:
        facts['database'] = 'PostgreSQL'
    if 'mysql-connector' in dep_text or 'mysql</artifactid>' in dep_text:
        facts['database'] = facts.get('database', '') + ',MySQL' if facts.get('database') else 'MySQL'
    if 'dynamodb' in dep_text:
        facts['database'] = facts.get('database', '') + ',DynamoDB' if facts.get('database') else 'DynamoDB'
    if 'mongodb' in dep_text or 'mongo-java-driver' in dep_text:
        facts['database'] = facts.get('database', '') + ',MongoDB' if facts.get('database') else 'MongoDB'

    # Key dependencies
    deps = []
    for dep_name in ['spring-boot-starter-web', 'spring-boot-starter-data-jpa',
                     'spring-cloud-starter', 'spring-security', 'spring-kafka',
                     'aws-java-sdk', 'software.amazon.awssdk', 'flyway', 'liquibase']:
        if dep_name in content:
            deps.append(dep_name)
    facts['key_deps'] = deps

    return facts


def check_build_gradle(owner: str, repo: str) -> dict:
    """Extract facts from build.gradle or build.gradle.kts."""
    content = gh_file_content(owner, repo, 'build.gradle.kts')
    if not content:
        content = gh_file_content(owner, repo, 'build.gradle')
    if not content:
        return {}

    facts = {'build_tool': 'Gradle'}

    # Java version
    for pattern in [r'jvmToolchain\((\d+)\)', r'JavaVersion\.VERSION_(\d+)',
                    r'sourceCompatibility\s*=\s*["\']?(\d+)', r'java\s*\{[^}]*languageVersion.*?(\d+)']:
        m = re.search(pattern, content)
        if m:
            facts['java_version'] = m.group(1)
            break

    # Spring Boot
    m = re.search(r"spring-boot.*?['\"](\d+\.\d+\.\d+)", content)
    if m:
        facts['spring_boot_version'] = m.group(1)

    if 'postgresql' in content.lower():
        facts['database'] = 'PostgreSQL'
    elif 'mysql' in content.lower():
        facts['database'] = 'MySQL'

    return facts


def check_package_json(owner: str, repo: str) -> dict:
    """Extract facts from package.json."""
    content = gh_file_content(owner, repo, 'package.json')
    if not content:
        return {}
    try:
        pkg = json.loads(content)
    except json.JSONDecodeError:
        return {}

    facts = {'build_tool': 'npm'}
    all_deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}

    if 'next' in all_deps:
        facts['framework'] = f"Next.js {all_deps['next']}"
    elif 'react' in all_deps:
        facts['framework'] = f"React {all_deps['react']}"
    elif 'express' in all_deps:
        facts['framework'] = 'Express'

    if 'typescript' in all_deps:
        facts['language'] = 'TypeScript'
    else:
        facts['language'] = 'JavaScript'

    return facts


def check_application_yml(owner: str, repo: str) -> dict:
    """Check application.yml/properties for DB config."""
    for path in ['src/main/resources/application.yml',
                 'src/main/resources/application.yaml',
                 'src/main/resources/application.properties']:
        content = gh_file_content(owner, repo, path)
        if content:
            facts = {}
            if 'postgresql' in content.lower():
                facts['database_config'] = 'PostgreSQL'
            elif 'mysql' in content.lower():
                facts['database_config'] = 'MySQL'
            elif 'h2' in content.lower() and 'postgresql' not in content.lower():
                facts['database_config'] = 'H2 (test)'
            return facts
    return {}


# ── Matching & Validation ────────────────────────────────────────────────

def match_node_to_repo(node_name: str, repo_names: set[str]) -> Optional[str]:
    """Match a brain node name to a GitHub repo name."""
    # Direct match
    if node_name in repo_names:
        return node_name

    # Try common transformations
    variants = [
        node_name,
        node_name.replace(' ', '-'),
        node_name.lower(),
        node_name.replace(' ', '-').lower(),
        f"eroad-{node_name}",
        node_name.replace('myeroad-', ''),
        node_name.replace('-service', ''),
    ]
    for v in variants:
        if v in repo_names:
            return v

    # Fuzzy: check if node name is a substring of any repo
    matches = [r for r in repo_names if node_name.lower() in r.lower()]
    if len(matches) == 1:
        return matches[0]

    return None


@dataclass
class ValidationResult:
    node_path: str
    node_name: str
    matched_repo: Optional[str] = None
    repo_exists: bool = False
    repo_archived: bool = False
    findings: list = field(default_factory=list)
    claims: dict = field(default_factory=dict)
    code_facts: dict = field(default_factory=dict)
    status: str = "pending"  # pending, matched, unmatched, validated, error
    discrepancies: list = field(default_factory=list)
    confirmations: list = field(default_factory=list)


def validate_service(node_path: str, content: str, repo_names: set[str],
                     archived_repos: set[str], owner: str = "eroad",
                     skip_api: bool = False) -> ValidationResult:
    """Validate a single service node against GitHub code."""
    # Extract node name from path
    node_name = os.path.splitext(os.path.basename(node_path))[0]
    result = ValidationResult(node_path=node_path, node_name=node_name)

    # 1. Match to repo
    matched = match_node_to_repo(node_name, repo_names)
    if not matched:
        result.status = "unmatched"
        result.findings.append(f"No GitHub repo found matching '{node_name}'")
        return result

    result.matched_repo = matched
    result.repo_exists = True
    result.status = "matched"

    if matched in archived_repos:
        result.repo_archived = True
        result.findings.append(f"Repo '{matched}' is archived")

    # 2. Extract claims from brain
    tech_stack = extract_tech_stack(content)
    result.claims = {
        'language': extract_language_claim(tech_stack, content),
        'java_version': extract_java_version(tech_stack),
        'framework': extract_framework_claim(tech_stack),
        'build_tool': extract_build_tool(tech_stack),
        'database': extract_database_claim(tech_stack),
        'integrations_count': len(extract_integrations(content)),
        'related_services': extract_related_services(content),
    }

    if skip_api:
        result.status = "matched_no_api"
        return result

    # 3. Fetch code facts (rate-limited)
    time.sleep(0.5)  # Rate limiting

    # Check repo language
    repo_data = gh_api(f'/repos/{owner}/{matched}')
    if repo_data:
        result.code_facts['github_language'] = repo_data.get('language')
        result.code_facts['github_archived'] = repo_data.get('archived', False)
        result.code_facts['github_description'] = repo_data.get('description', '')

    # Check build files based on expected language
    pom_facts = check_pom_xml(owner, matched)
    if pom_facts:
        result.code_facts.update(pom_facts)
    else:
        gradle_facts = check_build_gradle(owner, matched)
        if gradle_facts:
            result.code_facts.update(gradle_facts)
        else:
            pkg_facts = check_package_json(owner, matched)
            if pkg_facts:
                result.code_facts.update(pkg_facts)

    # Check application config
    app_facts = check_application_yml(owner, matched)
    result.code_facts.update(app_facts)

    # 4. Compare claims vs code
    result.status = "validated"

    # Language check
    claimed_lang = result.claims.get('language')
    code_lang = result.code_facts.get('github_language') or result.code_facts.get('language')
    if claimed_lang and code_lang:
        if claimed_lang.lower().replace('typescript', 'javascript') != code_lang.lower().replace('typescript', 'javascript'):
            # More nuanced check
            lang_map = {'java': 'java', 'kotlin': 'kotlin', 'typescript': 'typescript',
                        'javascript': 'javascript', 'python': 'python', 'c#': 'c#', '.net': 'c#', 'go': 'go'}
            claim_norm = lang_map.get(claimed_lang.split()[0].lower(), claimed_lang.lower())
            code_norm = lang_map.get(code_lang.lower(), code_lang.lower())
            if claim_norm != code_norm:
                result.discrepancies.append({
                    'field': 'language',
                    'claimed': claimed_lang,
                    'actual': code_lang,
                    'severity': 'HIGH'
                })
            else:
                result.confirmations.append(f"Language: {claimed_lang} ✓")
        else:
            result.confirmations.append(f"Language: {claimed_lang} ✓")

    # Java version
    claimed_java = result.claims.get('java_version')
    code_java = result.code_facts.get('java_version')
    if claimed_java and code_java:
        if claimed_java != code_java:
            result.discrepancies.append({
                'field': 'java_version',
                'claimed': f"Java {claimed_java}",
                'actual': f"Java {code_java}",
                'severity': 'MEDIUM'
            })
        else:
            result.confirmations.append(f"Java version: {claimed_java} ✓")

    # Build tool
    claimed_build = result.claims.get('build_tool')
    code_build = result.code_facts.get('build_tool')
    if claimed_build and code_build:
        if claimed_build.lower() != code_build.lower():
            result.discrepancies.append({
                'field': 'build_tool',
                'claimed': claimed_build,
                'actual': code_build,
                'severity': 'MEDIUM'
            })
        else:
            result.confirmations.append(f"Build tool: {claimed_build} ✓")

    # Database
    claimed_db = result.claims.get('database')
    code_db = result.code_facts.get('database') or result.code_facts.get('database_config')
    if code_db and not claimed_db:
        # Brain says no DB, but code has DB dependency
        result.discrepancies.append({
            'field': 'database',
            'claimed': 'None / not mentioned',
            'actual': f"{code_db} dependency found in build file",
            'severity': 'HIGH'
        })
    elif claimed_db and code_db:
        # Both claim a DB — check they match (handle multi-DB: "PostgreSQL,DynamoDB")
        code_dbs = set(d.strip().lower() for d in code_db.split(','))
        if claimed_db.lower() not in code_dbs:
            result.discrepancies.append({
                'field': 'database',
                'claimed': claimed_db,
                'actual': code_db,
                'severity': 'HIGH'
            })
        else:
            result.confirmations.append(f"Database: {claimed_db} ✓")

    # Spring Boot major version check
    claimed_fw = result.claims.get('framework', '') or ''
    code_sb = result.code_facts.get('spring_boot_version', '')
    if 'Spring Boot' in claimed_fw and code_sb:
        claimed_major = re.search(r'(\d+)', claimed_fw.replace('Spring Boot', ''))
        code_major = code_sb.split('.')[0] if code_sb else None
        if claimed_major and code_major:
            if claimed_major.group(1) != code_major:
                result.discrepancies.append({
                    'field': 'spring_boot_version',
                    'claimed': claimed_fw,
                    'actual': f"Spring Boot {code_sb}",
                    'severity': 'MEDIUM'
                })
            else:
                result.confirmations.append(f"Spring Boot major version: {code_major}.x ✓")

    return result


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Brain Validation Pipeline")
    parser.add_argument('--db', required=True, help='Path to brain-graph.db')
    parser.add_argument('--repos', required=True, help='Path to repo names file')
    parser.add_argument('--output', required=True, help='Output JSON path')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of nodes to validate (0=all)')
    parser.add_argument('--node', type=str, default='', help='Validate a single node by name')
    parser.add_argument('--skip-api', action='store_true', help='Skip GitHub API calls (matching only)')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    # Load repo names
    with open(args.repos) as f:
        repo_names = set(line.strip() for line in f if line.strip())
    print(f"Loaded {len(repo_names)} GitHub repo names")

    # Load archived repos from cached data
    archived_repos = set()
    if os.path.exists('/tmp/eroad-repos.tsv'):
        with open('/tmp/eroad-repos.tsv') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 3 and parts[2] == 'true':
                    archived_repos.add(parts[0])
    print(f"Known archived repos: {len(archived_repos)}")

    # Load brain nodes
    conn = sqlite3.connect(args.db)
    c = conn.cursor()

    if args.node:
        c.execute(
            "SELECT rel_path, content FROM nodes WHERE vault='eroad-brain' "
            "AND rel_path LIKE '01 - Services/%.md' AND rel_path LIKE ?",
            (f'%{args.node}%',)
        )
    else:
        c.execute(
            "SELECT rel_path, content FROM nodes WHERE vault='eroad-brain' "
            "AND rel_path LIKE '01 - Services/%.md' "
            "ORDER BY length(content) DESC"
        )

    nodes = c.fetchall()
    conn.close()

    if args.limit > 0:
        nodes = nodes[:args.limit]

    print(f"Validating {len(nodes)} service nodes...")
    print()

    results = []
    stats = {'total': 0, 'matched': 0, 'unmatched': 0, 'discrepancies': 0,
             'confirmations': 0, 'api_validated': 0, 'archived': 0}

    for i, (path, content) in enumerate(nodes, 1):
        node_name = os.path.splitext(os.path.basename(path))[0]
        print(f"[{i}/{len(nodes)}] {node_name}...", end=' ', flush=True)

        result = validate_service(path, content or '', repo_names, archived_repos,
                                  skip_api=args.skip_api)
        results.append(asdict(result))

        stats['total'] += 1
        if result.repo_exists:
            stats['matched'] += 1
            if result.repo_archived:
                stats['archived'] += 1
        else:
            stats['unmatched'] += 1
        stats['discrepancies'] += len(result.discrepancies)
        stats['confirmations'] += len(result.confirmations)
        if result.status == 'validated':
            stats['api_validated'] += 1

        status_icon = {
            'validated': '✓', 'matched': '~', 'matched_no_api': '~',
            'unmatched': '✗', 'error': '!'
        }.get(result.status, '?')

        disc_str = f" ({len(result.discrepancies)} issues)" if result.discrepancies else ""
        print(f"{status_icon} repo={result.matched_repo or 'NONE'}{disc_str}")

        if args.verbose and result.discrepancies:
            for d in result.discrepancies:
                print(f"    ⚠ {d['field']}: claimed={d['claimed']}, actual={d['actual']} [{d['severity']}]")

    # Write output
    output = {
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'stats': stats,
        'results': results
    }

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)

    print()
    print("═" * 60)
    print(f"  Total nodes:      {stats['total']}")
    print(f"  Matched repos:    {stats['matched']} ({stats['matched']*100//max(stats['total'],1)}%)")
    print(f"  Unmatched:        {stats['unmatched']}")
    print(f"  Archived repos:   {stats['archived']}")
    print(f"  API validated:    {stats['api_validated']}")
    print(f"  Confirmations:    {stats['confirmations']}")
    print(f"  Discrepancies:    {stats['discrepancies']}")
    print("═" * 60)
    print(f"  Output: {args.output}")


if __name__ == '__main__':
    main()
