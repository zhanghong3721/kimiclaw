#!/usr/bin/env python3
"""
股票监控主程序 - OpenClaw Skill 入口
每次被调度器触发时执行一次 tick：
  1. 重试历史失败的飞书消息
  2. 遍历自选股，获取行情 + 技术指标（每5分钟）
  3. 检查 change_abs / cost_pct / trailing_stop / 异动 等告警
  4. 每15分钟推送技术指标汇总报告

配置文件: ../config.json
状态文件: ../data/state.json（冷却时间 + 追踪止盈峰值 + 前次技术数据）
"""

import ast
import json
import os
import random
import sys
import time
import fcntl
import logging
import logging.handlers
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
try:
    from zoneinfo import ZoneInfo
    _ET_ZONE = ZoneInfo("America/New_York")
except ImportError:
    _ET_ZONE = None
from collections import OrderedDict
from requests.exceptions import RequestException, Timeout
from json import JSONDecodeError

# Prometheus 指标（可选）
try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# 设置日志
logger = logging.getLogger("stock_assistant")


def setup_logging(log_level: str = "INFO"):
    """设置分级日志系统"""
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除已有处理器
    logger.handlers = []
    
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "monitor.log"
    # 超过 2 天自动清空
    if log_path.exists():
        age_days = (time.time() - log_path.stat().st_mtime) / 86400
        if age_days > 2:
            log_path.write_text("", encoding="utf-8")
    # WatchedFileHandler 兼容多进程（cron 并发 tick）
    file_handler = logging.handlers.WatchedFileHandler(
        log_path, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    
    # 格式化
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s',
        datefmt='%H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.debug("日志系统初始化完成")


# Prometheus 指标（如果可用）
if PROMETHEUS_AVAILABLE:
    alerts_total = Counter('stock_alerts_total', 'Total alerts', ['type', 'code'])
    api_latency = Histogram('stock_api_latency_seconds', 'API latency', ['market'])
    last_run_timestamp = Gauge('stock_last_run_timestamp', 'Last run timestamp')
    active_stocks = Gauge('stock_active_stocks', 'Number of stocks being monitored')


class LRUCache(OrderedDict):
    """有限大小的 LRU 缓存"""
    def __init__(self, maxsize=100):
        super().__init__()
        self.maxsize = maxsize
    
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]


def validate_config(cfg: dict) -> tuple[bool, list[str]]:
    """验证配置完整性，返回 (是否通过, 错误列表)"""
    errors = []
    
    # 检查推送渠道（支持逗号分隔多渠道，如 "feishu,kimiclaw"）
    channel = cfg.get("push", {}).get("channel", "")
    valid_channels = {"feishu", "kimiclaw"}
    channels = {c.strip() for c in channel.split(",")} if channel else set()
    if not channels or not channels <= valid_channels:
        errors.append(f"push.channel 无效: {channel}（应为 feishu / kimiclaw / feishu,kimiclaw）")

    # 检查飞书配置（如果启用，含多渠道 feishu,kimiclaw 场景）
    if "feishu" in channels:
        feishu = cfg.get("feishu", {})
        if not feishu.get("app_id"):
            errors.append("feishu.app_id 缺失")
        if not feishu.get("app_secret"):
            errors.append("feishu.app_secret 缺失")
        # chat_id 优先，user_id 兜底，至少配一个
        has_chat = feishu.get("chat_id", "").strip() and not feishu["chat_id"].startswith("YOUR_")
        has_user = feishu.get("user_id", "").strip() and not feishu["user_id"].startswith("YOUR_")
        if not has_chat and not has_user:
            errors.append("feishu.chat_id 和 feishu.user_id 至少配置一个")
    
    # 检查 Kimi Code 配置
    if not cfg.get("kimiCodeAPIKey"):
        errors.append("kimiCodeAPIKey 缺失")
    if not cfg.get("kimiPluginBaseUrl"):
        errors.append("kimiPluginBaseUrl 缺失")

    card_mode = cfg.get("settings", {}).get("card_mode", "chart")
    if card_mode not in ("chart", "text"):
        errors.append(f"settings.card_mode 无效: {card_mode}（应为 chart / text）")

    return len(errors) == 0, errors


# --- 路径 ---
_SCRIPT_DIR = Path(__file__).parent
_ROOT_DIR   = _SCRIPT_DIR.parent
_DATA_DIR   = _ROOT_DIR / "data"
_LOG_DIR    = _ROOT_DIR / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOG_DIR.mkdir(exist_ok=True)

def _find_versioned(name: str) -> Path:
    """优先用 active 文件（config.json），不存在则找最新版本号文件（config_v2.json 等）。"""
    active = _ROOT_DIR / f"{name}.json"
    if active.exists():
        return active

    def _ver_key(p: Path):
        stem = p.stem.rsplit("_", 1)[-1].lstrip("v")  # "v2" → "2", "1.0.1" → "1.0.1"
        try:
            return tuple(int(x) for x in stem.split("."))
        except ValueError:
            return (0,)

    candidates = sorted(_ROOT_DIR.glob(f"{name}_*.json"), key=_ver_key, reverse=True)
    if candidates:
        return candidates[0]
    return active

_CONFIG_FILE    = _find_versioned("config")
_WATCHLIST_FILE = _find_versioned("watchlist")
_STATE_FILE        = _DATA_DIR / "state.json"
_INTRADAY_CACHE_FILE = _DATA_DIR / "tick_cache.json"


def load_intraday_cache() -> dict:
    if _INTRADAY_CACHE_FILE.exists():
        try:
            return json.loads(_INTRADAY_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_intraday_cache(cache: dict):
    tmp = _INTRADAY_CACHE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _INTRADAY_CACHE_FILE)
    except Exception as e:
        logger.warning(f"保存 intraday_cache 失败: {e}")
        tmp.unlink(missing_ok=True)

# --- 本地模块 ---
sys.path.insert(0, str(_SCRIPT_DIR))
import requests as _requests
from channel import push_message, push_card, flush_failed
from report import (parse_tech_items, format_alert, format_anomaly,
                    format_tech_text, build_tech_card,
                    build_alert_card, build_anomaly_card, _f, _cur,
                    build_monitor_intraday_card,
                    build_multi_stock_summary_card,
                    pick_sub_chart)
from data_fetch import TechnicalCalculator, get_intraday, fetch_hk_intraday, fetch_us_intraday


# ══════════════════════════════════════════════════════════════════
# 配置 & 状态
# ══════════════════════════════════════════════════════════════════

def _get_oc(oc: dict, *path, default="") -> str:
    """安全取 openclaw.json 嵌套值，取不到返回 default。"""
    node = oc
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
    return node if isinstance(node, str) else default


def _load_openclaw_defaults() -> dict:
    """
    从 ~/.openclaw/openclaw.json 按硬编码映射表提取默认值。
    优先级：env 节点 > plugins.entries bridge > channels bridge。
    所有映射关系集中在此函数，不暴露给 config.json。
    """
    oc_path = Path.home() / ".openclaw" / "openclaw.json"
    if not oc_path.exists():
        return {}
    try:
        oc = json.loads(oc_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    env  = oc.get("env", {})
    # kimi-claw bridge（两种路径兼容）
    br_p = _get_oc(oc, "plugins", "entries", "kimi-claw", "config", "bridge") or {}
    br_c = _get_oc(oc, "channels", "kimi-claw", "config", "bridge") or {}
    if not isinstance(br_p, dict): br_p = {}
    if not isinstance(br_c, dict): br_c = {}

    def first(*vals):
        """返回第一个非空字符串。"""
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    defaults = {}

    # ── kimiCodeAPIKey ──────────────────────────────────────────
    defaults["kimiCodeAPIKey"] = first(
        env.get("KIMI_CODE_API_KEY"),
        env.get("KIMI_API_KEY"),
        br_p.get("kimiCodeAPIKey"), br_p.get("kimiPluginAPIKey"),
        br_c.get("kimiCodeAPIKey"), br_c.get("kimiPluginAPIKey"),
    )

    # ── kimiPluginBaseUrl ─────────────────────────────────────────
    raw_url = first(
        br_p.get("kimiCodeBaseURL"), br_p.get("kimiCodeBaseUrl"),
        br_c.get("kimiCodeBaseURL"), br_c.get("kimiCodeBaseUrl"),
    )
    if raw_url:
        defaults["kimiPluginBaseUrl"] = raw_url.rstrip("/") + "/v1/tools"

    # ── feishu ──────────────────────────────────────────────────
    oc_fs = oc.get("channels", {}).get("feishu", {})
    if not isinstance(oc_fs, dict): oc_fs = {}
    feishu = {
        "app_id":     first(env.get("FEISHU_APP_ID"),     oc_fs.get("appId")),
        "app_secret": first(env.get("FEISHU_APP_SECRET"), oc_fs.get("appSecret")),
        "user_id":    first(env.get("FEISHU_USER_ID"),    oc_fs.get("userId")),
        "chat_id":    first(oc_fs.get("chatId")),
    }
    if any(feishu.values()):
        defaults["feishu"] = feishu

    return defaults


def load_config() -> dict:
    with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 1. 从 ~/.openclaw/openclaw.json 按硬编码映射表补全空字段
    oc_defaults = _load_openclaw_defaults()
    for key, val in oc_defaults.items():
        if isinstance(val, dict):
            section = cfg.setdefault(key, {})
            for k, v in val.items():
                if not section.get(k):
                    section[k] = v
        else:
            if not cfg.get(key) or str(cfg.get(key, "")).startswith("YOUR_"):
                cfg[key] = val

    # 2. 环境变量最高优先级
    for entry in [
        ("kimiCodeAPIKey",    "kimiCodeAPIKey"),
        ("KIMI_CODE_API_KEY", "kimiCodeAPIKey"),
        ("FEISHU_APP_ID",     "feishu", "app_id"),
        ("FEISHU_APP_SECRET", "feishu", "app_secret"),
        ("FEISHU_USER_ID",    "feishu", "user_id"),
    ]:
        val = os.environ.get(entry[0])
        if not val:
            continue
        if len(entry) == 3:
            _, section, field = entry
            cfg.setdefault(section, {})[field] = val
        else:
            _, cfg_key = entry
            cfg[cfg_key] = val

    # 3. 自选股从独立文件加载
    with open(_WATCHLIST_FILE, "r", encoding="utf-8") as f:
        cfg["watchlist"] = json.load(f)
    return cfg


_DEFAULT_STATE = {
    "cooldowns": {}, "trailing_peaks": {}, "prev_tech": {},
    "last_tech_ts": 0, "last_report_ts": 0,
    "last_startup_date": "", "last_run_ts": 0,
    "run_count_today": 0, "run_count_date": "",
    "profit_tiers": {},
    "tech_fail_counts": {},   # code → {"n": 连续失败次数, "ts": 最后失败时间戳}，成功时重置
    "kimi_price_backoff_until": 0,  # KimiFinance 行情 429 冷却截止时间戳
}

def load_state() -> dict:
    """加载状态文件（带文件锁）。用默认值补齐旧文件缺失的字段。"""
    state = dict(_DEFAULT_STATE)
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    saved = json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            state.update(saved)   # 已有字段以文件为准，缺失字段用默认值
        except Exception as e:
            logger.error(f"加载状态文件失败: {e}")
    return state


def _prune_state(state: dict):
    """清理 7 天前的 cooldown key，防止 state.json 无限膨胀。"""
    cutoff = time.time() - 7 * 24 * 3600
    state["cooldowns"] = {k: v for k, v in state.get("cooldowns", {}).items() if v > cutoff}
    # profit_tiers / trailing_peaks 按日期重置，过期 key 同样清理
    today = _now().strftime("%Y-%m-%d")
    for code, tier in list(state.get("profit_tiers", {}).items()):
        if isinstance(tier, dict) and tier.get("date", "") < today:
            del state["profit_tiers"][code]
    for code, peak in list(state.get("trailing_peaks", {}).items()):
        if isinstance(peak, dict) and peak.get("date", "") < today:
            del state["trailing_peaks"][code]
    for code, ct in list(state.get("change_tiers", {}).items()):
        if isinstance(ct, dict) and ct.get("date", "") < today:
            del state["change_tiers"][code]
    # tech_fail_counts：超过 7 天无活动视为废弃（股票已从自选股移除）
    state["tech_fail_counts"] = {
        k: v for k, v in state.get("tech_fail_counts", {}).items()
        if isinstance(v, dict) and v.get("ts", 0) > cutoff
    }
    # price_state 跨日有意义，不清理；旧 price_above/below cooldown key 会被 7 天 TTL 自然淘汰


def save_state(state: dict):
    """保存状态文件：写临时文件 + os.replace 原子替换，避免并发截断。"""
    _prune_state(state)
    tmp = _STATE_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, _STATE_FILE)
    except Exception as e:
        logger.error(f"保存状态文件失败: {e}")
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════
# 市场时间
# ══════════════════════════════════════════════════════════════════

