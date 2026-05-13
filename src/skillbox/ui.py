"""Themed console + hierarchical pickers for skillbox.

Layout philosophy: your skills are the foreground. Plugin skills are background
(collapsed by plugin, drill-down on demand). Actions (add / audit) sit below.
"""

from __future__ import annotations

import sys
from typing import Optional

import questionary
from rich.console import Console
from rich.theme import Theme

from .scan import Skill
from .splash_art import SKILLBOX_BANNER

_theme = Theme(
    {
        "box": "bold cyan",
        "border": "bold deep_sky_blue1",
        "nav": "cyan",
        "accent": "bright_cyan",
        "soft": "grey50",
        "warn": "yellow",
        "err": "red bold",
        "ok": "bold green",
        "skill": "bright_white",
        "kind_skill": "magenta",
        "kind_command": "bright_blue",
        "kind_agent": "bright_yellow",
        "src_user": "green",
        "src_project": "bright_green",
        "src_plugin": "cyan",
    }
)

console = Console(theme=_theme)

_picker_style = questionary.Style(
    [
        ("question", "bold"),
        ("pointer", "fg:#00d7ff bold"),
        ("highlighted", "bold reverse"),
        ("selected", "fg:#00d7ff"),
        ("answer", "fg:#00d7ff bold"),
        ("instruction", "fg:#888888"),
    ]
)

# Sentinel values for top-level picker
ACTION_PLUGIN = "__plugin__"        # drill into a plugin's skills
ACTION_PLUGINS_ALL = "__plugins_all__"  # show all plugin skills flat (legacy)
ACTION_ADD = "__add__"
ACTION_AUDIT = "__audit__"
ACTION_QUIT = "__quit__"
ACTION_BACK = "__back__"


def status_banner(msg: str, kind: str = "ok") -> None:
    """Render a status line at the top of the screen. kind: ok | warn | err | nav."""
    icon = {"ok": "✓", "warn": "⚠", "err": "✗", "nav": "›"}.get(kind, "›")
    style = {"ok": "ok", "warn": "warn", "err": "err", "nav": "nav"}.get(kind, "nav")
    console.print(f"[{style}]{icon}  {msg}[/{style}]")
    console.print()


def clear_screen() -> None:
    """Clear the terminal (only if attached to a TTY)."""
    if _is_tty():
        console.clear()


def _is_tty() -> bool:
    return sys.stdout.isatty()


def print_splash(skill_count: int, your_count: int, plugin_count: int) -> None:
    if not _is_tty():
        return
    console.print(f"[border]{'═' * 52}[/border]")
    console.print(f"[box]{SKILLBOX_BANNER}[/box]", end="")
    suffix = f"[ok]{your_count} yours[/ok] · [cyan]{plugin_count} plugin[/cyan] · {skill_count} total"
    console.print(f"  [nav]every tool earns its place.[/nav]   [soft]{suffix}[/soft]")
    console.print(f"[border]{'═' * 52}[/border]\n")


def info(msg: str) -> None:
    console.print(f"[nav]›[/nav] {msg}")


def warn(msg: str) -> None:
    console.print(f"[warn]⚠[/warn]  {msg}")


def error(msg: str) -> None:
    console.print(f"[err]✗[/err]  {msg}")


def ok(msg: str) -> None:
    console.print(f"[ok]✓[/ok]  {msg}")


def _kind_label(kind: str) -> str:
    style_key = f"kind_{kind}"
    return f"[{style_key}]{kind}[/{style_key}]"


def _source_label(source: str) -> str:
    if source.startswith("plugin:"):
        plugin = source.removeprefix("plugin:")
        return f"[src_plugin]plugin:{plugin}[/src_plugin]"
    if source == "user":
        return f"[src_user]user[/src_user]"
    if source == "project":
        return f"[src_project]project[/src_project]"
    return source


