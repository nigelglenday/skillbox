"""skillbox — main CLI entry point.

Subcommands:
    skillbox                       hierarchical picker (yours / plugins / actions)
    skillbox ls                    plain-text list (pipe-friendly)
    skillbox info <name>           show one skill's details
    skillbox plugins               list installed plugins
    skillbox audit                 flag duplicates, missing descriptions, etc.
    skillbox rm <name>             remove a user/project-level skill (never plugin)
    skillbox add [<path>]          install a user-level skill (interactive if no path)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from . import scan, ui


SKILL_TEMPLATE = """---
name: __NAME__
description: >
  One-line description of what this skill does and when to use it.
---

# __NAME__

(Write the skill's instructions here. This becomes the agent's prompt
when the skill is invoked.)
"""


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--no-splash", is_flag=True, help="Suppress the splash banner.")
@click.pass_context
def cli(ctx: click.Context, no_splash: bool) -> None:
    """skillbox — Claude Code skills manager. A-Team's companion."""
    ctx.ensure_object(dict)
    ctx.obj["no_splash"] = no_splash

    if ctx.invoked_subcommand is None:
        run_picker(no_splash=no_splash)


def _render_header(skills: list, status: tuple[str, str] | None, no_splash: bool) -> None:
    """Clear screen and render the persistent header (splash + optional status).

    Called at the top of EVERY screen so the app title stays visible
    — same pattern as a-team.
    """
    ui.clear_screen()
    if not no_splash:
        yours = [s for s in skills if s.source in ("user", "project")]
        plugin_skills = [s for s in skills if s.source.startswith("plugin:")]
        ui.print_splash(len(skills), len(yours), len(plugin_skills))
    if status:
        kind_, msg = status
        ui.status_banner(msg, kind=kind_)


def run_picker(no_splash: bool = False) -> None:
    """Hierarchical interactive picker with persistent header + status-bar UX."""
    status: tuple[str, str] | None = None  # (kind, message), one-shot

    while True:
        skills = scan.scan_all(project_root=Path(os.getcwd()))

        _render_header(skills, status, no_splash)
        status = None  # consumed

        selection = ui.picker_top(skills)

        # Esc / Ctrl-C from picker → exit cleanly
        if selection is None:
            ui.clear_screen()
            ui.console.print("[soft]bye.[/soft]")
            return

        kind, value = selection if isinstance(selection, tuple) else (None, None)

        if kind == "skill":
            target = scan.find_skill(skills, value)
            if target:
                status = _inspect_and_act(target, skills, no_splash)
            continue

        if kind == "plugin":
            plugin_subset = [
                s for s in skills if s.source == f"plugin:{value}"
            ]
            _render_header(skills, None, no_splash)
            drill = ui.picker_plugin_drill(value, plugin_subset)
            if drill is None:
                continue
            d_kind, d_value = drill if isinstance(drill, tuple) else (None, None)
            if d_kind == "skill":
                target = scan.find_skill(skills, d_value)
                if target:
                    status = _inspect_and_act(target, skills, no_splash)
            continue

        if kind == "action":
            if value == "quit":
                ui.clear_screen()
                ui.console.print("[soft]bye.[/soft]")
                return
            if value == "add":
                _render_header(skills, None, no_splash)
                result = _interactive_add()
                if result:
                    status = result
                continue
            if value == "audit":
                _render_header(skills, None, no_splash)
                _run_audit()
                ui.console.print()
                input("(press Enter to return to the picker)")
                continue
            if value == "help":
                _render_header(skills, None, no_splash)
                ui.show_help()
                input("(press Enter to return to the picker)")
                continue


