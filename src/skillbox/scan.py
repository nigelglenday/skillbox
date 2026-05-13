"""Scan the filesystem for skills, slash commands, and subagents.

Skills can live in several locations:

1. ~/.claude/skills/<name>/SKILL.md     — user skill (Anthropic convention)
2. ~/.claude/skills/<name>.md           — single-file user skill
3. ~/.claude/commands/<name>.md         — slash command (single-file)
4. ~/.claude/agents/<name>.md           — subagent definition
5. ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md
                                        — plugin-provided skill
6. <PWD>/.claude/skills/<name>/SKILL.md — project-level skill
7. <PWD>/.claude/commands/<name>.md     — project-level slash command

All are surfaced into Claude Code sessions as triggerable skills. Skillbox
treats them uniformly: name, description (from frontmatter or first
non-front-matter paragraph), source, path, kind.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
USER_SKILLS_DIR = CLAUDE_DIR / "skills"
USER_COMMANDS_DIR = CLAUDE_DIR / "commands"
USER_AGENTS_DIR = CLAUDE_DIR / "agents"
PLUGINS_CACHE_DIR = CLAUDE_DIR / "plugins" / "cache"
PLUGINS_INSTALLED_JSON = CLAUDE_DIR / "plugins" / "installed_plugins.json"


@dataclass
class Skill:
    """One skill / command / agent entry."""

    name: str                  # invocation name
    kind: str                  # "skill", "command", "agent"
    source: str                # "user", "project", "plugin:<plugin>"
    path: Path                 # path to SKILL.md or single .md file
    description: str = ""      # one-line description from frontmatter
    tags: list[str] = field(default_factory=list)
    project_root: Optional[Path] = None  # only set for project-scope skills

    @property
    def source_short(self) -> str:
        if self.source.startswith("plugin:"):
            return self.source.removeprefix("plugin:")
        return self.source

    @property
    def is_user_writable(self) -> bool:
        """Can skillbox safely modify this skill's file directly?"""
        return self.source in ("user", "project")

    @property
    def scope_label(self) -> str:
        """Human-readable availability scope.

        - user / plugin: available in every Claude Code session ("everywhere")
        - project: available only in that project's sessions ("in <path>")
        """
        if self.source == "project" and self.project_root is not None:
            home = str(Path.home())
            root = str(self.project_root)
            if root.startswith(home):
                root = "~" + root[len(home):]
            return f"in {root}/ only"
        if self.source == "user":
            return "everywhere (user-level)"
        if self.source.startswith("plugin:"):
            plugin = self.source.removeprefix("plugin:")
            return f"everywhere (via {plugin} plugin)"
        return self.source


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML-ish frontmatter and the remaining body.

    Looser than full YAML — just key: value pairs between leading `---`
    fences. Returns (metadata_dict, body_text).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, body


def _first_paragraph(body: str, max_len: int = 200) -> str:
    """First non-empty paragraph from body text, single-line."""
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Skip lone heading lines.
        if chunk.startswith("#"):
            continue
        # Collapse whitespace.
        chunk = re.sub(r"\s+", " ", chunk)
        if len(chunk) > max_len:
            chunk = chunk[: max_len - 1] + "…"
        return chunk
    return ""


def _load_skill_file(path: Path, name: str, kind: str, source: str) -> Skill:
    """Parse a SKILL.md / command.md / agent.md file into a Skill record."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Skill(name=name, kind=kind, source=source, path=path)

    meta, body = _parse_frontmatter(text)
    description = meta.get("description", "") or _first_paragraph(body)

    # Tags can be in frontmatter as a comma- or space-separated list.
    tags: list[str] = []
    if "tags" in meta:
        raw = meta["tags"].strip("[]")
        for t in re.split(r"[,\s]+", raw):
            t = t.strip().strip("'\"")
            if t:
                tags.append(t)

    return Skill(
        name=meta.get("name", name),
        kind=kind,
        source=source,
        path=path,
        description=description,
        tags=tags,
    )


def _scan_dir_of_singles(directory: Path, kind: str, source: str) -> list[Skill]:
    """Scan a directory of single-file skills/commands/agents."""
    if not directory.is_dir():
        return []
    out = []
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and entry.suffix == ".md":
            name = entry.stem
            out.append(_load_skill_file(entry, name, kind, source))
    return out


def _scan_dir_of_dirs(directory: Path, kind: str, source: str) -> list[Skill]:
    """Scan a directory of <name>/SKILL.md style skills."""
    if not directory.is_dir():
        return []
    out = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            out.append(_load_skill_file(skill_md, entry.name, kind, source))
    return out


def _scan_plugin_skills() -> list[Skill]:
    """Walk ~/.claude/plugins/cache/ for plugin-provided skills."""
    if not PLUGINS_CACHE_DIR.is_dir():
        return []
    out = []
    for skill_md in PLUGINS_CACHE_DIR.rglob("SKILL.md"):
        # Path shape:
        # cache/<marketplace>/<plugin>/<version>/skills/<skill-name>/SKILL.md
        parts = skill_md.relative_to(PLUGINS_CACHE_DIR).parts
        if len(parts) < 5 or parts[-3] != "skills":
            continue
        plugin = parts[1]
        skill_name = parts[-2]
        out.append(
            _load_skill_file(skill_md, skill_name, "skill", f"plugin:{plugin}")
        )
    return out


def _scan_project_skills(project_root: Path) -> list[Skill]:
    """Scan a project's .claude/ directory."""
    project_claude = project_root / ".claude"
    if not project_claude.is_dir():
        return []
    out: list[Skill] = []
    out.extend(_scan_dir_of_dirs(project_claude / "skills", "skill", "project"))
    out.extend(_scan_dir_of_singles(project_claude / "skills", "skill", "project"))
    out.extend(_scan_dir_of_singles(project_claude / "commands", "command", "project"))
    out.extend(_scan_dir_of_singles(project_claude / "agents", "agent", "project"))
    # Tag project skills with their root for scope_label
    for s in out:
        s.project_root = project_root
    return out