def render_table(skills: list[Skill], group_by: str = "source") -> None:
    """Render a categorized list of skills."""
    from rich.table import Table

    if not skills:
        warn("No skills found.")
        return

    if group_by == "source":
        groups: dict[str, list[Skill]] = {}
        for s in skills:
            groups.setdefault(s.source, []).append(s)
        order = (
            ["user", "project"]
            + sorted([k for k in groups if k.startswith("plugin:")])
        )
        groups = {k: groups[k] for k in order if k in groups}
    elif group_by == "kind":
        groups = {}
        for s in skills:
            groups.setdefault(s.kind, []).append(s)
        order = ["skill", "command", "agent"]
        groups = {k: groups[k] for k in order if k in groups}
    elif group_by == "tag":
        from .scan import group_by_tag
        groups = group_by_tag(skills)
        # Show real tags first (sorted), then (untagged) at the end
        tag_keys = sorted([k for k in groups if k != "(untagged)"])
        if "(untagged)" in groups:
            tag_keys.append("(untagged)")
        groups = {k: groups[k] for k in tag_keys}
    else:
        groups = {"all": skills}

    for group_name, group_skills in groups.items():
        table = Table(
            title=f"[box]{group_name}[/box]  [soft]({len(group_skills)})[/soft]",
            title_justify="left",
            show_header=True,
            header_style="border",
            border_style="soft",
            row_styles=["", "soft"],
        )
        table.add_column("name", style="skill", no_wrap=True)
        if group_by != "kind":
            table.add_column("kind", no_wrap=True)
        table.add_column("description", overflow="fold", max_width=80)
        for s in group_skills:
            # Truncate long descriptions for the table view
            desc_raw = s.description
            if len(desc_raw) > 120:
                desc_raw = desc_raw[:117] + "…"
            desc = desc_raw or "[soft]—[/soft]"
            row = [s.name]
            if group_by != "kind":
                row.append(_kind_label(s.kind))
            row.append(desc)
            table.add_row(*row)
        console.print(table)
        console.print()


_KIND_COLORS = {
    "skill":   "fg:#d75fff",  # magenta — capabilities
    "command": "fg:#5fafff",  # blue — slash commands
    "agent":   "fg:#ffd75f",  # yellow — subagents
}


def _skill_choice(s: Skill, *, indent: int = 0) -> questionary.Choice:
    """Format one skill as a picker Choice with a color-coded kind label.

    Compact: name + colored kind. The detail view shows description after enter.
    Kind colors: skill=magenta, command=blue, agent=yellow.
    """
    pad = " " * indent
    kind_style = _KIND_COLORS.get(s.kind, "")
    return questionary.Choice(
        title=[
            ("", f"{pad}{s.name:<30} "),
            (kind_style, s.kind),
        ],
        value=("skill", s.name),
    )


