# OpenClaw Backup - 2026-04-19

Backup of `~/.openclaw` configuration directory.

## Backup Info

- **Date**: 2026-04-19
- **Time**: 09:00:01
- **Branch**: backup/2026-04-19

## Contents

- Agents configuration
- Skills (including myskill/)
- Workspace
- Credentials (review before sharing)
- Plugins configuration

## Not Included

- `extensions/` - Plugin extensions (reinstall via `openclaw plugins install`)

## Restore

```bash
# Clone specific date
git clone --branch backup/2026-04-19 git@github.com:zhanghong3721/kimiclaw.git ~/.openclaw

# Or clone main branch for latest
git clone git@github.com:zhanghong3721/kimiclaw.git ~/.openclaw

# Reinstall extensions
openclaw plugins install
```

## View All Backups

```bash
git fetch --all
git branch -r | grep backup/
```
