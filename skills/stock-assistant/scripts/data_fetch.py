"""
数据拉取模块
- fetch_tech()        KimiFinance 5分钟技术指标（A股）
- get_kline()         日K线数据（A股：同花顺 / 港股/美股：腾讯财经，带当日缓存）
- fetch_daily_kline() A股日K线原始拉取（无缓存）
- fetch_hk_kline()    港股日K线（腾讯财经，前复权）
- fetch_us_kline()    美股日K线（东方财富，前复权，自动识别纳斯达克/纽交所/AMEX）
- get_intraday()      日内分时数据（同花顺）
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_ROOT_DIR        = Path(__file__).parent.parent
_CACHE_FILE      = _ROOT_DIR / "data" / "kline_cache.json"
_INTRADAY_CACHE  = _ROOT_DIR / "data" / "intraday_cache.json"

_SKILL_NAME = "stock-assistant-v2"
_TECH_CACHE_FILE = _ROOT_DIR / "data" / "tech_cache.json"


def _find_versioned(name: str) -> Path:
    """优先用 active 文件（config.json），不存在则找最新版本号文件（config_v2.json 等）。"""
    active = _ROOT_DIR / f"{name}.json"
    if active.exists():
        return active
    def _ver_key(p: Path):
        stem = p.stem.rsplit("_", 1)[-1].lstrip("v")
        try:
            return tuple(int(x) for x in stem.split("."))
        except ValueError:
            return (0,)
    candidates = sorted(_ROOT_DIR.glob(f"{name}_*.json"), key=_ver_key, reverse=True)
    return candidates[0] if candidates else active


# ══════════════════════════════════════════════════════════════════════════════
# KimiFinance 技术指标解析
# ══════════════════════════════════════════════════════════════════════════════

def _parse_ifind_tech_data(raw_data: list) -> dict:
    """将 KimiFinance 原始3行技术数据解析为结构化字典"""
    if not raw_data or len(raw_data) < 3:
        return {"error": "数据不足，期望3行数据"}

    result = {
        "thscode": raw_data[0].get("thscode"),
        "time":    raw_data[0].get("time", [None])[0],
        "interval": "5min",
    }

    row1 = raw_data[0].get("table", {})
    result["MA5"]       = row1.get("MA",   [None])[0]
    result["MACD_DIFF"] = row1.get("MACD", [None])[0]
    result["EXPMA5"]    = row1.get("EXPMA",[None])[0]
    result["BBI"]       = row1.get("BBI",  [None])[0]
    result["KDJ_K"]     = row1.get("KDJ",  [None])[0]
    result["RSI6"]      = row1.get("RSI",  [None])[0]
    result["CCI14"]     = row1.get("CCI",  [None])[0]
    result["ROC"]       = row1.get("ROC",  [None])[0]
    result["LB5"]       = row1.get("LB",   [None])[0]
    result["OBV"]       = row1.get("OBV",  [None])[0]
    result["BOLL_MID"]  = row1.get("BOLL", [None])[0]
    result["ATR14"]     = row1.get("ATR",  [None])[0]

    row2 = raw_data[1].get("table", {})
    result["MA10"]       = row2.get("MA",   [None])[0]
    result["MACD_DEA"]   = row2.get("MACD", [None])[0]
    result["KDJ_D"]      = row2.get("KDJ",  [None])[0]
    result["BOLL_UPPER"] = row2.get("BOLL", [None])[0]

    row3 = raw_data[2].get("table", {})
    result["MA20"]       = row3.get("MA",   [None])[0]
    result["KDJ_J"]      = row3.get("KDJ",  [None])[0]
    result["BOLL_LOWER"] = row3.get("BOLL", [None])[0]

    if result["MACD_DIFF"] is not None and result["MACD_DEA"] is not None:
        result["MACD_BAR"] = result["MACD_DIFF"] - result["MACD_DEA"]

    return result


# ══════════════════════════════════════════════════════════════════════════════
# KimiFinance 技术指标拉取
# ══════════════════════════════════════════════════════════════════════════════

def _load_kimi_cfg() -> dict:
    cfg_file = _find_versioned("config")
    cfg = {}
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            cfg = {
                "api_key":  data.get("kimiCodeAPIKey") or "",
                "base_url": data.get("kimiPluginBaseUrl") or "",
                "timeout":  data.get("kimiCodeTimeout", 30),
            }
        except Exception:
            pass
    api_key = os.environ.get("kimiCodeAPIKey") or os.environ.get("KIMI_CODE_API_KEY")
    if api_key:
        cfg["api_key"] = api_key
    return cfg


class TechnicalCalculator:
    """KimiFinance 5分钟技术指标计算器"""

    @staticmethod
    def fetch_from_kimi(ticker: str, time_str: str, kimi_cfg: dict = None) -> Optional[dict]:
        cfg     = kimi_cfg or _load_kimi_cfg()
        api_key  = cfg.get("api_key", "")
        base_url = cfg.get("base_url", "")
        if not api_key or api_key.startswith("YOUR_"):
            print("❌ kimiCodeAPIKey 未配置")
            return None
        if not base_url:
            print("❌ kimiPluginBaseUrl 未配置")
            return None

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "User-Agent":    "OpenClaw/1.0",
            "X-Kimi-Skill":  _SKILL_NAME,
        }
        payload = {
            "method": "get_stock_realtime_price",
            "params": {
                "ticker":    ticker,
                "time":      time_str,
                "type":      "realtime_tech",
                "file_path": f"/tmp/ifind_{ticker.replace('.','_')}_{time_str.replace(' ','_').replace(':','-')}.json",
            },
        }

        try:
            resp = requests.post(
                base_url,
                headers=headers, json=payload,
                timeout=cfg.get("timeout", 30),
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("is_success"):
                err = data.get("result", {}).get("user", [{}])[0].get("text", "未知错误")
                print(f"❌ iFind API 错误: {err}")
                return None

            result_text = data.get("result", {}).get("user", [{}])[0].get("text", "")
            result_json = json.loads(result_text)
            is_success  = result_json.get("is_success", "")

            if isinstance(is_success, str) and is_success.startswith("ifind"):
                if is_success.startswith("ifind, {"):
                    inner    = ast.literal_eval(is_success[7:])
                    data_str = inner.get("data_str", "")
                    raw_data = ast.literal_eval(data_str) if data_str else []
                else:
                    data_str = result_json.get("data_str", "")
                    if not data_str:
                        print("⚠️ iFind 返回数据为空")
                        return None
                    try:
                        raw_data = ast.literal_eval(data_str)
                    except Exception:
                        raw_data = json.loads(data_str)
            else:
                if isinstance(is_success, str) and "Response data is empty" in is_success:
                    print("⚠️ iFind 返回空数据（非交易日或非交易时间）")
                else:
                    print(f"⚠️ iFind 返回: {is_success}")
                return None

            if not raw_data or len(raw_data) < 3:
                print(f"⚠️ iFind 数据不足，期望3行，实际{len(raw_data)}行")
                return None

            result = _parse_ifind_tech_data(raw_data)

            tech_fields = ["MA5", "MACD_DIFF", "KDJ_K", "RSI6"]
            if not any(result.get(f) is not None for f in tech_fields):
                print(f"  ⚠️ {ticker} 无技术指标数据（可能为 ETF），尝试获取基础行情...")
                return {"_no_tech": True, "code": ticker, "time": time_str}

            return result

        except requests.exceptions.Timeout:
            print(f"❌ KimiFinance 请求超时: {ticker}")
        except requests.exceptions.RequestException as e:
            print(f"❌ KimiFinance 请求错误: {e}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析错误: {e}")
        except Exception as e:
            print(f"❌ 未知错误: {e}")
        return None

    @staticmethod
    def _aligned_time_str(mock_now=None) -> str:
        now    = mock_now or datetime.now()
        minute = (now.minute // 5) * 5 - 5
        if minute < 0:
            minute += 60
            hour = now.hour - 1
            if hour < 0:
                yesterday = now - timedelta(days=1)
                return yesterday.strftime("%Y-%m-%d 14:55:00")
            return now.strftime(f"%Y-%m-%d {hour:02d}:{minute:02d}:00")
        return now.strftime(f"%Y-%m-%d %H:{minute:02d}:00")

    @staticmethod
    def _is_near_trading_time(now=None) -> bool:
        now = now or datetime.now()
        if now.weekday() >= 5:
            return False
        tv = now.hour * 100 + now.minute
        return (930 <= tv <= 1130) or (1300 <= tv <= 1500)

    @staticmethod
    def _last_trading_time_str(now=None) -> str:
        now = now or datetime.now()
        tv  = now.hour * 100 + now.minute
        if now.weekday() < 5 and tv > 1500:
            return now.strftime("%Y-%m-%d 14:55:00")
        if now.weekday() < 5 and 1131 <= tv < 1300:
            return now.strftime("%Y-%m-%d 11:25:00")
        target = now - timedelta(days=1)
        while target.weekday() >= 5:
            target -= timedelta(days=1)
        return target.strftime("%Y-%m-%d 14:55:00")

    @staticmethod
    def _load_tech_cache() -> dict:
        """加载当日技术指标缓存，跨日自动清空。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if _TECH_CACHE_FILE.exists():
            try:
                data = json.loads(_TECH_CACHE_FILE.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    return data.get("entries", {})
            except Exception:
                pass
        return {}

    @staticmethod
    def _save_tech_cache(cache: dict):
        """保存技术指标缓存，附带日期用于跨日清空。"""
        today = datetime.now().strftime("%Y-%m-%d")
        _TECH_CACHE_FILE.parent.mkdir(exist_ok=True)
        _TECH_CACHE_FILE.write_text(
            json.dumps({"date": today, "entries": cache}, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def calculate_all(cls, code: str, time_str: str = None,
                      mock_now=None, kimi_cfg: dict = None) -> dict:
        """
        获取指定股票的 iFind 5分钟技术指标。
        - 命中当日缓存直接返回，不发 API 请求。
        - iFind 数据有发布延迟：首次失败等 10s 重试同一时间点，最多重试 3 次。
        - 全部失败返回 error dict，由上层决定是否用上次缓存数据。
        """
        is_market_closed = False
        effective_now    = mock_now or datetime.now()
        if time_str is None and not cls._is_near_trading_time(now=effective_now):
            is_market_closed = True

        if time_str is None:
            time_str = (
                cls._last_trading_time_str(now=effective_now)
                if is_market_closed
                else cls._aligned_time_str(mock_now=mock_now)
            )

        cache     = cls._load_tech_cache()
        cache_key = f"{code}@{time_str}"

        # ── 缓存命中，直接返回 ────────────────────────────────
        if cache_key in cache:
            return cache[cache_key]

        # ── 单次请求（不在此处重试，重试由 monitor.py 批量管理）──
        result = cls.fetch_from_kimi(code, time_str, kimi_cfg=kimi_cfg)

        if result is None:
            return {
                "code": code, "time": time_str, "interval": "5min",
                "error": "无法获取数据（已重试3次）",
                "MA5": None, "MA10": None, "MA20": None,
                "MACD_DIFF": None, "MACD_DEA": None, "MACD_BAR": None,
                "KDJ_K": None, "KDJ_D": None, "KDJ_J": None,
                "RSI6": None, "CCI14": None, "ROC": None,
                "LB5": None, "OBV": None, "BBI": None, "ATR14": None,
                "EXPMA5": None, "BOLL_UPPER": None, "BOLL_MID": None, "BOLL_LOWER": None,
            }

        result["code"] = code
        result["time"] = time_str
        if is_market_closed:
            result["market_closed"] = True

        # ── 写缓存 ────────────────────────────────────────────
        cache[cache_key] = result
        cls._save_tech_cache(cache)

        return result


# 兼容 monitor.py 直接 import
fetch_tech = TechnicalCalculator.calculate_all


# ══════════════════════════════════════════════════════════════════════════════
# 日K线（A股：同花顺 / 港股：腾讯财经）
# ══════════════════════════════════════════════════════════════════════════════

def _code_to_ths(code: str) -> str:
    """600519.SH → hs_600519"""
    return "hs_" + code.split(".")[0]


def _code_to_tencent_hk(code: str) -> str:
    """0700.HK / 9992.HK → hk00700 / hk09992"""
    return "hk" + code.split(".")[0].zfill(5)


def _code_to_tencent_us(code: str) -> str:
    """AAPL.US / TSLA → usAAPL / usTSLA"""
    return "us" + code.split(".")[0].upper()



def fetch_hk_kline(code: str, days: int = 120) -> Optional[list]:
    """腾讯财经拉取港股日K线（前复权），返回 list of {date,open,high,low,close,volume}"""
    from datetime import date, timedelta
    end   = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")  # 多取一些，过滤节假日
    tc    = _code_to_tencent_hk(code)
    url   = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,{start},{end},{days},qfq"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer":    "https://gu.qq.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[data_fetch] 港股K线拉取失败 {code}: {e}", file=sys.stderr)
        return None

    if data.get("code") != 0:
        print(f"[data_fetch] 港股K线返回错误 {code}: {data.get('msg')}", file=sys.stderr)
        return None

    raw = data.get("data", {}).get(tc, {}).get("day", [])
    if not raw:
        print(f"[data_fetch] 港股K线无数据 {code}", file=sys.stderr)
        return None

    rows = []
    for item in raw[-days:]:
        try:
            rows.append({
                "date":   item[0],
                "open":   float(item[1]),
                "close":  float(item[2]),
                "high":   float(item[3]),
                "low":    float(item[4]),
                "volume": float(item[5]),
            })
        except (IndexError, ValueError):
            continue
    return rows if rows else None


def fetch_us_kline(code: str, days: int = 120) -> Optional[list]:
    """东方财富拉取美股日K线（前复权），返回 list of {date,open,high,low,close,volume}
    secid 前缀：105=纳斯达克，106=纽交所，107=AMEX，依次尝试直到有数据。
    """
    from datetime import date
    ticker = code.split(".")[0].upper()
    end    = date.today().strftime("%Y%m%d")
    url    = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    "https://quote.eastmoney.com/",
    }

    for market in ("105", "106", "107"):
        params = {
            "secid":   f"{market}.{ticker}",
            "klt":     101,
            "fqt":     1,
            "beg":     0,
            "end":     end,
            "lmt":     days,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56",
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[data_fetch] 美股K线拉取失败 {code} market={market}: {e}", file=sys.stderr)
            continue

        klines = (data.get("data") or {}).get("klines") or []
        if not klines:
            continue

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                rows.append({
                    "date":   parts[0],
                    "open":   float(parts[1]),
                    "close":  float(parts[2]),
                    "high":   float(parts[3]),
                    "low":    float(parts[4]),
                    "volume": float(parts[5]),
                })
            except ValueError:
                continue
        if rows:
            return rows

    print(f"[data_fetch] 美股K线无数据 {code}", file=sys.stderr)
    return None


def fetch_daily_kline(code: str, days: int = 60) -> Optional[list]:
    """从同花顺拉取日K线，返回 list of {date,open,high,low,close,volume,amount,turnover}"""
    url = f"https://d.10jqka.com.cn/v4/line/{_code_to_ths(code)}/01/last.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer":    "https://www.10jqka.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()
        if text.startswith("quotebridge"):
            text = text[text.index("(") + 1 : text.rindex(")")]
        data = json.loads(text)
    except Exception as e:
        print(f"[data_fetch] 拉取K线失败 {code}: {e}", file=sys.stderr)
        return None

    raw = data.get("data", "")
    if not raw:
        print(f"[data_fetch] 无K线数据 {code}", file=sys.stderr)
        return None

    rows = []
    for line in raw.strip().split(";")[-days:]:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            rows.append({
                "date":     parts[0],
                "open":     float(parts[1]),
                "high":     float(parts[2]),
                "low":      float(parts[3]),
                "close":    float(parts[4]),
                "volume":   float(parts[5]),
                "amount":   float(parts[6]),
                "turnover": float(parts[7]) if len(parts) > 7 and parts[7] else None,
            })
        except ValueError:
            continue
    return rows if rows else None


def _load_kline_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            # 清掉 7 天前的条目
            from datetime import datetime as _dt2, timedelta as _td2
            cutoff = (_dt2.now() - _td2(days=7)).strftime("%Y-%m-%d")
            cache = {k: v for k, v in cache.items()
                     if isinstance(v, dict) and v.get("date", "") >= cutoff}
            return cache
        except Exception:
            pass
    return {}


def _save_kline_cache(cache: dict):
    _CACHE_FILE.parent.mkdir(exist_ok=True)
    # 只保留 watchlist 里还在的股票，自动清理已删除标的
    wl_file = _find_versioned("watchlist")
    if wl_file.exists():
        try:
            codes = {s["code"] for s in json.loads(wl_file.read_text(encoding="utf-8"))}
            cache = {k: v for k, v in cache.items() if k in codes}
        except Exception:
            pass
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_kline(code: str, days: int = 60, force: bool = False) -> Optional[list]:
    """带当日缓存的日K线获取，同一天内同一股票只拉一次。A股→同花顺，港股/美股→腾讯财经。"""
    today = datetime.now().strftime("%Y-%m-%d")
    cache = _load_kline_cache()

    if not force and cache.get(code, {}).get("date") == today:
        return cache[code]["data"]

    upper = code.upper()
    if upper.endswith(".HK"):
        rows = fetch_hk_kline(code, days)
    elif upper.endswith(".US") or ("." not in upper and upper.isalpha()):
        rows = fetch_us_kline(code, days)
    else:
        rows = fetch_daily_kline(code, days)
    if rows:
        cache[code] = {"date": today, "fetched_at": datetime.now().strftime("%H:%M"), "data": rows}
        _save_kline_cache(cache)
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 日内分时数据（A股：同花顺 v6/time / 港股+美股：腾讯财经 minute/query）
# ══════════════════════════════════════════════════════════════════════════════

def fetch_intraday(code: str, date: str = "today") -> Optional[dict]:
    """
    拉取日内分时数据
    date: "today" 或 "YYYYMMDD"
    返回 {code, date, pre_close, rows: [{time, price, cum_vol, vwap, vol}]}
    """
    ths_code = _code_to_ths(code)
    url = f"https://d.10jqka.com.cn/v6/time/{ths_code}/{date}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.10jqka.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()
        if text.startswith("quotebridge"):
            text = text[text.index("(") + 1: text.rindex(")")]
        raw = json.loads(text)
    except Exception as e:
        print(f"[data_fetch] 分时拉取失败 {code}: {e}", file=sys.stderr)
        return None

    obj = raw.get(ths_code) or (list(raw.values())[0] if raw else None)
    if not obj or not obj.get("data"):
        print(f"[data_fetch] 分时无数据 {code}", file=sys.stderr)
        return None

    pre_close  = float(obj.get("pre", 0) or 0)
    trade_date = obj.get("date", date)

    rows = []
    for seg in obj["data"].strip().split(";"):
        parts = seg.split(",")
        if len(parts) < 5:
            continue
        try:
            rows.append({
                "time":    parts[0],
                "price":   float(parts[1]),
                "cum_vol": float(parts[2]),
                "vwap":    float(parts[3]),
                "vol":     float(parts[4]),
            })
        except (ValueError, IndexError):
            continue

    return {"code": code, "date": trade_date, "pre_close": pre_close, "rows": rows}


def fetch_hk_intraday(code: str) -> Optional[dict]:
    """腾讯财经拉取港股日内分时（当日），返回格式与 fetch_intraday 对齐。
    API 返回 list[str]，每条 "HHMM price cum_vol amount"。
    """
    tc = _code_to_tencent_hk(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={tc}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer":    "https://gu.qq.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[data_fetch] 港股分时拉取失败 {code}: {e}", file=sys.stderr)
        return None

    info = data.get("data", {}).get(tc, {})
    if not info:
        print(f"[data_fetch] 港股分时无数据 {code}", file=sys.stderr)
        return None

    qt_fields = info.get("qt", {}).get(tc, [])
    pre_close = float(qt_fields[4]) if len(qt_fields) > 4 and qt_fields[4] else 0
    trade_date = info.get("data", {}).get("date", "")
    raw_list = info.get("data", {}).get("data", [])
    if not raw_list or not isinstance(raw_list, list):
        print(f"[data_fetch] 港股分时 data 为空 {code}", file=sys.stderr)
        return None

    rows = []
    for seg in raw_list:
        parts = seg.split(" ")
        if len(parts) < 2:
            continue
        try:
            rows.append({
                "time":  parts[0],
                "price": float(parts[1]),
            })
        except (ValueError, IndexError):
            continue

    return {"code": code, "date": trade_date, "pre_close": pre_close, "rows": rows}


def fetch_us_intraday(code: str) -> Optional[dict]:
    """腾讯财经拉取美股日内分时（当日），返回格式与 fetch_intraday 对齐。"""
    tc = _code_to_tencent_us(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={tc}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer":    "https://gu.qq.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[data_fetch] 美股分时拉取失败 {code}: {e}", file=sys.stderr)
        return None

    info = data.get("data", {}).get(tc, {})
    if not info:
        print(f"[data_fetch] 美股分时无数据 {code}", file=sys.stderr)
        return None

    qt_fields = info.get("qt", {}).get(tc, [])
    pre_close = float(qt_fields[4]) if len(qt_fields) > 4 and qt_fields[4] else 0
    trade_date = info.get("data", {}).get("date", "")
    raw_list = info.get("data", {}).get("data", [])
    if not raw_list or not isinstance(raw_list, list):
        print(f"[data_fetch] 美股分时 data 为空 {code}", file=sys.stderr)
        return None

    rows = []
    for seg in raw_list:
        parts = seg.split(" ")
        if len(parts) < 2:
            continue
        try:
            rows.append({
                "time":  parts[0],
                "price": float(parts[1]),
            })
        except (ValueError, IndexError):
            continue

    if len(rows) < 5:
        return None

    return {"code": code, "date": trade_date, "pre_close": pre_close, "rows": rows}


def get_intraday(code: str, date: str = "today") -> Optional[dict]:
    """
    分时数据获取，today 不缓存（每次拉最新），历史日期缓存。
    """
    if date == "today":
        return fetch_intraday(code, date)

    cache_key = f"{code}_{date}"
    _INTRADAY_CACHE.parent.mkdir(exist_ok=True)
    cache = {}
    if _INTRADAY_CACHE.exists():
        try:
            cache = json.loads(_INTRADAY_CACHE.read_text(encoding="utf-8"))
            # 清掉 7 天前的条目（key 格式 code_YYYYMMDD 或 code_YYYY-MM-DD）
            from datetime import datetime as _dt3, timedelta as _td3
            cutoff = (_dt3.now() - _td3(days=7)).strftime("%Y-%m-%d").replace("-", "")
            cache = {k: v for k, v in cache.items()
                     if k.split("_")[-1].replace("-", "") >= cutoff}
        except Exception:
            pass

    if cache_key in cache:
        return cache[cache_key]

    data = fetch_intraday(code, date)
    if data:
        cache[cache_key] = data
        _INTRADAY_CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return data


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="data_fetch CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_tech = sub.add_parser("tech", help="获取技术指标")
    p_tech.add_argument("code")
    p_tech.add_argument("--time", default=None)

    p_kline = sub.add_parser("kline", help="获取日K线")
    p_kline.add_argument("code")
    p_kline.add_argument("--days", type=int, default=60)
    p_kline.add_argument("--force", action="store_true")

    p_intraday = sub.add_parser("intraday", help="获取日内分时数据")
    p_intraday.add_argument("code")
    p_intraday.add_argument("date", nargs="?", default="today", help="today 或 YYYYMMDD")

    args = parser.parse_args()

    if args.cmd == "tech":
        print(json.dumps(TechnicalCalculator.calculate_all(args.code, args.time),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "kline":
        rows = get_kline(args.code, args.days, args.force)
        if rows:
            print(json.dumps({"code": args.code, "days": len(rows), "data": rows},
                             ensure_ascii=False))
        else:
            print(json.dumps({"code": args.code, "error": "无法获取数据"}))
            sys.exit(1)
    elif args.cmd == "intraday":
        data = get_intraday(args.code, args.date)
        if data:
            print(json.dumps(data, ensure_ascii=False))
        else:
            print(json.dumps({"code": args.code, "error": "无法获取分时数据"}))
            sys.exit(1)
    else:
        parser.print_help()