_SIMULATE_MARKET = False  # --simulate / --replay 时设为 True
_NOW_OVERRIDE    = None   # --replay 时覆盖 datetime.now()
_REPLAY_MODE     = False  # --replay 专用标记，用于跳过状态保存

def _now() -> datetime:
    """返回当前时间，--replay 时返回覆盖值。"""
    return _NOW_OVERRIDE if _NOW_OVERRIDE else datetime.now()

def _last_trading_day() -> datetime:
    """返回最近一个交易日的 10:00，用于 --replay 默认值。"""
    from datetime import timedelta, time as _time
    d = datetime.now().date()
    # 若今天未到 09:30（或周末），往前找最近工作日
    if datetime.now().hour < 9 or d.weekday() >= 5:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, _time(10, 0))

def _et_now() -> datetime:
    """返回当前美东时间（含 DST），优先用 zoneinfo，fallback 用 UTC 偏移。"""
    if _ET_ZONE:
        return datetime.now(_ET_ZONE).replace(tzinfo=None)
    # fallback：用 UTC 减偏移，DST 精确到周（3月第二个周日 → 11月第一个周日）
    utc = datetime.utcnow()
    def _nth_weekday(year, month, weekday, n):
        from calendar import monthrange
        days = [d for d in range(1, monthrange(year, month)[1]+1)
                if datetime(year, month, d).weekday() == weekday]
        return days[n-1]
    y = utc.year
    dst_start = datetime(y, 3,  _nth_weekday(y, 3,  6, 2), 2)  # 3月第二个周日 02:00
    dst_end   = datetime(y, 11, _nth_weekday(y, 11, 6, 1), 2)  # 11月第一个周日 02:00
    offset = -4 if dst_start <= utc < dst_end else -5
    return utc + timedelta(hours=offset)


def is_market_open(market: str = "CN") -> bool:
    if _SIMULATE_MARKET:
        return True
    now = _now()

    if market == "US":
        et = _et_now()
        if et.weekday() >= 5:
            return False
        t_et = et.hour * 100 + et.minute
        return 930 <= t_et < 1600

    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    if market == "CN": return (930 <= t <= 1130) or (1300 <= t <= 1500)
    if market == "HK": return (930 <= t <= 1200) or (1300 <= t <= 1600)
    return False


# ══════════════════════════════════════════════════════════════════
# 行情获取
# ══════════════════════════════════════════════════════════════════

def _make_session() -> _requests.Session:
    s = _requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "http://stockpage.10jqka.com.cn/",
    })
    return s


def fetch_cn_quote(code: str, session) -> Optional[dict]:
    """同花顺 A股/ETF 分时行情（带细化的异常处理和指标）"""
    pure     = code.split(".")[0]
    hex_code = f"hs_{pure}"
    ts       = int(time.time() * 1000)
    rand     = random.randint(1000, 9999)
    url      = f"http://d.10jqka.com.cn/v6/time/{hex_code}/today?_={ts}&rand={rand}"

    start_time = time.time()
    try:
        resp = session.get(url, timeout=10, headers={"Cache-Control": "no-cache"})
        resp.raise_for_status()
        text = resp.text
        if "quotebridge" not in text:
            logger.warning(f"{code} 行情数据格式异常")
            return None
        data = json.loads(text.split("(")[1].split(")")[0]).get(hex_code, {})
        raw  = data.get("data", "")
        if not raw:
            logger.warning(f"{code} 行情数据为空")
            return None

        minutes         = raw.split(";")
        total_vol       = total_amt = 0
        intraday_points = []
        for m in minutes:
            p = m.split(",")
            if len(p) >= 5:
                total_vol += int(float(p[4]))
                total_amt += float(p[2])
                try:
                    intraday_points.append({"label": p[0], "close": round(float(p[1]), 4)})
                except ValueError:
                    pass

        lp = minutes[-1].split(",")
        if len(lp) < 5:
            logger.warning(f"{code} 最新分钟数据格式异常")
            return None

        price      = float(lp[1])
        pre_close  = float(data.get("pre", price))
        change_acc = round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0
        prev_price = float(minutes[-2].split(",")[1]) if len(minutes) >= 2 else pre_close
        change_1m  = round((price - prev_price) / prev_price * 100, 2) if prev_price > 0 else 0

        buy_vol = sell_vol = 0
        prev_p  = pre_close
        for m in minutes:
            mp = m.split(",")
            if len(mp) >= 5:
                mp_price = float(mp[1])
                mp_vol   = int(float(mp[4]))
                if mp_price >= prev_p:
                    buy_vol  += mp_vol
                else:
                    sell_vol += mp_vol
                prev_p = mp_price

        # 记录 Prometheus 指标
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market='CN').observe(time.time() - start_time)

        return {
            "code":            code,
            "price":           price,
            "pre_close":       pre_close,
            "change_ratio_acc": change_acc,
            "change_ratio":    change_1m,
            "volume":          total_vol,
            "amount":          total_amt,
            "buy_volume":      buy_vol,
            "sell_volume":     sell_vol,
            "volume_ratio":    None,
            "time":            lp[0],
            "intraday_points": intraday_points,  # 飞书分时图卡片使用；KimiFinance 路径没有此字段
        }
    except Timeout:
        logger.error(f"{code} A股行情请求超时")
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market='CN').observe(time.time() - start_time)
        return None
    except RequestException as e:
        logger.error(f"{code} A股行情网络错误: {e}")
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market='CN').observe(time.time() - start_time)
        return None
    except JSONDecodeError as e:
        logger.error(f"{code} A股行情JSON解析失败: {e}")
        return None
    except Exception as e:
        logger.exception(f"{code} A股行情获取未知错误")
        return None


def fetch_hk_us_quote(symbol: str, session) -> Optional[dict]:
    """新浪财经港股近实时行情（兜底）
    HK: 0700.HK → rt_hk00700
    HK 实测字段: en_name(0),cn_name(1),prev_close(2),open(3),high(4),low(5),
                 price(6),chg_amt(7),chg_pct(8),bid(9),ask(10),amount(11),volume(12),...,date(17),time(18)
    """
    market = "HK"
    pure        = symbol.upper().replace(".HK", "").zfill(5)
    sina_symbol = f"rt_hk{pure}"

    url = f"https://hq.sinajs.cn/list={sina_symbol}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn",
    }

    start_time = time.time()
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        resp.encoding = "gbk"

        # 提取引号内的数据: var hq_str_rt_hk00700="..."
        raw = resp.text
        if '="' not in raw or raw.strip().endswith('=""'):
            logger.warning(f"{symbol} 新浪数据为空（可能非交易时间或代码无效）")
            if PROMETHEUS_AVAILABLE:
                api_latency.labels(market=market).observe(time.time() - start_time)
            return None

        content = raw.split('="', 1)[1].rstrip('";').rstrip('"')
        fields  = content.split(",")

        # 实测: price=f[6], prev_close=f[2], chg_pct=f[8], volume=f[12], time=f[18]
        if len(fields) < 13:
            logger.warning(f"{symbol} 港股字段数不足: {len(fields)}")
            return None
        price      = float(fields[6])
        pre_close  = float(fields[2])
        change_acc = float(fields[8])
        volume     = int(float(fields[12]))
        time_str   = fields[18] if len(fields) > 18 else ""
        currency   = "HKD"

        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market=market).observe(time.time() - start_time)

        return {
            "code":             symbol,
            "price":            price,
            "pre_close":        pre_close,
            "change_ratio_acc": round(change_acc, 2),  # 日涨跌幅
            "change_ratio":     None,                   # 分钟涨跌幅（港股/美股无分钟数据）
            "volume":           volume,
            "buy_volume":       0,
            "sell_volume":      0,
            "volume_ratio":     None,
            "currency":         currency,
            "time":             time_str,
        }
    except Timeout:
        logger.error(f"{symbol} 新浪行情请求超时")
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market=market).observe(time.time() - start_time)
        return None
    except RequestException as e:
        logger.error(f"{symbol} 新浪行情网络错误: {e}")
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market=market).observe(time.time() - start_time)
        return None
    except (ValueError, IndexError) as e:
        logger.error(f"{symbol} 新浪行情数据解析失败: {e} | raw={resp.text[:120] if 'resp' in dir() else ''}")
        return None
    except Exception:
        logger.exception(f"{symbol} 新浪行情获取未知错误")
        return None


