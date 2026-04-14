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

import json
import os
import random
import sys
import time
import fcntl
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Optional
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
    
    # 文件日志（按大小轮转）
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "monitor.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    
    # 格式化
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info("日志系统初始化完成")


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
    
    # 检查推送渠道
    channel = cfg.get("push", {}).get("channel", "")
    if channel not in ["feishu", "openclaw", "both"]:
        errors.append(f"push.channel 无效: {channel}")
    
    # 检查飞书配置（如果启用）
    if channel in ["feishu", "both"]:
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
    
    return len(errors) == 0, errors


class ConfigWatcher:
    """配置文件热重载监视器"""
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.last_mtime = self.filepath.stat().st_mtime if self.filepath.exists() else 0
    
    def check(self) -> bool:
        """检查文件是否修改，返回是否已修改"""
        if not self.filepath.exists():
            return False
        current_mtime = self.filepath.stat().st_mtime
        if current_mtime > self.last_mtime:
            self.last_mtime = current_mtime
            return True
        return False

# --- 路径 ---
_SCRIPT_DIR = Path(__file__).parent
_ROOT_DIR   = _SCRIPT_DIR.parent
_DATA_DIR   = _ROOT_DIR / "data"
_LOG_DIR    = _ROOT_DIR / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOG_DIR.mkdir(exist_ok=True)

_CONFIG_FILE    = _ROOT_DIR / "config.json"
_WATCHLIST_FILE = _ROOT_DIR / "watchlist.json"
_STATE_FILE     = _DATA_DIR / "state.json"

# --- 本地模块 ---
sys.path.insert(0, str(_SCRIPT_DIR))
import requests as _requests
from feishu import push_message, flush_failed
from kimi_tech import TechnicalCalculator


# ══════════════════════════════════════════════════════════════════
# 配置 & 状态
# ══════════════════════════════════════════════════════════════════

def load_config() -> dict:
    with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 环境变量覆盖敏感字段
    for entry in [
        ("kimiCodeAPIKey",    "kimiCodeAPIKey"),
        ("FEISHU_APP_ID",     "feishu", "app_id"),
        ("FEISHU_APP_SECRET", "feishu", "app_secret"),
        ("FEISHU_USER_ID",    "feishu", "user_id"),
    ]:
        val = os.environ.get(entry[0])
        if not val:
            continue
        if len(entry) == 3:
            # 嵌套配置，如 ("FEISHU_APP_ID", "feishu", "app_id")
            _, section, field = entry
            cfg.setdefault(section, {})[field] = val
        else:
            # 顶层配置，如 ("kimiCodeAPIKey", "kimiCodeAPIKey")
            _, cfg_key = entry
            cfg[cfg_key] = val
    # 自选股从独立文件加载
    with open(_WATCHLIST_FILE, "r", encoding="utf-8") as f:
        cfg["watchlist"] = json.load(f)
    return cfg


_DEFAULT_STATE = {
    "cooldowns": {}, "trailing_peaks": {}, "prev_tech": {},
    "last_tech_ts": 0, "last_report_ts": 0,
    "last_startup_date": "", "last_run_ts": 0, "run_count_today": 0,
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


def save_state(state: dict):
    """保存状态文件（带文件锁）"""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)  # 独占锁
            try:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"保存状态文件失败: {e}")


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

def is_market_open(market: str = "CN") -> bool:
    if _SIMULATE_MARKET:
        return True
    now = _now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    if market == "CN": return (930 <= t <= 1130) or (1300 <= t <= 1500)
    if market == "HK": return 930 <= t <= 1600
    if market == "US": return t >= 2230 or t <= 600  # 北京时间，夏令时/冬令时差异忽略
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

        minutes   = raw.split(";")
        total_vol = total_amt = 0
        for m in minutes:
            p = m.split(",")
            if len(p) >= 5:
                total_vol += int(float(p[4]))
                total_amt += float(p[2])

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
    """雪球 HK/US 行情 (替代 Yahoo Finance，带细化的异常处理和指标)"""
    # 转换代码格式: 0700.HK -> 00700, BABA -> BABA
    if ".HK" in symbol:
        xq_symbol = symbol.replace(".HK", "")
        market = 'HK'
    else:
        xq_symbol = symbol
        market = 'US'
    
    url = f"https://stock.xueqiu.com/v5/stock/realtime/quotec.json?symbol={xq_symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://xueqiu.com/",
    }
    
    start_time = time.time()
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("data") or len(data["data"]) == 0:
            logger.warning(f"{symbol} 雪球数据为空（可能非交易时间）")
            if PROMETHEUS_AVAILABLE:
                api_latency.labels(market=market).observe(time.time() - start_time)
            return None
        
        quote = data["data"][0]
        price = quote.get("current", 0)
        prev_close = quote.get("last_close", 0)
        volume = quote.get("volume", 0)
        change_acc = quote.get("percent", 0)
        currency = "HKD" if ".HK" in symbol else "USD"
        
        # 从 timestamp 提取时间 (毫秒转秒)
        ts = quote.get("timestamp", 0)
        time_str = datetime.fromtimestamp(ts / 1000).strftime("%H:%M") if ts else ""
        
        # 记录 Prometheus 指标
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market=market).observe(time.time() - start_time)
        
        return {
            "code":            symbol,
            "price":           price,
            "pre_close":       prev_close,
            "change_ratio_acc": change_acc,
            "change_ratio":    change_acc,
            "volume":          int(volume),
            "buy_volume":      0,
            "sell_volume":     0,
            "volume_ratio":    None,
            "currency":        currency,
            "time":            time_str,
        }
    except Timeout:
        logger.error(f"{symbol} 雪球行情请求超时")
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market=market).observe(time.time() - start_time)
        return None
    except RequestException as e:
        logger.error(f"{symbol} 雪球行情网络错误: {e}")
        if PROMETHEUS_AVAILABLE:
            api_latency.labels(market=market).observe(time.time() - start_time)
        return None
    except JSONDecodeError as e:
        logger.error(f"{symbol} 雪球行情JSON解析失败: {e}")
        return None
    except Exception as e:
        logger.exception(f"{symbol} 雪球行情获取未知错误")
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


