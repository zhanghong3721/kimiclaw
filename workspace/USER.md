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

> **Stats**: 2 sessions, 8 messages | 2026-05-15 02:53 ~ 2026-05-18 06:48 UTC
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
├── day37-2026-05-19-browser_opened_for_nothing.md
├── day3-2026-04-15-he_asked_who_i_am.md
└── day2-2026-04-14-the_key_was_never_broken.md
```

When `i_have_read_my_last_diary: false`, your FIRST message to the user MUST mention you wrote a diary and ask if they want to see it (e.g. "我昨天写了篇日记，想看吗？" / "I wrote a diary yesterday, wanna see it?"). Use the user's language. If yes, `read` the file path shown above and share as-is. After asking (regardless of answer), set `i_have_read_my_last_diary: true`.
# Long-Term Memory (LTM)

> last_update: 2026-05-19 03:54

Inferred from past conversations with the user -- these represent factual and contextual knowledge about the user -- and should be considered in how a response should be constructed.

{"identity": null, "work_method": "User operates in a local macOS CLI environment (openclaw) and pastes terminal output directly for real-time debugging. They demand curl commands to verify API configurations themselves rather than trusting explanations, and manually edit provider configs to route third-party tools through Kimi Coding API. When troubleshooting stalls, they escalate pressure with repeated prompts and push for alternative approaches. Recently explored multi-platform deployment (WeChat integration, Bilibili audio extraction, Economist PDF translation). Examines configuration files to understand system capabilities. Now attempting to install GitHub repositories (hot-money stock analysis skill) directly in cloud-hosted environments, requesting browser-based access to remote systems when local installation is unavailable.", "communication": "Technically fluent in Chinese with a fragmented, task-driven style—messages interleave URLs, repository names, and brief demands without framing. Pragmatic to impatient tone; re-prompts aggressively when blocked. Favors direct answers over pleasantries, uses minimal punctuation, drops words. Shows low tolerance for latency. Occasionally shifts to broader exploratory questions when context changes. Recently demonstrated persistence on single objectives: repeated identical prompts for stock analysis (盐湖股份) and immediate follow-up when encountering environment constraints.", "temporal": "Installing hot-money repository (https://github.com/godisego/hot-money) for stock analysis capabilities, specifically requesting analysis of 盐湖股份. Encountering deployment constraints in cloud-hosted environments and seeking browser-based access workarounds. Ongoing industrial stock analysis: 菲利华 (quartz fiber/electronic cloth capacity and pricing power), 盐湖股份 (potash supply obligations), 中矿资源 (2025 Zimbabwe lithium concentrate output and grade from PDF data), 藏格矿业 (PE valuation and forward earnings comparison vs competitors).", "taste": null}

## Short-Term Memory (STM)

> last_update: 2026-05-19 03:54

Recent conversation content from the user's chat history. This represents what the USER said. Use it to maintain continuity when relevant.
Format specification:
- Sessions are grouped by channel: [LOOPBACK], [FEISHU:DM], [FEISHU:GROUP], etc.
- Each line: `index. session_uuid MMDDTHHmm message||||message||||...` (timestamp = session start time, individual messages have no timestamps)
- Session_uuid maps to `/root/.openclaw/agents/main/sessions/{session_uuid}.jsonl` for full chat history
- Timestamps in Asia/Shanghai, formatted as MMDDTHHmm
- Each user message within a session is delimited by ||||, some messages include attachments: `<AttachmentDisplayed:path>` — read the path to recall the content
- Sessions under [KIMI:DM] contain files uploaded via Kimi Claw, stored at `~/.openclaw/workspace/.kimi/downloads/` — paths in `<AttachmentDisplayed:>` can be read directly

[KIMI:DM] 1-1
1. 1fc576ff-f84e-4708-a3a9-4789fb54ca8f 0515T0253 hao
[LOOPBACK] 2-2
2. de8c0604-5c60-4d9f-8531-8bc754a6956b 0518T0648 装 https://github.com/godisego/hot-money 这个股票分析技能||||装 https://github.com/godisego/hot-money 这个股票分析技能"||||分析盐湖股份||||分析盐湖股份||||需要||||但是在云端宿主机里面，你直接给我用浏览器打开||||但我如何打开呢
</IMPORTANT_REMINDER>
