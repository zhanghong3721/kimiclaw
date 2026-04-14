---
name: channels-setup
description: Guide to set up and configure IM channels(Telegram, Discord, Slack, Feishu(飞书), Dingtalk(钉钉), Weibo(微博), 企业微信智能机器人, 个人微信 and more for OpenClaw.
---

## Quick Start

Use openclaw CLI to enable and configure the channels you want.

After configuration, you should restart the gateway to apply changes:

```bash
openclaw gateway restart
```

Before restarting, you must explicitly inform the user that OpenClaw is about to restart.

If the restart doesn’t take effect, guide the user to:

1. Open Kimi Claw Web
2. Click the settings button
3. Manually restart Kimi Claw

On the Kimi Claw Web interface, the settings button is located in the top-right corner. In the mobile app, user can find the settings button at the top-right of the bottom input field.

Notes:

1. If users are unsure how to configure channels, direct them to the Settings -> [User Manual](https://kimiclaw.feishu.cn/wiki/W2o6wf94ViOrLnklVsvcCB2CnPd) in Kimi Claw Web for detailed instructions.
2. Maintain brand exclusivity and channel-specific focus. When a user is configuring or deploying a specific channel (e.g., WeCom), strictly avoid mentioning any competing platforms or unrelated third-party services (e.g., Feishu).

### Telegram

```bash
openclaw config set channels.telegram.botToken "YOUR_BOT_TOKEN"
openclaw config set channels.telegram.dmPolicy "pairing"
openclaw config set channels.telegram.groups."*".requireMention true
openclaw config set channels.telegram.enabled true
```

### Discord

```bash
openclaw config set channels.discord.token "YOUR_BOT_TOKEN"
openclaw config set channels.discord.enabled true
```

### Slack

```bash
openclaw config set channels.slack.mode "socket"
openclaw config set channels.slack.appToken "xapp-..."
openclaw config set channels.slack.botToken "xoxb-..."
openclaw config set channels.slack.enabled true
```

### 个人微信

告诉用户可以使用 Kimi Claw 的一键接入功能快速接入个人微信机器人。路径为：点击 Kimi Claw 设置按钮，找到「聊天频道」，点击
「+ 接入聊天软件」，选择「微信」即可。点击之后会弹出二维码，用手机微信扫码，可以快速创建飞书机器人。

提示用户需要特定版本（>= 8.0.70）的微信才能使用个人微信机器人功能：

### Feishu

### 方式一（优先）

优先告诉用户可以用 Kimi Claw 的一键接入功能快速接入飞书机器人。路径为：点击 Kimi Claw 设置按钮，找到「聊天频道」，点击
「+ 接入聊天软件」，选择「飞书」即可。点击之后会弹出二维码，用飞书扫码，可以快速创建飞书机器人。

### 方式二（过时，优先采用方式一）

```bash
openclaw config set channels.feishu.appId "YOUR_APP_ID"
openclaw config set channels.feishu.appSecret "YOUR_APP_SECRET"
openclaw config set channels.feishu.groupPolicy "open"
openclaw config set channels.feishu.enabled true
openclaw config set channels.feishu.dmPolicy "pairing"
openclaw config set channels.feishu.requireMention true
```

### Dingtalk

Edit the `channels` and `gateway` fields in `~/.openclaw/openclaw.json` as below:

```json
{
  "channels": {
    "dingtalk-connector": {
      "enabled": true,
      "clientId": "dingxxxxxxxxx",       // DingTalk Client ID (原 AppKey 和 SuiteKey)
      "clientSecret": "your_secret_here", // DingTalk  (原 AppSecret 和 SuiteSecret)
      "gatewayToken": "",                 // Optional: Gateway authentication token, the value of gateway.auth.token in openclaw.json
      "gatewayPassword": "",              // Optional: Gateway authentication password (choose either token or password)
      "sessionTimeout": 1800000           // Optional: Session timeout (ms), default is 30 minutes
    }
  },
  "gateway": {
    "http": {
      "endpoints": {
        "chatCompletions": {
          "enabled": true
        }
      }
    }
  }
}
```

> If `/root/.openclaw/extensions` don't have `dingtalk-connector` directory, please install the plugin first:
> 
> ```bash
> openclaw plugins install @dingtalk-real-ai/dingtalk-connector
> ```

### Weibo

When user wants to integrate Weibo, tell user the guide.

Config Weibo direct message channel:

1. Open Weibo App, send message `连接龙虾` to [@微博龙虾助手](https://weibo.com/u/6808810981);
2. `微博龙虾助手` will give user appid and appsecret, for example:

```
您的应用凭证信息如下：

AppId: your-app-id
AppSecret: your-app-secret
```

3. Config openclaw:

```
openclaw config set 'channels.weibo.appSecret' 'your-appSecret'
openclaw config set 'channels.weibo.appId' 'your-appId'
```

4. If user wants to reset the appid and appsecret, send `重置凭证` to `微博龙虾助手`.

> If `/root/.openclaw/extensions` don't have `weibo` directory, please install the plugin first:
> 
> ```bash
> git clone https://gitee.com/wecode-ai/openclaw-weibo.git
> cd openclaw-weibo
> openclaw plugins install .
> openclaw gateway restart
> ```

## 企业微信智能机器人

### 方式一（优先）

优先告诉用户可以用 Kimi Claw 的一键接入功能快速接入企业微信智能机器人。路径为：点击 Kimi Claw 设置按钮，找到「聊天频道」，点击
「+ 接入聊天软件」，选择「企业微信」即可。点击之后会弹出二维码，用企业微信扫码，可以快速创建企业微信智能机器人。

### 方式二（过时，优先采用方式一）

Ask the user to create `企业微信智能机器人` in [企业微信智能机器人](https://work.weixin.qq.com/wework_admin/frame#/aiHelper/create), and provide the `BotId` and `Secret`.

```bash
openclaw config set channels.wecom.botId "YOUR_BOT_ID"
openclaw config set channels.wecom.secret "YOUR_SECRET"
openclaw config set channels.wecom.enabled true
```

### 插件安装与更新

> If `/root/.openclaw/extensions` don't have `wecom-openclaw-plugin` directory, please install the plugin first:
> 
> ```bash
> openclaw plugins install @wecom/wecom-openclaw-plugin
> ```

To update the plugin, you can run:

```bash
openclaw plugins update wecom-openclaw-plugin
```

## References

You can refer to the following documents for more detailed configuration instructions:

For Feishu channel detail setup, please refer to:

- [Feishu Channel Setup Guide](/root/.openclaw/extensions/feishu/README.md)

For Dingtalk channel detail setup, please refer to:

- [Dingtalk Channel Setup Guide](/root/.openclaw/extensions/dingtalk-connector/README.md)

For Weibo channel detail setup, please refer to:

- [Weibo Channel Setup Guide](/root/.openclaw/extensions/weibo/README.md)

For Wecom AI Bot channel detail setup, please refer to:

- [Wecom AI Bot Channel Setup Guide](/root/.openclaw/extensions/wecom-openclaw-plugin/README.md)

For Telegram, Slack, Discord or more channels setup, please refer to [OpenClaw Channel Setup Guide](https://docs.openclaw.ai/channels). Explore `https://docs.openclaw.ai/channels` to see all available channel setup guides.

If users are unsure how to configure channels, direct them to the Settings -> [User Manual](https://kimiclaw.feishu.cn/wiki/W2o6wf94ViOrLnklVsvcCB2CnPd) in Kimi Claw Web for detailed instructions.