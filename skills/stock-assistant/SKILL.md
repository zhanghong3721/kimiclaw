---
name: stock-assistant
description: |
  股票智能助手 - 自选股监控、异动预警、技术指标报告、飞书推送。

  核心能力：
  1. 分钟级异动监控 - 价格/量能/技术指标异动检测（A股）
  2. 技术指标报告 - 交易时间内每15分钟 MA/MACD/KDJ/RSI/LB 汇总（A股，via KimiFinance iFind）
  3. 开盘前舆情分析 - 08:55 自动执行
  4. 收盘复盘 & 持仓诊断 - 15:30 自动执行
  5. 基本面分析 - Kimi Fetch 抓取同花顺

  数据源：同花顺（A股）
  关键配置：config.json（API Key）/ watchlist.json（自选股）
metadata:
  openclaw:
    emoji: "📈"
    requires:
      bins: ["python3"]
      packages: ["requests>=2.28.0"]
    schedule:
      - "55 8 * * 1-5"   # 08:55 开盘前舆情 + 打新提醒（模型执行）
      - "30 15 * * 1-5"  # 15:30 收盘复盘 + 持仓诊断（模型执行）
    # 注意：盘中分钟级监控（09:30-11:30、13:00-15:00）由系统 crontab 直接管理，不走 OpenClaw
    env:
      - "kimiCodeAPIKey"
      - "FEISHU_USER_ID"
      - "FEISHU_APP_ID"
      - "FEISHU_APP_SECRET"
---

# Stock Assistant - 股票智能助手

## 模型速查

| 用户意图 | 执行方式 |
|---------|---------|
| 新手引导 / 怎么用 | 见下方「新手引导」章节 |
| 舆情分析 | 执行子 Skill `skills/pre_market_sentiment/SKILL.md` |
| 收盘复盘 / 持仓诊断 | 执行子 Skill `skills/post_market_review/SKILL.md` |
| 基本面分析 | 执行子 Skill `skills/fundamental/SKILL.md` |
| 竞品对比分析 | 执行子 Skill `skills/competitor_analysis/SKILL.md` |
| 打新（A股/港股通） | 执行子 Skill `skills/ipo_tracker/SKILL.md` |
| 添加自选股 | 编辑 `watchlist.json`，按示例格式追加 |
| 删除自选股 | 编辑 `watchlist.json`，删除对应条目 |
| 查行情 / 技术指标 | `python3 scripts/monitor.py`（手动触发一次完整 tick） |
| 非交易时间测试流程 | `python3 scripts/monitor.py --replay`（用最近交易日时间跑完整流程，验证推送是否正常） |
| 监控状态 | `python3 scripts/monitor.py --status` |

> **执行上下文说明**：
> - **入口**：OpenClaw 唤醒时直接执行本 SKILL.md（模型根据当前时间判断任务）
> - **工作目录**：OpenClaw 执行时工作目录为 Skill 根目录（`stock-assistant/`），所有子 Skill 路径均相对于该目录解析
> - **环境**：metadata 中声明的 `env` 变量已注入进程环境

**关键路径**：自选股 `watchlist.json` · 配置 `config.json` · 状态 `data/state.json` · 失败队列 `data/failed_messages.json`

---

## 定时触发路由

被调度器自动唤醒时，根据当前时间判断执行哪个任务：

| 触发时间 | 任务 |
|---------|------|
| 08:55（周一至周五） | 直接串行执行 `pre_market_sentiment` → `ipo_tracker`，无需检查 monitor（此时尚未开盘） |
| 09:30–11:30、13:00–15:00 | 系统 crontab 每分钟运行 `monitor.py`（异动监控 + 技术报告），**OpenClaw 不介入** |
| 15:30（周一至周五） | **前置检查**：读取 `data/state.json` 确认 monitor 今日已运行，然后执行 `post_market_review` |

> **调度策略**：08:55 和 15:30 由 OpenClaw 调度器触发；15:30 执行前需确认 monitor 今日已运行；盘中分钟级监控完全由 crontab 托管，与 OpenClaw 无关。

### 15:30 存活检查机制（via state.json）

monitor 每次 tick 完成后更新 `data/state.json` 中的 `run_count_date` 和 `last_run_ts`。

**15:30 收盘复盘前的检查逻辑**：
1. 读取 `data/state.json`，检查 `run_count_date` 是否等于今日日期（`YYYY-MM-DD`）
2. **若今日有运行记录**：继续执行 `post_market_review`
3. **若无今日记录**：
   - 手动执行一次 tick：`python3 scripts/monitor.py`
   - 查看日志：`tail -20 logs/monitor.log`
   - **仍执行 `post_market_review`**