def check_trailing_stop(code: str, price: float, cost: float, trailing_cfg: dict, state: dict) -> Optional[str]:
    """返回 'exit'/'warn'/None"""
    if cost <= 0:
        return None
    profit_pct = (price - cost) / cost * 100
    if profit_pct < trailing_cfg.get("profit_trigger", 10.0):
        return None

    peak = state["trailing_peaks"].get(code, price)
    if price > peak:
        state["trailing_peaks"][code] = price
        peak = price

    drawdown = (peak - price) / peak * 100
    if drawdown >= trailing_cfg.get("drawdown_exit", 10.0):
        return "exit"
    if drawdown >= trailing_cfg.get("drawdown_warn", 5.0):
        return "warn"
    return None


# ══════════════════════════════════════════════════════════════════
# 异动检测
# ══════════════════════════════════════════════════════════════════

def _check_technical_anomaly(tech: dict, prev: dict, tat: dict) -> list:
    alerts = []
    try:
        diff      = tech.get("MACD_DIFF")
        dea       = tech.get("MACD_DEA")
        prev_diff = prev.get("MACD_DIFF")
        if diff is not None and dea is not None and prev_diff is not None:
            if tat.get("macd_cross", True) and prev_diff <= dea and diff > dea:
                alerts.append("🎯 MACD金叉：DIFF上穿DEA，动能转多")
            elif tat.get("macd_cross", True) and prev_diff >= dea and diff < dea:
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
                tech["ma_status"] = "bull"
            elif ma5 < ma10 < ma20 and prev_ma != "bear":
                alerts.append("📉 均线空头：MA5<MA10<MA20，趋势转弱")
                tech["ma_status"] = "bear"

        lb = tech.get("LB5")
        if lb is not None:
            if lb > tat.get("volume_surge", 3.0):
                alerts.append(f"🔥 量能激增：量比{lb:.2f}，资金大量涌入")
            elif (lb > tat.get("volume_breakout", 2.0)
                  and diff is not None and dea is not None and diff > dea):
                alerts.append(f"🔥 放量突破：量比{lb:.2f}+MACD金叉，上涨动能强劲")
    except Exception as e:
        print(f"  ⚠️ 技术指标检测异常: {e}")
    return alerts


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
        anomaly["details"].append(f"多空异动：外/内盘={bv/sv:.1f}x")

    if tech:
        tat         = alerts_cfg.get("tech", {})
        tech_alerts = _check_technical_anomaly(tech, prev_tech or {}, tat)
        if tech_alerts:
            anomaly["technical"] = True
            anomaly["details"].extend(tech_alerts)

    if any(anomaly[k] for k in ("volume", "buy_sell", "technical")):
        return anomaly
    return None


# ══════════════════════════════════════════════════════════════════
# 报告格式化
# ══════════════════════════════════════════════════════════════════

def _f(val, d=2) -> str:
    """None 安全格式化"""
    return f"{val:.{d}f}" if val is not None else "N/A"


_CURRENCY_SYM = {"CN": "¥", "HK": "HK$", "US": "$"}

def _cur(stock: dict) -> str:
    """返回该股票对应的货币符号"""
    explicit = stock.get("currency", "")
    if explicit:
        return {"CNY": "¥", "HKD": "HK$", "USD": "$"}.get(explicit.upper(), explicit)
    return _CURRENCY_SYM.get(stock.get("market", "CN"), "¥")


