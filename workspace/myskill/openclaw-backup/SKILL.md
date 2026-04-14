---
name: openclaw-backup
description: Backup OpenClaw configuration directory to a GitHub repository, excluding the extensions folder. Use when the user needs to backup their .openclaw directory, migrate settings to another machine, or version control their OpenClaw configuration.
---

# OpenClaw Backup Skill

This skill backs up the `~/.openclaw` directory to a GitHub repository, excluding the `extensions` folder which contains large plugin files that can be reinstalled.

## What Gets Backed Up

All directories and files under `~/.openclaw` **except**:
- `extensions/` - Plugin extensions (can be reinstalled via `openclaw plugins install`)

## Prerequisites

1. Git configured with user.name and user.email
2. GitHub repository created (e.g., `https://github.com/username/repo-name`)
3. Write access to the repository

## Backup Process

### Step 1: Configure Git (if not already done)

```bash
git config --global user.name "your-username"
git config --global user.email "your-email@example.com"
git config --global init.defaultBranch main
```

### Step 2: Run the Backup Script

Use the provided script:

```bash
~/.openclaw/workspace/myskill/openclaw-backup/scripts/backup.sh https://github.com/username/repo-name
```

Or perform the backup manually:

```bash
# Create temporary directory
mkdir -p /tmp/openclaw-backup
cd /tmp/openclaw-backup

# Initialize git repo
git init

# Copy all files except extensions
rsync -av --exclude=extensions ~/.openclaw/ .

# Remove nested git repositories (if any)
find . -mindepth 2 -name ".git" -type d -exec rm -rf {} + 2>/dev/null

# Add and commit
git add -A
git commit -m "Backup of .openclaw - $(date '+%Y-%m-%d %H:%M:%S')"

# Push to GitHub
git branch -M main
git remote add origin https://github.com/username/repo-name.git
git push -u origin main
```

## Restore Process

To restore on a new machine:

```bash
# Clone the backup repository
git clone https://github.com/username/repo-name.git ~/.openclaw

# Reinstall extensions (they are not backed up)
openclaw plugins install
```

## Important Notes

- **Credentials**: The `credentials/` folder is backed up. Review before pushing to a public repository.
- **Extensions**: Must be reinstalled separately via `openclaw plugins install`.
- **Large files**: The `openspace/.venv/` directory contains many Python packages and is quite large (~400MB).
- **Nested git repos**: Any nested git repositories (like cloned tools) are flattened to regular directories.

## Troubleshooting

### Push fails with authentication error

Ensure you have write access to the repository. You may need to:
- Use HTTPS with a personal access token
- Set up SSH keys for GitHub

### Repository too large

If the backup is too large for GitHub:
1. Add more exclusions to the rsync command (e.g., `logs/`, large model files)
2. Use Git LFS for large binary files
3. Split into multiple repositories (config vs data)

### Nested git repository warnings

These are handled automatically by removing nested `.git` directories before committing.
