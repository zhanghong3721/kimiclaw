"""
推送渠道模块
- kimiclaw → 通过 kimiim-cli notify-owner 推送到 Kimi Claw（默认）
- feishu   → 飞书 API（chat_id 优先，user_id 兜底）
"""

import json
import os
import time
import fcntl
import requests
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ── 数据目录 ──────────────────────────────────────────────────────────────────

_DATA_DIR        = Path(__file__).parent.parent / "data"
_TOKEN_CACHE     = _DATA_DIR / "feishu_token.json"
_FAILED_MSG_FILE = _DATA_DIR / "failed_messages.json"

_DATA_DIR.mkdir(exist_ok=True)


@contextmanager
def _json_file_lock(path: Path, exclusive: bool):
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _read_json_unlocked(path: Path, default):
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(default, dict) and not isinstance(data, dict):
                return default
            if isinstance(default, list) and not isinstance(data, list):
                return default
            return data
        except Exception:
            pass
    return default


def _atomic_write_json(path: Path, data, *, indent=None):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 飞书：失败队列
# ══════════════════════════════════════════════════════════════════════════════

class FailedMessageQueue:
    @staticmethod
    def _key(msg: dict):
        return (
            msg.get("id", ""),
            msg.get("receive_id") or msg.get("user_id", ""),
            msg.get("receive_id_type", "open_id"),
            msg.get("failed_at", ""),
            msg.get("content", ""),
        )

    @classmethod
    def add(cls, receive_id: str, receive_id_type: str,
            content: str, reason: str):
        with _json_file_lock(_FAILED_MSG_FILE, exclusive=True):
            msgs = cls._load_unlocked()
            msgs.append({
                "id":              f"{os.getpid()}-{time.time_ns()}",
                "receive_id":      receive_id,
                "receive_id_type": receive_id_type,
                "user_id":         receive_id if receive_id_type == "open_id" else "",
                "content":         content,
                "reason":          str(reason),
                "failed_at":       datetime.now().isoformat(),
                "retry_count":     0,
            })
            cls._save_unlocked(msgs)
        print(f"  ⚠️  消息入队（原因: {reason}），队列长度: {len(msgs)}")

    @classmethod
    def get_all(cls):
        return cls._load()

    @classmethod
    def remove_indices(cls, indices: list):
        with _json_file_lock(_FAILED_MSG_FILE, exclusive=True):
            msgs = cls._load_unlocked()
            for i in sorted(indices, reverse=True):
                if 0 <= i < len(msgs):
                    msgs.pop(i)
            cls._save_unlocked(msgs)

    @classmethod
    def _load(cls):
        with _json_file_lock(_FAILED_MSG_FILE, exclusive=False):
            return cls._load_unlocked()

    @classmethod
    def _save(cls, msgs: list):
        with _json_file_lock(_FAILED_MSG_FILE, exclusive=True):
            cls._save_unlocked(msgs)

    @classmethod
    def _load_unlocked(cls):
        return _read_json_unlocked(_FAILED_MSG_FILE, [])

    @classmethod
    def _save_unlocked(cls, msgs: list):
        _atomic_write_json(_FAILED_MSG_FILE, msgs, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# 飞书：Token 管理
# ══════════════════════════════════════════════════════════════════════════════

class _TokenManager:

    def __init__(self, app_id: str, app_secret: str):
        self.app_id     = app_id
        self.app_secret = app_secret
        self._token     = None
        self._expire    = 0
        self._load_cache()

    def _load_cache(self):
        with _json_file_lock(_TOKEN_CACHE, exclusive=False):
            cache = _read_json_unlocked(_TOKEN_CACHE, {})
        self._token  = cache.get("token")
        try:
            self._expire = float(cache.get("expire") or 0)
        except (TypeError, ValueError):
            self._expire = 0

    def _save_cache(self):
        with _json_file_lock(_TOKEN_CACHE, exclusive=True):
            _atomic_write_json(
                _TOKEN_CACHE, {"token": self._token, "expire": self._expire}
            )

    def get(self, force_refresh=False, write_cache=True) -> Optional[str]:
        now = time.time()
        if not force_refresh and self._token and self._expire > now + 300:
            return self._token
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            result = resp.json()
            if result.get("code") == 0:
                self._token  = result["tenant_access_token"]
                self._expire = now + result.get("expire", 7200)
                if write_cache:
                    self._save_cache()
                print("  ✅ 飞书 Token 已刷新")
                return self._token
            print(f"  ❌ 获取飞书 Token 失败: {result}")
        except Exception as e:
            print(f"  ❌ 获取飞书 Token 异常: {e}")
        return None


_token_managers: dict = {}

def _get_token_manager(app_id: str, app_secret: str) -> _TokenManager:
    key = f"{app_id}:{app_secret}"
    if key not in _token_managers:
        _token_managers[key] = _TokenManager(app_id, app_secret)
    return _token_managers[key]


def _no_persist_enabled(cfg: dict, feishu_cfg: dict = None) -> bool:
    return bool(cfg.get("_no_persist") or (feishu_cfg or {}).get("_no_persist"))


# ══════════════════════════════════════════════════════════════════════════════
# 飞书：发送
# ══════════════════════════════════════════════════════════════════════════════

def _text_to_post(text: str) -> dict:
    """将纯文本消息转换为飞书 post 富文本格式。
    - 第一个非分隔行作为标题（加粗）
    - ━━━ / ─── 分隔行跳过
    - markdown 表格行（| 开头）剥离竖线后以纯文本展示
    """
    _SEP = {"━", "─", "═", "-", " "}
    title   = ""
    content = []

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        # 分隔线：跳过
        if line and all(c in _SEP for c in line):
            continue
        # markdown 表格行或表头分隔行
        if line.startswith("|"):
            # 跳过 |---|---| 类分隔行
            inner = line.strip("|").strip()
            if all(c in {"-", " ", ":"} for c in inner):
                continue
            # 剥离竖线，各列用两空格连接
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            line  = "  ".join(cells)

        if not title:
            title = line
        else:
            content.append([{"tag": "text", "text": line}])

    return {"zh_cn": {"title": title, "content": content}}


def _feishu_send_one(receive_id: str, content: str, cfg: dict,
                     receive_id_type: str = "open_id", retry_count: int = 3) -> bool:
    app_id     = cfg.get("app_id", "")
    app_secret = cfg.get("app_secret", "")
    if not app_id or not app_secret:
        print("  ❌ 飞书 app_id / app_secret 未配置")
        return False

    tm    = _get_token_manager(app_id, app_secret)
    write_cache = not cfg.get("_no_persist")
    token = tm.get(write_cache=write_cache)
    if not token:
        return False

    url     = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params  = {"receive_id_type": receive_id_type}
    body    = {"receive_id": receive_id, "msg_type": "post",
               "content": json.dumps(_text_to_post(content))}

    for attempt in range(retry_count):
        try:
            resp   = requests.post(url, params=params, json=body,
                                   headers=headers, timeout=15)
            result = resp.json()
            if result.get("code") == 0:
                print(f"  ✅ 飞书推送成功（第{attempt+1}次）")
                return True
            if result.get("code") in (99991663, 99991661):
                print(f"  ⏳ Token 过期，刷新后重试 ({attempt+1}/{retry_count})")
                token = tm.get(force_refresh=True, write_cache=write_cache)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                continue
            print(f"  ❌ 飞书推送失败: code={result.get('code')} msg={result.get('msg')}")
            if result.get("code") in (99991668, 99991669, 10001):
                return False
        except requests.exceptions.Timeout:
            print(f"  ⏱ 飞书请求超时 ({attempt+1}/{retry_count})")
        except Exception as e:
            print(f"  ❌ 飞书请求异常: {e}")
        if attempt < retry_count - 1:
            wait = 2 * (2 ** attempt)
            print(f"  ⏳ {wait}s 后重试...")
            time.sleep(wait)
    return False


def _feishu_resolve_target(feishu_cfg: dict) -> tuple[str, str]:
    chat_id = feishu_cfg.get("chat_id", "")
    user_id = feishu_cfg.get("user_id", "")
    if chat_id and not chat_id.startswith("YOUR_"):
        return chat_id, "chat_id"
    if user_id and not user_id.startswith("YOUR_"):
        return user_id, "open_id"
    return "", ""


# ══════════════════════════════════════════════════════════════════════════════
# Kimi Claw：kimiim-cli notify-owner
# ══════════════════════════════════════════════════════════════════════════════

def _kimiclaw_push(content: str, cfg: dict) -> bool:
    """
    通过 kimiim-cli notify-owner 推送给 bot 关联的 owner。
    binary 自动从 ~/.openclaw/openclaw.json 的
    plugins.entries.kimi-claw.config.bridge 读取 kimiapiHost 和 token，
    无需手动配置 env var。
    """
    import subprocess
    kimiclaw_cfg = cfg.get("kimiclaw", {})
    cli          = kimiclaw_cfg.get("cli_path") or "/root/.local/bin/kimiim-cli"

    try:
        result = subprocess.run(
            [cli, "notify-owner", "--content", content],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print("  ✅ kimiclaw 推送成功")
            return True
        err = result.stderr.strip() or result.stdout.strip()
        print(f"  ❌ kimiclaw 推送失败: {err}")
        return False
    except FileNotFoundError:
        print(f"  ❌ kimiim-cli 未找到: {cli}")
        return False
    except Exception as e:
        print(f"  ❌ kimiclaw 推送异常: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 公开接口
# ══════════════════════════════════════════════════════════════════════════════

def push_message(content: str, cfg: dict, urgent: bool = False):
    """
    推送消息到指定渠道：kimiclaw（默认）| feishu
    """
    feishu_cfg  = dict(cfg.get("feishu", {}))
    no_persist = _no_persist_enabled(cfg, feishu_cfg)
    if no_persist:
        feishu_cfg["_no_persist"] = True
    channel_raw = cfg.get("push", {}).get("channel", "kimiclaw")
    channels    = {c.strip() for c in channel_raw.split(",")}

    if "feishu" in channels:
        receive_id, id_type = _feishu_resolve_target(feishu_cfg)
        if not receive_id:
            print("  ❌ 飞书推送目标未配置（chat_id 和 user_id 均缺失）")
        else:
            retry_count = 5 if urgent else 3
            ok = _feishu_send_one(receive_id, content, feishu_cfg,
                                  receive_id_type=id_type, retry_count=retry_count)
            if not ok and not no_persist:
                FailedMessageQueue.add(receive_id, id_type, content, "发送失败")

    if "kimiclaw" in channels:
        _kimiclaw_push(content, cfg)


def _feishu_send_card(receive_id: str, card_dict: dict, cfg: dict,
                      receive_id_type: str = "open_id", retry_count: int = 3) -> bool:
    """推送飞书 schema 2.0 交互卡片（interactive 类型）。"""
    app_id     = cfg.get("app_id", "")
    app_secret = cfg.get("app_secret", "")
    if not app_id or not app_secret:
        print("  ❌ 飞书 app_id / app_secret 未配置")
        return False

    tm    = _get_token_manager(app_id, app_secret)
    write_cache = not cfg.get("_no_persist")
    token = tm.get(write_cache=write_cache)
    if not token:
        return False

    url     = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params  = {"receive_id_type": receive_id_type}
    body    = {
        "receive_id": receive_id,
        "msg_type":   "interactive",
        "content":    json.dumps(card_dict),
    }

    for attempt in range(retry_count):
        try:
            resp   = requests.post(url, params=params, json=body,
                                   headers=headers, timeout=15)
            result = resp.json()
            if result.get("code") == 0:
                print(f"  ✅ 飞书卡片推送成功（第{attempt+1}次）")
                return True
            if result.get("code") in (99991663, 99991661):
                print(f"  ⏳ Token 过期，刷新后重试 ({attempt+1}/{retry_count})")
                token = tm.get(force_refresh=True, write_cache=write_cache)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                continue
            print(f"  ❌ 飞书卡片推送失败: code={result.get('code')} msg={result.get('msg')}")
            if result.get("code") in (99991668, 99991669, 10001):
                return False
        except requests.exceptions.Timeout:
            print(f"  ⏱ 飞书卡片请求超时 ({attempt+1}/{retry_count})")
        except Exception as e:
            print(f"  ❌ 飞书卡片请求异常: {e}")
        if attempt < retry_count - 1:
            wait = 2 * (2 ** attempt)
            print(f"  ⏳ {wait}s 后重试...")
            time.sleep(wait)
    return False


def push_card(card_dict: dict, cfg: dict) -> bool:
    """推送飞书 schema 2.0 交互卡片。返回是否成功。"""
    feishu_cfg  = dict(cfg.get("feishu", {}))
    if _no_persist_enabled(cfg, feishu_cfg):
        feishu_cfg["_no_persist"] = True
    channel_raw = cfg.get("push", {}).get("channel", "kimiclaw")
    channels    = {c.strip() for c in channel_raw.split(",")}

    if "feishu" in channels:
        receive_id, id_type = _feishu_resolve_target(feishu_cfg)
        if not receive_id:
            print("  ❌ 飞书推送目标未配置（chat_id 和 user_id 均缺失）")
        else:
            return _feishu_send_card(receive_id, card_dict, feishu_cfg,
                                     receive_id_type=id_type)
    return False


def flush_failed(cfg: dict):
    """重试历史失败的飞书消息（每次 monitor 启动时调用）。"""
    feishu_cfg = dict(cfg.get("feishu", {}))
    if _no_persist_enabled(cfg, feishu_cfg):
        return

    msgs = FailedMessageQueue.get_all()
    if not msgs:
        return

    print(f"\n📬 发现 {len(msgs)} 条历史失败消息，尝试重发...")
    remove_keys = set()
    retry_counts = {}

    for msg in msgs:
        msg_key = FailedMessageQueue._key(msg)
        if msg.get("retry_count", 0) >= 5:
            remove_keys.add(msg_key)
            continue
        try:
            failed_at = datetime.fromisoformat(msg["failed_at"])
        except Exception:
            remove_keys.add(msg_key)
            continue
        if datetime.now() - failed_at > timedelta(hours=1):
            remove_keys.add(msg_key)
            continue

        receive_id = msg.get("receive_id") or msg.get("user_id", "")
        id_type    = msg.get("receive_id_type", "open_id")
        ok = _feishu_send_one(receive_id, msg["content"], feishu_cfg,
                              receive_id_type=id_type, retry_count=2)
        if ok:
            remove_keys.add(msg_key)
            print(f"  ✅ 重发成功: {msg['failed_at'][:16]}")
        else:
            retry_counts[msg_key] = msg.get("retry_count", 0) + 1

    if not remove_keys and not retry_counts:
        return

    with _json_file_lock(_FAILED_MSG_FILE, exclusive=True):
        current = FailedMessageQueue._load_unlocked()
        kept = []
        for msg in current:
            msg_key = FailedMessageQueue._key(msg)
            if msg_key in remove_keys:
                continue
            if msg_key in retry_counts:
                msg["retry_count"] = max(msg.get("retry_count", 0), retry_counts[msg_key])
            kept.append(msg)
        FailedMessageQueue._save_unlocked(kept)

    if remove_keys:
        print(f"  已清理 {len(remove_keys)} 条（成功或过期）")