def picker_top(skills: list[Skill]) -> Optional[tuple[str, Optional[str]]]:
    """Top-level picker. Returns:
        ("skill", name)         user picked a specific skill to inspect
        ("plugin", plugin_name) user picked a plugin to drill into
        ("action", "add")       user picked the Add action
        ("action", "audit")     user picked the Audit action
        None                    user cancelled / quit
    """
    if not _is_tty():
        return None

    # Partition: yours (user + project) vs plugins
    yours = [s for s in skills if s.source in ("user", "project")]
    plugins: dict[str, list[Skill]] = {}
    for s in skills:
        if s.source.startswith("plugin:"):
            plugins.setdefault(s.source.removeprefix("plugin:"), []).append(s)

    choices: list = []
    name_map: dict[str, Skill] = {}

    # --- YOURS section: split user vs project so the scope is visible ---
    yours_user = [s for s in yours if s.source == "user"]
    yours_project = [s for s in yours if s.source == "project"]

    def _emit_yours_group(label: str, group: list[Skill]) -> None:
        """Render one YOURS subgroup (user or project), with tag subdivisions if any."""
        if not group:
            return
        choices.append(questionary.Separator(f"── {label} ({len(group)}) ──"))
        any_tagged = any(s.tags for s in group)
        if any_tagged:
            tag_groups: dict[str, list[Skill]] = {}
            for s in group:
                if s.tags:
                    for t in s.tags:
                        tag_groups.setdefault(t, []).append(s)
                else:
                    tag_groups.setdefault("(untagged)", []).append(s)
            tag_keys = sorted([t for t in tag_groups if t != "(untagged)"])
            if "(untagged)" in tag_groups:
                tag_keys.append("(untagged)")
            for tag in tag_keys:
                count = len(tag_groups[tag])
                tag_label = tag.upper() if tag != "(untagged)" else "UNTAGGED"
                choices.append(
                    questionary.Separator(f"  ── {tag_label} ({count}) ──")
                )
                for s in sorted(tag_groups[tag], key=lambda x: x.name):
                    choices.append(_skill_choice(s, indent=4))
                    name_map[s.name] = s
        else:
            for s in group:
                choices.append(_skill_choice(s, indent=2))
                name_map[s.name] = s

    # User-level always shows if present; project section only when scanned from a project
    _emit_yours_group("YOURS (user, available everywhere)", yours_user)
    _emit_yours_group("YOURS (this project)", yours_project)

    # --- PLUGINS section (collapsed) ---
    if plugins:
        total_plugin = sum(len(v) for v in plugins.values())
        choices.append(
            questionary.Separator(
                f"── PLUGINS ({total_plugin} across {len(plugins)}) ──"
            )
        )
        for plugin in sorted(plugins.keys()):
            count = len(plugins[plugin])
            choices.append(
                questionary.Choice(
                    title=f"  📁 {plugin:<28} {count:>3} skills",
                    value=("plugin", plugin),
                )
            )

    # --- ACTIONS section ---
    choices.append(questionary.Separator("── ACTIONS ──"))
    choices.append(
        questionary.Choice(title="  + Add a new skill", value=("action", "add"))
    )
    choices.append(
        questionary.Choice(title="  ⊕ Audit all skills", value=("action", "audit"))
    )
    choices.append(
        questionary.Choice(title="  ❓ Help", value=("action", "help"))
    )
    # Use a non-None sentinel for Quit so questionary's search-filter doesn't
    # treat it like a cancellation. Cancellation (Esc/Ctrl-C) still returns None.
    choices.append(questionary.Choice(title="  ✕ Quit", value=("action", "quit")))

    return questionary.select(
        "Pick a skill or action:",
        choices=choices,
        style=_picker_style,
        instruction="(type to filter, ↑↓ to move, enter to pick)",
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()


def picker_plugin_drill(plugin: str, plugin_skills: list[Skill]) -> Optional[tuple[str, Optional[str]]]:
    """Drill-down picker for a single plugin's skills."""
    if not _is_tty():
        return None

    choices: list = []
    choices.append(
        questionary.Separator(f"── plugin: {plugin} ({len(plugin_skills)}) ──")
    )
    for s in plugin_skills:
        choices.append(_skill_choice(s, indent=2))
    choices.append(questionary.Separator())
    choices.append(questionary.Choice(title="  ← back", value=("back", None)))

    return questionary.select(
        f"Pick a skill from {plugin}:",
        choices=choices,
        style=_picker_style,
        instruction="(type to filter, ↑↓ to move, enter to pick, esc to go back)",
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()


def show_skill_detail(skill: Skill) -> None:
    """Show a single skill's full detail page."""
    from rich.panel import Panel
    from rich.markdown import Markdown

    header = (
        f"[box]{skill.name}[/box]   "
        f"{_kind_label(skill.kind)}   "
        f"{_source_label(skill.source)}"
    )
    console.print(header)
    console.print(f"[soft]scope:[/soft] [accent]{skill.scope_label}[/accent]")
    console.print(f"[soft]path:[/soft]  {skill.path}")
    if skill.tags:
        console.print(f"[soft]tags:[/soft]  {', '.join(skill.tags)}")
    else:
        # Escape the bracketed example so rich doesn't parse it as markup
        console.print(
            "[soft]tags:[/soft]  [soft](none — add via frontmatter `tags: \\[a, b]`)[/soft]"
        )
    console.print()

    if skill.description:
        console.print(Panel(skill.description, title="description", border_style="soft"))
        console.print()

    try:
        content = skill.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    # Short preview keeps the action menu visible on one screen. For the full
    # content, use the "Open in default app" action.
    PREVIEW_LINES = 25
    lines = content.splitlines()
    preview = "\n".join(lines[:PREVIEW_LINES])
    if len(lines) > PREVIEW_LINES:
        remaining = len(lines) - PREVIEW_LINES
        preview += f"\n\n*({remaining} more lines. Use 'Open in default app' to see the full file.)*"
    console.print(
        Panel(
            Markdown(preview),
            title=f"SKILL.md preview (first {min(PREVIEW_LINES, len(lines))} lines)",
            border_style="border",
        )
    )


# ---------------------------------------------------------------------------
# Help screen
# ---------------------------------------------------------------------------

HELP_TEXT = """[box]What skillbox does[/box]

Manages your Claude Code skills, slash commands, and subagents.
Inventory what's installed, where it lives, what's available in which sessions.

[box]Keys in the picker[/box]

  [accent]type[/accent]              Filter the list (matches any substring)
  [accent]↑ ↓[/accent]               Move between items
  [accent]enter[/accent]             Open / drill into the highlighted item
  [accent]esc[/accent] / [accent]ctrl-c[/accent]      Quit (or back out of a sub-screen)

[box]Where skills live[/box]

  [src_user]user[/src_user]          ~/.claude/skills /commands /agents
                  → loaded in [accent]every[/accent] Claude Code session
  [src_plugin]plugin:X[/src_plugin]      ~/.claude/plugins/cache/.../skills/
                  → loaded in every session (managed via [accent]claude /plugin[/accent])
  [src_project]project[/src_project]       <cwd>/.claude/...
                  → only loaded in that project's sessions

[box]Three kinds of "skill"[/box]

  [kind_skill]skill[/kind_skill]           Auto-triggered capability (e.g. nigel-writing)
  [kind_command]command[/kind_command]         /<name> slash command (e.g. /checkmsg)
  [kind_agent]agent[/kind_agent]           Subagent — runs in a separate context

[box]CLI shortcuts (skip the picker)[/box]

  skillbox ls                    List all (with --source / --kind / --group-by / --plain)
  skillbox info <name>           Detail view for one skill
  skillbox audit                 Duplicates, missing descriptions, plugin sprawl
  skillbox plugins               Installed plugins overview
  skillbox add <path>            Install user skill from a path
  skillbox add --clipboard       Install from clipboard contents
  skillbox add --editor          Open editor with a SKILL.md template
  skillbox rm <name>             Remove a user/project skill

[box]Tips[/box]

  · Tag your skills via frontmatter ([accent]tags: \\[writing, eagent][/accent]) — they auto-group in the picker.
  · The picker [accent]doesn't[/accent] touch plugin skills — use [accent]claude /plugin remove <name>[/accent] for those.
  · After any action, a green/yellow/red status banner shows above the menu.
  · Press [accent]esc[/accent] anywhere to back out one level.
"""


def show_help() -> None:
    from rich.panel import Panel
    console.print()
    console.print(Panel.fit(HELP_TEXT, border_style="border", title="[box]skillbox help[/box]"))
    console.print()


# ---------------------------------------------------------------------------
# Skill action menu (shown after picking a skill)
# ---------------------------------------------------------------------------

ACT_OPEN = "open"
ACT_VIEW_FULL = "view_full"
ACT_REVEAL = "reveal"
ACT_EDIT_TAGS = "edit_tags"
ACT_COPY_PATH = "copy_path"
ACT_MOVE = "move"
ACT_REMOVE = "remove"
ACT_BACK = "back"


def skill_action_menu(skill: Skill, project_root: Optional["Path"] = None) -> Optional[str]:
    """Show action menu for a single skill. Returns the chosen action."""
    if not _is_tty():
        return None

    choices = [
        questionary.Choice(title="  📖 Open in default app", value=ACT_OPEN),
        questionary.Choice(title="  📄 View full content (in less)", value=ACT_VIEW_FULL),
        questionary.Choice(title="  🔍 Reveal in Finder", value=ACT_REVEAL),
        questionary.Choice(title="  📋 Copy path to clipboard", value=ACT_COPY_PATH),
    ]
    if skill.is_user_writable:
        choices.append(questionary.Choice(title="  🏷️  Edit tags", value=ACT_EDIT_TAGS))
        # Move action: only when there's somewhere meaningful to move to
        if skill.source == "user":
            label = "  ↔️  Move to project-level (this directory)" if project_root else "  ↔️  Move (no project in cwd)"
            disabled = project_root is None
            if disabled:
                choices.append(
                    questionary.Choice(title=label, value=None, disabled=True)
                )
            else:
                choices.append(questionary.Choice(title=label, value=ACT_MOVE))
        elif skill.source == "project":
            choices.append(
                questionary.Choice(
                    title="  ↔️  Move to user-level (available everywhere)",
                    value=ACT_MOVE,
                )
            )
        choices.append(questionary.Choice(title="  🗑️  Remove this skill", value=ACT_REMOVE))
    else:
        choices.append(
            questionary.Choice(
                title="  🏷️  Edit tags (disabled, plugin skill is read-only)",
                value=None,
                disabled=True,
            )
        )
        choices.append(
            questionary.Choice(
                title="  ↔️  Move (disabled, plugin skill is read-only)",
                value=None,
                disabled=True,
            )
        )
        choices.append(
            questionary.Choice(
                title="  🗑️  Remove (disabled, use `claude /plugin` for plugin skills)",
                value=None,
                disabled=True,
            )
        )
    choices.append(questionary.Separator())
    choices.append(questionary.Choice(title="  ← back to picker", value=ACT_BACK))

    return questionary.select(
        f"Action for '{skill.name}':",
        choices=choices,
        style=_picker_style,
    ).ask()


def prompt_tags(current_tags: list[str], suggestions: list[str] = None) -> Optional[list[str]]:
    """Prompt for a comma-separated tag list. Returns the new list, or None if cancelled."""
    if not _is_tty():
        return None

    suggestion_str = ""
    if suggestions:
        suggestion_str = f"  [soft]suggestions: {', '.join(suggestions)}[/soft]"

    console.print(f"[soft]current tags:[/soft] {', '.join(current_tags) if current_tags else '(none)'}")
    if suggestion_str:
        console.print(suggestion_str)

    raw = questionary.text(
        "New tags (comma-separated, blank to clear, esc to cancel):",
        default=", ".join(current_tags),
        style=_picker_style,
    ).ask()

    if raw is None:
        return None

    # Parse comma-separated, trim whitespace and quotes
    tags = []
    for t in raw.split(","):
        t = t.strip().strip("'\"")
        if t:
            tags.append(t)
    return tags


# ---------------------------------------------------------------------------
# Add flow
# ---------------------------------------------------------------------------

def add_flow() -> Optional[dict]:
    """Ask the user how they want to add a skill.

    Returns a dict describing the request, or None if cancelled:
      {"mode": "path", "path": str}
      {"mode": "paste", "content": str, "name": str, "kind": str}
      {"mode": "editor", "name": str, "kind": str}
      {"mode": "clipboard"}      # try clipboard contents — if path, use; if md, save
    """
    if not _is_tty():
        return None

    mode = questionary.select(
        "How would you like to add a skill?",
        choices=[
            questionary.Choice(
                title="  Paste a path to an existing .md file or skill directory",
                value="path",
            ),
            questionary.Choice(
                title="  Paste SKILL.md content (opens editor)", value="editor"
            ),
            questionary.Choice(
                title="  Use clipboard contents (auto-detect path or content)",
                value="clipboard",
            ),
            questionary.Choice(title="  ← back", value=None),
        ],
        style=_picker_style,
    ).ask()

    if mode is None:
        return None

    if mode == "path":
        path = questionary.path(
            "Path to .md file or skill directory:",
            style=_picker_style,
        ).ask()
        if not path:
            return None
        return {"mode": "path", "path": path}

    if mode == "editor":
        name = questionary.text(
            "Skill name (kebab-case, e.g. my-skill):",
            style=_picker_style,
            validate=lambda x: bool(x.strip()),
        ).ask()
        if not name:
            return None
        kind = questionary.select(
            "Kind:",
            choices=[
                questionary.Choice(title="skill (full SKILL.md in a directory)", value="skill"),
                questionary.Choice(title="command (single .md slash command)", value="command"),
                questionary.Choice(title="agent (single .md subagent definition)", value="agent"),
            ],
            style=_picker_style,
        ).ask()
        if not kind:
            return None
        return {"mode": "editor", "name": name.strip(), "kind": kind}

    if mode == "clipboard":
        return {"mode": "clipboard"}

    return None
