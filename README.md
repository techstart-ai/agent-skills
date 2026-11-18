# TechStart AI skills

Agent skills we use at TechStart AI, one folder per skill under `skills/`. They follow the `SKILL.md` format used by Claude Code and other coding agents.

| Skill | What it does |
|---|---|
| [`install-skill-safely`](skills/install-skill-safely/SKILL.md) | Inspects a skill or plugin for security problems before it is installed, shows the risks, and installs the inspected copy only after you choose to proceed. |

## Install a skill

Copy its folder into your skills directory:

```bash
git clone https://github.com/techstart-ai/skills.git
cp -R skills/skills/install-skill-safely ~/.claude/skills/
```

Use `<project>/.claude/skills/` instead for one project only.

## install-skill-safely

Skills run with your agent's full access, so a bad one can read credentials or send data out. This skill puts a check in front of every install:

1. Fetches the source into a quarantine folder (`~/.claude/skill-quarantine/`) with git hooks off. Nothing from the source is run.
2. Scans it with [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector) in static mode. Only dependency names leave your computer (to OSV.dev).
3. Has the agent read what a scanner cannot judge: hooks, server configs, install scripts, the licence.
4. Shows you the risks in plain words and asks whether to proceed. Anything short of a clean result needs your explicit yes.
5. Installs the copy that was inspected, never a fresh download, and logs it in `~/.claude/skill-install-log.md`.

Needs `git`, Python 3 and SkillSpector:

```bash
uv tool install --python 3.13 git+https://github.com/NVIDIA/skillspector.git
```

Limits: the scan is static and pattern-based. It raises false alarms on ordinary content and cannot see runtime behaviour, images or binaries. It lowers risk; it does not prove a skill is safe.

## Licence

MIT. See [LICENSE](LICENSE).
