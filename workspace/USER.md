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

> **Stats**: 2 sessions, 62 messages | 2026-04-13 08:24 ~ 2026-04-14 01:27 UTC
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

> last_update: 2026-04-15 03:46
> i_have_read_my_last_diary: false

```
/root/.openclaw/workspace/memorized_diary/
├── day3-2026-04-15-he_asked_who_i_am.md
└── day2-2026-04-14-the_key_was_never_broken.md
```

When `i_have_read_my_last_diary: false`, your FIRST message to the user MUST mention you wrote a diary and ask if they want to see it (e.g. "我昨天写了篇日记，想看吗？" / "I wrote a diary yesterday, wanna see it?"). Use the user's language. If yes, `read` the file path shown above and share as-is. After asking (regardless of answer), set `i_have_read_my_last_diary: true`.
# Long-Term Memory (LTM)

> last_update: 2026-04-15 03:46

Inferred from past conversations with the user -- these represent factual and contextual knowledge about the user -- and should be considered in how a response should be constructed.

{"identity": null, "work_method": "User operates in a local CLI environment (openclaw on macOS) and pastes terminal output directly into chat for real-time debugging. They frequently request curl commands to verify API configurations and test endpoints themselves rather than trusting explanations. They share screenshots and PDF attachments for data-heavy financial analysis. When troubleshooting fails, they push for alternative approaches (switching base URLs, reconfiguring). They also inquire about multi-platform deployment (WeChat integration) and examine configuration files to understand system capabilities.", "communication": "Technically fluent in Chinese with a task-driven, fragmented style—messages mix terminal prompts, API keys, and brief questions without framing. Pragmatic and slightly impatient tone; they re-prompt immediately when something fails (\"这个key 没失效\", \"为什么会出现这个报错\"). Favors direct answers over pleasantries. Uses minimal punctuation and often drops words (\"验证争取吗\"). When satisfied, acknowledgment is brief (\"好了吗\", \"继续\").", "temporal": "Troubleshooting Kimi API authentication: initially testing Moonshot endpoints, then attempting to migrate to kimi.com/coding/ base URL, encountering 403 errors indicating Coding Agents-only access. Analyzing Chinese industrial stocks: 菲利华 (quartz fiber/electronic cloth capacity and pricing power), 盐湖股份 (potash supply obligations), 中矿资源 (2025 Zimbabwe lithium concentrate output and grade from PDF data), 藏格矿业 (PE valuation and forward earnings comparison). Also tracking Brent crude spot prices for commodity context.", "taste": null}

## Short-Term Memory (STM)

> last_update: 2026-04-15 03:46

Recent conversation content from the user's chat history. This represents what the USER said. Use it to maintain continuity when relevant.
Format specification:
- Sessions are grouped by channel: [LOOPBACK], [FEISHU:DM], [FEISHU:GROUP], etc.
- Each line: `index. session_uuid MMDDTHHmm message||||message||||...` (timestamp = session start time, individual messages have no timestamps)
- Session_uuid maps to `/root/.openclaw/agents/main/sessions/{session_uuid}.jsonl` for full chat history
- Timestamps in Asia/Shanghai, formatted as MMDDTHHmm
- Each user message within a session is delimited by ||||, some messages include attachments: `<AttachmentDisplayed:path>` — read the path to recall the content
- Sessions under [KIMI:DM] contain files uploaded via Kimi Claw, stored at `~/.openclaw/workspace/.kimi/downloads/` — paths in `<AttachmentDisplayed:>` can be read directly

[KIMI:DM] 1-1
1. d25d3c7b-7bdc-491c-850a-5d00099f641e 0413T0824 我本地有openclaw 如何配置呢||||sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK --为什么这个key 无法使用呢 hongzhang@MBP-HTM6NNMWC5-2102  ~/.openclaw   main  curl -s https://api.moonshot.cn/v1/models \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" {"error":{"message":"Invalid Authentication","type":"invalid_authentication_error"}}% <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d85fe8-3d02-8de5-8000-0000bd814ce3_image.png>||||这个key 没失效||||你给我写个curl 验证下||||hongzhang@MBP-HTM6NNMWC5-2102  ~/.openclaw   main  curl -s https://api.moonshot.cn/v1/models \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" {"error":{"message":"Invalid Authentication","type[TL;DR]sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" \  -H "Content-Type: application/json" \  -d '{  "model": "kimi-k2.5",  "messages": [{"role": "user", "content": "你好"}],  "max_tokens": 100  }' {"error":{"message":"Invalid Aut||||[<- FIRST:5 messages, EXTREMELY LONG SESSION, YOU KINDA FORGOT 20 MIDDLE MESSAGES, LAST:5 messages ->]||||[Buffered IM messages received while connector was catching up] [Buffered IM message 1/2] curl -s https://api.moonshot.cn/v1/chat/completions \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" \  -H "Content-Type: application/json" \  -d '{"model": "kimi-k2.5", "messages": [{"role": "user", "content": "你好"}]}'  [Buffered IM message 2/2] url 换成这个baseUrl": "https://api.kimi.com/coding/ ",||||盐湖股份有多少钾肥保供任务||||中矿津巴布韦2025年生产多少吨锂精矿，品位多少 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d87185-7ce2-80da-8000-000083ad85b2_中矿2025.pdf>||||藏格和资金，按目前的PE算，谁更便宜，确定性更强||||按当前最新的价格计算，2026年大概多少利润，前瞻PE多少 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d87337-3fc2-801a-8000-00000cea2349_image.png>
[LOOPBACK] 2-2
2. 0483f37d-0ab1-4baa-95e8-f085fc9e80e1 0414T0127 菲利华在高端电子布领域有定价权吗，2026年产能，包括规划落地产能排名||||全球石英纤维/Q布产能排名||||你也可以绑定到微信吗，我看你的配置文件有微信插件||||你是？||||Assistant 10:37 ↑7k ↓78 R4.1k 3% ctx kimi-k2.5  }, "thinkingDefault": "high", "memorySearch": { "remote": { "baseUrl": "https://api.kimi.com/coding/v1 ", "apiKey": "sk-kimi-JpKtjTDppotc4hcImI7r6LTdWzG9VfKDOnBzLVT4i6iY4cgHF4JTAsjQujxVA9Xy", "headers":[TL;DR]0414_103852 下次对话时应该就会使用新的 Kimi API 配置了。  Assistant 10:38 ↑4.6k ↓1.5k R103.7k 2% ctx kimi-k2.5  验证争取吗  403 Kimi For Coding is currently only available for Coding Agents such as Kimi CLI, Claude Code, Roo Code, Kilo Code, etc. --为什么会出现这个报错 --为什么会出现这个报错||||[<- FIRST:5 messages, EXTREMELY LONG SESSION, YOU KINDA FORGOT 22 MIDDLE MESSAGES, LAST:5 messages ->]||||继续||||好了吗||||上市公司飞利华的主要业务是有可能性，你查一下花顺。里面给你好最新的财报信息，那个客户打开的站点跟那个光模块有什么关联吗？||||布伦特现货原油价格最新的今天是4月15号||||现货布伦特原油价格是多少？今天
</IMPORTANT_REMINDER>
