# Stock Assistant - Onboarding 新手引导

整体流程：**情况零（凭证）→ 情况一（收集自选股）→ 情况二（确认并开启监控）**
按顺序检查，遇第一个未完成就停下处理。

---

### 情况零：凭证检查与推送渠道配置

**步骤 0：判断运行环境**

读取 `plugin.json` 的 `runtime.host`：
- 值为 `kimi-code` → kimiCodeAPIKey 已由宿主注入，跳过步骤 1
- 文件不存在 / 值为 `standalone` / 无此字段 → 当前为 OpenClaw，继续步骤 1

**步骤 1：检查 kimiCodeAPIKey（仅 OpenClaw）**

读取 `config.json` 中 `kimiCodeAPIKey`，若为空：
- 自动从 `~/.openclaw/openclaw.json` 的 `plugins.entries.kimi-claw.config.bridge.kimiCodeAPIKey` 读取并回填
- 若 openclaw.json 也没有，提示用户填写

**步骤 2：推送渠道检查**

**自动检测当前对话渠道**，无需询问用户：
- 用户从 **Kimi IM** 发消息 → `push.channel = "kimiclaw"`（默认）
- 用户从 **飞书** 发消息 → `push.channel = "feishu"`，同时同步飞书配置：
  - **前置检查**：读取 `~/.openclaw/openclaw.json` 的 `channels.feishu.app_id` 和 `channels.feishu.app_secret`
    - **为空**：提示用户先在 OpenClaw **右侧面板扫码登录飞书账号**，绑定完成后再继续（扫码后 openclaw.json 会自动写入 app_id / app_secret）
    - **非空**：继续下一步
  - `app_id` / `app_secret` 从 `~/.openclaw/openclaw.json` 的 `channels.feishu` 读取并写入 `config.json`
  - `user_id` 从 `channels.feishu.allowFrom[0]` 读取：
    - **有值**：展示给用户确认「检测到飞书用户 ID：`ou_xxx`，将推送到此账号」，确认后写入
    - **为空**：提示用户给飞书 bot 发一条消息，自动从消息事件获取 user_id 后写入

将检测到的渠道写入 `config.json` 的 `push.channel`，完成后进入情况一。

---

### 情况一：推送渠道已就绪，自选股为空或全为示例股票

**步骤 0：初始化配置文件（全新安装时执行）**

检查 `config.json` 和 `watchlist.json` 是否存在，不存在则从模板初始化：

```bash
[ ! -f config.json ]    && cp config_v2.json config.json    && rm config_v2.json
[ ! -f watchlist.json ] && cp watchlist_v2.json watchlist.json && rm watchlist_v2.json
```

**步骤 1：验证配置并试跑**

运行 `python3 scripts/monitor.py --dry-run`，确认推送成功后输出：

```
📈 股票智能助手已就绪

盯盘范围：A股 + 港股 + 美股
• 08:55 开盘前舆情分析
• 09:30–11:30、13:00–15:00 A股异动提醒 + 每15分钟技术报告
• 09:30–12:00、13:00–16:00 港股异动提醒
• 21:30–04:00（夏令）/ 22:30–05:00（冬令） 美股异动提醒
• 16:10 收盘复盘（A股 + 港股）

推送渠道：{当前渠道}

告诉我要监控哪些股票？发代码、名称、持仓成本、想要什么提醒即可：
  600519 贵州茅台  成本1600  涨跌幅3%、5%提醒我
  0700.HK 腾讯控股  涨跌幅3%、5%提醒我，跌到480推我一次
  AAPL 苹果  涨跌幅3%、5%提醒我
```

**步骤 2：将用户自选股写入 watchlist.json**

收到用户股票后：
- 以**不带 `_example` 字段**的格式追加到 `watchlist.json`
- 示例股票保留不动（monitor.py 检测到真实股票后自动跳过示例）
- **默认只开启涨跌幅提醒**，其余全部关闭，用户明确要求时才开启：
  - 涨跌幅提醒 → 配 `change_abs`；正值只看涨，负值只看跌，混用均支持；用户未提阈值时默认 `[3, 5]`（双向），只要涨提醒用 `[3, 5]`，只要跌提醒用 `[-3, -5]`
  - 固定价位提醒 → 配 `price_alert: [{"above": X}, {"below": Y}]`；用户未提则 `[]`
  - 持仓成本/盈亏 → 配 `cost_pct: []`；用户提到成本价且明确要盈亏提醒时才填
  - 量比、多空比、追踪止盈、技术指标异动：默认 `0` 或 `enabled: false`
  - 技术汇总报告：CN 股票默认 `tech_report.enabled: true`（进汇总报告）

收到用户股票后，若**数量超过 20 只**，在写入前提示：

```
您一共提供了 {X} 只股票。建议优先盯 20 只以内的重点持仓，这样每分钟能在 20 秒内完成一轮扫描，提醒更及时；超过 20 只后响应会逐渐变慢，30 只是硬上限。
需要帮您筛选重点股票，还是全部加入？
```

配置完成后，告知用户当前已开启的内容，并简要介绍可以进一步开启的策略：

