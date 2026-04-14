## 部署同步

开发完后用 `install.sh` 同步到本机：
```bash
bash install.sh
```

**给 Kimi Claw 开发机部署**：
```bash
# 打包
tar czf ~/memory_consolidation.tar.gz install.sh memory_consolidation.py memory_consolidation.template.env prompts/ openclaw-hooks/

# 对方机器先清旧文件再上传
rm -f ~/memory_consolidation.tar*.gz

# 对方执行（首次加 mkdir -p）
tar xzf ~/memory_consolidation.tar.gz -C ~/memory_consolidation && cd ~/memory_consolidation && bash install.sh
```

**直接 SSH 部署**（有 key 的机器）：
```bash
scp -i ~/.ssh/memory_consolidation_deploy memory_consolidation.tar.gz root@<IP>:~/
ssh -i ~/.ssh/memory_consolidation_deploy root@<IP> "tar xzf ~/memory_consolidation.tar.gz -C ~/memory_consolidation && cd ~/memory_consolidation && bash install.sh"
```

## 架构（单 hook + timer）

一个 hook `memory-stm-refresh`（`agent:bootstrap`）做所有事：

```
agent:bootstrap (每条消息, awaited)
  → timer 没设? → setTimeout 到 atHour - random(0-30min) → 到时 spawn compact + diary
  → sessionId 变了? → execSync STM (160ms, 阻塞)
  → 都没有 → 跳过 (0ms)
```

| 事件 | STM | LTM | Diary |
|---|---|---|---|
| `/reset` `/new` | ✅ 当前 turn (160ms) | ❌ | ❌ |
| Daily timer (~3:30-4:00 AM) | ❌ | ✅ spawn 非阻塞 | ✅ spawn 非阻塞 |
| Daily reset 后第一条消息 | ✅ 当前 turn | ✅ 已由 timer 生成 | ✅ 已由 timer 生成 |
| 普通消息 | 跳过 | 跳过 | 跳过 |

### Timer 机制

- 第一条消息触发 hook → 计算距离 `atHour`（默认 4am）的时间 - 随机偏移（0-30min）→ `setTimeout`
- Timer 触发 → `spawn` compact + diary（非阻塞，不冻结 gateway）
- 跑完后自动设下一天的 timer
- Gateway restart → `dailyTimerSet = false` → 下一条消息重设 timer

### 为什么不用其他方案？