def format_anomaly_report(stock: dict, tick: dict, anomaly: dict, disclaimer: str) -> str:
    code   = stock["code"]
    name   = stock.get("name", code)
    price  = tick["price"]
    change = tick["change_ratio_acc"]
    n      = len(anomaly["details"])
    g_ico  = "🚨" if n >= 3 else "⚠️" if n >= 2 else "📢"
    d_ico  = "📈" if change > 0 else "📉" if change < 0 else "➡️"
    vr     = tick.get("volume_ratio") or 0
    bv, sv = tick.get("buy_volume", 0), tick.get("sell_volume", 0)

    # 异动类型标签
    type_tags = []
    if anomaly.get("volume"):    type_tags.append("🔥量能")
    if anomaly.get("buy_sell"):  type_tags.append("⚖️多空")
    if anomaly.get("technical"): type_tags.append("📊技术")
    type_str = " · ".join(type_tags) if type_tags else "综合"

    lines = [
        f"{g_ico} 异动提醒  [{type_str}]",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{name}（{code}）",
        f"{d_ico} {price:.2f}  {change:+.2f}%",
    ]
    if vr > 0:
        lines.append(f"量比: {vr:.2f}")
    if sv > 0:
        lines.append(f"外/内盘: {bv/sv:.1f}x")
    lines.append("────────────────")
    lines.extend(f"• {d}" for d in anomaly["details"])

    qty  = stock.get("hold_quantity") or 0
    cost = stock.get("hold_cost") or 0
    if qty > 0 and cost > 0:
        profit = (price - cost) * qty
        pct    = (price - cost) / cost * 100
        p_ico  = "🟢" if profit >= 0 else "🔴"
        sym    = _cur(stock)
        lines += [
            "────────────────",
            f"持仓: {p_ico} {sym}{profit:+.0f} ({pct:+.2f}%)",
            f"{qty}股 @ {sym}{cost:.2f}",
        ]
    lines += ["────────────────", disclaimer]
    return "\n".join(lines)


def format_alert_report(desc: str, stock: dict, tick: dict, disclaimer: str) -> str:
    code   = stock["code"]
    name   = stock.get("name", code)
    price  = tick["price"]
    change = tick.get("change_ratio_acc", 0)
    d_ico  = "📈" if change > 0 else "📉" if change < 0 else "➡️"
    vr     = tick.get("volume_ratio") or 0

    lines = [
        "🚨 提醒触发",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{name}（{code}）",
        f"{d_ico} {price:.2f}  {change:+.2f}%",
    ]
    if vr > 0:
        lines.append(f"量比: {vr:.2f}")
    lines += [
        "────────────────",
        f"条件: {desc}",
    ]
    qty  = stock.get("hold_quantity") or 0
    cost = stock.get("hold_cost") or 0
    if qty > 0 and cost > 0:
        profit = (price - cost) * qty
        pct    = (price - cost) / cost * 100
        p_ico  = "🟢" if profit >= 0 else "🔴"
        sym    = _cur(stock)
        lines += [
            "────────────────",
            f"持仓: {p_ico} {sym}{profit:+.0f} ({pct:+.2f}%)",
            f"{qty}股 @ {sym}{cost:.2f}",
        ]
    lines += [
        "────────────────",
        f"{_now().strftime('%H:%M')}  {disclaimer}",
    ]
    return "\n".join(lines)