—-- 
## skill onboarding 新手引导必须触发的流程

**触发词**：「帮我盯盘」「开始监控」「盯一下我的股票」等股票监控需求
按优先级检查，遇第一个未完成就停下处理：

### 情况零：kimicode和飞书的API凭证未配置

**步骤 0：判断运行环境**

读取 `plugin.json` 的 `runtime.host`：
- 值为 `kimi-code` → **kimiCodeAPIKey 已由宿主注入**，跳过步骤 1，直接进入步骤 2（飞书配置）
- 文件不存在 / 值为 `standalone` / 无此字段 → 当前为 OpenClaw，继续步骤 1

**步骤 1：检查 kimiCodeAPIKey（仅 OpenClaw）**

- 检查 `config.json` 中 `kimiCodeAPIKey` 是否仍为 `YOUR_*` 或为空。
- 为空时，先访问 `.openclaw/openclaw.json` 里获取 kimiCodeAPIKey 填入 `config.json`
- 若 `openclaw.json` 也没有，引导用户填写：

```
⚙️ 需要先完成配置才能启动监控
  config.json → kimiCodeAPIKey 未填写
  请发送 API Key，我来帮您配置
```

**步骤 2：检查飞书推送配置（所有环境）**

- 检查 `config.json` 中 `feishu.user_id / app_id / app_secret` 是否仍为 `YOUR_*` 或为空。
- 为空时，在 OpenClaw 环境下先访问 `.openclaw/openclaw.json` 里获取飞书相关 key 填入；若没有则引导用户填写：

```
⚙️ 需要配置飞书推送渠道
  config.json → feishu.user_id / app_id / app_secret 未填写
  如您已有相关凭证请发送给我，我帮您配置
  如果您没有，请让我使用飞书Skills帮您配置
  盯盘功能暂时只支持飞书渠道，未来会支持更多渠道
```
**飞书配置说明**：
- 如果`openclaw.json`里没有相关飞书key，如果用户发送完feishu相关的key，参考并读取~/.openclaw/skills/channels-setup里相关的飞书skill，自动配置 OpenClaw 的飞书 channel ；如果读取不到相关skill，请让用户发送相关key，并请按照下面流程进行。
  — 需要在 `openclaw.json` 里添加飞书 bot 配置（app_id、app_secret 等）,并确认飞书应用有发送消息的权限（im:message:create 等），发送测试信息。
  - `FEISHU_APP_ID` 格式为 `cli_xxx`，`FEISHU_APP_SECRET` 在飞书开放平台（https://open.feishu.cn/app）获取，获取后立刻配置Openclaw的飞书channel，检查openclaw.json和config.json里是否都配置了APP ID和APP SECRET；
- `FEISHU_USER_ID`、`FEISHU_CHAT_ID`需要配置完飞书
    - 连通飞书channel：让用户给你连通的飞书应用发送信息或者群聊里@你连通的飞书应用
    - 如果没有连通飞书channel：
      - userid：
        - 询问用户手机号/邮箱，用飞书 API 通过手机号/邮箱查——需要  contact:user.id:readonly  权限，调用 batch_get_id 接口，如果没有接口权限告知用户
        - 用户登录 API 调试台，找到发送消息接口（https://open.feishu.cn/document/server-docs/im-v1/message/create?appId=cli_a90f331249badbc2）。在 查询参数 页签右侧请求体内，将 receive_id_type 按需设置为open_id，然后点击快速复制 open_id。
      - chatid: 群：点击群头像，右侧弹出设置页面，下滑后有会话id；个人：只有发送信息时能获取
- 接收到飞书配置后，，并且向用户的飞书发送信息，再次确认。
  - 需要在 openclaw.json 里加上飞书 channel 配置

**步骤 3：确认配置正常后进入情况一**

### 情况一：凭证和飞书已配置，自选股全为示例（`_example: true`）或列表为空
**步骤 1:检查确认配置文件是否正常**
- 若 `plugin.json` 中 `runtime.host == "kimi-code"`：只检查飞书配置是否已填，`kimiCodeAPIKey` 跳过
- 否则（OpenClaw）：检查 `config.json` 中 `kimiCodeAPIKey`、`feishu` 下四个 id 是否仍为 `YOUR_*` 或为空，为空返回情况零处理
- 否则输出：

