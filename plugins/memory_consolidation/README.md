# Memory Consolidation

OpenClaw 跨会话记忆系统。`/reset` 后第一条消息就有最新记忆，零滞后。

## 安装

```bash
git clone ssh://git@dev.msh.team:30022/liaidi/memory_consolidation.git
cd memory_consolidation
bash install.sh
```

装完验证：发一条消息 → `/reset` → 问刚才说了什么 → 应该能答出来。

**测试环境额外步骤**：如果 LTM/diary 报 401，需要手动 `kimi` login 一次获取 OAuth credentials。线上镜像已预置。

### 合入 Kimi Claw 镜像

在 `kimiclaw-image/resources/commands/chinese-mainland-v1.sh` 末尾加：

```bash
git clone ssh://git@dev.msh.team:30022/liaidi/memory_consolidation.git /tmp/memory_consolidation
cd /tmp/memory_consolidation && bash install.sh
rm -rf /tmp/memory_consolidation
```

### 远程安装（Kimi Claw 开发机）

```bash
# 打包
tar czf ~/memory_consolidation.tar.gz install.sh memory_consolidation.py memory_consolidation.template.env prompts/ openclaw-hooks/

# Claw 上传页上传（先让对方 rm -f ~/memory_consolidation.tar*.gz）

# 对方机器执行
mkdir -p ~/memory_consolidation && tar xzf ~/memory_consolidation.tar.gz -C ~/memory_consolidation && cd ~/memory_consolidation && bash install.sh
```

`install.sh` 会：
1. 拷贝脚本 + prompts 到 `~/.openclaw/workspace/memory_consolidation/`
2. 拷贝 hook 到 `~/.openclaw/hooks/memory-stm-refresh/`
3. 在 `openclaw.json` 启用 `hooks.internal` + hook entry
4. 重启 gateway
5. 冷启动生成记忆（>= 5 sessions 跑 compact，否则只跑 STM）

## 架构

一个 hook `memory-stm-refresh`（`agent:bootstrap`）做所有事：

```
agent:bootstrap (每条消息, awaited)
  → timer 没设? → setTimeout 到 atHour - random(0-30min)
                  → 到时 spawn compact + diary（非阻塞）
  → sessionId 变了? → execSync STM (160ms)
  → 都没有 → 跳过 (0ms)
```

| 事件 | STM | LTM | Diary | 阻塞 |
|---|---|---|---|---|
| `/reset` `/new` | ✅ 当前 turn | ❌ | ❌ | 160ms |
| Daily timer (~3:30-4:00 AM) | ❌ | ✅ spawn | ✅ spawn | 0（无人在线） |
| Daily reset 后第一条消息 | ✅ 当前 turn | ✅ 已由 timer 生成 | ✅ 已由 timer 生成 | 160ms |
| 普通消息 | 跳过 | 跳过 | 跳过 | 0ms |

### Timer 机制

- 第一条消息 → `setTimeout` 到 `atHour`（默认 4am）前 0-30 分钟随机偏移
- Timer 触发 → spawn compact + diary（非阻塞，不冻结 gateway）
- 跑完自动设下一天 timer
- Gateway restart → 下一条消息重设 timer
- LLM 调用关闭 thinking（67s → 14s）

### LLM 认证（OAuth）

线上 Kimi Claw API key 不支持外部 HTTP 调用。通过 kimi-cli OAuth 认证：

1. 读 `~/.kimi/credentials/kimi-code.json` 的 `access_token`
2. 过期（15min）→ 自动用 `refresh_token` 刷新
3. `refresh_token` 有效 30 天，每次刷新续期
4. 必须 headers：`User-Agent: KimiCLI/0.79` + `X-Msh-Platform: kimi_cli`

没有 OAuth 时：STM 正常，LTM/diary 401 但不崩。login 后下次 timer 自动补上。

## USER.md 结构