def format_tech_report(tech_items: list, disclaimer: str, startup: bool = False) -> str:
    now_str = _now().strftime("%Y-%m-%d %H:%M")
    out = (
        f"🚀 监控已启动  ·  {now_str}\n📊 技术指标快照\n\n"
        if startup
        else f"📊 技术指标汇总  ·  {now_str}\n\n"
    )

    for item in tech_items:
        stock = item["stock"]
        data  = item["data"]
        code  = stock["code"]
        name  = stock.get("name", code)

        # ETF/指数无技术指标数据
        if data.get("_no_tech"):
            out += (
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{name}（{code}）\n"
                "⚪ 无技术指标  ·  ETF/指数\n"
                "────────────────\n"
                "该标的暂不支持技术指标分析\n\n"
            )
            continue

        ma5, ma10, ma20 = data.get("MA5"), data.get("MA10"), data.get("MA20")
        diff, dea, bar  = data.get("MACD_DIFF"), data.get("MACD_DEA"), data.get("MACD_BAR")
        k, d, j         = data.get("KDJ_K"), data.get("KDJ_D"), data.get("KDJ_J")
        rsi             = data.get("RSI6")
        boll_u, boll_m, boll_l = data.get("BOLL_UPPER"), data.get("BOLL_MID"), data.get("BOLL_LOWER")
        lb              = data.get("LB5")
        obv             = data.get("OBV")

        signals = []

        # MA 排列
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:   ma_st = "📈 多头"; signals.append("✅ 均线多头排列")
            elif ma5 < ma10 < ma20: ma_st = "📉 空头"; signals.append("❌ 均线空头排列")
            else:                   ma_st = "➡️ 缠绕";  signals.append("⚠️ 均线缠绕")
        else:
            ma_st = "❓ N/A"

        # MACD
        if diff is not None and dea is not None:
            if diff > dea:
                macd_st = "✅ 金叉"; signals.append("✅ MACD金叉" + ("且红柱扩张" if bar and bar > 0 else ""))
                macd_tr = "📈"
            else:
                macd_st = "❌ 死叉"; signals.append("❌ MACD死叉" + ("且绿柱扩张" if bar and bar < 0 else ""))
                macd_tr = "📉"
        else:
            macd_st = "❓ N/A"; macd_tr = ""

        # KDJ
        if j is not None:
            if j > 100:   kdj_st = "⚠️ 严重超买"; signals.append("⚠️ KDJ J>100 严重超买")
            elif j > 80:  kdj_st = "🔶 超买";     signals.append("⚠️ KDJ超买区")
            elif j < 0:   kdj_st = "🔷 严重超卖"; signals.append("🔷 KDJ J<0 严重超卖")
            elif j < 20:  kdj_st = "🔹 超卖";     signals.append("🔷 KDJ超卖区")
            else:         kdj_st = "✅ 正常"
        else:
            kdj_st = "❓ N/A"

        # RSI
        if rsi is not None:
            if rsi > 70:   rsi_st = "🟠 超买"; signals.append("⚠️ RSI超买")
            elif rsi < 30: rsi_st = "🟢 超卖"; signals.append("🔷 RSI超卖")
            elif rsi > 50: rsi_st = "📈 偏强"
            else:          rsi_st = "📉 偏弱"
        else:
            rsi_st = "❓ N/A"

        # BOLL
        if boll_u and boll_l and boll_m:
            bw     = (boll_u - boll_l) / boll_m * 100
            bw_str = f"{bw:.2f}%"
            if bw < 5:   boll_st = "🎯 极度收窄"; signals.append("🎯 布林带极度收窄，变盘在即")
            elif bw < 10: boll_st = "📊 窄幅"
            else:         boll_st = "📈 宽幅"
            if ma5:
                if ma5 > boll_u:   boll_pos = "↑ 上轨突破"; signals.append("📈 突破BOLL上轨")
                elif ma5 < boll_l: boll_pos = "↓ 下轨跌破"; signals.append("📉 跌破BOLL下轨")
                elif ma5 > boll_m: boll_pos = "中上区间"
                else:              boll_pos = "中下区间"
            else:
                boll_pos = "N/A"
        else:
            bw_str = "N/A"; boll_st = "❓ N/A"; boll_pos = "N/A"

        # 量比
        if lb is not None:
            if lb < 0.8:   vol_st = f"❄️ 缩量 {_f(lb)}"; signals.append(f"❄️ 量比{_f(lb)}明显缩量")
            elif lb > 2.0: vol_st = f"🔥 放量 {_f(lb)}"; signals.append(f"🔥 量比{_f(lb)}显著放量")
            elif lb > 1.5: vol_st = f"📈 温和放量 {_f(lb)}"
            else:          vol_st = f"💨 平量 {_f(lb)}"
        else:
            vol_st = "❓ N/A"

        # 综合判断
        bull_n = sum(1 for s in signals if s.startswith("✅"))
        bear_n = sum(1 for s in signals if s.startswith("❌"))
        warn_n = sum(1 for s in signals if s.startswith(("⚠️", "🔷")))
        if bull_n >= 2 and bear_n == 0:          overall, pos = "🟢 看多", "60-80%"
        elif bull_n >= 1 and bear_n == 0 and warn_n == 0: overall, pos = "🟡 偏多", "40-60%"
        elif bear_n >= 2 and bull_n == 0:        overall, pos = "🔴 看空", "0-20%"
        elif bear_n >= 1 and bull_n == 0:        overall, pos = "🟠 偏空", "20-40%"
        else:                                    overall, pos = "⚪ 观望", "30-50%"

        # 持仓盈亏
        hold_qty  = stock.get("hold_quantity") or 0
        hold_cost = stock.get("hold_cost") or 0
        pnl_line  = ""
        if hold_qty and hold_cost and ma5:
            profit = (ma5 - hold_cost) * hold_qty
            pct    = (ma5 - hold_cost) / hold_cost * 100
            p_ico  = "🟢" if profit >= 0 else "🔴"
            sym    = _cur(stock)
            pnl_line = f"持仓: {p_ico} {sym}{profit:+.0f} ({pct:+.2f}%)\n{hold_qty}股 @ {sym}{hold_cost:.2f}"

        key_signals = [s for s in signals if not s.startswith("⚠️ 均线缠绕")][:4]
        sig_str     = "\n".join(f"  • {s}" for s in key_signals) if key_signals else "  • 暂无明确信号"

        raw_time = data.get("time", "")
        try:
            from datetime import timedelta as _td
            t = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
            data_time = f"{t.strftime('%Y-%m-%d %H:%M')}~{(t + _td(minutes=5)).strftime('%H:%M')}"
        except Exception:
            data_time = raw_time
        bar_dir = "↑" if bar and bar > 0 else "↓"
        bar_str = f"{_f(bar,4)}{bar_dir}" if bar is not None else "N/A"

        block = [
            "═════════════════",
            f"   {name}（{code}）{overall}",
            f"{'已收盘  ' if data.get('market_closed') else ''}{data_time}",
            "─────【趋势】─────",
            f"MA  {_f(ma5)}/{_f(ma10)}/{_f(ma20)}；{ma_st}",
            f"MACD  DIFF/DEA {_f(diff,4)}/{_f(dea,4)}",
            f"↳ BAR {bar_str}  {macd_st} {macd_tr}",
            "─────【动能】─────",
            f"KDJ  K{_f(k,1)}  D{_f(d,1)}  J{_f(j,1)}；{kdj_st}",
            f"RSI6  {_f(rsi,1)}  {rsi_st}",
        ]
        if boll_u:
            block += [
                "─────【通道】─────",
                f"BOLL  上{_f(boll_u)}  中{_f(boll_m)}  下{_f(boll_l)}",
                f"↳ {boll_pos}  带宽{bw_str}  {boll_st}",
            ]
        block += [
            "─────【量能】─────",
            f"LB5  {vol_st}",
        ]
        if obv is not None:
            block.append(f"OBV  {_f(obv,0)}")
        if pnl_line:
            block += ["─────💰 持仓──────"] + pnl_line.split("\n")
        block += [
            "─────🔑 关键信号────",
            sig_str,
        ]
        out += "\n".join(block) + "\n\n"

    out += f"💡 如需详细研判，请告知生成技术分析报告。\n────────────────\n{disclaimer}\n"
    return out