def _move_skill(skill: scan.Skill, project_root: Path) -> tuple[Path, Path]:
    """Move a user-level skill to project-level, or vice versa.

    Returns (old_path, new_path) of the moved file/directory.
    Raises if the destination already exists or skill isn't movable.
    """
    if not skill.is_user_writable:
        raise RuntimeError("plugin skills cannot be moved")

    # Resolve the on-disk thing we're moving (directory for SKILL.md, else the file)
    src = skill.path
    if src.name == "SKILL.md":
        src = src.parent  # the skill directory

    # Compute destination based on direction
    if skill.source == "user":
        # user -> project: put under project_root/.claude/...
        if skill.kind == "skill":
            dest = project_root / ".claude" / "skills" / src.name
        elif skill.kind == "command":
            dest = project_root / ".claude" / "commands" / src.name
        elif skill.kind == "agent":
            dest = project_root / ".claude" / "agents" / src.name
        else:
            raise RuntimeError(f"unknown kind: {skill.kind}")
    elif skill.source == "project":
        # project -> user level
        if skill.kind == "skill":
            dest = scan.USER_SKILLS_DIR / src.name
        elif skill.kind == "command":
            dest = scan.USER_COMMANDS_DIR / src.name
        elif skill.kind == "agent":
            dest = scan.USER_AGENTS_DIR / src.name
        else:
            raise RuntimeError(f"unknown kind: {skill.kind}")
    else:
        raise RuntimeError(f"can't move from source: {skill.source}")

    if dest.exists():
        raise RuntimeError(f"destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return src, dest


def _open_in_default_app(path: Path) -> str:
    """Open a file in the user's default app.

    Prefer editors that support 'open at top' via CLI. macOS `open` lets the
    receiving app restore the last cursor position, which is annoying for
    long SKILL.md files. Try: code (VS Code), cursor, then plain open.
    """
    if path.suffix == ".md":
        if shutil.which("code"):
            subprocess.run(["code", "--goto", f"{path}:1:1"], check=False)
            return f"Opened at top in VS Code: {path.name}"
        if shutil.which("cursor"):
            subprocess.run(["cursor", "--goto", f"{path}:1:1"], check=False)
            return f"Opened at top in Cursor: {path.name}"
    subprocess.run(["open", str(path)], check=False)
    return f"Opened in default app: {path.name}"


def _inspect_and_act(
    skill: scan.Skill, all_skills: list, no_splash: bool
) -> tuple[str, str] | None:
    """Show detail for a skill, then loop on the action menu.

    Actions show their result as a one-shot status banner above the menu
    and stay on the same skill — only `back` (or remove) returns to the
    top picker. a-team pattern: actions are notifications, not navigation.
    """
    local_status: tuple[str, str] | None = None

    project_root = Path(os.getcwd())
    # Project is meaningful only if it has a .claude folder OR isn't $HOME
    project_meaningful = (project_root / ".claude").exists() or project_root != Path.home()

    while True:
        _render_header(all_skills, None, no_splash)
        ui.show_skill_detail(skill)
        ui.console.print()
        if local_status:
            ui.status_banner(local_status[1], kind=local_status[0])
            local_status = None  # one-shot

        action = ui.skill_action_menu(
            skill, project_root=project_root if project_meaningful else None
        )
        if action in (None, ui.ACT_BACK):
            return None

        target = skill.path
        if target.name == "SKILL.md":
            dir_target = target.parent
        else:
            dir_target = target

        if action == ui.ACT_OPEN:
            try:
                msg = _open_in_default_app(target)
                local_status = ("ok", msg)
            except Exception as e:
                local_status = ("err", f"open failed: {e}")
            continue

        if action == ui.ACT_VIEW_FULL:
            # Shell to less for full-content paging. -R passes ANSI through,
            # +1g starts at line 1, quit (q) returns here.
            try:
                subprocess.run(["less", "-R", "+1g", str(target)])
                local_status = ("ok", f"Viewed full content")
            except Exception as e:
                local_status = ("err", f"less failed: {e}")
            continue

        if action == ui.ACT_REVEAL:
            try:
                subprocess.run(["open", "-R", str(dir_target)], check=False)
                local_status = ("ok", f"Revealed in Finder: {dir_target.name}")
            except Exception as e:
                local_status = ("err", f"reveal failed: {e}")
            continue

        if action == ui.ACT_EDIT_TAGS:
            seen: set[str] = set()
            for s in all_skills:
                if s.source in ("user", "project"):
                    for t in s.tags:
                        seen.add(t)
            suggestions = sorted(seen)
            new_tags = ui.prompt_tags(skill.tags, suggestions=suggestions)
            if new_tags is None:
                local_status = ("warn", "Tag edit cancelled.")
                continue
            try:
                scan.update_tags(target, new_tags)
                skill.tags = new_tags
                if new_tags:
                    local_status = ("ok", f"Tags: {', '.join(new_tags)}")
                else:
                    local_status = ("ok", "Tags cleared.")
            except Exception as e:
                local_status = ("err", f"tag update failed: {e}")
            continue

        if action == ui.ACT_COPY_PATH:
            try:
                subprocess.run(
                    ["pbcopy"],
                    input=str(target),
                    text=True,
                    check=True,
                )
                local_status = ("ok", f"Copied to clipboard")
            except Exception as e:
                local_status = ("err", f"pbcopy failed: {e}")
            continue

        if action == ui.ACT_MOVE:
            try:
                old_path, new_path = _move_skill(skill, project_root)
                local_status = ("ok", f"Moved to {new_path}")
                # The skill object is now stale (path changed). Bail back to
                # the picker so the next iteration re-scans and finds it in
                # its new location.
                return ("ok", f"Moved '{skill.name}' to {new_path.parent}")
            except Exception as e:
                local_status = ("err", f"move failed: {e}")
            continue

        if action == ui.ACT_REMOVE:
            # Destructive — return to top picker since the skill is gone
            if not skill.is_user_writable:
                local_status = ("err", "refusing — use `claude /plugin` for plugin skills")
                continue
            import questionary
            confirm = questionary.confirm(
                f"Remove {skill.kind} '{skill.name}' at {dir_target}?",
                default=False,
            ).ask()
            if not confirm:
                local_status = ("warn", "Remove cancelled.")
                continue
            if dir_target.is_dir():
                shutil.rmtree(dir_target)
            else:
                dir_target.unlink()
            return ("ok", f"Removed {skill.name}")


def _interactive_add() -> tuple[str, str] | None:
    """The Add-skill flow, invoked from the picker.

    Returns a status tuple (kind, message) for the next picker render.
    """
    request = ui.add_flow()
    if request is None:
        return None

    mode = request["mode"]

    if mode == "path":
        return _install_from_path(Path(request["path"]).expanduser().resolve())

    if mode == "clipboard":
        try:
            clip = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2, check=True
            ).stdout
        except (subprocess.SubprocessError, FileNotFoundError):
            return ("err", "couldn't read clipboard (pbpaste failed)")

        clip_stripped = clip.strip()
        if not clip_stripped:
            return ("err", "clipboard is empty")

        candidate = Path(clip_stripped).expanduser()
        if "\n" not in clip_stripped and candidate.exists():
            return _install_from_path(candidate.resolve())

        ui.info("Clipboard looks like content, not a path.")
        import questionary
        name = questionary.text(
            "Skill name (kebab-case):",
            validate=lambda x: bool(x.strip()),
        ).ask()
        if not name:
            return None
        kind = questionary.select(
            "Kind:",
            choices=[
                questionary.Choice(title="skill (SKILL.md in a directory)", value="skill"),
                questionary.Choice(title="command (single .md slash command)", value="command"),
                questionary.Choice(title="agent (single .md subagent definition)", value="agent"),
            ],
        ).ask()
        if not kind:
            return None
        return _install_from_content(name.strip(), kind, clip)

    if mode == "editor":
        name = request["name"]
        kind = request["kind"]
        template = SKILL_TEMPLATE.replace("__NAME__", name)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(template)
            tmp_path = tf.name

        editor = os.environ.get("EDITOR", "nano")
        ui.info(f"Opening editor ({editor})…")
        result = subprocess.run([editor, tmp_path])
        if result.returncode != 0:
            Path(tmp_path).unlink(missing_ok=True)
            return ("err", "editor exited with non-zero status")

        content = Path(tmp_path).read_text(encoding="utf-8")
        Path(tmp_path).unlink(missing_ok=True)

        if content.strip() == template.strip():
            return ("warn", "template unchanged — nothing to install")

        return _install_from_content(name, kind, content)

    return None


