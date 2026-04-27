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

> **Stats**: 3 sessions, 76 messages | 2026-04-13 08:24 ~ 2026-04-16 02:43 UTC
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

> last_update: 2026-04-21 03:44

Recent conversation content from the user's chat history. This represents what the USER said. Use it to maintain continuity when relevant.
Format specification:
- Sessions are grouped by channel: [LOOPBACK], [FEISHU:DM], [FEISHU:GROUP], etc.
- Each line: `index. session_uuid MMDDTHHmm message||||message||||...` (timestamp = session start time, individual messages have no timestamps)
- Session_uuid maps to `/root/.openclaw/agents/main/sessions/{session_uuid}.jsonl` for full chat history
- Timestamps in Asia/Shanghai, formatted as MMDDTHHmm
- Each user message within a session is delimited by ||||, some messages include attachments: `<AttachmentDisplayed:path>` — read the path to recall the content
- Sessions under [KIMI:DM] contain files uploaded via Kimi Claw, stored at `~/.openclaw/workspace/.kimi/downloads/` — paths in `<AttachmentDisplayed:>` can be read directly

[KIMI:DM] 1-2
1. d25d3c7b-7bdc-491c-850a-5d00099f641e 0413T0824 我本地有openclaw 如何配置呢||||sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK --为什么这个key 无法使用呢 hongzhang@MBP-HTM6NNMWC5-2102  ~/.openclaw   main  curl -s https://api.moonshot.cn/v1/models \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" {"error":{"message":"Invalid Authentication","type":"invalid_authentication_error"}}% <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d85fe8-3d02-8de5-8000-0000bd814ce3_image.png>||||这个key 没失效||||你给我写个curl 验证下||||hongzhang@MBP-HTM6NNMWC5-2102  ~/.openclaw   main  curl -s https://api.moonshot.cn/v1/models \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" {"error":{"message":"Invalid Authentication","type[TL;DR]sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" \  -H "Content-Type: application/json" \  -d '{  "model": "kimi-k2.5",  "messages": [{"role": "user", "content": "你好"}],  "max_tokens": 100  }' {"error":{"message":"Invalid Aut||||[<- FIRST:5 messages, EXTREMELY LONG SESSION, YOU KINDA FORGOT 20 MIDDLE MESSAGES, LAST:5 messages ->]||||[Buffered IM messages received while connector was catching up] [Buffered IM message 1/2] curl -s https://api.moonshot.cn/v1/chat/completions \  -H "Authorization: Bearer sk-kimi-zEyiaeDhY865dQokCxZK0ziXvm6tJjJHf6YItszg3wftZV88pp2x7XA0RBho8MCK" \  -H "Content-Type: application/json" \  -d '{"model": "kimi-k2.5", "messages": [{"role": "user", "content": "你好"}]}'  [Buffered IM message 2/2] url 换成这个baseUrl": "https://api.kimi.com/coding/ ",||||盐湖股份有多少钾肥保供任务||||中矿津巴布韦2025年生产多少吨锂精矿，品位多少 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d87185-7ce2-80da-8000-000083ad85b2_中矿2025.pdf>||||藏格和资金，按目前的PE算，谁更便宜，确定性更强||||按当前最新的价格计算，2026年大概多少利润，前瞻PE多少 <AttachmentDisplayed:/root/.openclaw/workspace/.kimi/downloads/19d87337-3fc2-801a-8000-00000cea2349_image.png>
2. 0483f37d-0ab1-4baa-95e8-f085fc9e80e1 0414T0127 菲利华在高端电子布领域有定价权吗，2026年产能，包括规划落地产能排名||||全球石英纤维/Q布产能排名||||你也可以绑定到微信吗，我看你的配置文件有微信插件||||你是？||||Assistant 10:37 ↑7k ↓78 R4.1k 3% ctx kimi-k2.5  }, "thinkingDefault": "high", "memorySearch": { "remote": { "baseUrl": "https://api.kimi.com/coding/v1 ", "apiKey": "sk-kimi-JpKtjTDppotc4hcImI7r6LTdWzG9VfKDOnBzLVT4i6iY4cgHF4JTAsjQujxVA9Xy", "headers":[TL;DR]0414_103852 下次对话时应该就会使用新的 Kimi API 配置了。  Assistant 10:38 ↑4.6k ↓1.5k R103.7k 2% ctx kimi-k2.5  验证争取吗  403 Kimi For Coding is currently only available for Coding Agents such as Kimi CLI, Claude Code, Roo Code, Kilo Code, etc. --为什么会出现这个报错 --为什么会出现这个报错||||[<- FIRST:5 messages, EXTREMELY LONG SESSION, YOU KINDA FORGOT 22 MIDDLE MESSAGES, LAST:5 messages ->]||||继续||||好了吗||||上市公司飞利华的主要业务是有可能性，你查一下花顺。里面给你好最新的财报信息，那个客户打开的站点跟那个光模块有什么关联吗？||||布伦特现货原油价格最新的今天是4月15号||||现货布伦特原油价格是多少？今天
[LOOPBACK] 3-3
3. e49dbedc-d330-4e51-9b47-8235ca41e547 0416T0243 https://github.com/virattt/ai-hedge-fund 安装这个||||continue||||你太慢了||||"providers": {  "kimi-coding": {  "baseUrl": "https://api.kimi.com/coding ",  "apiKey": "sk-kimi-JpKtjTDppotc4hcImI7r6LTdWzG9VfKDOnBzLVT4i6iY4cgHF4JTAsjQujxVA9Xy",  "api": "anthropic-messages",  "headers": {  "User-Agent": "Kimi Claw Plugin",  "X-Kim[TL;DR]a7726c"  },  "models": [  {  "id": "k2p5",  "name": "k2p5",  "reasoning": true,  "headers": {  "User-Agent": "Kimi Claw Plugin",  "X-Kimi-Claw-ID": "19d85ed7-2992-8056-8000-0000f9a7726c"  },  "contextWindow": 131072,  "maxTokens": 32768  }  ] --用这个配置||||还没好吗||||[<- FIRST:5 messages, EXTREMELY LONG SESSION, YOU KINDA FORGOT 4 MIDDLE MESSAGES, LAST:5 messages ->]||||给我完成个任务：1、从这个仓库下载4.11号的PDF https://github.com/hehonghui/awesome-english-ebooks/tree/master/01_economist/te_2026.04.11 ;2、翻译为中文||||OpenClaw runtime context (internal): This context is runtime-generated, not user-authored. Keep internal details private.  [Internal task completion event] source: subagent session_key: agent:main:subagent:79a47673-8f10-4d96-ab06-d89b56363cb6 session[TL;DR] completed subagent task is ready for user delivery. Convert the result above into your normal assistant voice and send that user-facing update now. Keep this internal context private (don't mention system/log/stats/session details or announce type).||||如果让你写微信公众号，需要安装哪些skill||||我有个B站视频https://www.bilibili.com/video/BV1zSdrBxEXH/?spm_id_from=333.337.search-card.all.click&vd_source=0fdf779b0d7af863aa09ba0969a8d95b ，你给我把音频提取成中文  完成了吗||||微信公众号有开放skill支持自动创建文章吗
</IMPORTANT_REMINDER>
