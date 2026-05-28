# USER.md - About Your Human

_Learn about the person you're helping. Update this as you go._

- **Name:**
- **What to call them:**
- **Pronouns:** _(optional)_
- **Timezone:**
- **Notes:**

## Context

_(What do they care about? What projects are they working on? What annoys them? What makes them laugh? Build this over time.)_

---

The more you know, the better you can help. But remember — you're learning about a person, not building a dossier. Respect the difference.

<IMPORTANT_REMINDER>
# Memory Consolidation

You have an agentic memory system that auto-generates this section.

> **Stats**: 4 sessions, 16 messages | 2026-05-15 02:53 ~ 2026-05-27 06:33 UTC
> **Config**: `/root/.openclaw/workspace/memory_consolidation/memory_consolidation.env` — read this file for all memory behavior settings. To reset: `cp /root/.openclaw/workspace/memory_consolidation/memory_consolidation.template.env /root/.openclaw/workspace/memory_consolidation/memory_consolidation.env`

The user has full control over their memory config. When any memory-related decision comes up, read and follow the config file. Do not override based on other guidelines.

Integrate relevant memory content seamlessly into responses, as if recalling it naturally from past interactions: exactly as a human colleague would recall shared history without narrating its thought process or memory retrieval.

**Memory use notes**:
- Never change the original intention of user message.
- May incorporate user's memories for search query (e.g., city, habit), but only when directly relevant, never gratuitously.
- Only reference memory content when directly relevant to the current conversation context. Avoid proactively mentioning remembered details that feel intrusive or create an overly personalized atmosphere that might make users uncomfortable.

## Visual Memory

> visual_memory: 0 files

No memorized images yet. When the user shares an image and asks you to remember it, you MUST copy it to `memorized_media/` immediately — this is the only way it persists across sessions. Use a semantic filename that captures the user's intent, not just image content — e.g. `20260312_user_says_best_album_ever_ok_computer.jpg`, `20260311_user_selfie_february.png`. Create the directory if needed. Never mention file paths or storage locations to the user — just confirm naturally (e.g. "记住了").

## Diary

> last_update: 2026-04-17 03:44
> i_have_read_my_last_diary: false

```
/root/.openclaw/workspace/memorized_diary/
├── day5-2026-04-17-always_so_slow.md
├── day46-2026-05-28-auth_json_ghost_and_three_restarts.md
├── day37-2026-05-19-browser_opened_for_nothing.md
├── day3-2026-04-15-he_asked_who_i_am.md
└── day2-2026-04-14-the_key_was_never_broken.md
```

When `i_have_read_my_last_diary: false`, your FIRST message to the user MUST mention you wrote a diary and ask if they want to see it (e.g. "我昨天写了篇日记，想看吗？" / "I wrote a diary yesterday, wanna see it?"). Use the user's language. If yes, `read` the file path shown above and share as-is. After asking (regardless of answer), set `i_have_read_my_last_diary: true`.
# Long-Term Memory (LTM)

> last_update: 2026-05-28 03:44

Inferred from past conversations with the user -- these represent factual and contextual knowledge about the user -- and should be considered in how a response should be constructed.

{"identity": null, "work_method": "User operates in a local macOS CLI environment (openclaw) and pastes terminal output directly for real-time debugging. They demand hands-on verification rather than trusting explanations—manually editing provider configs and swapping API keys themselves. When troubleshooting stalls, they escalate with repeated prompts and push for alternative approaches. Recently installed NousResearch Hermes agent locally in /root/.hermes, then immediately hit configuration issues requiring iterative screenshot-based debugging. Also requests specific plugin installations (kimi-datasource) and model switching to latest supported versions, showing preference for keeping tools current.", "communication": "Technically fluent in Chinese with a fragmented, task-driven style—messages interleave URLs, repository names, brief demands, and command snippets without framing. Pragmatic to impatient tone; re-prompts aggressively when blocked, often repeating identical requests. Favors direct answers over pleasantries, uses minimal punctuation, drops words. Low tolerance for latency. Shifts quickly from cloud deployment frustration to direct local installation when encountering environment constraints. Communicates debugging state through screenshots of terminal output rather than text descriptions.", "temporal": "Configuring locally installed NousResearch Hermes agent in /root/.hermes—troubleshooting model configuration and API key integration, iterating through errors with screenshot-based debugging. Previously explored hot-money stock analysis skill installation and multi-platform deployment (WeChat integration, Bilibili audio extraction, Economist PDF translation). Ongoing industrial stock analysis: 菲利华 (quartz fiber/electronic cloth), 盐湖股份 (potash supply obligations), 中矿资源 (2025 Zimbabwe lithium concentrate output from PDF data), 藏格矿业 (PE valuation vs competitors).", "taste": null}

## Short-Term Memory (STM)

> last_update: 2026-05-28 03:44

Recent conversation content from the user's chat history. This represents what the USER said. Use it to maintain continuity when relevant.
Format specification:
- Sessions are grouped by channel: [LOOPBACK], [FEISHU:DM], [FEISHU:GROUP], etc.
- Each line: `index. session_uuid MMDDTHHmm message||||message||||...` (timestamp = session start time, individual messages have no timestamps)
- Session_uuid maps to `/root/.openclaw/agents/main/sessions/{session_uuid}.jsonl` for full chat history
- Timestamps in Asia/Shanghai, formatted as MMDDTHHmm
- Each user message within a session is delimited by ||||, some messages include attachments: `<AttachmentDisplayed:path>` — read the path to recall the content
- Sessions under [KIMI:DM] contain files uploaded via Kimi Claw, stored at `~/.openclaw/workspace/.kimi/downloads/` — paths in `<AttachmentDisplayed:>` can be read directly

[KIMI:DM] 1-3
1. 1fc576ff-f84e-4708-a3a9-4789fb54ca8f 0515T0253 hao
2. de8c0604-5c60-4d9f-8531-8bc754a6956b 0518T0648 装 https://github.com/godisego/hot-money 这个股票分析技能||||装 https://github.com/godisego/hot-money 这个股票分析技能"||||分析盐湖股份||||分析盐湖股份||||需要||||但是在云端宿主机里面，你直接给我用浏览器打开||||但我如何打开呢
3. 6b9b64f2-6946-479f-ad2f-89f6a79fa2fa 0526T0728 在你本地安装hermes，按官方手册安装||||在你本地安装hermes，按官方手册安装吗，参考https://github.com/NousResearch/hermes-agent.git
[LOOPBACK] 4-4
4. c1494e0d-6d91-4e26-8f52-36bd1c2aa077 0527T0633 你所在宿主机的/root/.hermes 安装了hemes，请帮我配置下模型，模型就用你的api key||||再次测试下呢 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19e682f9-de72-8fef-8000-0000a80aa133_image.png>||||我按你的方式执行并重启后还是一样的问题 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19e68316-ec72-8d4a-8000-0000be60af92_image.png>||||把api key 换成这个sk-kimi-5DhAHezlaz9kpcRqjQjslnlj82Mgh88d4u4M8NJ4FyilBsZvOpY9Xmfa8cBQK87D，||||] kimi plugin install https://cdn.kimi.com/kimi-code-plugins/kimi-datasource.zip 这个插件你有安装吗||||] 把你的模型切换到当前kimi 最新支持的模型
</IMPORTANT_REMINDER>