def _install_from_path(source_path: Path) -> tuple[str, str]:
    """Install a user-level skill from a local path.

    Returns a status tuple (kind, message).
    """
    if not source_path.exists():
        return ("err", f"path does not exist: {source_path}")

    if source_path.is_dir() and (source_path / "SKILL.md").is_file():
        dest_name = source_path.name
        dest = scan.USER_SKILLS_DIR / dest_name
        kind = "skill"
    elif source_path.is_file() and source_path.suffix == ".md":
        dest_name = source_path.stem
        dest = scan.USER_COMMANDS_DIR / f"{dest_name}.md"
        kind = "command"
    else:
        return (
            "err",
            f"don't know how to install {source_path} — expected SKILL.md dir or .md file",
        )

    if dest.exists():
        return ("err", f"already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, dest)
    else:
        shutil.copy2(source_path, dest)
    return ("ok", f"Installed {kind} '{dest_name}'")


def _install_from_content(name: str, kind: str, content: str) -> tuple[str, str]:
    """Install a user-level skill from raw SKILL.md content."""
    if kind == "skill":
        dest_dir = scan.USER_SKILLS_DIR / name
        dest = dest_dir / "SKILL.md"
        if dest_dir.exists():
            return ("err", f"already exists: {dest_dir}")
        dest_dir.mkdir(parents=True, exist_ok=False)
    elif kind == "command":
        dest = scan.USER_COMMANDS_DIR / f"{name}.md"
        if dest.exists():
            return ("err", f"already exists: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
    elif kind == "agent":
        dest = scan.USER_AGENTS_DIR / f"{name}.md"
        if dest.exists():
            return ("err", f"already exists: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        return ("err", f"unknown kind: {kind}")

    dest.write_text(content, encoding="utf-8")
    return ("ok", f"Installed {kind} '{name}'")


def _run_audit() -> None:
    skills = scan.scan_all(project_root=Path(os.getcwd()))
    issues = []

    name_to_sources: dict[str, list[scan.Skill]] = {}
    for s in skills:
        name_to_sources.setdefault(s.name, []).append(s)
    for name, srcs in name_to_sources.items():
        if len(srcs) > 1:
            issues.append(
                ("duplicate", name, f"appears in: {', '.join(s.source for s in srcs)}")
            )

    for s in skills:
        if not s.description:
            issues.append(("no-description", s.name, str(s.path)))

    plugin_counts: dict[str, int] = {}
    for s in skills:
        if s.source.startswith("plugin:"):
            plugin_counts[s.source] = plugin_counts.get(s.source, 0) + 1

    ui.console.print(f"[box]Audit[/box] — scanned {len(skills)} skills")
    ui.console.print()

    if issues:
        from rich.table import Table

        table = Table(
            show_header=True,
            header_style="border",
            border_style="soft",
            row_styles=["", "soft"],
        )
        table.add_column("issue", style="warn", no_wrap=True)
        table.add_column("name", style="skill", no_wrap=True)
        table.add_column("detail", overflow="fold")
        for issue, name, detail in issues:
            table.add_row(issue, name, detail)
        ui.console.print(table)
        ui.console.print()
    else:
        ui.ok("No issues found.")
        ui.console.print()

    if plugin_counts:
        ui.console.print("[box]Plugin sprawl[/box] — skill counts by plugin:")
        for src, count in sorted(plugin_counts.items(), key=lambda x: -x[1]):
            ui.console.print(f"  [cyan]{src.removeprefix('plugin:')}[/cyan]  {count}")
        ui.console.print()
        ui.console.print(
            "[soft]Consider `claude /plugin remove <name>` for plugins you don't actively use.[/soft]"
        )


@cli.command("ls")
@click.option(
    "--source",
    type=click.Choice(["user", "project", "plugin", "all"], case_sensitive=False),
    default="all",
    help="Filter by source.",
)
@click.option(
    "--kind",
    type=click.Choice(["skill", "command", "agent", "all"], case_sensitive=False),
    default="all",
    help="Filter by kind.",
)
@click.option(
    "--group-by",
    type=click.Choice(["source", "kind", "tag", "none"], case_sensitive=False),
    default="source",
    help="How to group the output.",
)
@click.option("--plain", is_flag=True, help="Pipe-friendly output (no tables, no color).")
def ls_cmd(source: str, kind: str, group_by: str, plain: bool) -> None:
    """List all skills, slash commands, and subagents."""
    skills = scan.scan_all(project_root=Path(os.getcwd()))

    if source != "all":
        if source == "plugin":
            skills = [s for s in skills if s.source.startswith("plugin:")]
        else:
            skills = [s for s in skills if s.source == source]
    if kind != "all":
        skills = [s for s in skills if s.kind == kind]

    if plain:
        for s in skills:
            src = s.source_short
            print(f"{s.kind:8}  {src:30}  {s.name}")
        return

    ui.render_table(skills, group_by=group_by)


@cli.command("info")
@click.argument("name")
def info_cmd(name: str) -> None:
    """Show details for one skill (frontmatter + content preview)."""
    skills = scan.scan_all(project_root=Path(os.getcwd()))
    skill = scan.find_skill(skills, name)
    if skill is None:
        ui.error(f"skill not found: {name}")
        ui.console.print("[soft]Run `skillbox ls` to see available skills.[/soft]")
        sys.exit(1)
    ui.show_skill_detail(skill)


@cli.command("plugins")
def plugins_cmd() -> None:
    """List installed plugins (read from ~/.claude/plugins/installed_plugins.json)."""
    plugins = scan.installed_plugins()
    if not plugins:
        ui.warn("No plugins installed (or installed_plugins.json not found).")
        return

    from rich.table import Table

    table = Table(
        title="[box]Installed plugins[/box]",
        title_justify="left",
        show_header=True,
        header_style="border",
        border_style="soft",
        row_styles=["", "soft"],
    )
    table.add_column("name", style="skill", no_wrap=True)
    table.add_column("scope", no_wrap=True)
    table.add_column("installed", no_wrap=True)
    table.add_column("updated", no_wrap=True)
    for p in plugins:
        table.add_row(
            p["name"],
            p["scope"],
            p["installed_at"][:10] if p["installed_at"] else "—",
            p["last_updated"][:10] if p["last_updated"] else "—",
        )
    ui.console.print(table)


@cli.command("audit")
def audit_cmd() -> None:
    """Flag duplicates, missing descriptions, and oddities."""
    _run_audit()


@cli.command("help")
def help_cmd() -> None:
    """Show the verbose in-app help screen (vs `--help` which lists subcommands)."""
    ui.show_help()


@cli.command("rm")
@click.argument("name")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def rm_cmd(name: str, force: bool) -> None:
    """Remove a user-level or project-level skill (never plugin skills)."""
    skills = scan.scan_all(project_root=Path(os.getcwd()))
    skill = scan.find_skill(skills, name)
    if skill is None:
        ui.error(f"skill not found: {name}")
        sys.exit(1)
    if not skill.is_user_writable:
        ui.error(
            f"refusing to remove {skill.source} skill — use `claude /plugin` "
            f"to remove plugin skills."
        )
        sys.exit(1)

    target = skill.path
    if target.name == "SKILL.md":
        target = target.parent

    if not force:
        import questionary

        confirm = questionary.confirm(
            f"Remove {skill.kind} '{skill.name}' at {target}?",
            default=False,
        ).ask()
        if not confirm:
            ui.warn("Cancelled.")
            return

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    ui.ok(f"Removed {skill.name}")


@cli.command("add")
@click.argument("source_path", type=click.Path(exists=False, path_type=Path), required=False)
@click.option(
    "--clipboard",
    is_flag=True,
    help="Read from clipboard (auto-detect path vs content).",
)
@click.option(
    "--editor",
    is_flag=True,
    help="Open editor with a SKILL.md template, then install on save.",
)
@click.option(
    "--symlink",
    is_flag=True,
    help="Symlink rather than copy (only with explicit path arg).",
)
def add_cmd(
    source_path: Path | None,
    clipboard: bool,
    editor: bool,
    symlink: bool,
) -> None:
    """Install a user-level skill.

    Three modes:

      skillbox add <path>          install from a local path (file or dir)
      skillbox add --clipboard     read clipboard (path or raw content)
      skillbox add --editor        open editor with template
      skillbox add                 (no args) — interactive picker

    Source can be either:
      - A directory containing SKILL.md (Anthropic skill convention)
      - A single .md file (slash command convention)
    """
    if not source_path and not clipboard and not editor:
        # Fully interactive
        _interactive_add()
        return

    if clipboard:
        try:
            clip = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2, check=True
            ).stdout
        except (subprocess.SubprocessError, FileNotFoundError):
            ui.error("couldn't read clipboard (pbpaste failed)")
            sys.exit(1)
        candidate = Path(clip.strip()).expanduser()
        if "\n" not in clip.strip() and candidate.exists():
            _install_from_path(candidate.resolve())
        else:
            ui.error(
                "clipboard isn't a path; use `skillbox add --editor` or interactive `skillbox add`"
            )
            sys.exit(1)
        return

    if editor:
        import questionary

        name = questionary.text(
            "Skill name (kebab-case):",
            validate=lambda x: bool(x.strip()),
        ).ask()
        if not name:
            return
        kind = questionary.select(
            "Kind:",
            choices=[
                questionary.Choice(title="skill (SKILL.md in a directory)", value="skill"),
                questionary.Choice(title="command (single .md slash command)", value="command"),
                questionary.Choice(title="agent (single .md subagent)", value="agent"),
            ],
        ).ask()
        if not kind:
            return
        template = SKILL_TEMPLATE.replace("__NAME__", name)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(template)
            tmp_path = tf.name
        editor_bin = os.environ.get("EDITOR", "nano")
        subprocess.run([editor_bin, tmp_path])
        content = Path(tmp_path).read_text(encoding="utf-8")
        Path(tmp_path).unlink(missing_ok=True)
        if content.strip() == template.strip():
            ui.warn("template unchanged — nothing to install")
            return
        _install_from_content(name.strip(), kind, content)
        return

    # path mode
    source_path = source_path.expanduser().resolve()
    if not source_path.exists():
        ui.error(f"path does not exist: {source_path}")
        sys.exit(1)

    if symlink:
        # Symlink path mode
        if source_path.is_dir() and (source_path / "SKILL.md").is_file():
            dest = scan.USER_SKILLS_DIR / source_path.name
            kind = "skill"
        elif source_path.is_file() and source_path.suffix == ".md":
            dest = scan.USER_COMMANDS_DIR / source_path.name
            kind = "command"
        else:
            ui.error(f"don't know how to install {source_path}")
            sys.exit(1)
        if dest.exists():
            ui.error(f"already exists: {dest}")
            sys.exit(1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(source_path, dest)
        ui.ok(f"Symlinked {kind} → {dest}")
    else:
        _install_from_path(source_path)


def main() -> int:
    cli()
    return 0