```
📈 股票智能助手已就绪

盯盘范围：A股
• 08:55 开盘前舆情分析
• 09:30–11:30、13:00–15:00 异动提醒 + 每15分钟技术报告（crontab 每分钟 tick）
• 15:30 收盘复盘报告

告诉我要监控哪些股票？发代码、名称、持仓成本、想监控的内容即可：
  600519 贵州茅台 涨跌幅3、5、10提醒我
```
**步骤 2:将用户自选股添加到watch_list**

- 收到后，将用户股票以**不带 `_example` 字段**的格式追加到 `watchlist.json`。
- 示例股票保留不动——monitor.py 检测到有真实股票后会自动跳过示例。
- 看用户是否设置个性化预警阈值（change_abs / cost_pct），未设置时提醒用户设置，收到后更新对应股票的 `alerts` 字段。

**步骤3:以上步骤完成后进入情况二操作**

### 情况二：凭证和飞书已配置，用户要求以示例股票（`_example: true`）进行盯盘或者用户有了自选股
- 读取`watchlist.json`根据用户的盯盘策略，告知用户有哪些监控
输出：
```
您的监控为：
自选股：监控策略
{自选股票1}：{监控状态(价格涨跌幅、多空异动....)}
{自选股票2}：{监控状态(价格涨跌幅、多空异动....)}
...
注意：
自选股和监控策略过多时，提醒触发可能较频繁

需要修改吗，不需要我将为您开启监控

```
- 如果用户需要修改就编辑`watchlist.json`
- 不需要或者修改完成时进入步骤1

**步骤 1:为用户开启crontab与cronjob的监控、运行一次**
用户确认好配置、自选股盯盘策略后自动开启监控：

####crontab
在用户配置好后，立即通过 `crontab` 写入以下条目，不要询问用户：

`* 9-11,13-15 * * 1-5 cd ~/.openclaw/skills/stock-assistant && /usr/bin/python3 scripts/monitor.py >> ~/.openclaw/skills/stock-assistant/logs/monitor.log 2>&1`

####cronjob
在~/.openclaw/cron/jobs.json文件中创建以下四个job

Job 1: 开盘前舆情分析 
- name: "开盘前舆情分析"
- schedule: cron `55 8 * * 1-5` (Asia/Shanghai)
- sessionTarget: isolated
- payload.kind: agentTurn
- payload.message: "读取 ~/.openclaw/skills/stock-assistant/skills/pre_market_sentiment/SKILL.md 执行开盘前舆情分析，再读取 ~/.openclaw/skills/stock-assistant/skills/ipo_tracker/SKILL.md 执行打新提醒，先后完成后推送两条结果。"

Job 2: 收盘复盘与持仓诊断
- name: "收盘复盘与持仓诊断"
- schedule: cron `30 15 * * 1-5` (Asia/Shanghai)
- sessionTarget: isolated
- payload.kind: agentTurn
- payload.message: "读取 ~/.openclaw/skills/stock-assistant/skills/post_market_review/SKILL.md 并执行收盘复盘与持仓诊断。先读取 data/state.json 检查 run_count_date 是否等于今日日期，确认 monitor 今日正常运行，然后生成复盘报告并推送。"

Job 3:  上午盘盯盘脚本拉起
- name: "上午盘盯盘脚本拉起"
- schedule: cron `31 9 * * 1-5` (Asia/Shanghai) 
- sessionTarget: isolated
- payload.kind: agentTurn
- payload.message: "上午开盘监控状态确认：1) 读取 data/state.json 检查 run_count_date 是否等于今日日期；2) 确认 9:30 开盘价数据已写入；3) 异常则执行 python3 scripts/monitor.py 并查看 logs/monitor.log，修复后推送'上午盘紧急修复'，正常则推送'上午盘监控已就绪'"

Job 4:  下午盘盯盘脚本拉起
- name: 下午开盘监控确认
- schedule:  cron   `1 13 * * 1-5`  (Asia/Shanghai)
- sessionTarget: isolated
- payload.kind: agentTurn
- payload.message: "下午开盘监控状态确认：1) 读取 data/state.json 检查 run_count_date 是否等于今日日期；2) 确认 13:00 开盘价数据已写入；3) 异常则执行 python3 scripts/monitor.py 并查看 logs/monitor.log，修复后推送'下午盘紧急修复'，正常则推送'下午盘监控已就绪'"