def scan_all(project_root: Optional[Path] = None) -> list[Skill]:
    """Scan every known location for skills, commands, and agents.

    If project_root is provided, also include that project's .claude/.
    """
    out: list[Skill] = []
    out.extend(_scan_dir_of_dirs(USER_SKILLS_DIR, "skill", "user"))
    out.extend(_scan_dir_of_singles(USER_SKILLS_DIR, "skill", "user"))
    out.extend(_scan_dir_of_singles(USER_COMMANDS_DIR, "command", "user"))
    out.extend(_scan_dir_of_singles(USER_AGENTS_DIR, "agent", "user"))
    out.extend(_scan_plugin_skills())
    if project_root:
        out.extend(_scan_project_skills(project_root))
    return out


def installed_plugins() -> list[dict]:
    """Read the plugins-installed registry. Returns a flat list of installed
    plugin records, each with {name, scope, install_path, installed_at,
    last_updated}.
    """
    if not PLUGINS_INSTALLED_JSON.is_file():
        return []
    try:
        data = json.loads(PLUGINS_INSTALLED_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for plugin_key, instances in (data.get("plugins") or {}).items():
        for inst in instances:
            out.append(
                {
                    "name": plugin_key.split("@")[0],
                    "scope": inst.get("scope", ""),
                    "install_path": inst.get("installPath", ""),
                    "installed_at": inst.get("installedAt", ""),
                    "last_updated": inst.get("lastUpdated", ""),
                }
            )
    return out


def group_by_source(skills: list[Skill]) -> dict[str, list[Skill]]:
    """Return skills grouped by their source label."""
    groups: dict[str, list[Skill]] = {}
    for s in skills:
        groups.setdefault(s.source, []).append(s)
    return groups


def group_by_kind(skills: list[Skill]) -> dict[str, list[Skill]]:
    """Return skills grouped by their kind (skill / command / agent)."""
    groups: dict[str, list[Skill]] = {}
    for s in skills:
        groups.setdefault(s.kind, []).append(s)
    return groups


def group_by_tag(skills: list[Skill]) -> dict[str, list[Skill]]:
    """Return skills grouped by tag. Skills with multiple tags appear under each.
    Skills with no tags go under '(untagged)'.
    """
    groups: dict[str, list[Skill]] = {}
    for s in skills:
        if not s.tags:
            groups.setdefault("(untagged)", []).append(s)
        else:
            for tag in s.tags:
                groups.setdefault(tag, []).append(s)
    return groups


def update_tags(path: Path, new_tags: list[str]) -> None:
    """Rewrite the `tags:` line in a markdown file's YAML frontmatter.

    - If frontmatter exists and has a `tags:` line → replace it.
    - If frontmatter exists but has no `tags:` line → insert one before the closing `---`.
    - If no frontmatter exists → prepend a minimal one with just tags.

    Preserves everything else in the file. Inline-list format only
    (`tags: [a, b]`); YAML block lists get rewritten to inline.

    Raises OSError on read/write failure.
    """
    text = path.read_text(encoding="utf-8")
    tag_line = f"tags: [{', '.join(new_tags)}]" if new_tags else "tags: []"

    if not text.startswith("---"):
        # No frontmatter — prepend one
        new_text = f"---\n{tag_line}\n---\n\n{text}"
        path.write_text(new_text, encoding="utf-8")
        return

    end = text.find("\n---", 3)
    if end == -1:
        # Malformed frontmatter — bail without writing
        raise ValueError(f"frontmatter missing closing '---' in {path}")

    fm_start = 3
    fm_end = end + 1  # position of '\n' before '---' line
    fm_text = text[fm_start:fm_end]  # raw frontmatter, with leading/trailing \n

    # Walk lines, looking for inline `tags:` (single-line form)
    lines = fm_text.split("\n")
    new_lines = []
    replaced = False
    skip_block_list = False
    for line in lines:
        stripped = line.lstrip()
        if not skip_block_list and (stripped.startswith("tags:") or stripped == "tags:"):
            # Replace with our inline form
            new_lines.append(tag_line)
            replaced = True
            # If the existing line was the start of a block list (`tags:` with no value),
            # skip subsequent `- ...` lines.
            after_colon = stripped[5:].strip()
            if not after_colon:
                skip_block_list = True
            continue
        if skip_block_list:
            # Drop indented list items that belong to the old block list
            if stripped.startswith("-") or (line.startswith(" ") and stripped and not stripped[0].isalpha()):
                continue
            skip_block_list = False
        new_lines.append(line)

    if not replaced:
        # Insert tag_line just before the (empty) trailing line that precedes ---
        # i.e., as the last non-empty entry inside the frontmatter
        # Find the last non-empty line
        insert_at = len(new_lines)
        while insert_at > 0 and new_lines[insert_at - 1].strip() == "":
            insert_at -= 1
        new_lines.insert(insert_at, tag_line)

    new_fm = "\n".join(new_lines)
    new_text = text[:fm_start] + new_fm + text[fm_end:]
    path.write_text(new_text, encoding="utf-8")


def find_skill(skills: list[Skill], name: str) -> Optional[Skill]:
    """Find a skill by exact name (case-insensitive)."""
    needle = name.lower()
    for s in skills:
        if s.name.lower() == needle:
            return s
    # Try ends-with match (handles plugin:slack/standup vs standup)
    for s in skills:
        if s.name.lower().endswith(needle):
            return s
    return None
