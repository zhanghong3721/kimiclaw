# Memory Consolidation PRD

## 问题

OpenClaw 的记忆持久化完全依赖 agent 在 session 内自主写文件。实测 50 用户中，64% 从未主动写过记忆文件。Daily reset 后 agent 失忆是结构性问题，不是偶发 bug。

## 解法

不依赖 agent 主动写入。离线脚本从聊天记录自动提取、总结、写回 `USER.md`。这个文件每个 turn 自动注入 system prompt，零 gateway 改动。

## 模块

| 模块 | 是什么 | 怎么生成 | 什么时候更新 | 什么时候不更新 | 相关配置 |
|---|---|---|---|---|---|
| **Visual Memory** | 用户发过的图片和文件列表（带描述性文件名） | 扫描 `{workspace}/memorized_media/` 目录 | 跟随 STM 一起 | 目录没有新文件 | `VISUAL_MEMORY=20`（最多展示条数） |
| **STM** | 用户最近聊了什么（原文摘录） | 从聊天记录 `~/.openclaw/agents/main/sessions/*.jsonl` 提取，反向清洗 gateway 装饰（详见下方） | 1. `/reset`、`/new`<br>2. Daily reset（默认凌晨 4 点）<br>3. Idle reset（用户超时未发消息） | — | `DAYS=30`（采样窗口）<br>`MAX_SESSIONS=20`<br>`MAX_PER_SESSION=10`<br>`MAX_CHARS_PER_MESSAGE=500`<br>`MIN_PER_CHANNEL=3`<br>`INCLUDE_GROUP=false` |
| **LTM** | 用户的偏好习惯总结（比如工作角色、沟通风格、关心的话题） | 把 STM 喂给 LLM 总结。调用 `openclaw.json` 里配置的 LLM provider，不需要额外配 key | 1. Daily reset（默认凌晨 4 点）<br>2. Idle reset | 用户没聊新内容（STM 没变化则跳过 LLM 调用） | `LLM_API_KEY=`（留空自动从 openclaw.json 读）<br>`session.reset.atHour`（daily 时间）<br>`session.reset.idleMinutes`（idle 超时） |

## STM 消息清洗

原始消息经过 gateway 装饰，需要反向清洗才能还原用户原文：

| 清洗项 | 示例 | 处理方式 |
|---|---|---|
| System Event | `System: [timestamp] Feishu[default] DM from ou_xxx: preview` | 整行删除 |
| IM Envelope | `[Feishu ou_xxx 2026-03-09T08:22Z] 用户原文` | 剥离 envelope，只保留用户原文 |
| PDS 传感器数据 | 心率/GPS/电量粘在消息里 | 剥离 |
| Heartbeat | 系统心跳注入的消息 | 从 `HEARTBEAT.md` 动态读签名过滤 |
| CRON session | 定时任务产生的 session | 整个 session 过滤 |
| 群聊噪声 | 群里多人发言 | 只保留触发 agent 的那条消息 |

STM 只保留用户消息，不存模型回复。每行带 session_uuid，agent 需要完整对话时可自行读取对应 JSONL。

## STM 采样策略

时间优先，最近的 session 优先入选：

1. 每个 channel（FEISHU:DM、FEISHU:GROUP、LOOPBACK 等）保底取最近 N 个 session
2. 剩余名额按时间倒序填充
3. 总数不超过 `MAX_SESSIONS`
4. 每个 session 取首尾各半消息，中间插跳过标记
5. 超长消息截断
6. 只保留 session 开始时间戳，逐条消息不带时间戳

## 触发机制

Gateway plugin 监听 `message_received`，每条消息检测两个条件：

| 触发条件 | 检测方式 | 触发 STM | 触发 LTM |
|---|---|---|---|
| `/reset`、`/new` | sessionId 变化 | ✅ | ❌ |
| Daily reset | `updatedAt` 早于当天 reset 时间 | ✅ | ✅ |
| Idle reset | `updatedAt` 距现在超过 idleMinutes | ✅ | ✅ |

- 一条消息一次性扫描所有 session，STM 只跑一次（全局的，不是 per-session）
- 冷启动时从 `sessions.json` 读取当前 sessionId 作为 baseline
- LTM 有 stm_hash 去重，内容没变不调 LLM

## 安装

```bash
git clone https://dev.msh.team/liaidi/memory_consolidation.git
cd memory_consolidation
bash install.sh
```

`install.sh` 做三件事：
1. 拷贝脚本到 `~/.openclaw/workspace/memory_consolidation/`
2. 拷贝 plugin 到 `~/.openclaw/extensions/memory-consolidation/`（OpenClaw 自动发现）
3. 重启 gateway

零配置。API key、session 路径、workspace、timezone 全从 `openclaw.json` 自动读取。

## USER.md 结构

```
（用户手写的 Profile、通讯录等 — 永不覆盖）

<IMPORTANT_REMINDER>
> 统计信息 + 配置路径

## Visual Memory
# Long-Term Memory (LTM)
## Short-Term Memory (STM)
</IMPORTANT_REMINDER>
```

脚本只操作 `<IMPORTANT_REMINDER>` 块，用户手写的内容原样保留。

## 设计原则

- **聊天记录只读**：JSONL 是 source of truth，脚本不改它
- **单文件交付**：只写 USER.md，利用 OpenClaw 已有的注入机制
- **Agent 可自治**：`.env` 对 agent 可读写，agent 可以自己调参数
- **不替代内置记忆**：不碰 MEMORY.md / memory/*.md 向量检索

## 不做

- 不修改 JSONL 聊天记录
- 不改 SOUL.md / AGENTS.md
- 不做多用户编排（当前：单用户部署）