```
已为 {X} 只股票配置提醒：{股票列表及已开启的告警类型}

⏱ 告警冷却时间（同一信号触发后的静默期）：
• 涨跌幅 / 持仓盈亏：10分钟
• 量能 / 技术异动：15分钟
• 追踪止盈：30分钟
• 固定价位：24小时（到价只推一次）
如需调整冷却时间，直接告诉我，例如「涨跌幅提醒改成10分钟冷却」。

还可以按需开启：
🔔 简单盯盘  • 涨跌幅提醒  • 固定价位提醒（到价推一次）
📊 持仓跟踪  • 相对成本盈亏提醒  • 追踪止盈
🔬 技术策略  • MACD金叉/死叉、KDJ超买超卖、RSI极值、布林带突破
              （信号较频繁，建议只对重点股票开启）

需要加哪个告诉我，或者直接说「开启监控」。
```

> **技术汇总报告配置**（用户问到时才说）：推送间隔默认15分钟，某只不想进报告可单独关闭。

完成后进入情况二。

---

### 情况二：自选股已就绪，等待用户确认开启监控

**步骤 1：展示当前配置摘要，等待用户确认**

读取 `watchlist.json`，输出当前监控概览：

```
您的监控配置：
{股票1}（{市场}）：{已开启的告警类型，如 涨跌幅±3%/±5%、跌到X推一次}
{股票2}（{市场}）：{已开启的告警类型}
...

需要调整吗？确认无误就说「开启」，我来部署定时任务。
```

- 需要修改 → 编辑 `watchlist.json` 后重新展示
- 用户说「开启」/ 「没问题」/ 「可以」→ 进入步骤 2

**步骤 2：部署定时任务**

用户确认后，写入 crontab 和 cronjob。执行前先用 `pwd` 获取路径并赋值，后续命令直接用变量：

#### crontab

```bash
D=$(pwd)
(crontab -l 2>/dev/null; cat << EOF
# A股+港股日盘（精确覆盖交易时段，跳过午休）
30-59 9 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 10-11 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 13-16 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
# 美股监控（夏令21:30-04:00 / 冬令22:30-05:00，内部自动判断开盘）
30-59 21 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 22-23 * * 1-5 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
* 0-5 * * 2-6 cd $D && /usr/bin/python3 scripts/monitor.py >> $D/logs/monitor.log 2>&1
EOF
) | crontab -
```

> 无美股自选股时可省略最后三条。

#### cronjob

```bash
# 开盘前舆情分析 + 打新提醒（工作日 08:55，实际触发约 08:56-57）
openclaw cron add --name "开盘前舆情分析" --cron "55 8 * * 1-5" --tz "Asia/Shanghai" --session isolated --message "执行 stock-assistant 的 pre_market_sentiment 子技能，分析开盘前舆情和消息面，汇报给我。执行 stock-assistant 的 ipo_tracker 子技能，检查本周打新日历和打新资格，汇报给我。"

# 收盘复盘（工作日 16:10，实际触发约 16:11-12）
openclaw cron add --name "收盘复盘" --cron "10 16 * * 1-5" --tz "Asia/Shanghai" --session isolated --message "执行 stock-assistant 的 post_market_review 子技能，结合今日 watchlist、大盘和消息面生成复盘报告，汇报给我。"
```

**步骤 3：验证并告知用户**

- `crontab -l` 确认 `30-59 9` / `* 10-11` / `* 13-16` / `30-59 21` / `* 22-23` / `* 0-5` 条目存在（无美股自选股时后三条可省略）
- `openclaw cron list` 确认 2 个 job 存在（开盘前舆情分析、收盘复盘）
- 开盘时间内：运行一次 `python3 scripts/monitor.py`，确认正常
- 非开盘时间：无需运行，等待下次开盘自动触发

```
🟢 监控已启动，定时任务运行中。

随时可以说：
「看一下行情」        → 当前持仓报价 + 技术指标快照（未到开盘时间则数据暂未拉取）
「舆情分析」          → 立即触发开盘前舆情分析
「K线分析 {股票}」    → 日K标注图 + 形态识别 + 完整技术报告
「分时图 {股票}」     → 今日分时图 + 盘中分析
「基本面分析 {股票}」 → 财务/股东/估值深度报告
「竞品分析 {股票}」   → 同行横向对比 + 相对估值
「打新」              → 本周新股日历 + 打新资格核查
「复盘」              → 立即触发收盘复盘与持仓诊断
```

**步骤4：检查上述步骤是否都完成**
[ ] 推送渠道已就绪
`python3 scripts/monitor.py --dry-run` 出现 `✅ 飞书推送成功` 或 `✅ KimiIM 推送成功`（任一即可）
[ ] 自选股已添加（用户要求以示例股票运行时可忽略）
watchlist.json 包含用户真实股票（非仅 _example），且已设置预警阈值
[ ] 定时任务已部署
`crontab -l` 有 `30-59 9` / `* 10-11` / `* 13-16` 三条条目（有美股自选股时还需 `30-59 21` / `* 22-23` / `* 0-5`），且 `openclaw cron list` 输出中包含「开盘前舆情分析」和「收盘复盘」
[ ] 监控脚本运行正常
`python3 scripts/monitor.py` 无报错，日志写入正常
[ ] 启动通知已送达
用户收到推送消息："🟢 监控已启动" + 快捷指令说明
