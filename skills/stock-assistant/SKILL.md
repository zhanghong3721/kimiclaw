---
name: stock-assistant
description: "AI-powered stock assistant: minute-level price/volume/technical alerts (CN/HK/US), 15-min MA/MACD/KDJ/RSI reports, pre-market sentiment (08:55), post-market review & position diagnosis (16:10), fundamental analysis, competitor comparison, IPO tracking, and K-line pattern analysis. Use when user mentions 盯盘, 股票, 自选股, 涨跌提醒, 技术指标, 舆情, 复盘, 持仓, 基本面, 竞品, 打新, K线, or requests monitoring/analysis for CN/HK/US equities."
compatibility: Requires KimiFinance API key (kimiCodeAPIKey) for real-time quotes and technical data
license: Proprietary. LICENSE.txt has complete terms
metadata:
  author: Moonshot AI
  version: "2"
  category: finance
  openclaw:
    onInstall: true   # 安装后立即触发一次 SKILL.md（用于升级迁移检测）
    # 定时任务由 openclaw cron add 独立创建，不走 schedule
    env:
      - "kimiCodeAPIKey"
---

# Stock Assistant - 股票智能助手

---

## ⚠️ 执行任何操作前的强制检查

> **这是硬性前置条件，不得跳过。**

检查 `UPGRADE.md` 是否存在：

- **存在** → 必须立即用 Read 工具读取并完整执行（**包含定时任务更新，不可跳过**），**执行完毕前不得进行任何其他操作**
- **不存在** → 正常继续

---

## 模型速查

| 用户意图 | 执行方式 |
|---------|---------|
| 新手引导 / 怎么用 | 读取 `ONBOARDING.md` |
| 舆情分析 | 执行子 Skill `skills/pre_market_sentiment/SKILL.md` |
| 收盘复盘 / 持仓诊断 | 执行子 Skill `skills/post_market_review/SKILL.md` |
| 基本面分析 | 执行子 Skill `skills/fundamental/SKILL.md` |
| 竞品对比分析 | 执行子 Skill `skills/competitor_analysis/SKILL.md` |
| 打新（A股/港股通） | 执行子 Skill `skills/ipo_tracker/SKILL.md` |
| K 线 / 形态分析 | 执行子 Skill `skills/kline_analysis/SKILL.md` |
| 添加自选股 | 编辑 `watchlist.json`，按示例格式追加 |
| 删除自选股 | 编辑 `watchlist.json`，删除对应条目 |
| 查行情 / 技术指标 | `python3 scripts/monitor.py`（手动触发一次完整 tick；非交易时间运行不拉技术指标，如需测试用 `--replay`） |
| 非交易时间测试流程 | `python3 scripts/monitor.py --replay`（用最近交易日时间跑完整流程，验证推送是否正常） |
| 监控状态 | `python3 scripts/monitor.py --status` |
| 停止盯盘 | 见下方「停止/暂停监控」章节 |
| 暂停盯盘（临时） | 见下方「停止/暂停监控」章节 |
| 关闭技术汇总报告 | 编辑 `watchlist.json`，目标股票设 `tech_report.enabled: false` |
| 关闭某只股票的告警 | 编辑 `watchlist.json`，清空对应 alert 字段（`change_abs: []`、`volume_ratio: 0` 等） |
| 关闭开盘舆情提醒 | 删除 `~/.openclaw/cron/jobs.json` 中 name 为「开盘前舆情分析」的 job |
| 关闭收盘复盘 | 删除 `~/.openclaw/cron/jobs.json` 中 name 为「收盘复盘与持仓诊断」的 job |

> **添加或修改自选股后必做**：每次按用户需求更新完 `watchlist.json` 告警配置后，根据阈值和冷却时间**估算推送频率**并告知用户，例如：「当前配置下，若股票在 ±1% 附近震荡，最短每 10 分钟推一次（冷却时间），穿越阈值且回落 0.5% 以上才会再次触发（解锁带宽）。如推送过于频繁可调高冷却时间，如希望更敏感可缩小解锁带宽——**直接告诉我想怎么调，我来改。**」

> **执行上下文说明**：
> - **入口**：OpenClaw 唤醒时直接执行本 SKILL.md（模型根据当前时间判断任务）
> - **工作目录**：OpenClaw 执行时工作目录为 Skill 根目录（`stock-assistant/`），所有子 Skill 路径均相对于该目录解析
> - **环境**：metadata 中声明的 `env` 变量已注入进程环境
> - **子 Skill 推送说明**：用户手动触发子 Skill（舆情分析、K 线分析、基本面等）时，**不需要 follow config.json 的推送渠道**，直接在用户发消息的对话窗口回复即可；只有定时自动触发的任务才需要推送到飞书/KimiIM。

> **渠道推荐**：受限于渠道插件能力，**飞书**和 **Kimi Claw（kimiclaw）** 是盯盘体验最好的两个渠道，支持实时推送、富文本、图片。若用户坚持使用其他渠道（如钉钉、企业微信），告知体验受限，并自动在 crontab 中加入每分钟任务 `python3 scripts/monitor.py`——monitor.py 内部直接调用 KimiFinance API 拉取行情数据并触发异动推送，无需额外脚本。