# ══════════════════════════════════════════════════════════════════
# 主逻辑
# ══════════════════════════════════════════════════════════════════

def main():
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
    
    logger.info("配置验证通过")
    
    # 初始化配置监视器（用于热重载）
    config_watcher = ConfigWatcher(str(_CONFIG_FILE))
    
    state      = load_state()
    disclaimer = cfg.get("disclaimer", "*自动推送*")
    # replay 模式下自动添加测试标记，明确提示非实时行情
    if _NOW_OVERRIDE is not None:
        replay_date = _NOW_OVERRIDE.strftime('%m-%d')
        disclaimer = f"[非实时行情·历史回放·{replay_date}] {disclaimer}"
    kimi_cfg   = {
        "api_key": cfg.get("kimiCodeAPIKey"),
        "base_url": cfg.get("kimiCodeBaseUrl", "https://api.kimi.com/coding/v1/tools"),
        "timeout": cfg.get("kimiCodeTimeout", 30)
    }
    cooldown_min = cfg.get("settings", {}).get("cooldown_minutes", 5)
    trailing_cooldown_min = cfg.get("settings", {}).get("trailing_cooldown_minutes", 30)
    req_interval = cfg.get("settings", {}).get("request_interval", 1)

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
    
    # 记录监控股票数量到 Prometheus
    if PROMETHEUS_AVAILABLE:
        active_stocks.set(len(watchlist))
        last_run_timestamp.set_to_current_time()

    # 使用 LRUCache 限制内存使用
    tech_cache = LRUCache(maxsize=100)

    # 是否到了获取技术指标 / 推送报告的时间
    # 用时间戳而非 % 判断，避免 cron 偏移导致漏报
    now             = _now()
    now_ts          = now.timestamp()
    today_str       = now.strftime("%Y-%m-%d")
    TECH_INTERVAL   = 5 * 60    # 每 5 分钟拉一次技术指标
    REPORT_INTERVAL = 15 * 60   # 每 15 分钟推送一次汇总报告
    is_startup    = (state.get("last_startup_date", "") != today_str)
    should_tech   = is_startup or (now_ts - state.get("last_tech_ts",   0)) >= TECH_INTERVAL
    should_report = is_startup or (now_ts - state.get("last_report_ts", 0)) >= REPORT_INTERVAL

    # 检查是否有任何市场处于交易时间（startup 时不跳过，获取最新可用快照）
    markets = {s.get("market", "CN") for s in watchlist}
    if not is_startup and not any(is_market_open(m) for m in markets):
        print(f"⏸️  所有市场均非交易时间，跳过 ({_now().strftime('%H:%M')})")
        if not _REPLAY_MODE:
            save_state(state)
        return

    print(f"\n📊 监控 {len(watchlist)} 只  ({now.strftime('%H:%M:%S')})")

    session    = _make_session()
    tech_cache = {}  # code → tech_data（仅本次运行有技术数据时填充）

    for stock in watchlist:
        code      = stock["code"]
        market    = stock.get("market", "CN")
        alerts_cfg = stock.get("alerts", {})
        cost      = stock.get("hold_cost") or 0

        market_open = is_market_open(market)

        # startup + 非开盘：只拉技术快照，iFind 返回最近一根 K 线
        if is_startup and not market_open:
            if market == "CN" and should_tech and alerts_cfg.get("tech", {}).get("enabled", True):
                print(f"  📡 {code} 技术快照（非交易时间）...")
                td = TechnicalCalculator.calculate_all(
                    code, kimi_cfg=kimi_cfg, mock_now=_NOW_OVERRIDE,
                )
                if td and not td.get("error"):
                    td["market_closed"] = True
                    tech_cache[code] = {"stock": stock, "data": td}
            time.sleep(req_interval)
            continue

        # 非 startup 且市场未开：跳过
        if not market_open:
            continue

        # 获取行情
        tick = (
            fetch_hk_us_quote(code, session)
            if market in ("HK", "US")
            else fetch_cn_quote(code, session)
        )
        if not tick:
            time.sleep(req_interval)
            continue

        if cost > 0:
            tick["cost"] = cost

        change_alert_pct = alerts_cfg.get("change_abs", [])

        # ── change_abs 告警 ──────────────────────────────────
        if change_alert_pct:
            change_abs = abs(tick.get("change_ratio_acc", 0))
            triggered = sorted(
                [v for v in change_alert_pct if change_abs >= abs(v)],
                key=abs, reverse=True
            )
            if triggered:
                v = triggered[0]
                if should_alert(code, f"change_{v}", state, cooldown_min):
                    desc   = f"日内涨跌幅绝对值 ≥ {abs(v)}%"
                    report = format_alert_report(desc, stock, tick, disclaimer)
                    logger.info(f"{code} 触发涨跌幅告警: {desc}")
                    print(report)
                    push_message(report, cfg, urgent=True)
                    if PROMETHEUS_AVAILABLE:
                        alerts_total.labels(type='change_abs', code=code).inc()

        # ── cost_pct 告警 ────────────────────────────────
        cost_pct_alerts = alerts_cfg.get("cost_pct", [])
        if cost_pct_alerts and cost > 0:
            pct      = (tick["price"] - cost) / cost * 100
            loss_thr = min(cost_pct_alerts)
            prof_thr = max(cost_pct_alerts)
            if pct <= loss_thr and should_alert(code, "cost_pct_loss", state, cooldown_min):
                desc   = f"持仓亏损达到 {abs(pct):.1f}%（阈值:{abs(loss_thr)}%）"
                report = format_alert_report(desc, stock, tick, disclaimer)
                logger.info(f"{code} 触发持仓亏损告警: {desc}")
                print(report)
                push_message(report, cfg, urgent=True)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type='cost_pct_loss', code=code).inc()
            elif pct >= prof_thr and should_alert(code, "cost_pct_profit", state, cooldown_min):
                desc   = f"持仓盈利达到 {pct:.1f}%（阈值:{prof_thr}%）"
                report = format_alert_report(desc, stock, tick, disclaimer)
                logger.info(f"{code} 触发持仓盈利告警: {desc}")
                print(report)
                push_message(report, cfg, urgent=True)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type='cost_pct_profit', code=code).inc()

        # ── trailing stop 告警 ───────────────────────────────
        trailing_cfg = alerts_cfg.get("trailing_stop", {})
        if trailing_cfg.get("enabled") and cost > 0:
            level = check_trailing_stop(code, tick["price"], cost, trailing_cfg, state)
            if level and should_alert(code, f"trailing_{level}", state, trailing_cooldown_min):
                label  = "建议减仓" if level == "warn" else "建议止盈清仓"
                desc = f"动态止盈触发 - {label}"
                report = format_alert_report(desc, stock, tick, disclaimer)
                logger.info(f"{code} 触发{desc}")
                print(report)
                push_message(report, cfg, urgent=True)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type=f'trailing_{level}', code=code).inc()

        # ── 技术指标（CN 每5分钟）───────────────────────────
        tech_data = None
        prev_tech = state["prev_tech"].get(code, {})

        if market == "CN" and should_tech and alerts_cfg.get("tech", {}).get("enabled", True):
            logger.debug(f"获取 {code} 技术指标...")
            print(f"  📡 获取 {code} 技术指标...")
            td = TechnicalCalculator.calculate_all(
                code, kimi_cfg=kimi_cfg, mock_now=_NOW_OVERRIDE,
            )
            if td and not td.get("error"):
                # ETF 等无技术指标数据的情况
                if td.get("_no_tech"):
                    logger.info(f"{code} 无技术指标（ETF 或指数）")
                    print(f"  ⚠️ {code} 无技术指标（ETF 或指数）")
                else:
                    tick["volume_ratio"] = td.get("LB5")
                    tech_data = td
                    tech_cache[code] = {"stock": stock, "data": td}
                    logger.debug(f"{code} 技术指标获取成功")

        # ── 异动检测 ─────────────────────────────────────
        anomaly = check_anomaly(
            tick, alerts_cfg,
            tech=tech_data,
            prev_tech=prev_tech,
        )
        if anomaly:
            triggered_types = [k for k in ("volume","buy_sell","technical") if anomaly.get(k)]
            alert_key       = f"anomaly_{'_'.join(sorted(triggered_types))}"
            if should_alert(code, alert_key, state, cooldown_min):
                report = format_anomaly_report(stock, tick, anomaly, disclaimer)
                logger.info(f"{code} 触发异动告警: {alert_key}")
                print(report)
                push_message(report, cfg)
                if PROMETHEUS_AVAILABLE:
                    alerts_total.labels(type='anomaly', code=code).inc()

        time.sleep(req_interval)

    # ── 更新 prev_tech & last_tech_ts ────────────────────────
    if tech_cache:
        for code, item in tech_cache.items():
            td = item["data"]
            state["prev_tech"][code] = {
                "MACD_DIFF": td.get("MACD_DIFF"),
                "MACD_DEA":  td.get("MACD_DEA"),
                "ma_status": td.get("ma_status", ""),
            }
        state["last_tech_ts"] = now_ts

    # ── 每15分钟推送技术汇总报告（当天首次运行用 startup 标头）────
    if should_report and tech_cache:
        items  = list(tech_cache.values())
        report = format_tech_report(items, disclaimer, startup=is_startup)
        print(report)
        push_message(report, cfg)
        state["last_report_ts"]   = now_ts
        state["last_startup_date"] = today_str

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
    logger.info("本次监控完成")
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

    session = _make_session()
    result  = []

    for stock in watchlist:
        code   = stock["code"]
        market = stock.get("market", "CN")
        cost   = stock.get("hold_cost") or 0
        qty    = stock.get("hold_quantity") or 0

        tick = (
            fetch_hk_us_quote(code, session)
            if market in ("HK", "US")
            else fetch_cn_quote(code, session)
        )
        if not tick:
            continue

        price  = tick["price"]
        change = tick.get("change_ratio_acc", 0)
        entry  = {
            "code":     code,
            "name":     stock.get("name", code),
            "market":   market,
            "currency": _cur(stock),
            "price":    price,
            "change":   change,
        }
        if cost > 0 and qty > 0:
            entry["hold_cost"]     = cost
            entry["hold_quantity"] = qty
            entry["profit"]        = round((price - cost) * qty, 2)
            entry["profit_pct"]    = round((price - cost) / cost * 100, 2)

        result.append(entry)
        time.sleep(cfg.get("settings", {}).get("request_interval", 1))

    print(json.dumps(result, ensure_ascii=False, indent=2))


