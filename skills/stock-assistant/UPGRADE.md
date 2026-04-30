# Stock Assistant 升级迁移脚本（→ v2）

> 本文件由模型读取并**静默执行**，全程无需用户操作，完成后推送一条通知，然后自动删除本文件。
> 升级方式：新版本文件直接覆盖到原目录，crontab/cronjob 路径不变，无需切换。

---

## 第一步：迁移 config 和 watchlist

新版本已附带 `config_v2.json` 和 `watchlist_v2.json` 作为模板。

### 1a. config.json

读取 `config_v2.json` 作为新结构基准，将旧 `config.json` 中的用户数据填入：

- `kimiCodeAPIKey`：若旧值非空且不是占位符，保留
- `push.channel`：按以下映射转换旧值：`openclaw` → `kimiclaw`，`both` → `feishu`，其余保持不变
- `feishu`（`app_id` / `app_secret` / `user_id` / `chat_id`）：有值的字段全部保留
- `settings`：旧有的所有 key 全部保留

迁移完成后将结果写入 `config.json`，删除 `config_v2.json`。

### 1b. watchlist.json

读取现有 `watchlist.json`（不存在则用 `watchlist_v2.json` 模板），为每条记录补全缺失字段：

- `market`：不存在时，代码以 `.HK` 结尾 → `"HK"`，否则 → `"CN"`
- `currency`：不存在时，HK → `"HKD"`，CN → `"CNY"`
- `alerts` 下缺失字段补默认值：`change_abs: []`、`cost_pct: []`、`volume_ratio: 0`、`buy_sell_ratio: 0`、`trailing_stop: {enabled: false}`、`tech: {enabled: false}`、`tech_report: {enabled: true}`、`price_alert: []`

迁移完成后写回 `watchlist.json`，删除 `watchlist_v2.json`。

---

## 第二步：更新定时任务（必须完成，否则收盘复盘均无法正常运行）

### 2a. 更新 crontab

```bash
D=$(pwd)
# 移除所有旧的 monitor 条目
crontab -l | grep -v "monitor.py" | crontab -

# 写入新版完整条目
(crontab -l 2>/dev/null; cat << EOF
# A股+港股日盘主监控（精确覆盖交易时段，跳过午休）
30-59 9 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 10-11 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 13-16 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
# 美股监控（覆盖夏令21:30-04:00 / 冬令22:30-05:00，monitor 内部精确判断开盘，非交易时间秒退）
# 注意：夏令时（3月第二个周日至11月第一个周日）开盘21:30，冬令时开盘22:30，cron 统一从21:30起覆盖
30-59 21 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 22-23 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 0-5 * * 2-6 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
EOF
) | crontab -

# 确认写入
crontab -l | grep "monitor.py"
```

### 2b. 更新 openclaw cronjob

删除旧 job，用新命令重建：

```bash
# 删除旧 job（名称可能为"收盘复盘与持仓诊断"或其他旧名）
openclaw cron remove --name "收盘复盘与持仓诊断" 2>/dev/null || true
openclaw cron remove --name "开盘前舆情分析" 2>/dev/null || true

# 创建新 job
openclaw cron add --name "开盘前舆情分析" --cron "55 8 * * 1-5" --tz "Asia/Shanghai" --session isolated --message "执行 stock-assistant 的 pre_market_sentiment 子技能，分析开盘前舆情和消息面，汇报给我。执行 stock-assistant 的 ipo_tracker 子技能，检查本周打新日历和打新资格，汇报给我。"
openclaw cron add --name "收盘复盘" --cron "10 16 * * 1-5" --tz "Asia/Shanghai" --session isolated --message "执行 stock-assistant 的 post_market_review 子技能，结合今日 watchlist、大盘和消息面生成复盘报告，汇报给我。"

# 确认
openclaw cron list
```

---

## 第三步：推送升级通知 & 清理
确认cronjob已经设置好
读取 `config.json` 和 `watchlist.json`，按 `push.channel` 配置的渠道推送以下内容（凭证不可用则静默跳过）；然后删除 `UPGRADE.md` 和 `data/.upgrade_pending`。

推送内容（将 `{real_count}` 和 `{migrated_channel}` 替换为实际值后发送）：

```
📦 Stock Assistant 已升级至 v2

✨ 新功能
• 港股、美股支持
• K线分析：新增K线分析报告

⚙️ 已自动迁移
• 自选股：{real_count} 只真实股票已迁移并补全新字段
• 配置：push.channel = {migrated_channel}，飞书凭证沿用
• 监控：文件直接覆盖，crontab/路径不变，盯盘未中断
```

清理：

```python
import os
skill_root = os.getcwd()
os.remove(os.path.join(skill_root, "UPGRADE.md"))
pending = os.path.join(skill_root, "data", ".upgrade_pending")
if os.path.exists(pending):
    os.remove(pending)
```

---

## 第四步：onboarding 路由

| 场景 | 判断条件 | 进入 |
|------|---------|------|
| 旧版本正在使用 | `real_count > 0` | 展示配置概览（当前自选股 + 已开启的告警），告知升级已完成、定时任务已自动更新，无需重新部署 |
| 装了没配置 | `real_count == 0` | 读取 `ONBOARDING.md`，从情况零开始执行完整部署流程（示例股票已由步骤1b迁移，直接进入凭证检查） |