**关键路径**：自选股 `watchlist.json` · 配置 `config.json` · 状态 `data/state.json` · 失败队列 `data/failed_messages.json` · 日内价格缓存 `data/tick_cache.json`（供复盘读取，运行时自动生成）· K线缓存 `data/kline_cache.json` · 分时缓存 `data/intraday_cache.json`

**子 Skill 输出文件统一写入 `workspace/` 目录**（不写 `data/`）：基本面报告 → `workspace/fundamental/`，其他子 Skill 如需写文件同理。

---

## Onboarding 检查

**每次被唤醒时，先执行以下三项检查，全部通过则跳过 onboarding：**

1. **watchlist 有真实股票**：`python3 -c "import json; s=[x for x in json.load(open('watchlist.json')) if not x.get('_example')]; print(len(s))"`  → 输出 > 0
2. **crontab 已配置**：`crontab -l 2>/dev/null | grep -c monitor.py` → 输出 > 0
3. **OpenClaw cronjob 已配置**：`openclaw cron list` → 列表中包含「开盘前舆情分析」和「收盘复盘」

**全部通过** → 跳过 onboarding，直接处理用户请求
**任一未通过** → 读取 `ONBOARDING.md` 执行对应步骤（触发词：「帮我盯盘」「开始监控」「盯一下我的股票」等）

---

### 启动/停止命令（OpenClaw 可直接执行）

**手动触发一次 tick**：
```bash
python3 scripts/monitor.py
```

**查看监控状态**：
```bash
python3 scripts/monitor.py --status
```

---

### 停止/暂停监控

#### 完全停止盯盘

```bash
# 1. 删除 crontab 中所有 monitor.py 条目
crontab -l | grep -v 'monitor.py' | crontab -

# 2. 确认已清除
crontab -l | grep monitor.py   # 无输出即成功
```

然后删除 OpenClaw 中的两个 cronjob（编辑 `~/.openclaw/cron/jobs.json`，移除 name 为「开盘前舆情分析」和「收盘复盘与持仓诊断」的条目）。

#### 暂停盯盘（临时，保留配置）

```bash
# 注释掉 crontab 中的 monitor.py 条目（加 # 前缀）
crontab -l | sed 's|^\(.*monitor\.py.*\)|#\1|' | crontab -

# 恢复时去掉注释
crontab -l | sed 's|^#\(.*monitor\.py.*\)|\1|' | crontab -
```

OpenClaw cronjob 暂时不动，仅在 `jobs.json` 中将对应 job 的 `enabled` 字段设为 `false`（若平台支持），或直接删除后重新添加。

#### 仅停止美股监控

```bash
# 删除美股时段的 monitor.py 条目（21、22、23 点及 0-5 点）
crontab -l | grep -v -E '^[^#].*(21|22|23| 0-5).*monitor\.py' | crontab -

# 确认 A股/港股条目仍在
crontab -l | grep monitor.py
```

#### 关闭单只股票的告警

直接编辑 `watchlist.json` 对应股票的 `alerts` 字段，无需重启，下一分钟自动生效：

```json
"alerts": {
  "change_abs":    [],
  "price_alert":   [],
  "cost_pct":      [],
  "volume_ratio":  0,
  "buy_sell_ratio": 0,
  "trailing_stop": { "enabled": false },
  "tech":          { "enabled": false },
  "tech_report":   { "enabled": false }
}
```

## 部署架构

**双轨制调度**：
- **OpenClaw**：仅触发需要 LLM 能力的任务（08:55 开盘前舆情、16:10 收盘复盘），共 2 个 job
- **crontab**：交易时段每分钟 tick，python脚本执行

### 1. 安装 crontab 任务

首次部署见 `ONBOARDING.md` 情况二步骤2；升级见 `UPGRADE.md` 第二步。

### 2. 手动执行

```bash
python3 scripts/monitor.py          # 执行一次 tick
python3 scripts/monitor.py --status # 查看运行状态
python3 scripts/monitor.py --replay # 回放最近交易日（测试推送）
```

### 3. 配置热重载

monitor 每次 tick 启动时重新读取 `config.json` 和 `watchlist.json`，直接编辑保存即可，下一分钟自动生效。

---

## 自选股配置格式

编辑 `watchlist.json`，每条记录格式：

```json
{
  "code":          "600519.SH",
  "name":          "贵州茅台",
  "market":        "CN",
  "currency":      "CNY",
  "hold_cost":     1600.0,
  "hold_quantity": 10,
  "alerts": {
    "change_abs":    [3, 5],
    "price_alert":   [],
    "cost_pct":      [-10, 20],
    "volume_ratio":  0,
    "buy_sell_ratio": 0,
    "trailing_stop": { "enabled": false, "profit_trigger": 10, "drawdown_warn": 5, "drawdown_exit": 10 },
    "tech":          { "enabled": false },
    "tech_report":   { "enabled": true }
  }
}
```

