# Backup Date Branches

This repository contains daily backups of the OpenClaw configuration.

## Latest Backups

| Date | Branch | Size |
|------|--------|------|
| 2026-05-01 | backup/2026-05-01 | 1.6G |

## List All Backups

```bash
git branch -a | grep backup/
```

## Restore from Specific Date

```bash
git checkout backup/YYYY-MM-DD
```
