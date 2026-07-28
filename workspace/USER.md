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

> **Stats**: 0 sessions, 0 messages | 2026-07-27 15:22 ~ 2026-07-27 15:22 UTC
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

> No conversations yet.
</IMPORTANT_REMINDER>