| 字段 | 说明 |
|------|------|
| `market` | `CN`（A股/ETF）、`HK`（港股）、`US`（美股） |
| `currency` | 持仓成本的货币：`CNY`（默认）/ `HKD`（港股）/ `USD`（美股）；不填则按 market 自动推断 |
| `hold_cost` | 持仓成本价，单位为 `currency` 指定的货币 |
| `change_abs` | 日内涨跌幅触发阈值列表。正值只看涨，负值只看跌，混用均支持。如 `[3, 5]` 涨幅达 3%/5% 推送，`[-3, -5]` 跌幅达 3%/5% 推送，`[5, -3]` 涨 5% 或跌 3% 均推送；冷却时间默认 **10分钟**（`config.json` → `settings.cooldown_minutes`） |
| `price_alert` | 固定价位告警，状态机触发：价格穿越阈值推一次，回到另一侧后才解锁（不会每天重推）。`above/below` 必须 > 0。格式：`[{"above": 7.5}, {"below": 5.8}]` |
| `cost_pct` | `[亏损阈值, 盈利阈值]`，如 `[-12, 15]` |
| `trailing_stop` | 动态止盈配置（`enabled` / `profit_trigger` / `drawdown_warn` / `drawdown_exit`，单位 %） |
| `tech.enabled` | 是否启用 KimiFinance 技术指标异动检测（仅 CN 市场有效） |
| `volume_ratio` | 量比异动阈值，`0` 表示关闭 |
| `buy_sell_ratio` | 多空比异动阈值，`0` 表示关闭 |
| `tech_report.enabled` | 是否进入每15分钟技术汇总报告（仅 CN 市场有效，默认 `true`） |

---

## 全局配置示例（config.json）

```json
{
  "kimiCodeAPIKey": "YOUR_kimiCodeAPIKey",
  "push": {
    "channel": "feishu"
  },
  "feishu": {
    "user_id": "ou_xxx",
    "app_id": "cli_xxx",
    "app_secret": "YOUR_APP_SECRET",
    "chat_id": ""
  },
  "watchlist": "watchlist.json",
  "settings": {
    "cooldown_minutes": 10,
    "price_alert_cooldown_hours": 24,
    "report_interval_minutes": 15,
    "card_mode": "chart"
  }
}
```

| 字段 | 说明 |
|------|------|
| `kimiCodeAPIKey` | Kimi Code API Key，必填 |
| `push.channel` | 推送渠道：`kimiclaw`（默认）/ `feishu` |
| `feishu.*` | 飞书推送配置（`push.channel = "feishu"` 时必填），留空则自动从 openclaw.json 读取；**若 openclaw.json 中尚未配置飞书 app_id/app_secret，需先完成渠道配置，见 `ONBOARDING.md` 情况零步骤2** |
| `feishu.chat_id` | 群推送 ID，优先于 user_id；留空则用 user_id 单推 |
| `watchlist` | 自选股文件路径，默认为 `watchlist.json` |
| `settings.cooldown_minutes` | 涨跌幅 / 持仓盈亏告警冷却时间（分钟），默认 `10` |
| `settings.price_alert_cooldown_hours` | 固定价位告警冷却时间（小时），默认 `24` |
| `settings.report_interval_minutes` | 技术汇总报告推送间隔（分钟），最小 `15`，默认 `15` |
| `settings.card_mode` | 飞书告警卡片样式：`chart`（含分时图的交互卡片，默认）/ `text`（纯文本兜底卡片，用于抓图/排查）；当行情无分时点位时会自动回退到 `text` 效果 |

**优先级规则**：
1. 环境变量 `kimiCodeAPIKey` 优先级最高，存在时自动覆盖 `config.json` 中的对应值
2. 飞书配置（app_id / app_secret / user_id）由 onboarding 从 `openclaw.json` 同步写入，无需手动设置

---

## 数据源

| 市场 | 行情 | 技术指标 | 交易时间（北京） |
|------|------|---------|----------------|
| A股（CN） | KimiFinance，同花顺兜底 | KimiFinance 5分钟 | 09:30–11:30、13:00–15:00 |
| 港股（HK） | KimiFinance，新浪财经兜底 | 不支持 | 09:30–12:00、13:00–16:00 |
| 美股（US） | KimiFinance（ticker 自动补 `.US`） | 不支持 | 21:30–04:00（夏令）/ 22:30–05:00（冬令） |


---

## 故障排查

```bash
# 监控状态检查
python3 scripts/monitor.py --status              # 查看上次运行时间、今日次数等

# 日志查看
tail -f logs/monitor.log  # 实时日志
cat logs/monitor.log      # 查看全部日志

# 手动调试
python3 scripts/monitor.py                       # 手动执行一次完整 tick
python3 scripts/monitor.py --dry-run             # 模拟异动推送，验证配置和推送通路
python3 scripts/monitor.py --replay              # 用最近交易日时间跑完整 tick（默认）

# 数据检查
cat data/state.json                              # 上次运行时间戳、今日次数、冷却状态
cat data/failed_messages.json                    # 失败推送队列（如有）

# 环境检查
echo $kimiCodeAPIKey                             # 环境变量是否设置
crontab -l | grep monitor.py                     # 检查 crontab 配置
```