def fetch_us_intraday_quote(symbol: str, session=None) -> Optional[dict]:
    """[留存未启用] Yahoo Finance chart 接口拿美股 1 分钟分时。
    返回字段与 fetch_cn_quote 对齐（含 intraday_points），可直接供飞书分时图卡片使用。

    当前主循环 US 分支走 fetch_hk_us_quote（只支持 HK，对美股返回 None），美股告警实际不会触发。
    启用美股时：在 main() 的 US 分支改成 `tick = fetch_us_intraday_quote(code, session)`，
    或叠加 KimiFinance 兜底。本函数独立可调用，不依赖其他改动。

    依赖：zoneinfo（Python 3.9+ 标准库）。curl_cffi 可选（伪装浏览器 TLS，绕 Yahoo 风控），
    无此依赖时自动回退 requests.Session。
    """
    from zoneinfo import ZoneInfo

    symbol = str(symbol).strip().upper()
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "interval":       "1m",
        "range":          "1d",
        "includePrePost": "false",
        "events":         "div,splits",
    }
    headers = {"Referer": f"https://finance.yahoo.com/quote/{symbol}/chart"}

    try:
        try:
            from curl_cffi import requests as _curl_requests  # type: ignore
            resp = _curl_requests.get(url, params=params, headers=headers,
                                      impersonate="chrome124", timeout=20)
        except ImportError:
            sess = session or _make_session()
            resp = sess.get(url, params=params, headers=headers, timeout=12)
        resp.raise_for_status()
        payload = resp.json()

        result = (((payload or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            logger.error(f"{symbol} Yahoo chart 返回为空")
            return None

        meta       = result.get("meta") or {}
        indicators = result.get("indicators") or {}
        quote      = (indicators.get("quote") or [{}])[0]
        timestamps = result.get("timestamp") or []
        closes     = quote.get("close") or []
        volumes    = quote.get("volume") or []
        tz_name    = meta.get("exchangeTimezoneName") or "America/New_York"
        tz         = ZoneInfo(tz_name)

        intraday_points = []
        total_vol = 0.0
        for ts, close, vol in zip(timestamps, closes, volumes):
            if close is None:
                continue
            dt = datetime.fromtimestamp(ts, tz=tz)
            intraday_points.append({
                "label": dt.strftime("%H%M"),
                "close": round(float(close), 4),
            })
            if vol is not None:
                total_vol += float(vol)

        if not intraday_points:
            return None

        prev_close = float(meta.get("chartPreviousClose")
                           or meta.get("previousClose")
                           or intraday_points[0]["close"])
        price      = float(meta.get("regularMarketPrice") or intraday_points[-1]["close"])
        prev_price = float(intraday_points[-2]["close"]) if len(intraday_points) >= 2 else prev_close
        change_acc = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        change_1m  = round((price - prev_price) / prev_price * 100, 2) if prev_price else change_acc

        return {
            "code":            symbol,
            "price":           price,
            "pre_close":       prev_close,
            "change_ratio_acc": change_acc,
            "change_ratio":    change_1m,
            "volume":          total_vol,
            "amount":          0.0,
            "buy_volume":      0,
            "sell_volume":     0,
            "volume_ratio":    None,
            "time":            intraday_points[-1]["label"],
            "intraday_points": intraday_points,
            "currency":        "USD",
            "source":          "yahoo_chart",
        }
    except Exception as e:
        logger.error(f"{symbol} Yahoo chart 分时获取失败: {e}")
        return None


def _fetch_kimi_price_batch(codes: list, kimi_cfg: dict, market: str) -> dict:
    """
    批量拉取同一市场最多3只股票的实时行情。
    返回 {code: tick_dict}，失败返回 {}，限速返回 {"__429__": True}。
    批量接口固定走 data_preview CSV 路径，无 buyVolume/sellVolume。
    """
    api_key = (kimi_cfg or {}).get("api_key", "")
    if not api_key or api_key.startswith("YOUR_"):
        return {}

    def _ifind_ticker(c):
        return (c + ".US") if (market == "US" and not c.upper().endswith(".US")) else c

    tickers    = [_ifind_ticker(c) for c in codes]
    ticker_str = ",".join(tickers)
    if market == "US":
        now_str = _et_now().strftime("%Y-%m-%d %H:%M:00")
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:00")

    base_url  = (kimi_cfg or {}).get("base_url") or ""
    if not base_url:
        return {}
    timeout   = (kimi_cfg or {}).get("timeout", 30)
    safe_key  = ticker_str.replace(",", "_").replace(".", "_")[:40]
    headers   = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "User-Agent": "OpenClaw/1.0", "X-Kimi-Skill": "stock-assistant-v2"}
    payload   = {
        "method": "get_stock_realtime_price",
        "params": {
            "ticker":    ticker_str,
            "time":      now_str,
            "type":      "realtime_price",
            "file_path": f"/tmp/kimi_batch_{safe_key}.json",
        },
    }

    try:
        resp = _requests.post(base_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        outer = resp.json()
        if not outer.get("is_success"):
            err = str(outer.get("error", ""))
            if "429" in err or "rate" in err.lower() or "limit" in err.lower():
                return {"__429__": True}
            return {}
        result_text = outer.get("result", {}).get("user", [{}])[0].get("text", "")
        if not result_text:
            return {}
        result_json = json.loads(result_text)
        preview = result_json.get("data_preview", "")
        if not preview:
            return {}

        lines = [l for l in preview.strip().split("\n") if l and not l.startswith("#")]
        if len(lines) < 2:
            return {}
        headers_csv = lines[0].split(",")

        def _frow(row, *keys):
            for k in keys:
                v = row.get(k, "").strip()
                if v:
                    try: return float(v)
                    except ValueError: pass
            return None

        result = {}
        for line in lines[1:]:
            vals = line.split(",")
            row  = dict(zip(headers_csv, vals))
            _f   = lambda *keys: _frow(row, *keys)
            ts_code = row.get("ts_code", "").strip()
            # 反查原始 code（去掉 .US 后缀或保持原样）
            orig_code = next((c for c in codes if _ifind_ticker(c) == ts_code), ts_code)
            price   = _f("close")
            pct_chg = _f("pct_change")
            pct_1m  = _f("pct_change_1m")
            volume  = _f("vol")
            amount  = _f("amount")
            open_   = _f("open")
            high    = _f("high")
            low     = _f("low")
            if price is None:
                continue
            pre_close = round(price / (1 + pct_chg / 100), 4) if pct_chg and pct_chg != 0 else (price if pct_chg == 0 else None)
            currency  = "HKD" if market == "HK" else ("USD" if market == "US" else "CNY")
            result[orig_code] = {
                "code":             orig_code,
                "price":            price,
                "open":             open_,
                "high":             high,
                "low":              low,
                "pre_close":        pre_close,
                "change_ratio_acc": round(pct_chg, 2) if pct_chg is not None else None,
                "change_ratio":     round(pct_1m,  2) if pct_1m  is not None else None,
                "volume":           int(volume) if volume else 0,
                "amount":           amount or 0,
                "buy_volume":       0,
                "sell_volume":      0,
                "volume_ratio":     None,
                "currency":         currency,
            }
        return result
    except Exception as e:
        logger.warning(f"KimiFinance 批量行情异常: {e}")
        return {}


def _fetch_kimi_price(code: str, kimi_cfg: dict, market: str = "") -> Optional[dict]:
    """
    KimiFinance realtime_price 接口获取实时行情（A股 / 港股 / 美股）。
    A股: 000001.SZ；港股: 0700.HK；美股: AAPL（内部自动补 .US）。
    返回与 fetch_cn_quote / fetch_hk_us_quote 同格式的 dict，失败返回 None。
    """
    api_key = (kimi_cfg or {}).get("api_key", "")
    if not api_key or api_key.startswith("YOUR_"):
        return None

    upper = code.upper()
    # 美股：KimiFinance 需要 AAPL.US 格式
    if market == "US" and not upper.endswith(".US"):
        ifind_ticker = code + ".US"
    else:
        ifind_ticker = code

    base_url = (kimi_cfg or {}).get("base_url") or ""
    if not base_url:
        return None
    timeout  = (kimi_cfg or {}).get("timeout", 30)
    # iFind 对美股期望美东时间（ET），其余市场传北京时间
    if market == "US" or ifind_ticker.upper().endswith(".US"):
        now_str = _et_now().strftime("%Y-%m-%d %H:%M:00")
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:00")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "OpenClaw/1.0",
        "X-Kimi-Skill": "stock-assistant-v2",
    }
    payload = {
        "method": "get_stock_realtime_price",
        "params": {
            "ticker": ifind_ticker,
            "time":   now_str,
            "type":   "realtime_price",
            "file_path": f"/tmp/kimi_price_{ifind_ticker.replace('.', '_')}.json",
        },
    }

    try:
        resp = _requests.post(base_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        outer = resp.json()

        if not outer.get("is_success"):
            # 检查是否限速（HTTP 200 但 body 含 429 相关信息）
            err_text = str(outer.get("error", ""))
            if "429" in err_text or "rate" in err_text.lower() or "limit" in err_text.lower():
                logger.warning(f"KimiFinance price 被限速 (body): {ifind_ticker}")
                return "__429__"
            logger.debug(f"KimiFinance price API 返回失败: {ifind_ticker}")
            return None

        result_text = outer.get("result", {}).get("user", [{}])[0].get("text", "")
        if not result_text:
            return None
        result_json = json.loads(result_text)
        is_ok       = result_json.get("is_success", "")

        # 解析 iFind 嵌套响应（同 kimi_tech.py 格式）
        raw_data = None
        is_ok_str = is_ok if isinstance(is_ok, str) else ""
        if not is_ok_str and not isinstance(is_ok, str):
            # is_success 类型非预期（如 bool/dict），尝试从 result_json 直接读 data_str
            logger.debug(f"KimiFinance is_success 非字符串: {type(is_ok).__name__}={is_ok}, ticker={ifind_ticker}")
            is_ok_str = result_json.get("data_str", "") and "ifind"  # 触发下方 data_str 读取路径
        if is_ok_str.startswith("ifind"):
            if is_ok_str.startswith("ifind, {"):
                inner    = ast.literal_eval(is_ok_str[7:])
                data_str = inner.get("data_str", "")
                raw_data = ast.literal_eval(data_str) if data_str else []
            else:
                data_str = result_json.get("data_str", "")
                if data_str:
                    try:
                        raw_data = ast.literal_eval(data_str)
                    except Exception:
                        raw_data = json.loads(data_str)
        elif "Response data is empty" in is_ok_str:
            logger.debug(f"KimiFinance price 返回空数据（非交易时间？）: {ifind_ticker}")
            return None

        # 美股 fallback：返回 data_preview（CSV）而非 data_str（Python list）
        if not raw_data:
            preview = result_json.get("data_preview", "")
            if not preview:
                return None
            lines = [l for l in preview.strip().split("\n") if l]
            if len(lines) < 2:
                return None
            headers  = lines[0].split(",")
            values   = lines[1].split(",")
            row_csv  = dict(zip(headers, values))

            def _csv(*keys):
                for k in keys:
                    v = row_csv.get(k, "").strip()
                    if v:
                        try:
                            return float(v)
                        except ValueError:
                            pass
                return None

            price   = _csv("close")
            pct_chg = _csv("pct_change")
            volume  = _csv("vol", "volume")
            amount  = _csv("amount")
            pct_1m  = _csv("pct_change_1m")

            if price is None:
                logger.debug(f"KimiFinance price CSV 无法解析价格: {ifind_ticker}")
                return None

            is_us_csv = ifind_ticker.upper().endswith(".US") or market == "US"
            if pct_chg is not None and pct_chg != 0:
                pre_close = round(price / (1 + pct_chg / 100), 4)
            else:
                pre_close = None

            return {
                "code":             code,
                "price":            price,
                "pre_close":        pre_close,
                "change_ratio_acc": round(pct_chg, 2) if pct_chg is not None else None,
                "change_ratio":     round(pct_1m,  2) if pct_1m  is not None else None,
                "volume":           int(volume) if volume else 0,
                "amount":           amount or 0,
                "buy_volume":       0,
                "sell_volume":      0,
                "volume_ratio":     None,
                "time":             row_csv.get("time", ""),
                "currency":         "USD" if is_us_csv else "CNY",
            }

        # 提取字段（iFind high_frequency 接口返回小驼峰字段名）
        row   = raw_data[0]
        table = row.get("table", {})
        logger.debug(f"iFind table keys ({ifind_ticker}): {list(table.keys())}")

        def _first(*keys):
            for k in keys:
                v = table.get(k)
                if v and v[0] is not None:
                    try:
                        return float(v[0])
                    except (TypeError, ValueError):
                        pass
            return None

        price      = _first("close")
        open_      = _first("open")
        high       = _first("high")
        low        = _first("low")
        pct_chg    = _first("changeRatio_accumulated", "pct_change")  # 日涨跌幅（相对昨收）
        change_abs = _first("change")            # 港股：涨跌额
        pct_1m     = _first("changeRatio", "pct_change_1m")    # 分钟涨跌幅（相对前一分钟收盘）
        volume     = _first("volume")
        amount     = _first("amount")
        buy_vol    = _first("buyVolume")
        sell_vol   = _first("sellVolume")
        time_val   = (row.get("time") or [None])[0]

        if price is None:
            logger.debug(f"KimiFinance price 无法解析价格字段: {ifind_ticker}, keys={list(table.keys())}")
            return None

        ticker_upper = ifind_ticker.upper()
        is_hk = ticker_upper.endswith(".HK")
        is_us = ticker_upper.endswith(".US") or market == "US"
        if is_hk:
            # 港股优先用 changeRatio_accumulated（已在 line 709 读入 pct_chg）
            # 仅在缺失时才用涨跌额反推；反推结果超出 ±50% 视为字段单位异常，丢弃
            if pct_chg is not None and abs(pct_chg) <= 50:
                pre_close = round(price / (1 + pct_chg / 100), 4) if pct_chg != 0 else price
            elif change_abs is not None:
                _pre = round(price - change_abs, 4)
                _pct = round(change_abs / _pre * 100, 2) if _pre else None
                if _pct is not None and abs(_pct) <= 50:
                    pre_close = _pre
                    pct_chg   = _pct
                else:
                    logger.warning(f"{ifind_ticker} 港股涨跌幅异常({_pct}%)，可能字段单位错误，丢弃")
                    pre_close = None
                    pct_chg   = None
            else:
                pre_close = None
                pct_chg   = None
        else:
            # A股 / 美股：用涨跌幅反推昨收；pct_chg 缺失时保持 None，不伪造 0
            if pct_chg is not None and pct_chg != 0:
                pre_close = round(price / (1 + pct_chg / 100), 4)
            else:
                pre_close = price if pct_chg == 0 else None

        currency = "HKD" if is_hk else ("USD" if is_us else "CNY")
        return {
            "code":             code,
            "price":            price,
            "open":             open_,
            "high":             high,
            "low":              low,
            "pre_close":        pre_close,
            "change_ratio_acc": round(pct_chg, 2) if pct_chg is not None else None,  # 日涨跌幅
            "change_ratio":     round(pct_1m,  2) if pct_1m  is not None else None,  # 分钟涨跌幅
            "volume":           int(volume) if volume else 0,
            "amount":           amount or 0,
            "buy_volume":       int(buy_vol)  if buy_vol  else 0,
            "sell_volume":      int(sell_vol) if sell_vol else 0,
            "volume_ratio":     None,
            "time":             str(time_val) if time_val else "",
            "currency":         currency,
        }

    except _requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            logger.warning(f"KimiFinance price 被限速 (HTTP 429): {ifind_ticker}")
            return "__429__"
        logger.warning(f"KimiFinance price HTTP错误: {e}")
    except _requests.exceptions.Timeout:
        logger.warning(f"KimiFinance price 超时: {ifind_ticker}")
    except _requests.exceptions.RequestException as e:
        logger.warning(f"KimiFinance price 网络错误: {e}")
    except Exception as e:
        logger.debug(f"KimiFinance price 异常 {ifind_ticker}: {e}")
    return None


# ══════════════════════════════════════════════════════════════════
# 冷却 / 追踪止盈
# ══════════════════════════════════════════════════════════════════

def should_alert(code: str, key: str, state: dict, cooldown_min: int = 30) -> bool:
    full_key = f"{code}_{key}"
    last     = state["cooldowns"].get(full_key, 0)
    if time.time() - last < cooldown_min * 60:
        return False
    state["cooldowns"][full_key] = time.time()
    return True


def should_profit_alert(code: str, pct: float, prof_thr: float,
                        step: float, state: dict, today: str) -> tuple[bool, str]:
    """按档位判断是否推送盈利告警，每日重置，返回 (是否推送, 触发描述)。"""
    if pct < prof_thr:
        return False, ""
    current_tier = int(pct / step) * step
    if current_tier < prof_thr:
        return False, ""
    tiers = state.setdefault("profit_tiers", {})
    last  = tiers.get(code, {})
    if last.get("date") != today:
        last = {}
    if current_tier <= last.get("tier", 0):
        return False, ""
    tiers[code] = {"tier": current_tier, "date": today}
    return True, f"持仓盈利突破 {current_tier:.0f}%（当前 {pct:.1f}%）"


def check_trailing_stop(code: str, price: float, cost: float, trailing_cfg: dict,
                        state: dict, today_str: str = "") -> Optional[str]:
    """返回 'exit'/'warn'/None"""
    if cost <= 0:
        return None
    profit_pct = (price - cost) / cost * 100
    if profit_pct < trailing_cfg.get("profit_trigger", 10.0):
        return None

    # 跨日重置：存 {"peak": float, "date": str}，旧格式 float 视为跨日
    raw  = state["trailing_peaks"].get(code)
    peak = raw["peak"] if isinstance(raw, dict) and raw.get("date") == today_str else price
    if price > peak:
        peak = price
    state["trailing_peaks"][code] = {"peak": peak, "date": today_str}

    drawdown = (peak - price) / peak * 100
    if drawdown >= trailing_cfg.get("drawdown_exit", 10.0):
        return "exit"
    if drawdown >= trailing_cfg.get("drawdown_warn", 5.0):
        return "warn"
    return None


# ══════════════════════════════════════════════════════════════════
# 异动检测
# ══════════════════════════════════════════════════════════════════

def _check_technical_anomaly(tech: dict, prev: dict, tat: dict) -> tuple:
    """返回 (alerts, new_ma_status)，不修改传入的 tech dict。"""
    alerts = []
    new_ma_status = ""
    try:
        diff      = tech.get("MACD_DIFF")
        dea       = tech.get("MACD_DEA")
        prev_diff = prev.get("MACD_DIFF")
        prev_dea  = prev.get("MACD_DEA")
        if diff is not None and dea is not None and prev_diff is not None and prev_dea is not None:
            if tat.get("macd_cross", True) and prev_diff <= prev_dea and diff > dea:
                alerts.append("🎯 MACD金叉：DIFF上穿DEA，动能转多")
            elif tat.get("macd_cross", True) and prev_diff >= prev_dea and diff < dea:
                alerts.append("🎯 MACD死叉：DIFF下穿DEA，动能转空")

        j = tech.get("KDJ_J")
        if j is not None:
            if j > tat.get("kdj_overbought", 100):
                alerts.append(f"⚠️ KDJ超买：J={j:.1f}，警惕回调")
            elif j < tat.get("kdj_oversold", 0):
                alerts.append(f"🔷 KDJ超卖：J={j:.1f}，关注反弹")

        rsi = tech.get("RSI6")
        if rsi is not None:
            if rsi > tat.get("rsi_overbought", 80):
                alerts.append(f"🟠 RSI超买：{rsi:.1f}，短期过热")
            elif rsi < tat.get("rsi_oversold", 20):
                alerts.append(f"🟢 RSI超卖：{rsi:.1f}，极度弱势")

        ma5, ma10, ma20 = tech.get("MA5"), tech.get("MA10"), tech.get("MA20")
        boll_u, boll_l  = tech.get("BOLL_UPPER"), tech.get("BOLL_LOWER")
        if ma5 is not None and boll_u and boll_l:
            if tat.get("boll_break", True) and ma5 > boll_u * 0.995:
                alerts.append(f"📈 突破上轨：{ma5:.2f} > 布林上轨 {boll_u:.2f}")
            elif tat.get("boll_break", True) and ma5 < boll_l * 1.005:
                alerts.append(f"📉 跌破下轨：{ma5:.2f} < 布林下轨 {boll_l:.2f}")

        prev_ma = prev.get("ma_status", "")
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20 and prev_ma != "bull":
                alerts.append("📈 均线多头：MA5>MA10>MA20，趋势转强")
                new_ma_status = "bull"
            elif ma5 < ma10 < ma20 and prev_ma != "bear":
                alerts.append("📉 均线空头：MA5<MA10<MA20，趋势转弱")
                new_ma_status = "bear"

        lb = tech.get("LB5")
        if lb is not None:
            if lb > tat.get("volume_surge", 3.0):
                alerts.append(f"🔥 量能激增：量比{lb:.2f}，资金大量涌入")
            elif (lb > tat.get("volume_breakout", 2.0)
                  and diff is not None and dea is not None and diff > dea):
                alerts.append(f"🔥 放量突破：量比{lb:.2f}+MACD金叉，上涨动能强劲")
    except Exception as e:
        logger.warning(f"技术指标检测异常: {e}")
    return alerts, new_ma_status


def check_anomaly(tick: dict, alerts_cfg: dict, tech=None, prev_tech=None) -> Optional[dict]:
    anomaly = {"volume": False, "buy_sell": False, "technical": False, "details": []}

    vr = tick.get("volume_ratio") or 0
    vr_thr = alerts_cfg.get("volume_ratio", 0)
    if vr_thr and vr >= vr_thr:
        anomaly["volume"] = True
        anomaly["details"].append(f"量能异动：量比 {vr:.2f}")

    bv, sv = tick.get("buy_volume", 0), tick.get("sell_volume", 0)
    bs_thr = alerts_cfg.get("buy_sell_ratio", 0)
    if bs_thr and sv > 0 and bv / sv >= bs_thr:
        anomaly["buy_sell"] = True
        anomaly["details"].append(f"多空异动：涨量/跌量={bv/sv:.1f}x")

    if tech and alerts_cfg.get("tech", {}).get("enabled", False):
        tat                    = alerts_cfg.get("tech", {})
        tech_alerts, new_ma_st = _check_technical_anomaly(tech, prev_tech or {}, tat)
        if new_ma_st:
            tech["ma_status"] = new_ma_st  # 调用方统一写，明确副作用位置
        if tech_alerts:
            anomaly["technical"] = True
            anomaly["details"].extend(tech_alerts)

    if any(anomaly[k] for k in ("volume", "buy_sell", "technical")):
        return anomaly
    return None


# ══════════════════════════════════════════════════════════════════
# 报告格式化（已移至 report.py）
# _f, _cur, format_alert, format_anomaly, format_tech_text,
# build_tech_card, parse_tech_items 均从 report 模块导入。
# ══════════════════════════════════════════════════════════════════

def format_anomaly_report(stock: dict, tick: dict, anomaly: dict, disclaimer: str) -> str:
    """委托给 report.format_anomaly（保留此名称供内部调用）。"""
    return format_anomaly(stock, tick, anomaly, disclaimer,
                          now_str=_now().strftime("%H:%M"))


def format_alert_report(desc: str, stock: dict, tick: dict, disclaimer: str,
                        title: str = "🔔价格提醒") -> str:
    """委托给 report.format_alert（保留此名称供内部调用）。"""
    return format_alert(desc, stock, tick, disclaimer, title,
                        now_str=_now().strftime("%H:%M"))


# 同一 tick 内同一股票最多推一次分时图卡片，后续告警自动退化为旧文字卡，避免
# 同股多告警触发时用户被重复的图轰炸。main() 入口处 clear() 重置。
_TREND_SENT_THIS_TICK: set[str] = set()


def _push(card: dict, text: str, cfg: dict, urgent: bool = True,
          stock: Optional[dict] = None, tick: Optional[dict] = None,
          analysis_text: Optional[str] = None,
          anomaly: Optional[dict] = None,
          extra_marks: Optional[list] = None):
    """飞书走卡片，kimiclaw 走文本，互斥不重复；未知渠道文本兜底。

    当 settings.card_mode == "chart" 且传入了 stock+tick 且 tick 含 intraday_points
    时，会把飞书卡片升级为带分时图的 build_monitor_intraday_card；构建失败自动回退
    到调用方传入的 card（保持旧行为）。
    同一只股票在同一 tick 内只升级第一次，后续推送保留旧卡片防刷屏。
    """
    channels = {c.strip() for c in cfg.get("push", {}).get("channel", "kimiclaw").split(",")}
    card_mode = cfg.get("settings", {}).get("card_mode", "chart")
    code = (stock or {}).get("code", "")
    trend_already_sent = bool(code) and code in _TREND_SENT_THIS_TICK

    # 趋势卡需要分时点位；Kimi 行情接口不带，按需补一次
    # CN→同花顺, HK→腾讯财经, US→腾讯财经; 全部失败→tick_cache 兜底
    # 本 tick 已推过本股票的趋势图时跳过此 HTTP，省一次开销
    if (card_mode == "chart"
            and "feishu" in channels
            and stock is not None
            and tick is not None
            and not tick.get("intraday_points")
            and not trend_already_sent):
        _mkt = stock.get("market", "CN")
        # 美股走腾讯 API（美东时间转北京时间显示），失败则不出趋势图
        if _mkt == "US":
            try:
                _intra = fetch_us_intraday(stock["code"])
                if _intra and _intra.get("rows"):
                    _pts = []
                    for r in _intra["rows"]:
                        try:
                            _et_str = str(r["time"]).zfill(4)
                            _et_dt = datetime.strptime(_et_str, "%H%M")
                            if _ET_ZONE:
                                from zoneinfo import ZoneInfo
                                _et_dt = _et_dt.replace(tzinfo=_ET_ZONE)
                                _bj_dt = _et_dt.astimezone(ZoneInfo("Asia/Shanghai"))
                            else:
                                _bj_dt = _et_dt + timedelta(hours=12)
                            _pts.append({"label": _bj_dt.strftime("%H%M"), "close": r["price"]})
                        except Exception:
                            _pts.append({"label": r["time"], "close": r["price"]})
                    tick["intraday_points"] = _pts
            except Exception as e:
                logger.debug(f"{code} US 分时 API 失败: {e}")
        else:
            try:
                if _mkt == "CN":
                    _intra = get_intraday(stock["code"], "today")
                elif _mkt == "HK":
                    _intra = fetch_hk_intraday(stock["code"])
                else:
                    _intra = None
                if _intra and _intra.get("rows"):
                    tick["intraday_points"] = [
                        {"label": r["time"], "close": r["price"]}
                        for r in _intra["rows"]
                    ]
            except Exception as e:
                logger.debug(f"{stock.get('code')} 按需补分时失败: {e}")
            # CN/HK 分时 API 失败时 tick_cache 兜底
            if not tick.get("intraday_points"):
                try:
                    _icache_data = load_intraday_cache()
                    _today_str = _now().strftime("%Y-%m-%d")
                    _cached = _icache_data.get(code, {})
                    if _cached.get("date") == _today_str and len(_cached.get("ticks", [])) >= 3:
                        tick["intraday_points"] = [
                            {"label": t["t"].replace(":", ""), "close": t["p"]}
                            for t in _cached["ticks"] if t.get("p")
                        ]
                except Exception as e:
                    logger.debug(f"{code} tick_cache 兜底失败: {e}")

    feishu_card = card
    if (card_mode == "chart"
            and "feishu" in channels
            and stock is not None
            and tick
            and tick.get("intraday_points")
            and not trend_already_sent):
        try:
            sub = None
            # 卡片右列：
            #   首行 "{告警类型}·{股票名} {代码}" 拆成两行 —— 告警类型用 ### 标题，股票+代码加粗
            #   ━ 分隔线替换为空行（保持垂直间距，不画线）
            # 依赖：report.py::format_alert/format_anomaly 首行用 "·" 分隔、report.SEP 以 "━" 开头
            #   如果上游改了这两处的格式（比如换成 "─" 或 title 里塞 "·"），这里要同步改
            _raw = analysis_text if analysis_text is not None else text
            _lines = [("" if ln.strip().startswith("━") else ln)
                      for ln in _raw.split("\n")]
            _parts = ("\n".join(_lines)).split("\n", 1)
            _first = _parts[0]
            if "·" in _first:
                # split(·, 1) 只切第一个，股票名本身含 "·"（如"美国·英特尔"）不会误切
                _alert, _sub = _first.split("·", 1)
                _first_out = f"### {_alert.strip()}\n#### {_sub.strip()}"
            else:
                _first_out = f"### {_first}"
            # 把「股价：/触发：/持仓：」这种键值行的 label 加粗（全角冒号 "：" 作为判据；
            # 不匹配 HH:MM 里的半角 ":"，所以时间戳行不会被影响）
            _rest: list[str] = []
            for ln in _parts[1].split("\n") if len(_parts) > 1 else []:
                s = ln.strip()
                if "：" in s and not s.startswith("**"):
                    key, _sep, value = s.partition("：")
                    # 闭合 ** 后必须有空格/标点，飞书 markdown 才能识别粗体边界
                    _rest.append(f"**{key}：** {value}")
                else:
                    _rest.append(ln)
            # 脚注（"HH:MM 自动推送"）放到卡片底部全宽显示，不挤在右列里
            _footer = None
            while _rest and not _rest[-1].strip():
                _rest.pop()
            if _rest and not _rest[-1].strip().startswith("**"):
                _footer = _rest.pop().strip()
            while _rest and not _rest[-1].strip():
                _rest.pop()
            _analysis = f"{_first_out}\n" + "\n".join(_rest) if _rest else _first_out
            _summary = ""
            if isinstance(card, dict):
                _summary = (card.get("header", {})
                            .get("title", {}).get("content", ""))
            feishu_card = build_monitor_intraday_card(
                stock=stock,
                tick=tick,
                analysis_text=_analysis,
                sub_chart=sub,
                header=None,
                summary=_summary or None,
                footer=_footer,
            )
            if code:
                _TREND_SENT_THIS_TICK.add(code)  # 本 tick 本股票已出图
        except Exception as e:
            logger.warning(f"分时图卡片构建失败，回退旧卡片: {e}")
            feishu_card = card

    if "feishu" in channels:
        if not push_card(feishu_card, cfg) and feishu_card is not card:
            push_card(card, cfg)
    if "kimiclaw" in channels:
        push_message(text, cfg, urgent=urgent)
    if not channels & {"feishu", "kimiclaw"}:
        push_message(text, cfg, urgent=urgent)


# ── 以下大段解析/渲染逻辑已移至 report.py ─────────────────────────────────────
# format_tech_report 仅作为本地别名保留，实际由 parse_tech_items + format_tech_text
# 组合实现。主逻辑中新代码直接调用 report 模块函数。

def format_tech_report(tech_items: list, disclaimer: str, startup: bool = False) -> str:
    """已拆分至 report.py；此处保留以兼容 dry_run() 旧调用。"""
    now_str = _now().strftime("%Y-%m-%d %H:%M")
    title   = (
        f"🚀 监控已启动 · {now_str}\n📊 技术指标快照"
        if startup else
        f"📊 技术指标汇总 · {now_str}"
    )
    parsed, etf_names = parse_tech_items(tech_items)
    return format_tech_text(parsed, etf_names, title, disclaimer)




# ══════════════════════════════════════════════════════════════════
# 主逻辑
# ══════════════════════════════════════════════════════════════════

def _watchlist_markets() -> set:
    """快速读取 watchlist 中实际使用的市场，用于早退判断，失败时保守返回全集。"""
    try:
        wl   = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        real = [s for s in wl if not s.get("_example")]
        stocks = real if real else wl
        return {s.get("market", "CN") for s in stocks} or {"CN"}
    except Exception:
        return {"CN", "HK", "US"}


def main():
    _TREND_SENT_THIS_TICK.clear()  # 每个 tick 重置：同股多告警时只第一次带趋势图
    # 非交易时间直接退出，不做任何加载（--replay/--simulate 时跳过此检查）
    if not _SIMULATE_MARKET:
        from datetime import datetime as _dt
        _now_check = _dt.now()
        _t  = _now_check.hour * 100 + _now_check.minute
        _wd = _now_check.weekday()

        # 只按 watchlist 实际包含的市场判断，无港股则不为港股撑着，无美股同理
        _mkts    = _watchlist_markets()
        _cn_open = (930 <= _t <= 1130) or (1300 <= _t <= 1500)
        _hk_open = ("HK" in _mkts) and ((930 <= _t <= 1200) or (1300 <= _t <= 1600))
        _utc_t   = (_now_check - timedelta(hours=8)).hour * 100 + (_now_check - timedelta(hours=8)).minute
        _utc_wd  = (_now_check - timedelta(hours=8)).weekday()
        _us_open = ("US" in _mkts) and _utc_wd < 5 and (1330 <= _utc_t < 2100)

        if _wd >= 5 and not _us_open:
            print(f"⏸️  非交易时间，跳过 ({_now_check.strftime('%H:%M')})")
            return
        if not _cn_open and not _hk_open and not _us_open:
            print(f"⏸️  非交易时间，跳过 ({_now_check.strftime('%H:%M')})")
            return


    # 初始化日志
    setup_logging()

    # 加载并验证配置
    cfg = load_config()
    valid, errors = validate_config(cfg)
    if not valid:
        logger.error("配置验证失败:")
        for err in errors:
            logger.error(f"  - {err}")
        print("❌ 配置验证失败，请检查 config.json")
        for err in errors:
            print(f"  - {err}")
        return
    
    logger.debug("配置验证通过")
    
    state      = load_state()
    disclaimer = cfg.get("disclaimer") or "*自动推送*"
    # replay 模式下自动添加测试标记，明确提示非实时行情
    if _NOW_OVERRIDE is not None:
        replay_date = _NOW_OVERRIDE.strftime('%m-%d')
        disclaimer = f"[非实时行情·历史回放·{replay_date}] {disclaimer}"
    kimi_cfg   = {
        "api_key": cfg.get("kimiCodeAPIKey"),
        "base_url": cfg.get("kimiPluginBaseUrl"),
        "timeout": cfg.get("kimiCodeTimeout", 30)
    }
    cooldown_min          = cfg.get("settings", {}).get("cooldown_minutes", 10)
    anomaly_cooldown_min  = cfg.get("settings", {}).get("anomaly_cooldown_minutes", 15)
    trailing_cooldown_min = cfg.get("settings", {}).get("trailing_cooldown_minutes", 30)
    profit_alert_step     = cfg.get("settings", {}).get("profit_alert_step", 10)
    req_interval          = cfg.get("settings", {}).get("request_interval", 1)

    # 重试上次失败的飞书消息
    flush_failed(cfg)

    watchlist = cfg.get("watchlist", [])
    if not watchlist:
        logger.warning("自选股列表为空")
        print("📭 自选股列表为空")
        if not _REPLAY_MODE:
            save_state(state)
        return

    # 若有用户自己添加的股票（无 _example 标记），过滤掉示例股票
    user_stocks = [s for s in watchlist if not s.get("_example")]
    if user_stocks:
        watchlist = user_stocks

    # 清理已从自选股移除的 code 的 prev_tech（无时间戳，只能对比 watchlist）
    active_codes = {s["code"] for s in watchlist}
    for _code in list(state.get("prev_tech", {}).keys()):
        if _code not in active_codes:
            del state["prev_tech"][_code]

    MAX_WATCH = 30
    if len(watchlist) > MAX_WATCH:
        logger.warning(f"自选股 {len(watchlist)} 只超过上限 {MAX_WATCH}，每分钟循环可能超时；建议精简或调低 request_interval")

    # 记录监控股票数量到 Prometheus
    if PROMETHEUS_AVAILABLE:
        active_stocks.set(len(watchlist))
        last_run_timestamp.set_to_current_time()

    # 是否到了获取技术指标 / 推送报告的时间
    # 用时间戳而非 % 判断，避免 cron 偏移导致漏报
    now             = _now()
    now_ts          = now.timestamp()
    today_str       = now.strftime("%Y-%m-%d")
    # 美股跨 0 点时用 ET 日期判断 startup，避免凌晨触发第二次启动推送
    markets_in_list = {s.get("market", "CN") for s in watchlist}
    if markets_in_list == {"US"}:
        session_date = _et_now().strftime("%Y-%m-%d")
    else:
        session_date = today_str
    TECH_INTERVAL   = 5 * 60    # 每 5 分钟拉一次技术指标
    _cfg_interval   = cfg.get("settings", {}).get("report_interval_minutes", 15)
    REPORT_INTERVAL = max(15, int(_cfg_interval)) * 60   # 最小 15 分钟，不可更短
    is_startup    = (state.get("last_startup_date", "") != session_date)
    should_tech   = is_startup or (now_ts - state.get("last_tech_ts",   0)) >= TECH_INTERVAL
    should_report = is_startup or (now_ts - state.get("last_report_ts", 0)) >= REPORT_INTERVAL

    # 检查是否有任何市场处于交易时间（startup 时不跳过，获取最新可用快照）
    markets = {s.get("market", "CN") for s in watchlist}
    if not is_startup and not any(is_market_open(m) for m in markets):
        print(f"⏸️  所有市场均非交易时间，跳过 ({_now().strftime('%H:%M')})")
        if not _REPLAY_MODE:
            save_state(state)
        return

    _active_count = sum(1 for s in watchlist if is_market_open(s.get("market", "CN")))
    print(f"\n📊 监控 {_active_count} 只  ({now.strftime('%H:%M:%S')})")

    if is_startup:
        _codes = [s.get("name", s["code"]) for s in watchlist if not s.get("_example")]
        _startup_msg = f"🟢 监控已开启 · {now.strftime('%m-%d %H:%M')}\n监控 {len(_codes)} 只：{'、'.join(_codes[:5])}{'…' if len(_codes) > 5 else ''}"
        _push({"title": "监控已开启", "content": _startup_msg}, _startup_msg, cfg, urgent=False)

    session      = _make_session()
    tech_cache   = {}   # code → tech_data（仅本次运行有技术数据时填充）
    tech_attempted = False
    stock_by_code = {s["code"]: s for s in watchlist}  # O(1) 查找
    _alert_count = 0

    # ── 日内价格缓存（供 snapshot 盘后读取）──────────────────────────
    _icache = load_intraday_cache()
    # 清掉不是今天的条目
    _icache = {k: v for k, v in _icache.items() if v.get("date") == today_str}

    _TECH_FAIL_LIMIT    = 5
    _TECH_FAIL_INTERVAL = 30 * 60  # 连续失败达上限后，改为每30分钟重试

    # ── 技术指标批量预拉取（所有 CN 股票统一处理，共享等待）──────
    # 好处：iFind 发布延迟是全局的，等一次10s对所有股票都有效，
    #       避免每只股票各等一遍导致 N×10s 阻塞
    if should_tech and is_market_open("CN"):
        # 收集本次需要拉取技术指标的 CN 股票
        _tech_needed = []
        for _s in watchlist:
            if _s.get("market", "CN") != "CN":
                continue
            _ac = _s.get("alerts", {})
            _need_anomaly = _ac.get("tech", {}).get("enabled")
            _need_report  = _ac.get("tech_report", {}).get("enabled")
            if not _need_anomaly and not _need_report:
                continue
            # 只开了 tech_report 的股票，按报告间隔拉即可，不必每5分钟拉
            if not _need_anomaly and not should_report:
                continue
            _fi = state["tech_fail_counts"].get(_s["code"], {"n": 0, "ts": 0})
            if _fi["n"] >= _TECH_FAIL_LIMIT:
                # 达到上限后每30分钟给一次重试机会，不永久封禁
                if (now_ts - _fi["ts"]) < _TECH_FAIL_INTERVAL:
                    continue
            _tech_needed.append(_s["code"])

        if _tech_needed:
            tech_attempted = True
            # 等5s再开始：iFind 数据在整点后需要几秒写入
            time.sleep(5)
            _tech_deadline = time.time() + 40  # 总预算40s，避免阻塞主循环超过60s
            # 第一轮：全部尝试一次
            _failed = []
            for _code in _tech_needed:
                _td = TechnicalCalculator.calculate_all(
                    _code, kimi_cfg=kimi_cfg, mock_now=_NOW_OVERRIDE)
                if _td and not _td.get("error"):
                    tech_cache[_code] = {"stock": stock_by_code[_code], "data": _td}
                else:
                    _failed.append(_code)

            # 失败了：统一等一次，最多重试3轮，超时直接跳出
            for _round in range(3):
                if not _failed:
                    break
                if time.time() > _tech_deadline:
                    logger.warning(f"技术指标拉取超时，跳过剩余 {len(_failed)} 只")
                    break
                print(f"  ⏳ {len(_failed)} 只技术指标未就绪，等待5s后重试（第{_round+1}轮）...")
                time.sleep(5)
                _still_failed = []
                for _code in _failed:
                    _td = TechnicalCalculator.calculate_all(
                        _code, kimi_cfg=kimi_cfg, mock_now=_NOW_OVERRIDE)
                    if _td and not _td.get("error"):
                        tech_cache[_code] = {"stock": stock_by_code[_code], "data": _td}
                    else:
                        _still_failed.append(_code)
                _failed = _still_failed

            # 更新失败计数
            for _code in _tech_needed:
                if _code in tech_cache:
                    state["tech_fail_counts"][_code] = {"n": 0, "ts": 0}
                else:
                    _fi = state["tech_fail_counts"].get(_code, {"n": 0, "ts": 0})
                    _new_n = _fi["n"] + 1
                    state["tech_fail_counts"][_code] = {"n": _new_n, "ts": now_ts}
                    if _new_n >= _TECH_FAIL_LIMIT:
                        logger.warning(f"{_code} 技术指标连续失败 {_new_n} 次，改为每30分钟重试")

    # ── KimiFinance 行情批量预拉取（同市场最多3只一批）──────────────
    _price_cache: dict = {}  # code → tick_dict
    if time.time() >= state.get("kimi_price_backoff_until", 0):
        from itertools import islice
        def _batches(lst, n):
            it = iter(lst)
            while chunk := list(islice(it, n)):
                yield chunk
        _got_429 = False
        for _mkt in ("CN", "HK", "US"):
            if _got_429:
                break
            _mkt_codes = [s["code"] for s in watchlist
                          if s.get("market", "CN") == _mkt and is_market_open(_mkt)]
            for _batch in _batches(_mkt_codes, 3):
                _res = _fetch_kimi_price_batch(_batch, kimi_cfg, _mkt)
                if _res.get("__429__"):
                    state["kimi_price_backoff_until"] = time.time() + 30 * 60
                    logger.warning("KimiFinance 行情 429，冷却30分钟")
                    if _mkt == "US" and should_alert("__system__", "kimi_us_429", state, 30):
                        msg = "⚠️ 美股行情降级失败：KimiFinance 被限速，未来30分钟美股监控暂停"
                        _push({"title": "监控告警", "content": msg}, msg, cfg, urgent=False)
                    _got_429 = True
                    break
                _price_cache.update(_res)

    def _kimi_price(c, m):
        """先查批量预拉取缓存，缓存缺失时单只兜底（同时处理 429 冷却）。"""
        if c in _price_cache:
            return _price_cache[c]
        if time.time() < state.get("kimi_price_backoff_until", 0):
            if m == "US":
                logger.warning(f"{c} KimiFinance 限速冷却中（无兜底），本 tick 跳过")
            return None
        r = _fetch_kimi_price(c, kimi_cfg, m)
        if r == "__429__":
            state["kimi_price_backoff_until"] = time.time() + 30 * 60
            logger.warning("KimiFinance 行情 429，冷却30分钟，切换降级源")
            if m == "US" and should_alert("__system__", "kimi_us_429", state, 30):
                msg = "⚠️ 美股行情降级失败：KimiFinance 被限速，未来30分钟美股监控暂停"
                _push({"title": "监控告警", "content": msg}, msg, cfg, urgent=False)
            return None
        return r

    for stock in watchlist:
        code      = stock["code"]
        market    = stock.get("market", "CN")
        alerts_cfg = stock.get("alerts", {})
        cost      = stock.get("hold_cost") or 0

        market_open = is_market_open(market)

        _need_tech = (alerts_cfg.get("tech", {}).get("enabled", False) or
                      alerts_cfg.get("tech_report", {}).get("enabled", False))

        # 市场未开：跳过（startup 也不拉盘前快照，避免传昨日时间给 API）
        if not market_open:
            continue

        # 获取行情：KimiFinance 优先，失败降级到网页（429冷却期内自动跳过）
        if market == "CN":
            tick = _kimi_price(code, market) or fetch_cn_quote(code, session)
        elif market == "HK":
            tick = _kimi_price(code, market) or fetch_hk_us_quote(code, session)
        elif market == "US":
            tick = _kimi_price(code, market)
        else:
            tick = fetch_hk_us_quote(code, session)
        if not tick:
            time.sleep(req_interval)
            continue

        if cost > 0:
            tick["cost"] = cost

        change_alert_pct = alerts_cfg.get("change_abs", [])

        # ── change_abs 告警 ──────────────────────────────────
        if change_alert_pct:
            _cr = tick.get("change_ratio_acc")
            if _cr is None:
                triggered = []   # 涨跌幅未知，跳过告警
            else:
                # 状态机：每档独立 armed/fired，价格跌回档位以下才解锁
                # intraday_high/low 记今日实际涨跌幅
                _ct = state.setdefault("change_tiers", {}).setdefault(code, {})
                if _ct.get("date") != today_str or "intraday_high" not in _ct:
                    _ct.update({"date": today_str, "states": {},
                                "intraday_high": None, "intraday_low": None})
                _states = _ct.setdefault("states", {})
                # 更新今日实际高低点
                if _cr is not None:
                    _ct["intraday_high"] = max(_cr, _ct["intraday_high"]) if _ct["intraday_high"] is not None else _cr
                    _ct["intraday_low"]  = min(_cr, _ct["intraday_low"])  if _ct["intraday_low"]  is not None else _cr
                # 解锁：价格回到档位另一侧则 re-arm
                for _v in change_alert_pct:
                    if _v == 0: continue
                    _k = str(_v)
                    _hyst = cfg.get("settings", {}).get("change_abs_hysteresis", 0.5)
                    if _states.get(_k) == "fired":
                        if _v > 0 and _cr < _v - _hyst:   _states[_k] = "armed"
                        elif _v < 0 and _cr > _v + _hyst: _states[_k] = "armed"
                # 取最高 armed 且满足条件的档位
                triggered = sorted(
                    [v for v in change_alert_pct if v != 0
                     and _states.get(str(v), "armed") == "armed"
                     and ((_cr >= v) if v > 0 else (_cr <= v))],
                    key=abs, reverse=True
                )
            if triggered:
                v = triggered[0]
                if should_alert(code, f"change_{v}", state, cooldown_min):
                    _states[str(v)] = "fired"
                    # 顺带标记所有低档（同向且已满足条件），避免同 tick 刷多条
                    for _ov in change_alert_pct:
                        if _ov != 0 and _ov != v and _states.get(str(_ov), "armed") == "armed":
                            if v > 0 and 0 < _ov < v and _cr >= _ov:
                                _states[str(_ov)] = "fired"
                            elif v < 0 and v < _ov < 0 and _cr <= _ov:
                                _states[str(_ov)] = "fired"
                    title = "🔔涨幅提醒" if v > 0 else "🔴跌幅提醒"
                    desc  = (f"日内涨幅 ≥ {v}%" if v > 0 else f"日内跌幅 ≥ {abs(v)}%")
                    report = format_alert_report(desc, stock, tick, disclaimer, title)
                    logger.info(f"{code} 触发涨跌幅告警: {desc}")
                    print(report)
                    _alert_count += 1
                    _push(build_alert_card(title, desc, stock, tick, disclaimer, _now().strftime("%H:%M")), report, cfg,
                          stock=stock, tick=tick)
                    if PROMETHEUS_AVAILABLE:
                        alerts_total.labels(type='change_abs', code=code).inc()

        # ── price_alert 固定价位告警（状态机：必须穿越到另一侧才能再次触发）──
        price_alerts = alerts_cfg.get("price_alert", [])
        if price_alerts:
            price      = tick["price"]
            _ps        = state.setdefault("price_state", {}).setdefault(code, {})
            for pa in price_alerts:
                above = pa.get("above")
                below = pa.get("below")
                if above is not None and above > 0:
                    key = f"above_{above}"
                    armed = _ps.get(key, "armed")
                    if price >= above and armed == "armed":
                        _ps[key] = "fired"
                        desc   = f"价格突破 {above}（当前 {price}）"
                        report = format_alert_report(desc, stock, tick, disclaimer, "🔔价格提醒")
                        logger.info(f"{code} 触发价格告警: {desc}")
                        print(report)
                        _alert_count += 1
                        _push(build_alert_card("🔔价格提醒", desc, stock, tick, disclaimer, _now().strftime("%H:%M")), report, cfg,
                              stock=stock, tick=tick)
                        if PROMETHEUS_AVAILABLE:
                            alerts_total.labels(type='price_above', code=code).inc()
                    elif price < above and armed == "fired":
                        _ps[key] = "armed"  # 回落到阈值下方，重新解锁
                if below is not None and below > 0:
                    key = f"below_{below}"
                    armed = _ps.get(key, "armed")
                    if price <= below and armed == "armed":
                        _ps[key] = "fired"
                        desc   = f"价格跌破 {below}（当前 {price}）"
                        report = format_alert_report(desc, stock, tick, disclaimer, "🔔价格提醒")
                        logger.info(f"{code} 触发价格告警: {desc}")
                        print(report)
                        _alert_count += 1
                        _push(build_alert_card("🔔价格提醒", desc, stock, tick, disclaimer, _now().strftime("%H:%M")), report, cfg,
                              stock=stock, tick=tick)
                        if PROMETHEUS_AVAILABLE:
                            alerts_total.labels(type='price_below', code=code).inc()
                    elif price > below and armed == "fired":
                        _ps[key] = "armed"  # 反弹到阈值上方，重新解锁

        # ── cost_pct 告警 ────────────────────────────────
        cost_pct_cfg    = alerts_cfg.get("cost_pct", [])
        cost_pct_alerts = cost_pct_cfg if isinstance(cost_pct_cfg, list) else cost_pct_cfg.get("values", [])
        cost_pct_on     = cost_pct_cfg.get("enabled", True) if isinstance(cost_pct_cfg, dict) else bool(cost_pct_alerts)
        if cost_pct_on and cost_pct_alerts and cost > 0:
            pct      = (tick["price"] - cost) / cost * 100
            loss_thr = min(cost_pct_alerts)
            prof_thr = max(cost_pct_alerts)
            if pct <= loss_thr and should_alert(code, "cost_pct_loss", state, cooldown_min):
                desc   = f"持仓亏损达到 {abs(pct):.1f}%（阈值:{abs(loss_thr)}%）"
                report = format_alert_report(desc, stock, tick, disclaimer, "🔴止损提醒")
                logger.info(f"{code} 触发持仓亏损告警: {desc}")
                print(report)
                _alert_count += 1
                _push(build_alert_card("🔴止损提醒", desc, stock, tick, disclaimer, _now().strftime("%H:%M")), report, cfg,
                      stock=stock, tick=tick)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type='cost_pct_loss', code=code).inc()
            elif pct > loss_thr:
                fire, desc = should_profit_alert(
                    code, pct, prof_thr, profit_alert_step, state, today_str)
                if fire:
                    report = format_alert_report(desc, stock, tick, disclaimer, "🟢止盈提醒")
                    logger.info(f"{code} 触发持仓盈利告警: {desc}")
                    print(report)
                    _alert_count += 1
                    _push(build_alert_card("🟢止盈提醒", desc, stock, tick, disclaimer, _now().strftime("%H:%M")), report, cfg,
                          stock=stock, tick=tick)
                    if PROMETHEUS_AVAILABLE:
                        alerts_total.labels(type='cost_pct_profit', code=code).inc()

        # ── trailing stop 告警 ───────────────────────────────
        trailing_cfg = alerts_cfg.get("trailing_stop", {})
        if trailing_cfg.get("enabled") and cost > 0:
            level = check_trailing_stop(code, tick["price"], cost, trailing_cfg, state, today_str)
            if level and should_alert(code, f"trailing_{level}", state, trailing_cooldown_min):
                label  = "建议减仓" if level == "warn" else "建议止盈清仓"
                desc   = f"动态止盈触发 - {label}"
                title  = "⚠️动态止盈" if level == "warn" else "🚨建议清仓"
                report = format_alert_report(desc, stock, tick, disclaimer, title)
                logger.info(f"{code} 触发{desc}")
                print(report)
                _alert_count += 1
                _push(build_alert_card(title, desc, stock, tick, disclaimer, _now().strftime("%H:%M")), report, cfg,
                      stock=stock, tick=tick)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type=f'trailing_{level}', code=code).inc()

        # ── 技术指标（预拉取阶段已完成，直接从 tech_cache 读取）──
        tech_data = None
        prev_tech = state["prev_tech"].get(code, {})

        if code in tech_cache:
            td = tech_cache[code]["data"]
            if td.get("_no_tech"):
                logger.debug(f"{code} 无技术指标（ETF 或指数）")
            else:
                tick["volume_ratio"] = td.get("LB5")
                tech_data = td
                logger.debug(f"{code} 使用预拉取技术指标")
            # 把当前价格写入 tech_cache，供技术报告展示
            tech_cache[code]["price"]  = tick["price"]
            tech_cache[code]["change"] = tick.get("change_ratio_acc")

        # ── 异动检测 ─────────────────────────────────────
        anomaly = check_anomaly(
            tick, alerts_cfg,
            tech=tech_data,
            prev_tech=prev_tech,
        )
        if anomaly:
            triggered_types = [k for k in ("volume","buy_sell","technical") if anomaly.get(k)]
            alert_key       = f"anomaly_{'_'.join(sorted(triggered_types))}"
            if should_alert(code, alert_key, state, anomaly_cooldown_min):
                report = format_anomaly_report(stock, tick, anomaly, disclaimer)
                logger.info(f"{code} 触发异动告警: {alert_key}")
                print(report)
                _alert_count += 1
                _push(build_anomaly_card(stock, tick, anomaly, disclaimer, _now().strftime("%H:%M")), report, cfg, urgent=False)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type='anomaly', code=code).inc()

        # ── 写入日内价格缓存 ──────────────────────────────────
        _entry = _icache.setdefault(code, {"date": today_str, "ticks": []})
        if _entry.get("date") != today_str:
            _entry.update({"date": today_str, "ticks": []})
        _entry["ticks"].append({
            "t":   _now().strftime("%H:%M"),
            "o":   tick.get("open"),
            "h":   tick.get("high"),
            "l":   tick.get("low"),
            "p":   tick["price"],
            "chg": tick.get("change_ratio_acc"),
            "pct": tick.get("change_ratio"),
            "vol": tick.get("volume"),
            "amt": tick.get("amount"),
        })

        time.sleep(req_interval)

    save_intraday_cache(_icache)

    # ── 更新 prev_tech & last_tech_ts ────────────────────────
    if tech_cache:
        for code, item in tech_cache.items():
            td = item["data"]
            state["prev_tech"][code] = {
                "MACD_DIFF": td.get("MACD_DIFF"),
                "MACD_DEA":  td.get("MACD_DEA"),
                "ma_status": td.get("ma_status", ""),
            }
    if tech_attempted:
        # 真正尝试过拉取才更新时间戳，避免 API 失败时每分钟重试；
        # _need_tech=False 全部跳过时不算，保留 should_tech 让下次继续触发
        state["last_tech_ts"] = now_ts

    # ── 每N分钟推送技术汇总报告（当天首次运行用 startup 标头）────
    if should_report and tech_cache:
        items = [
            item for item in tech_cache.values()
            if item["stock"].get("alerts", {}).get("tech_report", {}).get("enabled", True)
        ]
        if items:
            now_str_ts  = _now().strftime("%Y-%m-%d %H:%M")
            title       = (f"🚀 监控已启动 · {now_str_ts}" if is_startup
                           else f"📊 技术指标汇总 · {now_str_ts}")
            parsed_items, etf_names = parse_tech_items(items)
            channel_set = {c.strip() for c in cfg.get("push", {}).get("channel", "kimiclaw").split(",")}

            if "feishu" in channel_set:
                push_card(build_tech_card(parsed_items, etf_names, title, disclaimer), cfg)
            if "kimiclaw" in channel_set:
                text = format_tech_text(parsed_items, etf_names, title, disclaimer)
                print(text)
                push_message(text, cfg)
            elif "feishu" not in channel_set:
                text = format_tech_text(parsed_items, etf_names, title, disclaimer)
                print(text)
                push_message(text, cfg)

        # 无论是否推送，都更新时间戳，避免下次重复触发
        state["last_report_ts"] = now_ts

    # 首次运行结束后标记 startup 完成，无论 tech 是否成功
    # 避免 tech_cache 为空时 is_startup 全天卡在 True 导致跳过逻辑失效
    if is_startup:
        state["last_startup_date"] = session_date

    # ── 记录本次运行时间戳 ────────────────────────────────
    state["last_run_ts"] = now_ts
    if today_str != state.get("run_count_date"):
        state["run_count_date"] = today_str
        state["run_count_today"] = 1
    else:
        state["run_count_today"] = state.get("run_count_today", 0) + 1

    # replay 模式不保存状态，避免污染实际监控时间戳
    if not _REPLAY_MODE:
        save_state(state)
    else:
        print("  (回放模式：跳过状态保存)")
    logger.info(f"tick · {_active_count}只 · 无告警" if _alert_count == 0 else f"tick · {_active_count}只 · {_alert_count}条告警")
    print("\n✅ 本次监控完成")

    # 记录 Prometheus 指标
    if PROMETHEUS_AVAILABLE:
        last_run_timestamp.set_to_current_time()


