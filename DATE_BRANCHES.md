# Backup Date Branches

This repository contains daily backups of the OpenClaw configuration.

## Latest Backups

| Date | Branch | Size |
|------|--------|------|
| 2026-04-28 | backup/2026-04-28 | 1.5G |

## List All Backups

```bash
git branch -a | grep backup/
```

## Restore from Specific Date

```bash
git checkout backup/YYYY-MM-DD
```
