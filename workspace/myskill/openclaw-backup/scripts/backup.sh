#!/bin/bash
# OpenClaw Backup Script
# Usage: backup.sh <github-repo-url>
# Example: backup.sh https://github.com/zhanghong3721/kimiclaw

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

echo "Starting OpenClaw backup..."
echo "Source: $SOURCE_DIR"
echo "Target: $REPO_URL"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

# Initialize git repo
git init
git config init.defaultBranch main

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

# Add README
cat > README.md << EOF
# OpenClaw Backup

Backup of \`~/.openclaw\` configuration directory.

## Contents

- Agents configuration
- Skills
- Workspace
- Credentials (review before sharing)
- Plugins configuration

## Not Included

- \`extensions/\` - Plugin extensions (reinstall via \`openclaw plugins install\`)

## Restore

\`\`\`bash
git clone $REPO_URL ~/.openclaw
openclaw plugins install  # Reinstall extensions
\`\`\`

## Last Backup

$(date '+%Y-%m-%d %H:%M:%S')
EOF

# Commit
echo ""
echo "Committing files..."
git add -A
git commit -m "Backup of .openclaw - $(date '+%Y-%m-%d %H:%M:%S')"

# Push
echo ""
echo "Pushing to GitHub..."
git branch -M main
git remote add origin "$REPO_URL"

if git push -u origin main 2>&1; then
    echo ""
    echo "✅ Backup completed successfully!"
    echo "Repository: $REPO_URL"
    echo "Backup size: $(du -sh . | cut -f1)"
else
    echo ""
    echo "❌ Push failed. Check your repository URL and permissions."
    exit 1
fi

# Cleanup
cd /
rm -rf "$BACKUP_DIR"