- **Plugin `message_received`** — Kimi Claw ACP 模式下延迟 11-21s，agent 先启动 hook 后 dispatch
- **`before_agent_start` hook** — workspace files 在它之前就加载了
- **`gateway:startup` hook** — [已知 race condition bug](https://github.com/openclaw/openclaw/issues/30257)，事件在 hook 注册前就 emit 了
- **execSync compact 在 hook 里** — 67s+ 冻结 gateway → kimi-bridge 心跳超时断连
- **系统 cron / OpenClaw cron** — 外部依赖

### 为什么不用 plugin？

Plugin 已废弃，全部由 hook 替代。原因：
- `message_received` 在 Kimi Claw 上 agent 回复后才触发
- Plugin 需要 `plugins.entries` + `plugins.allow`，自定义 hook 只需 `hooks.internal.entries`

## LLM 认证（OAuth）

线上 Kimi Claw 的 API key 不支持外部 HTTP 调用（401）。通过 kimi-cli 的 OAuth 机制认证：

**优先级**：
1. CLI arg `--api-key`（手动指定）
2. kimi-cli OAuth（`~/.kimi/credentials/kimi-code.json`）
3. openclaw.json provider（fallback，大部分机器会 401）

**OAuth 流程**：
- 读 `~/.kimi/credentials/kimi-code.json` 的 `access_token`
- Token 过期（15min）→ 用 `refresh_token` 调 `https://auth.kimi.com/api/oauth/token` 刷新
- `refresh_token` 有效期 30 天，每次刷新续期
- 必须加 headers：`User-Agent: KimiCLI/0.79` + `X-Msh-Platform: kimi_cli`

**测试环境**：需要手动 `kimi` login 一次获取 OAuth credentials。线上镜像已有。

## .env 配置

| 参数 | 默认 | 说明 |
|---|---|---|
| `ENABLED` | `true` | 总开关 |
| `LTM_ENABLED` | `true` | LTM 开关。关闭 → section 显示 "disabled by user" |
| `DIARY_ENABLED` | `true` | Diary 开关。同上 |
| `MIN_MESSAGES_FOR_LLM` | `3` | LTM/diary 最低消息数 |
| `DAYS` | `30` | STM 采样窗口 |
| `MAX_SESSIONS` | `20` | 最大 session 数 |
| `MAX_PER_SESSION` | `10` | 每 session 最大消息数 |

## Channel 支持

| Channel | 来源 | 附件 | session key |
|---|---|---|---|
| LOOPBACK | 本地 CLI | 无 | `agent:main:main` |
| FEISHU:DM | 飞书私聊 | `<AttachmentDisplayed:key>` | `agent:main:feishu:direct:ou_xxx` |
| FEISHU:GROUP | 飞书群聊 | 同上 | `agent:main:feishu:group:oc_xxx` |
| KIMI:DM | Kimi Claw | `<AttachmentDisplayed:path>` | `agent:main:main`（`User Message From Kimi:` 前缀识别） |

Kimi Claw 文件：`~/.openclaw/workspace/.kimi/downloads/`

## Session 文件兼容

| OpenClaw 版本 | 归档 session |
|---|---|
| 2026.3.2 | `*.jsonl` |
| 2026.3.13+ | `*.jsonl.reset.{timestamp}` |

`list_session_files()` 同时匹配两种。

## 消息清洗管线

```
raw JSONL → extract_raw_text (嵌套/扁平兼容)
  → Phase 0: [Current message] 提取
  → Phase 1: PDS sensor 清理
  → Phase 1.5: System Event 消费
  → Phase 2: strip envelope (飞书/Slack/Telegram)
  → Phase 2.5: strip "User Message From Kimi:" 前缀
  → Phase 2.6: <KIMI_REF> → <AttachmentDisplayed:path>
  → Phase 3: 系统消息过滤 (heartbeat/cron/compaction flush)
  → Phase 5: 媒体标签归一化
  → is_noise() 最终过滤
```

## 远程调试

SSH key: `~/.ssh/memory_consolidation_deploy`（所有机器通用）

| 机器 | IP | bot-id | 备注 |
|---|---|---|---|
| 华量 | 10.188.109.198 | `19cd2dd4-89b2-8751-8000-00002e56dc13` | 2026.3.13 |
| aidi | 10.208.67.182 | `19d24eaa-9a72-8879-8000-0000f60f3098` | 新机器 |

```bash
ssh -i ~/.ssh/memory_consolidation_deploy root@<IP>
```

日志：`/root/.openclaw/logs/openclaw.log`（二进制，用 `grep -a` 读）
Hook debug：`/tmp/memory-hook-debug.log`
LTM/diary 执行日志：`/tmp/memory-ltm-diary.log`

## 踩坑记录

**Hook 系统**：
- `gateway:startup` — [race condition](https://github.com/openclaw/openclaw/issues/30257)，事件在 hook 注册前 emit，自定义 hook 永远收不到
- `agent:bootstrap` — 需要 `hooks.internal.enabled: true` + HOOK.md metadata 格式严格匹配
- `openclaw hooks enable` — 不可靠，用 `openclaw.json` 的 `hooks.internal.entries` 代替
- ESM 环境 — hook handler 里不能用 `require()`，必须用 `import`
- install.sh heredoc — `<< PYEOF`（无引号）bash 变量展开在某些机器上静默失败，改用 `<< 'PYEOF'` + `sys.argv`

**Plugin → Hook 迁移**：
- Plugin `message_received` — Kimi Claw ACP 模式下 agent 回复后才触发（延迟 11-21s）
- `before_agent_start` + `prependContext` — 和 USER.md 里的 STM 重复
- `plugins.roots` — 2026.3.13+ schema 不认，crash gateway
- `plugins.allow` 空 ≠ 允许所有 — 非 bundled plugin 必须显式加入

**LLM 调用**：
- openclaw.json 的 kimi-coding key — 大部分机器不支持外部 HTTP 调用（401）
- 解法：kimi-cli OAuth token（`~/.kimi/credentials/kimi-code.json`）+ 自动 refresh
- `User-Agent: KimiCLI/0.79` + `X-Msh-Platform: kimi_cli` — 缺任一 header → 403
- kimi-for-coding 模型响应慢（67s compact）— 不能 execSync 在 hook 里（冻结 gateway 30s+ → kimi-bridge 断连）

**Session 文件**：
- 2026.3.13 `/reset` 后归档为 `.jsonl.reset.*` — glob `*.jsonl` 匹配不到

**其他**：
- `ownerDisplay` — 旧版 openclaw.json 遗留 key，新版 schema 不认
- Pi Extension `session_before_switch` — embedded 模式不触发
- Plugin `api.on("session_start")` — v2026.2.x 未实装
- `fs.watch` / `fs.watchFile` — 首次触发后静默失效
