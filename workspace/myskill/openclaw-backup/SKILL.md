---
name: openclaw-backup
description: Daily backup OpenClaw configuration to GitHub with dated branches. Runs at 9:00 AM daily, creating a new branch for each date (backup/YYYY-MM-DD).
---

# OpenClaw Daily Backup Skill

每日自动备份 OpenClaw 配置到 GitHub，每天创建一个以日期命名的分支（backup/YYYY-MM-DD）。

## 备份策略

- **频率**: 每天上午 9:00
- **分支命名**: `backup/YYYY-MM-DD` (如 `backup/2026-04-14`)
- **保留**: 所有历史分支永久保留
- **Main 分支**: 始终指向最新备份

## 目录结构

```
~/.openclaw/workspace/myskill/openclaw-backup/
├── SKILL.md           # 本说明文档
├── scripts/
│   └── backup.sh      # 备份脚本
└── cron/              # 定时任务配置
    └── openclaw-backup.cron
```

## 快速开始

### 1. 配置 Git

```bash
git config --global user.name "your-username"
git config --global user.email "your-email@example.com"
```

### 2. 测试备份脚本

```bash
# 首次运行，创建第一个备份分支
~/.openclaw/workspace/myskill/openclaw-backup/scripts/backup.sh https://github.com/username/repo-name
```

### 3. 设置定时任务 (每天 9:00)

```bash
# 编辑 crontab
crontab -e

# 添加以下行
0 9 * * * /root/.openclaw/workspace/myskill/openclaw-backup/scripts/backup.sh git@github.com:zhanghong3721/kimiclaw.git >> /var/log/openclaw-backup.log 2>&1
```

或使用提供的配置：

```bash
# 安装 cron 任务
sudo cp ~/.openclaw/workspace/myskill/openclaw-backup/cron/openclaw-backup.cron /etc/cron.d/
sudo chmod 644 /etc/cron.d/openclaw-backup.cron
```

## 备份内容

**包含**:
- Agents 配置
- Skills (包括 myskill/)
- Workspace
- Credentials
- Plugins 配置

**排除**:
- `extensions/` - 可通过 `openclaw plugins install` 重新安装

## 查看备份历史

```bash
# 克隆仓库
git clone https://github.com/username/repo-name.git
cd repo-name

# 查看所有备份分支
git branch -a | grep backup/

# 查看某天的备份
git checkout backup/2026-04-14
```

## 恢复备份

```bash
# 从特定日期恢复
git clone --branch backup/2026-04-14 https://github.com/username/repo-name.git ~/.openclaw

# 重装扩展
openclaw plugins install
```

## 手动触发备份

```bash
~/.openclaw/workspace/myskill/openclaw-backup/scripts/backup.sh https://github.com/username/repo-name
```

## 分支说明

| 分支 | 用途 |
|------|------|
| `main` | 最新备份，自动更新 |
| `backup/YYYY-MM-DD` | 每日历史备份 |

## 注意事项

- **首次运行**: 需要手动执行一次，验证配置正确
- **网络依赖**: 定时任务需要机器联网
- **存储空间**: GitHub 免费版有 2GB 软限制
- **认证方式**: 建议使用 SSH key 或 GitHub Token，避免密码输入