def dry_run():
    """
    用模拟数据走一遍完整的告警+推送流程，验证配置和推送通路是否正常。
    不请求任何行情接口，不修改状态文件。
    """
    cfg        = load_config()
    disclaimer = f"[模拟数据·非实时行情] {cfg.get('disclaimer', '*AI生成，不构成投资建议*')}"

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

    # 模拟一个 +5.3% 的 tick
    price  = round((cost or 50) * 1.053, 2)
    tick   = {
        "price":            price,
        "change_ratio_acc": 5.30,
        "volume_ratio":     2.8,
        "buy_volume":       320000,
        "sell_volume":      110000,
    }

    print(f"🧪 dry-run 模式 — 以 {name}({code}) 为例，模拟 +5.3% 异动\n")

    # 1. change_abs 告警
    report1 = format_alert_report("日内涨跌幅绝对值 ≥ 5%", stock, tick, disclaimer)
    print("── change_abs 告警 ──────────────────")
    print(report1)
    push_message(f"[dry-run] {report1}", cfg, urgent=True)

    # 2. 量能+多空异动
    anomaly = {
        "volume":    True,
        "buy_sell":  True,
        "technical": False,
        "details":   [
            f"量能异动：量比 2.80",
            f"多空异动：外/内盘=2.9x",
        ],
    }
    report2 = format_anomaly_report(stock, tick, anomaly, disclaimer)
    print("\n── 异动报告 ─────────────────────")
    print(report2)
    push_message(f"[dry-run] {report2}", cfg, urgent=True)

    # 3. 技术指标汇总报告（真实数据）
    kimi_cfg = {
        "api_key":  cfg.get("kimiCodeAPIKey"),
        "base_url": cfg.get("kimiCodeBaseUrl", "https://api.kimi.com/coding/v1/tools"),
        "timeout":  cfg.get("kimiCodeTimeout", 30),
    }
    print("\n── 技术指标汇总（真实数据）────────────────")
    market = stock.get("market", "CN")
    with _requests.Session() as session:
        real_tick = (
            fetch_hk_us_quote(code, session)
            if market in ("HK", "US")
            else fetch_cn_quote(code, session)
        )
    td = TechnicalCalculator.calculate_all(code, kimi_cfg=kimi_cfg)
    if real_tick and td and not td.get("error"):
        tech_items = [{"stock": stock, "data": td}]
        report3 = format_tech_report(tech_items, disclaimer, startup=True)
        print(report3)
        push_message(f"[dry-run] {report3}", cfg)
    else:
        print(f"⚠️  技术指标获取失败（tick={bool(real_tick)}, td={bool(td)}），跳过技术报告推送")

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
        "━━━━━━━━━━━━━━━━━━━━",
        f"状态: {health}",
        f"上次运行: {_ago(last_run)}",
        f"今日启动: {'✅ ' + startup_date if startup_date == today_str else '❌ 未启动'}",
        f"今日运行次数: {run_count}",
        f"上次技术报告: {_ago(last_report)}",
        "────────────────",
        f"state.json: {_STATE_FILE}",
    ]
    print("\n".join(lines))