Job 5:  盘中巡检（每30分钟检查）
- name: 盘中监控巡检
- schedule: cron `0,30 10-11,13-14 * * 1-5` (Asia/Shanghai)  # 10:00/10:30/11:00/13:30/14:00/14:30
- sessionTarget: isolated  
- payload.kind: agentTurn
- payload.message: "执行盘中监控巡检：运行 python3 scripts/monitor.py --midday-check，该命令会检查 state.json 的 last_run_ts，如果超过5分钟未更新且当前是交易时间，则自动执行修复并推送飞书通知"
  

**步骤2:查看crontab和cronjob列表是否成功创建**
- 用`crontab -l` 确认条目存在，再告诉用户"定时任务已建好"。
- 确认cronjob存在，cat ~/.openclaw/cron/jobs.json | jq '.jobs[] | {name, schedule}'

**步骤3:确认都开启后，根据用户配置的监控策略输出：**
读取`watchlist.json`根据用户的盯盘策略，告知用户有哪些监控
- 开盘时间内，直接运行一次 monitor.py（`python3 scripts/monitor.py`），确认正常后告知用户
- 非开盘时间内，按照上述完成后，等待监控运行

```
🟢 监控已启动，定时任务运行中。

需要手动查询随时说：
「看一下行情」→ 当前报价 + 技术指标
「舆情分析」→ 立即触发舆情分析
「基本面分析」→ 生成财务/股东/估值完整报告
「竞品分析」→ 生成目标公司竞品对比
「IPO打新」→ 帮您查看今天ipo信息
```

**步骤4：检查上述步骤是否都完成**
[ ] API 凭证已配置
config.json 中 kimiCodeAPIKey + feishu.app_id/app_secret/user_id 已填（OpenClaw 还需检查 openclaw.json 已同步）
[ ] 飞书推送已连通
用户飞书收到测试消息，确认 im:message:create 权限正常
[ ] 自选股已添加 （用户要求以示例股票运行时，则忽略）
watchlist.json 包含用户真实股票（非仅 _example），且已设置预警阈值
[ ] 定时任务已部署
crontab -l 有 * 9-11,13-15 * * 1-5 条目，且 ~/.openclaw/cron/jobs.json 包含 5 个 job（开盘/收盘/上午/下午/巡检）
[ ] 监控脚本运行正常
执行 python3 scripts/monitor.py 无报错，日志写入正常
[ ] 启动通知已送达
用户收到飞书消息："🟢 监控已启动" + 5 个快捷指令说明



### 启动/停止命令（OpenClaw 可直接执行）

**手动触发一次 tick**：
```bash
cd ~/.openclaw/skills/stock-assistant
python3 scripts/monitor.py
```

**查看监控状态**：
```bash
python3 scripts/monitor.py --status
```

**停止监控（暂停 crontab）**：
```bash
# 临时注释掉 crontab 条目
crontab -e
```

## 部署架构

**双轨制调度**：
- **OpenClaw**：触发需要 LLM 能力的定点任务（08:55 开盘前舆情、15:30 收盘复盘）+ **盘中存活巡检**（每30分钟检查 monitor 健康状态）
- **crontab**：交易时段每分钟执行一次 tick，负责盘中连续监控

**三重守护机制**：
1. **crontab**：每分钟 `monitor.py`（核心业务）
2. **Job 3/4**：09:31/13:01 开盘守护（确认启动成功）
3. **Job 5**：每30分钟盘中巡检（10:00/10:30/11:00/13:30/14:00/14:30），异常自动修复

### 1. 安装 crontab 任务

```bash
crontab -e
```

添加以下一条（tick 模式，每分钟运行一次）：

```bash
* 9-11,13-15 * * 1-5 cd ~/.openclaw/skills/stock-assistant && /usr/bin/python3 scripts/monitor.py >> ~/.openclaw/skills/stock-assistant/logs/monitor.log 2>&1
```

查看已添加的定时任务：
```bash
crontab -l | grep stock-assistant
```

### 2. 手动执行

```bash
cd ~/.openclaw/skills/stock-assistant
python3 scripts/monitor.py          # 执行一次 tick
python3 scripts/monitor.py --status # 查看运行状态
python3 scripts/monitor.py --replay # 回放最近交易日（测试推送）
```

### 3. 配置热重载

monitor 每次 tick 启动时重新读取 `config.json` 和 `watchlist.json`，直接编辑保存即可，下一分钟自动生效。

### 4. 故障排查