def snapshot():
    """
    输出当日持仓快照 JSON，供子 Skill（收盘复盘）读取。
    不推送消息，不更新状态。
    """
    cfg       = load_config()
    watchlist = cfg.get("watchlist", [])
    user_stocks = [s for s in watchlist if not s.get("_example")]
    if user_stocks:
        watchlist = user_stocks

    session  = _make_session()
    kimi_cfg = {
        "api_key":  cfg.get("kimiCodeAPIKey"),
        "base_url": cfg.get("kimiPluginBaseUrl"),
        "timeout":  cfg.get("kimiCodeTimeout", 30),
    }
    result   = []
    _snap_cache = load_intraday_cache()
    _today = datetime.now().strftime("%Y-%m-%d")

    for stock in watchlist:
        code   = stock["code"]
        market = stock.get("market", "CN")
        cost   = stock.get("hold_cost") or 0
        qty    = stock.get("hold_quantity") or 0

        # snapshot 设计用于收盘后复盘：优先从 tick_cache 取今天最后一条，
        # 市场仍在交易时才调实时接口（兜底场景，如盘中手动触发复盘）
        cached = _snap_cache.get(code, {})
        cached_ticks = cached.get("ticks", [])
        if cached_ticks and cached.get("date") == _today:
            last = cached_ticks[-1]
            tick = {"price": last["p"], "change_ratio_acc": last.get("chg"), "_from_cache": True}
        elif is_market_open(market):
            if market == "CN":
                tick = _fetch_kimi_price(code, kimi_cfg, market) or fetch_cn_quote(code, session)
            elif market == "HK":
                tick = _fetch_kimi_price(code, kimi_cfg, market) or fetch_hk_us_quote(code, session)
            elif market == "US":
                tick = _fetch_kimi_price(code, kimi_cfg, market)
            else:
                tick = fetch_hk_us_quote(code, session)
        else:
            tick = None
        if not tick:
            # 兜底：从 intraday cache 读最后一条已知价格（美股 16:10 复盘时未开盘）
            cached = _snap_cache.get(code, {})
            cached_ticks = cached.get("ticks", [])
            if cached_ticks and cached.get("date") == _today:
                last = cached_ticks[-1]
                tick = {"price": last["p"], "change_ratio_acc": last.get("chg"), "_from_cache": True}
            else:
                continue

        price  = tick["price"]
        change = tick.get("change_ratio_acc")
        entry  = {
            "code":     code,
            "name":     stock.get("name", code),
            "market":   market,
            "currency": _cur(stock),
            "price":    price,
            "change":   change,
            "price_source": "cache" if tick.get("_from_cache") else "live",
        }
        entry["hold_cost"]     = cost if cost > 0 else None
        entry["hold_quantity"] = qty  if qty  > 0 else None
        if cost > 0 and qty > 0:
            entry["profit"]     = round((price - cost) * qty, 2)
            entry["profit_pct"] = round((price - cost) / cost * 100, 2)
        else:
            entry["profit"]     = None
            entry["profit_pct"] = None

        result.append(entry)
        time.sleep(cfg.get("settings", {}).get("request_interval", 1))

    if not result and watchlist:
        import sys
        sys.stderr.write(
            f"WARNING: snapshot returned empty result "
            f"({len(watchlist)} stocks configured, market may be closed or API unavailable)\n"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def dry_run():
    """
    用模拟数据走一遍完整的告警+推送流程，验证配置和推送通路是否正常。
    不请求任何行情接口，不修改状态文件。
    """
    cfg        = load_config()
    disclaimer = "[模拟数据·测试推送通路，非真实告警]"

    watchlist = cfg.get("watchlist", [])
    user_stocks = [s for s in watchlist if not s.get("_example")]
    target = (user_stocks or watchlist)[:1]  # 取第一只股票做演示
    if not target:
        print("❌ watchlist 为空，无法演示")
        return

    stock  = target[0]
    code   = stock["code"]
    name   = stock.get("name", code)
    cost   = stock.get("hold_cost") or 0

    # 模拟一个 +5.3% 的 tick（含 1 分钟分时点，供 card_mode=chart 时渲染分时图）
    price  = round((cost or 50) * 1.053, 2)
    _base  = price / 1.053
    _pts   = []
    for h in (9, 10, 11, 13, 14):
        for m in range(30 if h == 9 else 0, 60 if h != 11 else 31, 5):
            _ratio = _pts[-1]["close"] / _base if _pts else 1.0
            _ratio = min(_ratio + 0.004, 1.053)
            _pts.append({"label": f"{h:02d}{m:02d}", "close": round(_base * _ratio, 2)})
    tick   = {
        "price":            price,
        "change_ratio_acc": 5.30,
        "volume_ratio":     2.8,
        "buy_volume":       320000,
        "sell_volume":      110000,
        "intraday_points":  _pts,
        "currency":         (stock.get("currency") or
                             ({"CN": "CNY", "HK": "HKD"}.get(stock.get("market", "CN"), "USD"))),
    }

    print(f"🧪 dry-run 模式 — 以 {name}({code}) 为例，模拟 +5.3% 异动\n")

    now_str_hm = _now().strftime("%H:%M")
    now_str_ts = _now().strftime("%Y-%m-%d %H:%M")

    # 1. change_abs 告警
    desc1   = "日内涨跌幅绝对值 ≥ 5%"
    report1 = format_alert(desc1, stock, tick, disclaimer, "🔔涨跌提醒", now_str=now_str_hm)
    print("── change_abs 告警 ──────────────────")
    print(report1)
    _push(build_alert_card("🔔涨跌提醒", desc1, stock, tick, disclaimer, now_str_hm),
          f"[dry-run] {report1}", cfg, stock=stock, tick=tick)

    # 2. 量能+多空异动
    anomaly = {
        "volume": True, "buy_sell": True, "technical": False,
        "details": ["量能异动：量比 2.80", "多空异动：涨量/跌量=2.9x"],
    }
    report2 = format_anomaly(stock, tick, anomaly, disclaimer, now_str=now_str_hm)
    print("\n── 异动报告 ─────────────────────")
    print(report2)
    _push(build_anomaly_card(stock, tick, anomaly, disclaimer, now_str_hm),
          f"[dry-run] {report2}", cfg, stock=stock, tick=tick, anomaly=anomaly)

    # 模拟最近一根已收盘的 5 分钟 K 线时间（与 _aligned_time_str 逻辑一致）
    _now_dt   = _now()
    _bar_min  = (_now_dt.minute // 5) * 5 - 5
    if _bar_min < 0:
        _bar_min += 60
        _bar_time = _now_dt.replace(hour=_now_dt.hour - 1, minute=_bar_min, second=0, microsecond=0)
    else:
        _bar_time = _now_dt.replace(minute=_bar_min, second=0, microsecond=0)
    mock_bar_time = _bar_time.strftime("%Y-%m-%d %H:%M:%S")

    mock_td1 = {
        "MA5": 10.80, "MA10": 10.60, "MA20": 10.30,
        "MACD_DIFF": 0.12, "MACD_DEA": 0.08, "MACD_BAR": 0.04,
        "KDJ_K": 72.5, "KDJ_D": 65.3, "KDJ_J": 86.9,
        "RSI6": 61.2, "BOLL_UPPER": 11.40, "BOLL_MID": 10.80, "BOLL_LOWER": 10.20,
        "LB5": 2.1, "time": mock_bar_time,
    }
    mock_td2 = {
        "MA5": 185.0, "MA10": 192.0, "MA20": 198.0,
        "MACD_DIFF": -0.80, "MACD_DEA": -0.50, "MACD_BAR": -0.30,
        "KDJ_K": 28.0, "KDJ_D": 32.0, "KDJ_J": 20.0,
        "RSI6": 38.5, "BOLL_UPPER": 200.0, "BOLL_MID": 190.0, "BOLL_LOWER": 180.0,
        "LB5": 0.7, "time": mock_bar_time,
    }
    mock_stock2 = {"code": "300750.SZ", "name": "宁德时代", "market": "CN", "currency": "CNY",
                   "hold_cost": 180.0, "hold_quantity": 500}

    # 3a. 单股技术报告
    print("\n── 技术指标汇总·单股（模拟数据）────────────────")
    tech_items1   = [{"stock": stock, "data": mock_td1}]
    dr_title1     = f"🚀 监控已启动 · {now_str_ts}\n📊 技术指标快照"
    parsed1, etf1 = parse_tech_items(tech_items1)
    report3a      = format_tech_text(parsed1, etf1, dr_title1, disclaimer)
    print(report3a)
    _push(build_tech_card(parsed1, etf1, dr_title1, disclaimer), f"[dry-run] {report3a}", cfg, urgent=False)

    # 3b. 多股技术报告
    print("\n── 技术指标汇总·多股（模拟数据）────────────────")
    tech_items2   = [{"stock": stock, "data": mock_td1}, {"stock": mock_stock2, "data": mock_td2}]
    dr_title2     = f"📊 定时技术指标汇总 · {now_str_ts}"
    parsed2, etf2 = parse_tech_items(tech_items2)
    report3b      = format_tech_text(parsed2, etf2, dr_title2, disclaimer)
    print(report3b)
    _push(build_tech_card(parsed2, etf2, dr_title2, disclaimer), f"[dry-run] {report3b}", cfg, urgent=False)

    print("✅ dry-run 完成，若未收到推送请检查 config.json 凭证")


def status():
    """
    输出监控健康状态，供模型或用户手动检查。
    """
    state = load_state()
    now   = datetime.now()

    def _ago(ts):
        if not ts:
            return "从未"
        diff = now.timestamp() - ts
        if diff < 60:    return f"{int(diff)}秒前"
        if diff < 3600:  return f"{int(diff/60)}分钟前"
        if diff < 86400: return f"{int(diff/3600)}小时前"
        return f"{int(diff/86400)}天前"

    last_run     = state.get("last_run_ts", 0)
    last_report  = state.get("last_report_ts", 0)
    run_count    = state.get("run_count_today", 0)
    startup_date = state.get("last_startup_date", "")
    today_str    = now.strftime("%Y-%m-%d")

    # 判断健康状态
    stale_threshold = 3 * 60  # 超过 3 分钟未运行视为异常（cron 每分钟一次）
    is_stale = (last_run > 0) and ((now.timestamp() - last_run) > stale_threshold)
    never_ran = (last_run == 0)

    if never_ran:
        health = "⚠️  从未运行"
    elif is_stale and is_market_open("CN"):
        health = "🔴  异常：交易时间内超过3分钟未运行"
    else:
        health = "🟢  正常"

    lines = [
        "📊 监控健康状态",
        "━━━━━━━━━━━━━━━━━━",
        f"状态: {health}",
        f"上次运行: {_ago(last_run)}",
        f"今日启动: {'✅ ' + startup_date if startup_date == today_str else '⏳ 未到开盘时间，数据暂未拉取'}",
        f"今日运行次数: {run_count}",
        f"上次技术报告: {_ago(last_report)}",
        "────────────────",
        f"state.json: {_STATE_FILE}",
    ]
    print("\n".join(lines))




def _check_upgrade():
    """
    启动自检：若 skill 根目录存在 UPGRADE.md，说明是新版本首次运行，
    通知模型执行迁移（monitor.py 本身不执行迁移逻辑，由模型读取 UPGRADE.md 处理）。
    这里只做日志提示，实际迁移由 openclaw onInstall 或调度器触发 SKILL.md 完成。
    """
    upgrade_file = _ROOT_DIR / "UPGRADE.md"
    if upgrade_file.exists():
        logger.warning(
            "检测到 UPGRADE.md，新版本尚未完成迁移。"
            "请确认 openclaw 已触发 onInstall，或手动唤醒 skill 执行升级。"
        )
        # 写入标记文件，供 openclaw/模型侧检测
        (_ROOT_DIR / "data" / ".upgrade_pending").touch()


if __name__ == "__main__":
    _check_upgrade()
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--snapshot":
        snapshot()
    elif arg == "--dry-run":
        dry_run()
    elif arg == "--status":
        status()
    elif arg == "--simulate":
        _SIMULATE_MARKET = True
        print("⚠️  模拟交易时间模式（--simulate），跳过所有市场时间检查")
        main()
    elif arg == "--replay":
        # 支持 --replay 或 --replay YYYY-MM-DD
        if len(sys.argv) > 2:
            try:
                base_dt = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
            except ValueError:
                print("日期格式错误，应为 YYYY-MM-DD，已使用最近交易日")
                base_dt = _last_trading_day().date()
        else:
            base_dt = _last_trading_day().date()
        
        # 方案 B：获取实际最后一根 K 线的时间
        print(f"▶  回放模式：正在获取 {base_dt} 实际收盘数据...")
        try:
            # 临时加载配置获取股票列表
            _cfg = load_config()
            _watchlist = _cfg.get("watchlist", [])
            _user_stocks = [s for s in _watchlist if not s.get("_example")]
            if _user_stocks:
                _watchlist = _user_stocks
            
            if _watchlist:
                _stock = _watchlist[0]
                _code = _stock["code"]
                _market = _stock.get("market", "CN")
                
                # 先尝试获取行情，提取实际时间
                _session = _make_session()
                if _market == "HK":
                    _tick = fetch_hk_us_quote(_code, _session)
                else:
                    _tick = fetch_cn_quote(_code, _session)
                _session.close()
                
                replay_dt = None
                if _tick and _tick.get("time"):
                    # 解析 tick 时间 (兼容 HHMM 或 HH:MM 格式)
                    _time_str = _tick["time"].replace(":", "")
                    if len(_time_str) >= 4:
                        try:
                            _hour, _min = int(_time_str[:2]), int(_time_str[2:4])
                            if 0 <= _hour <= 23 and 0 <= _min <= 59:
                                replay_dt = datetime.combine(base_dt, __import__('datetime').time(_hour, _min))
                                print(f"  取到实际数据时间: {_hour:02d}:{_min:02d} (基于 {_code})")
                        except ValueError:
                            pass
                
                if replay_dt is None:
                    # 回退到默认下午盘
                    replay_dt = datetime.combine(base_dt, __import__('datetime').time(14, 30))
                    print(f"  使用默认时间 14:30 (基于 {_code})")
            else:
                replay_dt = datetime.combine(base_dt, __import__('datetime').time(14, 30))
        except Exception as e:
            print(f"  获取实际时间失败 ({e})，使用默认时间")
            replay_dt = datetime.combine(base_dt, __import__('datetime').time(14, 30))
        
        _NOW_OVERRIDE    = replay_dt
        _SIMULATE_MARKET = True
        _REPLAY_MODE     = True
        print(f"▶  回放模式：模拟时间 {replay_dt.strftime('%Y-%m-%d %H:%M')}，数据拉取最新可用值")
        main()
    else:
        main()