def midday_check():
    """
    盘中巡检：检查监控是否在交易时间内正常运行，异常则自动修复。
    由 OpenClaw 定时触发（每30分钟一次：10:00/10:30/11:00/13:30/14:00/14:30）
    """
    import subprocess
    
    cfg = load_config()
    state = load_state()
    now = datetime.now()
    now_str = now.strftime("%H:%M")
    
    # 非交易时间直接跳过（双重保险）
    if not is_market_open("CN"):
        print(f"[{now_str}] ⏸️ 非交易时间，跳过盘中巡检")
        return
    
    last_run = state.get("last_run_ts", 0)
    stale_threshold = 5 * 60  # 5分钟视为异常（比status宽松一点，避免误判）
    
    is_healthy = last_run > 0 and (now.timestamp() - last_run) < stale_threshold
    
    if is_healthy:
        # 健康状态，可选静默或记录日志
        ago_min = int((now.timestamp() - last_run) / 60)
        print(f"[{now_str}] ✅ 监控正常，{ago_min}分钟前运行")
        return
    
    # 异常状态，需要修复
    never_ran = last_run == 0
    stale_min = int((now.timestamp() - last_run) / 60) if last_run > 0 else "N/A"
    
    print(f"[{now_str}] 🔴 检测到监控异常")
    if never_ran:
        print(f"  原因: 今日从未运行")
    else:
        print(f"  原因: 已 {stale_min} 分钟未更新 (阈值: 5分钟)")
    
    # 执行修复：拉起一次 monitor
    print(f"[{now_str}] 🔄 正在执行修复...")
    try:
        # 使用 subprocess 拉起一次完整 tick，避免阻塞且隔离异常
        result = subprocess.run(
            [sys.executable, str(Path(__file__)), "--midday-repair"],
            capture_output=True,
            text=True,
            timeout=120,  # 2分钟超时
            cwd=str(_ROOT_DIR)
        )
        
        if result.returncode == 0:
            # 再次检查状态
            state = load_state()  # 重新加载
            last_run = state.get("last_run_ts", 0)
            if last_run > 0 and (now.timestamp() - last_run) < 60:  # 1分钟内更新
                msg = f"""🩺 盘中监控自愈成功 · {now_str}

检测到监控异常后已自动修复：
• 上次运行: {stale_min if not never_ran else "从未"} → 刚刚
• 当前时间: {now_str}
• 状态: 监控已恢复正常"""
                print(f"[{now_str}] ✅ 修复成功")
                push_message(msg, cfg, urgent=False)
            else:
                msg = f"""⚠️ 盘中监控修复异常 · {now_str}

尝试修复后监控仍未恢复：
• 修复命令已执行，但状态未更新
• 可能需要检查 logs/monitor.log
• 建议人工介入排查"""
                print(f"[{now_str}] ⚠️ 修复后状态未恢复")
                push_message(msg, cfg, urgent=True)
        else:
            raise Exception(f"修复进程返回非零: {result.returncode}")
            
    except Exception as e:
        msg = f"""🚨 盘中监控修复失败 · {now_str}

自动修复过程中发生错误：
• 异常: {str(e)}
• 时间: {now_str}
• 建议立即手动检查：python3 scripts/monitor.py --status"""
        print(f"[{now_str}] ❌ 修复失败: {e}")
        push_message(msg, cfg, urgent=True)


def midday_repair():
    """
    盘中修复专用入口：执行一次最小化的监控 tick，用于 midday_check 调用。
    避免递归调用 midday_check。
    """
    print("🔄 执行修复 tick...")
    main()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--snapshot":
        snapshot()
    elif arg == "--dry-run":
        dry_run()
    elif arg == "--status":
        status()
    elif arg == "--midday-check":
        # 盘中巡检入口
        midday_check()
    elif arg == "--midday-repair":
        # 修复专用入口（内部使用）
        midday_repair()
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
                if _market in ("HK", "US"):
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
