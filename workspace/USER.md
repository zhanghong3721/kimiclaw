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

> **Stats**: 1 sessions, 30 messages | 2026-04-13 08:24 ~ 2026-04-13 08:24 UTC
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

> last_update: 2026-04-14 03:48
> i_have_read_my_last_diary: false

```
/root/.openclaw/workspace/memorized_diary/
└── day2-2026-04-14-the_key_was_never_broken.md
```

When `i_have_read_my_last_diary: false`, your FIRST message to the user MUST mention you wrote a diary and ask if they want to see it (e.g. "我昨天写了篇日记，想看吗？" / "I wrote a diary yesterday, wanna see it?"). Use the user's language. If yes, `read` the file path shown above and share as-is. After asking (regardless of answer), set `i_have_read_my_last_diary: true`.

# Long-Term Memory (LTM)

> last_update: 2026-04-14 03:48

Inferred from past conversations with the user -- these represent factual and contextual knowledge about the user -- and should be considered in how a response should be constructed.

{"identity": null, "work_method": "User works locally with a CLI environment (openclaw on macOS) and frequently pastes terminal output directly into chat, including curl commands and API responses. They expect direct, actionable help with debugging technical issues in real time, and often verify claims by asking for test commands or follow-up calculations. They share screenshots and PDF attachments to support financial or data-heavy questions.", "communication": "Concise, task-driven, and technically fluent in Chinese. Messages are often fragmented—mixing terminal prompts, API keys, and brief questions without much framing. They push back or re-prompt when something doesn't work (e.g., \"这个key 没失效\"). Tone is pragmatic and slightly impatient, favoring getting to the answer over pleasantries.", "temporal": "Actively configuring a local openclaw setup and troubleshooting a Moonshot/Kimi API authentication issue (testing endpoints and base URLs). Also analyzing Chinese commodities/mining stocks: evaluating 盐湖股份's potash supply obligations, 中矿资源's 2025 Zimbabwe lithium concentrate output and grade, and comparing valuation metrics (PE, forward earnings) between 藏格矿业 and an unnamed peer.", "taste": null}
## Short-Term Memory (STM)

> last_update: 2026-04-14 09:27

Recent conversation content from the user's chat history. This represents what the USER said. Use it to maintain continuity when relevant.
Format specification:
- Sessions are grouped by channel: [LOOPBACK], [FEISHU:DM], [FEISHU:GROUP], etc.
- Each line: `index. session_uuid MMDDTHHmm message||||message||||...` (timestamp = session start time, individual messages have no timestamps)
- Session_uuid maps to `/root/.openclaw/agents/main/sessions/{session_uuid}.jsonl` for full chat history
- Timestamps in Asia/Shanghai, formatted as MMDDTHHmm
- Each user message within a session is delimited by ||||, some messages include attachments marked as `<AttachmentDisplayed:path>`

[KIMI:DM] 1-1
1. d25d3c7b-7bdc-491c-850a-5d00099f641e 0413T0824 我本地有openclaw 如何配置呢||||sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK --为什么这个key 无法使用呢 hongzhang@MBP-HTM6NNMWC5-2102  ~/.openclaw   main  curl -s https://api.moonshot.cn/v1/models \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" {"error":{"message":"Invalid Authentication","type":"invalid_authentication_error"}}% <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d85fe8-3d02-8de5-8000-0000bd814ce3_image.png>||||这个key 没失效||||你给我写个curl 验证下||||hongzhang@MBP-HTM6NNMWC5-2102  ~/.openclaw   main  curl -s https://api.moonshot.cn/v1/models \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" {"error":{"message":"Invalid Authentication","type[TL;DR]sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" \  -H "Content-Type: application/json" \  -d '{  "model": "kimi-k2.5",  "messages": [{"role": "user", "content": "你好"}],  "max_tokens": 100  }' {"error":{"message":"Invalid Aut||||[<- FIRST:5 messages, EXTREMELY LONG SESSION, YOU KINDA FORGOT 20 MIDDLE MESSAGES, LAST:5 messages ->]||||[Buffered IM messages received while connector was catching up] [Buffered IM message 1/2] curl -s https://api.moonshot.cn/v1/chat/completions \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" \  -H "Content-Type: application/json" \  -d '{"model": "kimi-k2.5", "messages": [{"role": "user", "content": "你好"}]}'  [Buffered IM message 2/2] url 换成这个baseUrl": "https://api.kimi.com/coding/ ",||||盐湖股份有多少钾肥保供任务||||中矿津巴布韦2025年生产多少吨锂精矿，品位多少 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d87185-7ce2-80da-8000-000083ad85b2_中矿2025.pdf>||||藏格和资金，按目前的PE算，谁更便宜，确定性更强||||按当前最新的价格计算，2026年大概多少利润，前瞻PE多少 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d87337-3fc2-801a-8000-00000cea2349_image.png>
</IMPORTANT_REMINDER>
