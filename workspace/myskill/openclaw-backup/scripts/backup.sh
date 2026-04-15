#!/bin/bash
# OpenClaw Daily Backup Script
# Usage: backup.sh <github-repo-url>
# Example: backup.sh https://github.com/zhanghong3721/kimiclaw
#
# This script creates a dated branch (backup/YYYY-MM-DD) and pushes the backup to it.
# Designed to run daily at 9:00 AM via cron.

set -e

# Check arguments
if [ $# -ne 1 ]; then
    echo "Usage: $0 <github-repo-url>"
    echo "Example: $0 https://github.com/username/repo-name"
    exit 1
fi

REPO_URL="$1"
BACKUP_DIR="/tmp/openclaw-backup-$(date +%Y%m%d-%H%M%S)"
SOURCE_DIR="${HOME}/.openclaw"
DATE_BRANCH="backup/$(date +%Y-%m-%d)"
DATE_STR=$(date +%Y-%m-%d)
TIME_STR=$(date +%H:%M:%S)

# Check source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source directory $SOURCE_DIR does not exist"
    exit 1
fi

# Check git is configured
if ! git config --global user.name > /dev/null 2>&1; then
    echo "Error: Git user.name not configured"
    echo "Run: git config --global user.name 'your-username'"
    exit 1
fi

if ! git config --global user.email > /dev/null 2>&1; then
    echo "Error: Git user.email not configured"
    echo "Run: git config --global user.email 'your-email@example.com'"
    exit 1
fi

echo "Starting OpenClaw daily backup..."
echo "Source: $SOURCE_DIR"
echo "Target: $REPO_URL"
echo "Branch: $DATE_BRANCH"
echo "Date: $DATE_STR $TIME_STR"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

# Clone the existing repository (or initialize if empty)
echo "Cloning repository..."
if git clone "$REPO_URL" . 2>/dev/null; then
    echo "Repository cloned successfully"
else
    echo "Initializing new repository..."
    git init
    git config init.defaultBranch main
fi

# Create and switch to date branch
echo "Creating branch: $DATE_BRANCH"
git checkout -b "$DATE_BRANCH" 2>/dev/null || git checkout "$DATE_BRANCH"

# Clean existing files (keep .git)
echo "Cleaning old files..."
find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} + 2>/dev/null || true

# Create .gitignore
cat > .gitignore << 'EOF'
# OpenClaw Backup Exclusions
# Extensions are not backed up (can be reinstalled)
extensions/
EOF

# Copy all files except extensions
echo "Copying files (excluding extensions/)..."
rsync -av --exclude=extensions "$SOURCE_DIR/" . 2>&1 | tail -5

# Remove nested git repositories
find . -mindepth 2 -name ".git" -type d -exec rm -rf {} + 2>/dev/null || true

# Create README for this backup
cat > README.md << EOF
# OpenClaw Backup - $DATE_STR

Backup of \`~/.openclaw\` configuration directory.

## Backup Info

- **Date**: $DATE_STR
- **Time**: $TIME_STR
- **Branch**: $DATE_BRANCH

## Contents

- Agents configuration
- Skills (including myskill/)
- Workspace
- Credentials (review before sharing)
- Plugins configuration

## Not Included

- \`extensions/\` - Plugin extensions (reinstall via \`openclaw plugins install\`)

## Restore

\`\`\`bash
# Clone specific date
git clone --branch $DATE_BRANCH $REPO_URL ~/.openclaw

# Or clone main branch for latest
git clone $REPO_URL ~/.openclaw

# Reinstall extensions
openclaw plugins install
\`\`\`

## View All Backups

\`\`\`bash
git fetch --all
git branch -r | grep backup/
\`\`\`
EOF

# Add date-branches index file
cat > DATE_BRANCHES.md << EOF
# Backup Date Branches

This repository contains daily backups of the OpenClaw configuration.

## Latest Backups

| Date | Branch | Size |
|------|--------|------|
| $DATE_STR | $DATE_BRANCH | $(du -sh . | cut -f1) |

## List All Backups

\`\`\`bash
git branch -a | grep backup/
\`\`\`

## Restore from Specific Date

\`\`\`bash
git checkout backup/YYYY-MM-DD
\`\`\`
EOF

# Commit
echo ""
echo "Committing files..."
git add -A
git commit -m "Backup: $DATE_STR $TIME_STR" || echo "No changes to commit"

# Push to date branch
echo ""
echo "Pushing to branch: $DATE_BRANCH..."
if git push -u origin "$DATE_BRANCH" 2>&1; then
    echo ""
    echo "✅ Daily backup completed successfully!"
    echo "Repository: $REPO_URL"
    echo "Branch: $DATE_BRANCH"
    echo "Backup size: $(du -sh . | cut -f1)"
else
    echo ""
    echo "❌ Push failed. Check your repository URL and permissions."
    exit 1
fi

# Also update main branch with latest
echo ""
echo "Updating main branch with latest backup..."
git checkout main 2>/dev/null || git checkout -b main
git merge "$DATE_BRANCH" --strategy-option=theirs --no-edit 2>/dev/null || true
git push origin main 2>/dev/null || echo "Main branch update skipped"

# Cleanup
cd /
rm -rf "$BACKUP_DIR"

echo ""
echo "✅ Backup process completed!"
