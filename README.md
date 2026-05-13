# skillbox

**Parallel Claude Code skills manager — A-Team's companion.**

Same TUI feel as [a-team](https://github.com/nigelglenday/a-team), different job:
A-Team manages **sessions**. Skillbox manages **skills** — the markdown SKILL.md
files, slash commands (`~/.claude/commands/`), and subagent definitions
(`~/.claude/agents/`) that get loaded into every Claude Code session.

```
 _____ _   _ _ _ _ _                  
/  ___| | (_) | | | |                 
\ `--.| | ___| | | | |__   _____  __  
 `--. \ |/ / | | | | '_ \ / _ \ \/ /  
/\__/ /   <| | | | | |_) | (_) >  <   
\____/|_|\_\_|_|_|_|_.__/ \___/_/\_\  
```

## Why

A clean Claude Code install has maybe a dozen skills. After a few plugins,
some experiments, and a handful of custom slash commands, that number creeps
past 80. Most of it is silent — you forget what's installed, what's used,
what's dormant. Skillbox gives you a single inventory view and lets you cull.

## What it does

- **Scans every skill location** in one pass:
  - `~/.claude/skills/` — your user-level skills
  - `~/.claude/commands/` — your user-level slash commands
  - `~/.claude/agents/` — your subagent definitions
  - `~/.claude/plugins/cache/<plugin>/.../skills/` — plugin-provided skills
  - `$PWD/.claude/` — current project's skills/commands/agents
- **Categorizes** by source (user / project / plugin:X) and kind (skill / command / agent)
- **Picker UI** (questionary + rich, mirrors a-team's pattern) lets you filter, pick, inspect
- **Audit** flags duplicates, missing descriptions, and plugin sprawl
- **Add / remove** user-level skills with safe defaults (never touches plugin-managed ones)

## Install

```bash
pipx install -e ~/Documents/other-projects/skillbox
```

Or from the published version once it's on GitHub:

```bash
pipx install git+https://github.com/nigelglenday/skillbox
```

## Usage

```bash
skillbox                       # picker — splash + grouped list with filter
skillbox ls                    # table view, grouped by source
skillbox ls --source user      # only your user-level skills
skillbox ls --kind command     # only slash commands
skillbox ls --plain            # pipe-friendly: 'kind  source  name'
skillbox info <name>           # full detail for one skill (frontmatter + preview)
skillbox plugins               # list installed plugins (from installed_plugins.json)
skillbox audit                 # duplicates, missing descriptions, plugin sprawl
skillbox add <path>            # install a user-level skill from a local path
skillbox add <path> --symlink  # symlink instead of copy (for git-tracked skill libraries)
skillbox rm <name>             # remove a user/project skill (refuses to touch plugin skills)
```

## Layout

Same shape as a-team:

```
src/skillbox/
├── __init__.py
├── __main__.py
├── cli.py          # click command dispatch
├── scan.py         # filesystem scanning, frontmatter parsing
├── ui.py           # themed console + picker (rich + questionary)
└── splash_art.py   # ASCII banner
```

## Calling skillbox from an agent

Claude Code agents can invoke skillbox's non-interactive subcommands via the
Bash tool. The interactive picker requires a TTY and won't work in headless
mode, but everything else is agent-callable:

| Command | Use case |
|---|---|
| `skillbox ls --plain` | Full skill inventory in pipe-friendly format (`kind  source  name`) |
| `skillbox ls --plain --source user` | Just user-level skills |
| `skillbox ls --kind command` | Just slash commands |
| `skillbox info <name>` | Get description, scope, tags, content preview for one skill |
| `skillbox audit` | Find duplicates, missing descriptions, plugin sprawl |
| `skillbox plugins` | List installed plugins with install/update timestamps |
| `skillbox add <path>` | Install a user-level skill from a known local path |
| `skillbox rm <name> --force` | Remove a user/project skill non-interactively |

The interactive flows (picker, `add --clipboard`, `add --editor`) all require
a real terminal — they're for humans.

Example agent use:
```bash
# An EA agent auditing its own toolkit
skillbox ls --plain --source user
skillbox audit
```

## Relationship to a-team

| | a-team | skillbox |
|---|---|---|
| Manages | Claude Code sessions | Claude Code skills, commands, agents |
| Registry | `~/.config/a-team/agents.toml` | Filesystem scan (no separate registry) |
| Launches | Ghostty windows running `claude` | Nothing — read-only by default |
| Theme | Orange/red (A-Team van) | Cyan/teal (workshop) |
| Companion to | Skillbox | A-Team |

Run them side by side. A-Team picks who you're talking to. Skillbox tells you
what tools they're all carrying.

## License

MIT
