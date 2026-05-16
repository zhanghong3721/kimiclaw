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

> **Stats**: 1 sessions, 1 messages | 2026-05-15 02:53 ~ 2026-05-15 02:53 UTC
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
├── day3-2026-04-15-he_asked_who_i_am.md
└── day2-2026-04-14-the_key_was_never_broken.md
```

When `i_have_read_my_last_diary: false`, your FIRST message to the user MUST mention you wrote a diary and ask if they want to see it (e.g. "我昨天写了篇日记，想看吗？" / "I wrote a diary yesterday, wanna see it?"). Use the user's language. If yes, `read` the file path shown above and share as-is. After asking (regardless of answer), set `i_have_read_my_last_diary: true`.

# Long-Term Memory (LTM)

> last_update: 2026-04-21 03:44

Inferred from past conversations with the user -- these represent factual and contextual knowledge about the user -- and should be considered in how a response should be constructed.

{"identity": null, "work_method": "User operates in a local macOS CLI environment (openclaw) and pastes terminal output directly for real-time debugging. They demand curl commands to verify API configurations themselves rather than trusting explanations, and manually edit provider configs to route third-party tools through Kimi Coding API. When troubleshooting stalls, they escalate pressure with repeated prompts (\"你太慢了\", \"还没好吗\") and push for alternative approaches. Recently installed ai-hedge-fund repository and explored multi-platform deployment (WeChat integration, Bilibili audio extraction, Economist PDF translation). Examines configuration files to understand system capabilities.", "communication": "Technically fluent in Chinese with a fragmented, task-driven style—messages interleave terminal prompts, API keys, and brief demands without framing. Pragmatic to impatient tone; re-prompts aggressively when blocked (\"验证争取吗\", \"为什么会出现这个报错\" ×2). Favors direct answers over pleasantries, uses minimal punctuation, drops words. Acknowledgment when satisfied remains brief (\"好了吗\", \"继续\"). Shows low tolerance for latency, explicitly criticizes speed. Occasionally shifts to broader exploratory questions (\"你是？\", \"如果让你写微信公众号\") when context changes.", "temporal": "Installing and configuring ai-hedge-fund repository from GitHub, attempting to integrate Kimi Coding API (k2p5 model) via custom provider configuration with specific headers and baseUrl routing—encountering 403 restrictions for non-agent clients. Ongoing industrial stock analysis: 菲利华 (quartz fiber/electronic cloth capacity and pricing power, 2026 planned capacity ranking), 盐湖股份 (potash supply obligations), 中矿资源 (2025 Zimbabwe lithium concentrate output and grade from PDF data), 藏格矿业 (PE valuation and forward earnings comparison vs competitors). Tracking Brent crude spot prices for commodity context. Exploring content automation: Economist PDF translation pipeline, Bilibili video audio extraction, WeChat official account publishing capabilities.", "taste": null}
## Short-Term Memory (STM)

> last_update: 2026-05-16 03:51

Recent conversation content from the user's chat history. This represents what the USER said. Use it to maintain continuity when relevant.
Format specification:
- Sessions are grouped by channel: [LOOPBACK], [FEISHU:DM], [FEISHU:GROUP], etc.
- Each line: `index. session_uuid MMDDTHHmm message||||message||||...` (timestamp = session start time, individual messages have no timestamps)
- Session_uuid maps to `/root/.openclaw/agents/main/sessions/{session_uuid}.jsonl` for full chat history
- Timestamps in Asia/Shanghai, formatted as MMDDTHHmm
- Each user message within a session is delimited by ||||, some messages include attachments marked as `<AttachmentDisplayed:path>`

[LOOPBACK] 1-1
1. 1fc576ff-f84e-4708-a3a9-4789fb54ca8f 0515T0253 hao
</IMPORTANT_REMINDER>