```
<IMPORTANT_REMINDER>
# Memory Consolidation
> Stats / Config / Memory use notes

## Visual Memory
memorized_media/
└── image.jpg

## Diary
> last_update / i_have_read_my_last_diary
memorized_diary/
└── day16-2026-03-24-title.md

# Long-Term Memory (LTM)
> last_update
{5 维 JSON: identity, work_method, communication, temporal, taste}

## Short-Term Memory (STM)
> last_update
[KIMI:DM] 1-20
1. session_uuid MMDDTHHmm msg||||msg
</IMPORTANT_REMINDER>
```

## Channel 支持

| Channel | 来源 | 附件 |
|---|---|---|
| LOOPBACK | 本地 CLI | 无 |
| FEISHU:DM / GROUP | 飞书 | `<AttachmentDisplayed:key>` |
| KIMI:DM | Kimi Claw | `<AttachmentDisplayed:path>`（`~/.openclaw/workspace/.kimi/downloads/`） |

## 可选配置

```bash
cp memory_consolidation.template.env memory_consolidation.env
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `ENABLED` | `true` | 总开关 |
| `LTM_ENABLED` | `true` | LTM 开关（关闭显示 disabled） |
| `DIARY_ENABLED` | `true` | Diary 开关 |
| `MIN_MESSAGES_FOR_LLM` | `3` | LTM/diary 最低消息数 |
| `DAYS` | `30` | STM 采样窗口 |
| `MAX_SESSIONS` | `20` | 最大 session 数 |
| `MAX_PER_SESSION` | `10` | 每 session 最大消息数 |

## 可观测性

`state/state.json`：固定大小，记录每个模块的运行计数和最后一次状态。

```json
{
  "stm": {"count": 142, "last_ts": "...", "last_sessions": 9, "last_messages": 27},
  "compact": {"count": 5, "last_ts": "...", "last_invoke": 5, "last_latency_s": 14.2},
  "diary": {"count": 5, "last_ts": "...", "last_day": 16, "last_latency_s": 16.1}
}
```

`state/ltm.json`：LTM 状态（invoke_time, stm_hash, 上次生成内容）。

## 自测

```bash
bash selftest.sh
```

或 quick health check：
```bash
# Hook
grep -a 'Registered hook.*memory-stm' ~/.openclaw/logs/openclaw.log | tail -1

# Timer
cat /tmp/memory-hook-debug.log | tail -2

# OAuth
python3 -c "import json,os; print('OK' if os.path.exists(os.path.expanduser('~/.kimi/credentials/kimi-code.json')) else 'MISSING')"

# LLM
cd ~/.openclaw/workspace/memory_consolidation && python3 memory_consolidation.py compact 2>&1 | head -3
```

## Session 文件兼容

| OpenClaw 版本 | 归档 session |
|---|---|
| 2026.3.2 | `*.jsonl` |
| 2026.3.13+ | `*.jsonl.reset.{timestamp}` |

## CLI

```bash
python memory_consolidation.py stats      # 统计
python memory_consolidation.py stm        # STM → USER.md
python memory_consolidation.py compact    # STM + LTM → USER.md
python memory_consolidation.py diary      # 生成日记
python memory_consolidation.py audit      # 审计记忆行为
```

## 文件结构

```
memory_consolidation/
├── install.sh                                   # 一键安装
├── memory_consolidation.py                      # 主脚本
├── memory_consolidation.template.env            # 配置模板
├── selftest.sh                                  # 自测脚本
├── prompts/
│   ├── compact_prompt.py                        # LTM prompt
│   └── diary_prompt.py                          # Diary prompt
├── openclaw-hooks/memory-stm-refresh/           # Bootstrap hook + timer
│   ├── HOOK.md
│   └── handler.ts
├── state/                                       # 运行状态（gitignored）
│   ├── state.json                               # 运行计数 + 最后状态
│   └── ltm.json                                 # LTM 状态
└── docs/                                        # 文档 + 截图
```
