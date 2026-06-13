# skillbox

![License](https://img.shields.io/badge/license-MIT-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Platform](https://img.shields.io/badge/platform-macOS-black) ![Termpaper](https://img.shields.io/badge/set-termpaper-cyan)

> *Every tool earns its place.*

Inventory and manage your Claude Code skills, slash commands, and subagents. A TUI companion to [a-team](https://github.com/nigelglenday/a-team).

Part of [**termpaper.dev**](https://termpaper.dev), a set of utilities for managing Claude Code from the terminal. See [a-team](https://github.com/nigelglenday/a-team), [whispertty](https://github.com/nigelglenday/whispertty), and [eagent](https://github.com/nigelglenday/eagent) for the rest of the set.

```
 _____ _   _ _ _ _ _
/  ___| | (_) | | | |
\ `--.| | ___| | | | |__   _____  __
 `--. \ |/ / | | | | '_ \ / _ \ \/ /
/\__/ /   <| | | | | |_) | (_) >  <
\____/|_|\_\_|_|_|_|_.__/ \___/_/\_\
```

## What it is

A clean Claude Code install has maybe a dozen skills. After a few plugins, some experiments, and a handful of custom slash commands, that number creeps past 200. `skillbox` gives you one inventory view across all of it (yours, plugins, and per-project) with a picker, an audit, and safe add/remove.

Manages three things uniformly:

- **skills**: `~/.claude/skills/<name>/SKILL.md` (auto-triggered capabilities)
- **commands**: `~/.claude/commands/<name>.md` (slash commands)
- **agents**: `~/.claude/agents/<name>.md` (subagents)

Plus everything plugins drop into `~/.claude/plugins/cache/...` and anything a project ships in its own `.claude/` directory.

Requires macOS, Claude Code, and Python 3.11+.

## Install

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/nigelglenday/skillbox.git
```

For local dev:

```bash
git clone https://github.com/nigelglenday/skillbox.git
cd skillbox
pipx install -e .
```

## Use

```
skillbox                       splash + hierarchical picker (yours / plugins / actions)
skillbox ls                    plain table, grouped by source
skillbox ls --plain            pipe-friendly: 'kind  source  name'
skillbox ls --source user      filter by source (user | project | plugin | all)
skillbox ls --kind command     filter by kind (skill | command | agent)
skillbox ls --group-by tag     group by frontmatter tag
skillbox info <name>           detail view: scope, tags, description, content preview
skillbox audit                 duplicates, missing descriptions, plugin sprawl
skillbox plugins               installed plugins with install/update timestamps
skillbox add <path>            install a user-level skill from a path
skillbox add --clipboard       install from clipboard contents
skillbox add --editor          open editor with a SKILL.md template
skillbox rm <name>             remove a user/project skill (refuses plugin skills)
skillbox help                  verbose in-app help
```

In the picker:

- type to filter, ↑↓ to move, enter to pick
- pick a skill → action menu (open, reveal in Finder, copy path, edit tags, remove)
- pick a plugin folder → drill into that plugin's skills
- esc / ctrl-c to go back

After every action, a one-shot status banner appears above the menu. Same pattern as a-team: app frame stays anchored, transient feedback above the menu.

## Layout

Skills live in a few canonical places. `skillbox` scans all of them on every invocation. No separate registry to maintain.

| Source | Path | Available in |
|---|---|---|
| `user` | `~/.claude/skills /commands /agents` | every Claude Code session |
| `plugin:X` | `~/.claude/plugins/cache/<plugin>/.../skills/` | every session (managed by `claude /plugin`) |
| `project` | `<cwd>/.claude/...` | only that project's sessions |

The detail view shows the **scope** explicitly: *"everywhere (user-level)"*, *"everywhere (via X plugin)"*, or *"in `<path>/` only"*.

## Tags

Add `tags:` to a skill's frontmatter to organize them:

```yaml
---
name: my-skill
description: One-line description.
tags: [writing, finance]
---
```

When any of your skills have tags, the picker sub-groups YOURS by tag (skills with multiple tags appear under each). `skillbox ls --group-by tag` does the same on the command line. Tagging is the recommended way to organize. Folders force a single hierarchy; tags don't.

## Calling skillbox from an agent

Non-interactive subcommands work in headless mode (Bash tool, CI, scripts):

| Command | Use case |
|---|---|
| `skillbox ls --plain` | Full inventory in pipe-friendly format |
| `skillbox info <name>` | Description + scope + content preview for one skill |
| `skillbox audit` | Find duplicates, missing descriptions, plugin sprawl |
| `skillbox plugins` | Installed plugins overview |
| `skillbox add <path>` | Install a skill from a known local path |
| `skillbox rm <name> --force` | Remove non-interactively |

The interactive flows (picker, paste-content, editor, clipboard) all require a real terminal. They're for humans.

## Part of termpaper

The termpaper suite (so far):

- **[a-team](https://github.com/nigelglenday/a-team)**: manage parallel Claude Code sessions; pick one to open, restore all of them
- **skillbox**: manage skills, commands, and subagents installed across those sessions
- (more to come)

Different colors, same pattern: a splash banner anchors the screen, a filterable picker lets you find what you need, an action menu lets you act without leaving the screen. Each tool ships independently so you can install only what you use.

## License

MIT