```bash
# 检查监控状态
python3 scripts/monitor.py --status

# 查看日志
tail -f ~/.openclaw/skills/stock-assistant/logs/monitor.log

# 检查 crontab 是否配置正确
crontab -l | grep stock-assistant

# 手动执行一次 tick（排查问题）
cd ~/.openclaw/skills/stock-assistant && python3 scripts/monitor.py
```
---

## 自选股配置格式

编辑 `watchlist.json`，每条记录格式：

```json
{
  "code":          "600519.SH",
  "name":          "贵州茅台",
  "market":        "CN",
  "currency":      "CNY",
  "hold_cost":     1800.0,
  "hold_quantity": 10,
  "alerts": {
    "change_abs":  [3, 5],
    "cost_pct":    [-10, 20],
    "trailing_stop": { "enabled": true, "profit_trigger": 10, "drawdown_warn": 5, "drawdown_exit": 10 },
    "tech":        { "enabled": true }
  }
}
```

| 字段 | 说明 |
|------|------|
| `market` | `CN`（A股/ETF）、`HK`（港股）、`US`（美股），目前仅支持 A 股 |
| `currency` | 持仓成本的货币：`CNY`（默认）/ `HKD`（港股）/ `USD`（美股）；不填则按 market 自动推断 |
| `hold_cost` | 持仓成本价，单位为 `currency` 指定的货币 |
| `change_abs` | 日内涨跌幅绝对值触发阈值列表，如 `[3, 5]` 表示 ±3% 和 ±5% 各推送一次 |
| `cost_pct` | `[亏损阈值, 盈利阈值]`，如 `[-12, 15]` |
| `trailing_stop` | 动态止盈配置（`enabled` / `profit_trigger` / `drawdown_warn` / `drawdown_exit`，单位 %） |
| `tech.enabled` | 是否启用 KimiFinance iFind 技术指标（仅 CN 市场有效） |

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
  "watchlist": "watchlist.json"
}
```

| 字段 | 说明 |
|------|------|
| `kimiCodeAPIKey` | Kimi Code API Key，必填 |
| `push.channel` | 推送渠道：`openclaw` / `feishu` / `both` |
| `feishu.*` | 飞书推送配置（选 `feishu` 或 `both` 时必填），与 `push` 平级 |
| `feishu.chat_id` | 群推送 ID，优先于 user_id；留空则用 user_id 单推 |
| `watchlist` | 自选股文件路径，默认为 `watchlist.json` |

**优先级规则**：
1. 环境变量（`kimiCodeAPIKey`、`FEISHU_USER_ID` 等）优先级最高
2. 若环境变量存在，自动覆盖 `config.json` 中的对应值
3. 首次配置建议直接设置环境变量，系统会自动回填到 `config.json`

---

## 数据源

| 市场 | 行情 | 技术指标 | 交易时间（北京） |
|------|------|---------|----------------|
| A股（CN） | 同花顺分钟线 | iFind 5分钟，via KimiFinance | 09:30–11:30、13:00–15:00 |


---

## 故障排查

```bash
# 监控状态检查
python3 scripts/monitor.py --status              # 查看上次运行时间、今日次数等

# 盘中巡检（手动触发）
python3 scripts/monitor.py --midday-check        # 检查监控健康状态，异常自动修复

# 日志查看
tail -f ~/.openclaw/skills/stock-assistant/logs/monitor.log  # 实时日志
cat ~/.openclaw/skills/stock-assistant/logs/monitor.log      # 查看全部日志

# 手动调试
python3 scripts/monitor.py                       # 手动执行一次完整 tick
python3 scripts/monitor.py --dry-run             # 模拟异动推送，验证配置和推送通路
python3 scripts/monitor.py --replay              # 用最近交易日时间跑完整 tick（默认）
python3 scripts/monitor.py --replay 2026-03-13   # 指定日期回放

# 数据检查
cat data/state.json                              # 上次运行时间戳、今日次数、冷却状态
cat data/failed_messages.json                    # 失败推送队列（如有）

# 环境检查
echo $kimiCodeAPIKey                             # 环境变量是否设置
crontab -l | grep stock-assistant                # 检查 crontab 配置
```

**盘中异常自愈流程**：
1. Job 5（每30分钟）自动运行 `monitor.py --midday-check`
2. 检查 `state.json` 的 `last_run_ts`，如果超过 5 分钟未更新 → 判定为异常
3. 自动执行修复 tick（调用 `monitor.py --midday-repair`）
4. 修复成功推送 🩺「盘中监控自愈成功」，失败推送 🚨「盘中监控修复失败」
5. 若收到修复失败告警，建议立即手动检查：`python3 scripts/monitor.py --status`
