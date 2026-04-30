"""
报告构建模块 - 三层架构中的 Report 层
- parse_tech_items  : 解析技术指标原始数据 → 结构化列表
- format_alert      : 格式化价格/告警文本（原 format_alert_report）
- format_anomaly    : 格式化异动文本（原 format_anomaly_report）
- format_tech_text  : 渲染技术指标汇总文本
- build_tech_card   : 构建飞书 schema 2.0 交互卡片
"""

import json
from datetime import datetime, timedelta
from typing import Optional

# ── 分隔线常量 ─────────────────────────────────────────────────────────────────
# monitor._push 依赖 SEP 以 "━" 开头来剔除分时图卡片右列的分隔线，换字符需同步改 _push
SEP = "━━━━━━━━━━━"

# ── 货币符号映射 ───────────────────────────────────────────────────────────────

_CURRENCY_SYM = {"CN": "¥", "HK": "HK$"}


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数（纯函数，无副作用）
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_bar_time(time_str: str) -> str:
    """把 K 线时间戳格式化为 5 分钟区间，如 '2026-04-05 19:20:00' → '19:20-19:25'。"""
    if not time_str:
        return ""
    try:
        dt = datetime.strptime(time_str[:16], "%Y-%m-%d %H:%M")
        end = dt + timedelta(minutes=5)
        return f"{dt.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    except ValueError:
        return time_str[:16]


def _f(val, d=2) -> str:
    """None 安全格式化"""
    return f"{val:.{d}f}" if val is not None else "N/A"


def _cur(stock: dict) -> str:
    """返回该股票对应的货币符号"""
    explicit = stock.get("currency", "")
    if explicit:
        return {"CNY": "¥", "HKD": "HK$", "USD": "$"}.get(explicit.upper(), explicit)
    return _CURRENCY_SYM.get(stock.get("market", "CN"), "¥")


# ══════════════════════════════════════════════════════════════════════════════
# 解析层：parse_tech_items
# ══════════════════════════════════════════════════════════════════════════════

def parse_tech_items(tech_items: list) -> tuple:
    """
    解析技术指标原始列表，返回 (parsed: list[dict], etf_names: list[str])。
    parsed 每项包含所有渲染所需的计算字段。
    """
    parsed    = []
    etf_names = []

    for item in tech_items:
        stock = item["stock"]
        data  = item["data"]
        code  = stock["code"]
        name  = stock.get("name", code)

        if data.get("_no_tech"):
            etf_names.append(f"{name}（{code}）")
            continue

        ma5, ma10, ma20         = data.get("MA5"), data.get("MA10"), data.get("MA20")
        diff, dea, bar          = data.get("MACD_DIFF"), data.get("MACD_DEA"), data.get("MACD_BAR")
        k, d, j                 = data.get("KDJ_K"), data.get("KDJ_D"), data.get("KDJ_J")
        rsi                     = data.get("RSI6")
        boll_u, boll_m, boll_l  = data.get("BOLL_UPPER"), data.get("BOLL_MID"), data.get("BOLL_LOWER")
        lb                      = data.get("LB5")

        signals = []

        # MA
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:   ma_st = "📈多头"; signals.append("✅ 均线多头排列")
            elif ma5 < ma10 < ma20: ma_st = "📉空头"; signals.append("❌ 均线空头排列")
            else:                   ma_st = "➡️缠绕";  signals.append("⚠️ 均线缠绕")
        else:
            ma_st = "❓"

        # MACD
        bar_dir = "↑" if bar and bar > 0 else "↓"
        bar_str = f"{_f(bar,4)}{bar_dir}" if bar is not None else "N/A"
        if diff is not None and dea is not None:
            axis = "轴上" if diff > 0 else "轴下"
            if diff > dea:
                macd_st = f"✅{axis}金叉"; signals.append("✅ MACD金叉" + ("且红柱扩张" if bar and bar > 0 else ""))
            else:
                macd_st = f"❌{axis}死叉"; signals.append("❌ MACD死叉" + ("且绿柱扩张" if bar and bar < 0 else ""))
        else:
            macd_st = "❓"

        # KDJ
        if j is not None:
            if j > 100:  kdj_st = "⚠️严重超买"; signals.append("⚠️ KDJ J>100 严重超买")
            elif j > 80: kdj_st = "🔶超买";     signals.append("⚠️ KDJ超买区")
            elif j < 0:  kdj_st = "🔷严重超卖"; signals.append("🔷 KDJ J<0 严重超卖")
            elif j < 20: kdj_st = "🔹超卖";     signals.append("🔷 KDJ超卖区")
            else:        kdj_st = "✅正常"
        else:
            kdj_st = "❓"

        # RSI
        if rsi is not None:
            if rsi > 70:   rsi_st = "🟠超买"; signals.append("⚠️ RSI超买")
            elif rsi < 30: rsi_st = "🟢超卖"; signals.append("🔷 RSI超卖")
            elif rsi > 50: rsi_st = "📈偏强"
            else:          rsi_st = "📉偏弱"
        else:
            rsi_st = "❓"

        # BOLL
        if boll_u and boll_l and boll_m:
            bw = (boll_u - boll_l) / boll_m * 100
            if bw < 5:    signals.append("🎯 布林带极度收窄，变盘在即")
            if ma5:
                if ma5 > boll_u:   boll_pos = "↑上轨突破"; signals.append("📈 突破BOLL上轨")
                elif ma5 < boll_l: boll_pos = "↓下轨跌破"; signals.append("📉 跌破BOLL下轨")
                elif ma5 > boll_m: boll_pos = "中上"
                else:              boll_pos = "中下"
            else:
                boll_pos = "中"
        else:
            bw = None; boll_pos = "❓"

        # 量比
        if lb is not None:
            if lb < 0.8:   vol_st = "❄️缩量";   signals.append(f"❄️ 量比{_f(lb)}明显缩量")
            elif lb > 2.0: vol_st = "🔥放量";   signals.append(f"🔥 量比{_f(lb)}显著放量")
            elif lb > 1.5: vol_st = "📈温和放量"
            else:          vol_st = "💨平量"
        else:
            vol_st = "❓"

        # 综合判断
        bull_n = sum(1 for s in signals if s.startswith("✅"))
        bear_n = sum(1 for s in signals if s.startswith("❌"))
        warn_n = sum(1 for s in signals if s.startswith(("⚠️", "🔷")))
        if bull_n >= 2 and bear_n == 0:                    overall = "🟢看多"
        elif bull_n >= 1 and bear_n == 0 and warn_n == 0:  overall = "🟡偏多"
        elif bear_n >= 2 and bull_n == 0:                  overall = "🔴看空"
        elif bear_n >= 1 and bull_n == 0:                  overall = "🟠偏空"
        else:                                              overall = "⚪观望"

        # 持仓盈亏
        hold_qty  = stock.get("hold_quantity") or 0
        hold_cost = stock.get("hold_cost") or 0
        pnl_str   = ""
        if hold_qty and hold_cost and ma5:
            profit  = (ma5 - hold_cost) * hold_qty
            pct     = (ma5 - hold_cost) / hold_cost * 100
            p_ico   = "🟢" if profit >= 0 else "🔴"
            sym     = _cur(stock)
            pnl_str = f"{p_ico}{sym}{profit:+.0f}（{pct:+.2f}%）"

        key_signals = [s for s in signals if not s.startswith("⚠️ 均线缠绕")][:3]

        price  = item.get("price")
        change = item.get("change")

        parsed.append({
            "name": name, "code": code, "stock": stock,
            "price": price, "change": change,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma_st": ma_st,
            "diff": diff, "dea": dea, "bar_str": bar_str, "macd_st": macd_st,
            "k": k, "d": d, "j": j, "kdj_st": kdj_st,
            "rsi": rsi, "rsi_st": rsi_st,
            "boll_u": boll_u, "boll_m": boll_m, "boll_l": boll_l,
            "boll_pos": boll_pos, "bw": bw,
            "lb": lb, "vol_st": vol_st,
            "overall": overall,
            "pnl_str": pnl_str, "hold_qty": hold_qty, "hold_cost": hold_cost,
            "key_signals": key_signals,
            "market_closed": data.get("market_closed", False),
            "data_time": _fmt_bar_time(str(data.get("time", ""))),
        })

    return parsed, etf_names


# ══════════════════════════════════════════════════════════════════════════════
# 文本格式化层
# ══════════════════════════════════════════════════════════════════════════════

def format_alert(desc: str, stock: dict, tick: dict, disclaimer: str,
                 title: str = "🔔价格提醒",
                 now_str: str = "") -> str:
    """
    格式化价格/告警文本。
    now_str: 格式为 HH:MM，由调用方传入（避免 report.py 依赖 _now()）。
    """
    code   = stock["code"]
    name   = stock.get("name", code)
    price  = tick["price"]
    change = tick.get("change_ratio_acc")
    change_str = f"{change:+.2f}%" if change is not None else "N/A"

    # 首行 "·" 被 monitor._push 用来拆成 "### 告警类型 / **股票 代码**" 两行，title 里塞 "·" 会被错切
    lines = [
        f"{title}·{name} {code}",
        SEP,
        f"股价：{price:.2f}（{change_str}）",
        f"触发：{desc}",
    ]

    qty  = stock.get("hold_quantity") or 0
    cost = stock.get("hold_cost") or 0
    if qty > 0 and cost > 0:
        profit = (price - cost) * qty
        pct    = (price - cost) / cost * 100
        p_ico  = "🟢" if profit >= 0 else "🔴"
        sym    = _cur(stock)
        lines.append(f"持仓：{p_ico}{sym}{profit:+.0f}（{pct:+.2f}%）")

    time_prefix = f"{now_str}  " if now_str else ""
    lines += [SEP, f"{time_prefix}{disclaimer}"]
    return "\n".join(lines)


def format_anomaly(stock: dict, tick: dict, anomaly: dict, disclaimer: str,
                   now_str: str = "") -> str:
    """
    格式化异动文本。
    now_str: 格式为 HH:MM，由调用方传入（避免 report.py 依赖 _now()）。
    """
    code   = stock["code"]
    name   = stock.get("name", code)
    price  = tick["price"]
    change = tick.get("change_ratio_acc")
    vr     = tick.get("volume_ratio") or 0
    bv, sv = tick.get("buy_volume", 0), tick.get("sell_volume", 0)

    # 标题：异动类型 + 股票
    type_parts = []
    if anomaly.get("volume"):    type_parts.append("量能")
    if anomaly.get("buy_sell"):  type_parts.append("多空")
    if anomaly.get("technical"): type_parts.append("技术")
    type_str = (type_parts[0] + "异动") if len(type_parts) == 1 else "多技术异动"
    n     = len(anomaly["details"])
    g_ico = "🚨" if n >= 3 else "⚠️" if n >= 2 else "📢"

    change_str = f"{change:+.2f}%" if change is not None else "N/A"

    # 同 format_alert：首行 "·" 被 monitor._push 用于拆分告警类型和股票信息
    lines = [
        f"{g_ico}{type_str}·{name} {code}",
        SEP,
        f"股价：{price:.2f}（{change_str}）",
    ]

    # 量比 / 涨跌量行（仅量能或多空异动时）
    if anomaly.get("volume") or anomaly.get("buy_sell"):
        vr_parts = []
        if vr > 0:  vr_parts.append(f"量比：{vr:.2f}")
        if sv > 0:  vr_parts.append(f"涨量/跌量：{bv/sv:.1f}x")
        if vr_parts:
            lines.append("  ".join(vr_parts))

    # 技术信号行（过滤掉量能/多空的冗余描述）
    tech_labels = [
        d
        for d in anomaly["details"]
        if "：" in d and not d.startswith(("量能异动", "多空异动"))
    ]
    if tech_labels:
        lines.append(f"信号：{'  '.join(tech_labels)}")

    qty  = stock.get("hold_quantity") or 0
    cost = stock.get("hold_cost") or 0
    if qty > 0 and cost > 0:
        profit = (price - cost) * qty
        pct    = (price - cost) / cost * 100
        p_ico  = "🟢" if profit >= 0 else "🔴"
        sym    = _cur(stock)
        lines.append(f"持仓：{p_ico}{sym}{profit:+.0f}（{pct:+.2f}%）")

    time_prefix = f"{now_str}  " if now_str else ""
    lines += [SEP, f"{time_prefix}{disclaimer}"]
    return "\n".join(lines)


def format_tech_text(parsed: list, etf_names: list, title: str, disclaimer: str) -> str:
    """
    渲染技术指标汇总文本（markdown 表格格式）。
    parsed 和 etf_names 来自 parse_tech_items()。
    title 由调用方构造（已含时间戳）。
    """
    out = title + "\n\n"

    if len(parsed) == 1:
        # ── 单股：竖表 ────────────────────────────────────────
        p          = parsed[0]
        closed_tag = "  已收盘" if p["market_closed"] else ""
        data_time_str = f"  数据：{p['data_time']}" if p.get("data_time") else ""
        price_str = f"  {_f(p['price'])}（{p['change']:+.2f}%）" if p.get("price") and p.get("change") is not None else (f"  {_f(p['price'])}" if p.get("price") else "")
        out += f"### {p['name']}（{p['code']}）{p['overall']}{price_str}{closed_tag}{data_time_str}\n\n"
        out += "| 指标 | 数值 | 状态 |\n| --- | --- | --- |\n"

        out += f"| MA5/10/20 | {_f(p['ma5'])}/{_f(p['ma10'])}/{_f(p['ma20'])} | {p['ma_st']} |\n"
        out += f"| MACD D/E/B | {_f(p['diff'],4)}/{_f(p['dea'],4)}/{p['bar_str']} | {p['macd_st']} |\n"
        out += f"| KDJ K/D/J | {_f(p['k'],1)}/{_f(p['d'],1)}/{_f(p['j'],1)} | {p['kdj_st']} |\n"
        out += f"| RSI6 | {_f(p['rsi'],1)} | {p['rsi_st']} |\n"
        if p["boll_u"]:
            bw_str = f"{p['bw']:.1f}%" if p["bw"] is not None else "N/A"
            out += (f"| BOLL | 上{_f(p['boll_u'])} 中{_f(p['boll_m'])} 下{_f(p['boll_l'])} "
                    f"| {p['boll_pos']} · 带宽{bw_str} |\n")
        out += f"| 量比 LB5 | {_f(p['lb'])} | {p['vol_st']} |\n"

        if p["key_signals"]:
            out += "\n🔑 " + "  ".join(p["key_signals"]) + "\n"
        if p["pnl_str"]:
            sym = _cur(p["stock"])
            out += f"💰 {p['pnl_str']}  {p['hold_qty']}股 @ {sym}{p['hold_cost']:.2f}\n"

    elif parsed:
        # ── 多股：横向汇总表 ──────────────────────────────────
        has_pnl   = any(p["pnl_str"] for p in parsed)
        has_price = any(p.get("price") for p in parsed)
        header = "| 股票 | 价格 | 综合 | MA | MACD | KDJ-J | RSI | 量比 |" if has_price else "| 股票 | 综合 | MA | MACD | KDJ-J | RSI | 量比 |"
        if has_pnl: header += " 持仓 |"
        out += header + "\n"
        out += "| --- " * (header.count("|") - 1) + "|\n"

        for p in parsed:
            j_str   = (f"{_f(p['j'],0)}{p['kdj_st'].split()[0]}"
                       if p["j"] is not None else "❓")
            rsi_str = _f(p["rsi"], 1) if p["rsi"] is not None else "❓"
            lb_str  = (f"{_f(p['lb'],1)}{p['vol_st'].split()[0]}"
                       if p["lb"] is not None else "❓")
            ma_str  = (f"{p['ma_st']} {_f(p['ma5'],1)}"
                       if p["ma5"] is not None else p["ma_st"])
            closed  = " 已收" if p["market_closed"] else ""
            price_col = ""
            if has_price:
                if p.get("price") and p.get("change") is not None:
                    price_col = f" {_f(p['price'])}（{p['change']:+.2f}%） |"
                else:
                    price_col = " — |"
            row = f"| {p['name']} {p['code']}{closed} |{price_col} {p['overall']} | {ma_str} | {p['macd_st']} | {j_str} | {rsi_str} | {lb_str} |"
            if has_pnl:
                row += f" {p['pnl_str'] or '—'} |"
            out += row + "\n"

        # 数据时间脚注
        times = [(p["name"], p["data_time"]) for p in parsed if p.get("data_time")]
        if times:
            unique_times = set(t for _, t in times)
            if len(unique_times) == 1:
                out += f"\n🕐 数据时间：{unique_times.pop()}\n"
            else:
                out += "\n🕐 数据时间：" + "  ".join(f"{n} {t}" for n, t in times) + "\n"

    if etf_names:
        out += "\n⚪ ETF/指数（无技术指标）：" + "、".join(etf_names) + "\n"

    out += f"\n💡 如需详细研判，请告知生成技术分析报告。\n{disclaimer}\n"
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 卡片构建层：build_alert_card / build_anomaly_card / build_tech_card
# ══════════════════════════════════════════════════════════════════════════════

def _header_color(title: str) -> str:
    if title.startswith(("🔴", "🚨")):  return "red"
    if title.startswith("🟢"):          return "green"
    if title.startswith(("⚠️", "📢")): return "orange"
    return "blue"


def build_alert_card(title: str, desc: str, stock: dict, tick: dict,
                     disclaimer: str, now_str: str = "") -> dict:
    """构建告警飞书卡片（涨跌/价格/止损/止盈/追踪止盈）。"""
    code   = stock["code"]
    name   = stock.get("name", code)
    price  = tick["price"]
    change = tick.get("change_ratio_acc")
    chg_str = f"{change:+.2f}%" if change is not None else "N/A"

    lines = [f"**股价：** {price:.2f}（{chg_str}）", f"**触发：** {desc}"]

    qty  = stock.get("hold_quantity") or 0
    cost = stock.get("hold_cost") or 0
    if qty > 0 and cost > 0:
        profit = (price - cost) * qty
        pct    = (price - cost) / cost * 100
        sym    = _cur(stock)
        ico    = "🟢" if profit >= 0 else "🔴"
        lines.append(f"**持仓：** {ico}{sym}{profit:+.0f}（{pct:+.2f}%）")

    time_line = f"{now_str}  " if now_str else ""
    lines.append(f"{time_line}{disclaimer}")

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title":    {"tag": "plain_text", "content": f"{title}·{name} {code}"},
            "template": _header_color(title),
        },
        "body": {
            "elements": [{"tag": "markdown", "content": "\n".join(lines)}]
        },
    }


def build_anomaly_card(stock: dict, tick: dict, anomaly: dict,
                       disclaimer: str, now_str: str = "") -> dict:
    """构建异动飞书卡片。"""
    code   = stock["code"]
    name   = stock.get("name", code)
    price  = tick["price"]
    change = tick.get("change_ratio_acc")
    vr     = tick.get("volume_ratio") or 0
    bv, sv = tick.get("buy_volume", 0), tick.get("sell_volume", 0)

    type_parts = []
    if anomaly.get("volume"):    type_parts.append("量能")
    if anomaly.get("buy_sell"):  type_parts.append("多空")
    if anomaly.get("technical"): type_parts.append("技术")
    type_str = (type_parts[0] + "异动") if len(type_parts) == 1 else "多技术异动"
    n     = len(anomaly["details"])
    g_ico = "🚨" if n >= 3 else "⚠️" if n >= 2 else "📢"

    chg_str = f"{change:+.2f}%" if change is not None else "N/A"
    lines   = [f"**股价：** {price:.2f}（{chg_str}）"]

    if anomaly.get("volume") or anomaly.get("buy_sell"):
        parts = []
        if vr > 0:  parts.append(f"量比：{vr:.2f}")
        if sv > 0:  parts.append(f"涨量/跌量：{bv/sv:.1f}x")
        if parts:   lines.append("  ".join(parts))

    tech_labels = [
        d
        for d in anomaly["details"]
        if "：" in d and not d.startswith(("量能异动", "多空异动"))
    ]
    if tech_labels:
        lines.append(f"**信号：** {'  '.join(tech_labels)}")

    qty  = stock.get("hold_quantity") or 0
    cost = stock.get("hold_cost") or 0
    if qty > 0 and cost > 0:
        profit = (price - cost) * qty
        pct    = (price - cost) / cost * 100
        sym    = _cur(stock)
        ico    = "🟢" if profit >= 0 else "🔴"
        lines.append(f"**持仓：** {ico}{sym}{profit:+.0f}（{pct:+.2f}%）")

    time_line = f"{now_str}  " if now_str else ""
    lines.append(f"{time_line}{disclaimer}")

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title":    {"tag": "plain_text", "content": f"{g_ico}{type_str}·{name} {code}"},
            "template": "orange",
        },
        "body": {
            "elements": [{"tag": "markdown", "content": "\n".join(lines)}]
        },
    }




def build_tech_card(parsed: list, etf_names: list, title: str, disclaimer: str) -> dict:
    """
    构建飞书 schema 2.0 交互卡片。
    - 多股：table 元素（横向汇总）
    - 单股：div/column_set（竖向 key-value）
    """
    is_startup = title.startswith("🚀")
    header_template = "green" if is_startup else "blue"

    elements = []

    if len(parsed) == 1:
        # ── 单股：table 卡片 ──────────────────────────────────
        p          = parsed[0]
        closed_tag = "  已收盘" if p["market_closed"] else ""
        price_str = f"  {_f(p['price'])}（{p['change']:+.2f}%）" if p.get("price") and p.get("change") is not None else (f"  {_f(p['price'])}" if p.get("price") else "")
        stock_title = f"{p['name']}（{p['code']}）{p['overall']}{price_str}{closed_tag}"

        data_time_str = f"  数据：{p['data_time']}" if p.get("data_time") else ""
        block = f"**{stock_title}{data_time_str}**\n\n"
        # 构建指标 markdown 表格（覆盖下面的 block 赋值）
        md_rows = [
            f"| MA5/10/20 | {_f(p['ma5'])}/{_f(p['ma10'])}/{_f(p['ma20'])} | {p['ma_st']} |",
            f"| MACD D/E/B | {_f(p['diff'],4)}/{_f(p['dea'],4)}/{p['bar_str']} | {p['macd_st']} |",
            f"| KDJ K/D/J | {_f(p['k'],1)}/{_f(p['d'],1)}/{_f(p['j'],1)} | {p['kdj_st']} |",
            f"| RSI6 | {_f(p['rsi'],1)} | {p['rsi_st']} |",
        ]
        if p["boll_u"]:
            bw_str = f"{p['bw']:.1f}%" if p["bw"] is not None else "N/A"
            md_rows.append(f"| BOLL | 上{_f(p['boll_u'])} 中{_f(p['boll_m'])} 下{_f(p['boll_l'])} | {p['boll_pos']} · 带宽{bw_str} |")
        md_rows.append(f"| 量比 LB5 | {_f(p['lb'])} | {p['vol_st']} |")

        block += "| 指标 | 数值 | 状态 |\n| --- | --- | --- |\n" + "\n".join(md_rows)
        if p["key_signals"]:
            block += "\n\n🔑 " + "  ".join(p["key_signals"])
        if p["pnl_str"]:
            sym = _cur(p["stock"])
            block += f"\n💰 {p['pnl_str']}  {p['hold_qty']}股 @ {sym}{p['hold_cost']:.2f}"
        elements.append({"tag": "markdown", "content": block})

    elif parsed:
        # ── 多股：markdown 表格 ────────────────────────────────
        has_pnl   = any(p["pnl_str"] for p in parsed)
        has_price = any(p.get("price") for p in parsed)
        header = "| 股票 | 价格 | 综合 | MA | MACD | KDJ-J | RSI | 量比 |" if has_price else "| 股票 | 综合 | MA | MACD | KDJ-J | RSI | 量比 |"
        sep    = "| --- " * (header.count("|") - 1) + "|\n"
        if has_pnl:
            header += " 持仓 |"

        md_rows = []
        for p in parsed:
            j_str   = f"{_f(p['j'],0)}{p['kdj_st'].split()[0]}" if p["j"] is not None else "❓"
            rsi_str = _f(p["rsi"], 1) if p["rsi"] is not None else "❓"
            lb_str  = f"{_f(p['lb'],1)}{p['vol_st'].split()[0]}" if p["lb"] is not None else "❓"
            ma_str  = f"{p['ma_st']} {_f(p['ma5'],1)}" if p["ma5"] is not None else p["ma_st"]
            closed  = " 已收" if p["market_closed"] else ""
            price_col = ""
            if has_price:
                if p.get("price") and p.get("change") is not None:
                    price_col = f" {_f(p['price'])}（{p['change']:+.2f}%） |"
                else:
                    price_col = " — |"
            row = f"| {p['name']} {p['code']}{closed} |{price_col} {p['overall']} | {ma_str} | {p['macd_st']} | {j_str} | {rsi_str} | {lb_str} |"
            if has_pnl:
                row += f" {p['pnl_str'] or '—'} |"
            md_rows.append(row)

        table_md = header + "\n" + sep + "\n".join(md_rows)
        # 数据时间脚注
        times = [(p["name"], p["data_time"]) for p in parsed if p.get("data_time")]
        if times:
            unique_times = set(t for _, t in times)
            time_note = (f"🕐 数据时间：{unique_times.pop()}" if len(unique_times) == 1
                         else "🕐 数据时间：" + "  ".join(f"{n} {t}" for n, t in times))
            table_md += "\n\n" + time_note
        elements.append({"tag": "markdown", "content": table_md})

    # ETF 注释行
    if etf_names:
        elements.append({
            "tag":     "markdown",
            "content": "⚪ ETF/指数（无技术指标）：" + "、".join(etf_names),
        })

    # 页脚
    elements.append({
        "tag":     "markdown",
        "content": "💡 如需详细研判，请告知生成技术分析报告。",
    })
    elements.append({
        "tag":     "markdown",
        "content": disclaimer,
    })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title":    {"tag": "plain_text", "content": title},
            "template": header_template,
        },
        "body": {
            "elements": elements,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 飞书分时图交互卡片（schema 2.0 VChart）
# 源自 monitor_v2.py，按「主图 + 可选副图（MACD/KDJ/RSI）+ 右侧分析文」布局
# ══════════════════════════════════════════════════════════════════════════════

def _aggregate_5min(points: list) -> list:
    """把 1 分钟 intraday_points 聚合为每 5 分钟取收盘价的序列。"""
    buckets = {}
    for p in points:
        raw = str(p["label"]).zfill(4)
        h, m = int(raw[:2]), int(raw[2:])
        m5 = m - (m % 5)
        key = f"{h:02d}{m5:02d}"
        buckets[key] = p
    result = []
    for key in sorted(buckets.keys()):
        bp = buckets[key]
        result.append({
            "label": key,
            "close": float(bp["close"]),
            "x": bp.get("x", key),
        })
    return result


def _ema(data: list, period: int) -> list:
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


def _calc_kdj(closes: list, n: int = 9) -> tuple:
    k_arr, d_arr, j_arr = [], [], []
    for i in range(len(closes)):
        start = max(0, i - n + 1)
        hn = max(closes[start:i+1])
        ln = min(closes[start:i+1])
        rsv = ((closes[i] - ln) / (hn - ln) * 100) if hn != ln else 50
        if i == 0:
            k, d = 50, 50
        else:
            k = 2/3 * k_arr[-1] + 1/3 * rsv
            d = 2/3 * d_arr[-1] + 1/3 * k
        j = 3 * k - 2 * d
        k_arr.append(round(k, 2))
        d_arr.append(round(d, 2))
        j_arr.append(round(j, 2))
    return k_arr, d_arr, j_arr


def _calc_rsi(closes: list, period: int = 6) -> list:
    gains, losses = [], []
    rsi = [50.0]
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
        if i < period:
            rsi.append(50.0)
        elif i == period:
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
            rs = avg_g / avg_l if avg_l > 0 else 100
            rsi.append(round(100 - 100 / (1 + rs), 2))
        else:
            avg_g = (gains[-2] * (period - 1) + gains[-1]) / period if len(gains) >= 2 else gains[-1]
            avg_l = (losses[-2] * (period - 1) + losses[-1]) / period if len(losses) >= 2 else losses[-1]
            rs = avg_g / avg_l if avg_l > 0 else 100
            rsi.append(round(100 - 100 / (1 + rs), 2))
    return rsi


def _build_sub_chart(spec: dict, height: str = "70px") -> dict:
    return {"tag": "chart", "height": height, "preview": False, "chart_spec": spec}


def build_macd_sub_chart(points: list) -> tuple:
    """返回 (label_element, chart_element)，使用 5 分钟聚合数据。"""
    points = _aggregate_5min(points)
    closes = [float(p["close"]) for p in points]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    diff_arr = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    dea_arr = _ema(diff_arr, 9)
    macd_data = []
    for i, p in enumerate(points):
        bar = 2 * (diff_arr[i] - dea_arr[i])
        macd_data.append({"x": p.get("x", p["label"]), "diff": round(diff_arr[i], 3), "dea": round(dea_arr[i], 3), "bar": round(bar, 3), "bar_color": "#C5221F" if bar >= 0 else "#0B8043"})
    bv = [abs(d["bar"]) for d in macd_data]
    dv = [d["diff"] for d in macd_data] + [d["dea"] for d in macd_data]
    ym = max(max(bv), max(abs(v) for v in dv)) * 1.2
    label = {"tag": "markdown", "content": "**MACD** <font color='orange'>DIFF</font> · <font color='blue'>DEA</font> · BAR"}
    chart = _build_sub_chart({
        "type": "common", "background": "#FFFFFF",
        "padding": {"top": 4, "right": 8, "bottom": 4, "left": 28},
        "data": [{"id": "ml", "values": macd_data}, {"id": "mb", "values": macd_data}],
        "series": [
            {"type": "bar", "dataId": "mb", "xField": "x", "yField": "bar", "bar": {"style": {"fill": {"field": "bar_color"}}}},
            {"type": "line", "dataId": "ml", "xField": "x", "yField": "diff", "line": {"style": {"stroke": "#FF6600", "lineWidth": 1}}, "point": {"style": {"size": 0}}},
            {"type": "line", "dataId": "ml", "xField": "x", "yField": "dea", "line": {"style": {"stroke": "#0080FF", "lineWidth": 1}}, "point": {"style": {"size": 0}}},
        ],
        "axes": [
            {"orient": "left", "visible": True, "type": "linear", "min": -ym, "max": ym, "nice": False, "zero": True, "tickCount": 3, "tick": {"visible": False}, "domainLine": {"visible": False}, "grid": {"visible": False}, "label": {"visible": True, "style": {"fill": "#80868B", "fontSize": 9}}},
            {"orient": "bottom", "visible": False},
        ],
        "legends": {"visible": False}, "tooltip": {"visible": False}, "title": {"visible": False},
    })
    return label, chart


def build_kdj_sub_chart(points: list) -> tuple:
    points = _aggregate_5min(points)
    closes = [float(p["close"]) for p in points]
    k_arr, d_arr, j_arr = _calc_kdj(closes)
    kdj_data = [{"x": points[i].get("x", points[i]["label"]), "K": k_arr[i], "D": d_arr[i], "J": j_arr[i]} for i in range(len(points))]
    label = {"tag": "markdown", "content": "**KDJ** <font color='orange'>K</font> · <font color='blue'>D</font> · <font color='purple'>J</font>"}
    chart = _build_sub_chart({
        "type": "common", "background": "#FFFFFF",
        "padding": {"top": 4, "right": 8, "bottom": 4, "left": 28},
        "data": [{"id": "kdj", "values": kdj_data}],
        "series": [
            {"type": "line", "dataId": "kdj", "xField": "x", "yField": "K", "line": {"style": {"stroke": "#FF6600", "lineWidth": 1}}, "point": {"style": {"size": 0}}},
            {"type": "line", "dataId": "kdj", "xField": "x", "yField": "D", "line": {"style": {"stroke": "#0080FF", "lineWidth": 1}}, "point": {"style": {"size": 0}}},
            {"type": "line", "dataId": "kdj", "xField": "x", "yField": "J", "line": {"style": {"stroke": "#9B59B6", "lineWidth": 1}}, "point": {"style": {"size": 0}}},
        ],
        "axes": [
            {"orient": "left", "visible": True, "type": "linear", "min": 0, "max": 100, "nice": False, "zero": False, "tickCount": 3, "tick": {"visible": False}, "domainLine": {"visible": False}, "grid": {"visible": False}, "label": {"visible": True, "style": {"fill": "#80868B", "fontSize": 9}}},
            {"orient": "bottom", "visible": False},
        ],
        "markLine": [
            {"y": 80, "line": {"style": {"stroke": "rgba(197,34,31,0.3)", "lineWidth": 1, "lineDash": [3, 3]}}, "label": {"visible": False}, "startSymbol": {"visible": False}, "endSymbol": {"visible": False}},
            {"y": 20, "line": {"style": {"stroke": "rgba(11,128,67,0.3)", "lineWidth": 1, "lineDash": [3, 3]}}, "label": {"visible": False}, "startSymbol": {"visible": False}, "endSymbol": {"visible": False}},
        ],
        "legends": {"visible": False}, "tooltip": {"visible": False}, "title": {"visible": False},
    })
    return label, chart


def build_rsi_sub_chart(points: list) -> tuple:
    points = _aggregate_5min(points)
    closes = [float(p["close"]) for p in points]
    rsi_arr = _calc_rsi(closes, 6)
    rsi_data = [{"x": points[i].get("x", points[i]["label"]), "rsi": rsi_arr[i]} for i in range(len(points))]
    label = {"tag": "markdown", "content": "**RSI6**"}
    chart = _build_sub_chart({
        "type": "line", "background": "#FFFFFF",
        "padding": {"top": 4, "right": 8, "bottom": 4, "left": 28},
        "data": [{"id": "rsi", "values": rsi_data}],
        "xField": "x", "yField": "rsi",
        "line": {"style": {"stroke": "#9B59B6", "lineWidth": 1.2}},
        "point": {"style": {"size": 0}},
        "axes": [
            {"orient": "left", "visible": True, "type": "linear", "min": 0, "max": 100, "nice": False, "zero": False, "tickCount": 3, "tick": {"visible": False}, "domainLine": {"visible": False}, "grid": {"visible": False}, "label": {"visible": True, "style": {"fill": "#80868B", "fontSize": 9}}},
            {"orient": "bottom", "visible": False},
        ],
        "markLine": [
            {"y": 70, "line": {"style": {"stroke": "rgba(197,34,31,0.3)", "lineWidth": 1, "lineDash": [3, 3]}}, "label": {"visible": False}, "startSymbol": {"visible": False}, "endSymbol": {"visible": False}},
            {"y": 30, "line": {"style": {"stroke": "rgba(11,128,67,0.3)", "lineWidth": 1, "lineDash": [3, 3]}}, "label": {"visible": False}, "startSymbol": {"visible": False}, "endSymbol": {"visible": False}},
        ],
        "legends": {"visible": False}, "tooltip": {"visible": False}, "title": {"visible": False},
        "label": {"visible": False},
    })
    return label, chart


# ── 非关键时间 x 值的隐形编码 ──────────────────────────────────────────────────
# 用 4 个零宽 unicode 字符做 base-4 编码，给每个非关键时间分钟点一个「唯一且隐形」的 x 值。
# 原实现 `"\u200b" * idx` 长度随点序线性增长，总字节 O(N²)，332 点（HK 全天）可达 55KB，
# 叠加其他字段后整张卡 ~75KB 会触发 Feishu error 230025（content reaches limit）。
# base-4 编码后每个点最多 log₄(N) 字符：332 点最多 5 字符，总量 ~1.7KB（~97% 降幅）。
# 飞书 VChart formatter 只支持 `{field}` 简单替换、不支持条件表达式，故无法用白名单直接
# 隐藏非关键时间标签，只能继续走"让非关键点的 x 本身就是隐形字符串"的思路。
_ZWS_ALPHABET = ("\u200b", "\u200c", "\u200d", "\ufeff")


def _encode_invisible(n: int) -> str:
    """把正整数 n 编码成由 4 种零宽字符组成的唯一隐形串（base-4，最低位在前）。"""
    if n <= 0:
        return _ZWS_ALPHABET[0]
    out = []
    while n > 0:
        out.append(_ZWS_ALPHABET[n % 4])
        n //= 4
    return "".join(out)


def pick_sub_chart(anomaly: Optional[dict], points: list) -> Optional[tuple]:
    """根据异动 details 选择对应副图；取不到就返回 None。"""
    if not anomaly or not points:
        return None
    details_text = " ".join(anomaly.get("details", []))
    if "MACD" in details_text:
        return build_macd_sub_chart(points)
    if "KDJ" in details_text:
        return build_kdj_sub_chart(points)
    if "RSI" in details_text:
        return build_rsi_sub_chart(points)
    return None


def build_monitor_intraday_card(
    *,
    stock: dict,
    tick: dict,
    analysis_text: str,
    sub_chart: Optional[tuple] = None,
    header: Optional[dict] = None,
    top_title: Optional[str] = None,
    summary: Optional[str] = None,
    footer: Optional[str] = None,
    mark_prices: Optional[list] = None,
) -> dict:
    """分时图主卡：[可选横跨标题] + 左 2/3 分时图 + 可选副图，右 1/3 分析文，[可选横跨脚注]。
    header : schema 2.0 header 块（彩色色条，带预览抓取）；None 即不推 header。
    top_title : markdown 文本，会作为 body 首个元素横跨整个宽度，同时兼做消息列表预览。
    summary : config.summary.content — 仅控制消息列表预览文本，不影响卡片渲染（schema 2.0）。
    footer : markdown 文本，作为 body 最后元素横跨整宽，贴在分时图下方（如时间戳 + 免责声明）。
    """
    points = tick.get("intraday_points") or []
    if not points:
        raise ValueError("missing intraday points")

    # 横轴可见标签按市场交易时段：
    #   A股：09:30 开 / 11:30 午休 / 13:00 续 / 15:00 收
    #   HK：腾讯分时里 "1200" 是上午竞价、"1300" 是下午首条，两者相邻太近会被 autoHide，
    #       "1600" 没有（收盘是 "1559"，另有 "1608" 竞价点）。
    #       所以用 09:30 / 11:00（上午中段）/ 14:00（下午中段）/ 15:59 四个分散点，
    #       但 "1559" 在轴上显示成更自然的 "16:00"
    #   US：单场 09:30 / 12:00 / 14:00 / 15:59（同样 "1559" 显示为 "16:00"）
    _market = stock.get("market", "CN")
    display_override: dict = {}
    if _market == "HK":
        key_times = {"0930", "1100", "1400", "1559"}
        display_override = {"1559": "16:00"}
    elif _market == "US":
        # 美股 key_times 用北京时间（ET+12 EDT / ET+13 EST）
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as _dt, timezone
            _et_keys = [930, 1200, 1400, 1559]
            _now_utc = _dt.now(timezone.utc)
            _et_off = _now_utc.astimezone(ZoneInfo("America/New_York")).utcoffset().total_seconds() / 3600
            _bj_off = 8
            _diff_h = _bj_off - _et_off  # EDT: 12h, EST: 13h
            _bj_keys = []
            _display = {}
            for ek in _et_keys:
                _m = (ek // 100) * 60 + (ek % 100) + int(_diff_h * 60)
                _m = _m % 1440
                _bk = f"{_m // 60:02d}{_m % 60:02d}"
                _bj_keys.append(_bk)
                if ek == 1559:
                    _disp_m = (1600 // 100) * 60 + int(_diff_h * 60)
                    _disp_m = _disp_m % 1440
                    _display[_bk] = f"{_disp_m // 60:02d}:{_disp_m % 60:02d}"
            key_times = set(_bj_keys)
            display_override = _display
        except Exception:
            key_times = {"2130", "0000", "0200", "0400"}
            display_override = {"0400": "04:00"}
    else:
        key_times = {"0930", "1130", "1300", "1500"}

    zws_idx = 0
    for p in points:
        raw = str(p["label"]).zfill(4)
        p["time"] = f"{raw[:2]}:{raw[2:]}"
        if raw in key_times:
            p["x"] = display_override.get(raw, p["time"])
        else:
            zws_idx += 1
            p["x"] = _encode_invisible(zws_idx)

    values = [float(p["close"]) for p in points]
    # mark_prices 也纳入 Y 轴范围计算，确保标记线不被截断
    _extra_ys = [mp["price"] for mp in (mark_prices or []) if mp.get("price")]
    all_ys = values + _extra_ys
    low, high = min(all_ys), max(all_ys)
    span = high - low
    mid = (high + low) / 2
    min_pad = mid * 0.002
    pad = max(span * 0.1, min_pad)
    axis_min = round(max(0.0, low - pad), 4)
    axis_max = round(high + pad, 4)

    price = float(tick["price"])
    change = float(tick.get("change_ratio_acc", 0))
    open_price = float(points[0]["close"])
    pre_close  = float(tick.get("pre_close") or open_price)
    price_diff = price - pre_close
    title = stock.get("name") or stock["code"]
    currency = tick.get("currency") or stock.get("currency", "")
    price_symbol = {"USD": "$", "HKD": "HK$", "CNY": "¥"}.get(str(currency).upper(), _cur(stock))
    market = stock.get("market", "CN")

    is_up = price >= open_price
    if market == "CN":
        line_color = "#C5221F" if is_up else "#0B8043"
        area_color_top = "rgba(197,34,31,0.18)" if is_up else "rgba(11,128,67,0.18)"
        area_color_bot = "rgba(197,34,31,0.02)" if is_up else "rgba(11,128,67,0.02)"
        change_color = "red" if is_up else "green"
    else:
        line_color = "#00C805" if is_up else "#F04438"
        area_color_top = "rgba(0,200,5,0.18)" if is_up else "rgba(240,68,56,0.18)"
        area_color_bot = "rgba(0,200,5,0.02)" if is_up else "rgba(240,68,56,0.02)"
        change_color = "#00C805" if is_up else "#F04438"

    title_block = f"## {title} {price_symbol}{price:.2f}\n### <font color='{change_color}'>{change:+.2f}%  {price_diff:+.2f}</font>"

    chart_element = {
        "tag": "chart",
        "height": "150px",
        "preview": False,
        "chart_spec": {
            "type": "area",
            "background": "#FFFFFF",
            "padding": {"top": 6, "right": 8, "bottom": 4, "left": 28},
            "data": [{"values": points}],
            "xField": "x",
            "yField": "close",
            "label": {"visible": False},
            "axes": [
                {"orient": "left", "visible": True, "type": "linear", "min": axis_min, "max": axis_max, "nice": False, "zero": False, "tickCount": 5, "tick": {"visible": False}, "domainLine": {"visible": False}, "grid": {"visible": False}, "label": {"visible": True, "style": {"fill": "#80868B", "fontSize": 10}}},
                {"orient": "bottom", "visible": True, "type": "band", "tick": {"visible": False}, "domainLine": {"visible": False}, "label": {"visible": True, "autoRotate": False, "style": {"fill": "#80868B", "fontSize": 10, "angle": 0}}},
            ],
            "legends": {"visible": False},
            "line": {"style": {"stroke": line_color, "lineWidth": 1.5, "curveType": "monotone"}},
            "area": {"style": {"fill": {"gradient": "linear", "x0": 0, "y0": 0, "x1": 0, "y1": 1, "stops": [{"offset": 0, "color": area_color_top}, {"offset": 1, "color": area_color_bot}]}, "curveType": "monotone"}},
            "point": {"style": {"size": 0, "fill": line_color}, "state": {"dimension_hover": {"size": 4, "stroke": "#FFFFFF", "lineWidth": 2, "fill": line_color}}},
            "markLine": [
                {"y": open_price, "line": {"style": {"stroke": "#DADCE0", "lineWidth": 1, "lineDash": [4, 4]}}, "label": {"visible": False}, "startSymbol": {"visible": False}, "endSymbol": {"visible": False}},
            ] + [
                {"y": mp["price"], "line": {"style": {"stroke": mp.get("color", "#FF9800"), "lineWidth": 1, "lineDash": mp.get("dash", [4, 4])}}, "label": {"visible": True, "text": mp.get("label", ""), "position": "insideEndBottom", "style": {"fill": mp.get("color", "#FF9800"), "fontSize": 9}}, "startSymbol": {"visible": False}, "endSymbol": {"visible": False}}
                for mp in (mark_prices or [])
            ],
            "crosshair": {"xField": {"visible": True, "line": {"style": {"stroke": "#DADCE0", "lineWidth": 1}}, "label": {"visible": False}}, "yField": {"visible": False}},
            "tooltip": {"visible": True, "trigger": "hover", "dimension": {"title": {"value": {"field": "time"}}, "content": [{"key": " ", "value": {"field": "close"}}]}},
            "title": {"visible": False},
        },
    }

    left_elements = [{"tag": "markdown", "content": title_block}, chart_element]
    if sub_chart:
        label_el, sub_chart_el = sub_chart
        left_elements.extend([label_el, sub_chart_el])

    column_set = {
        "tag": "column_set",
        "flex_mode": "flow",
        "horizontal_spacing": "16px",
        "columns": [
            {"tag": "column", "width": "weighted", "weight": 3, "vertical_align": "top", "elements": left_elements},
            {"tag": "column", "width": "weighted", "weight": 2, "vertical_align": "center", "elements": [{"tag": "markdown", "content": analysis_text or ""}]},
        ],
    }
    elements = []
    if top_title:
        elements.append({"tag": "markdown", "content": top_title})
    elements.append(column_set)
    if footer:
        elements.append({"tag": "markdown", "content": footer, "text_align": "right", "text_size": "notation"})

    config = {"wide_screen_mode": True}
    if summary:
        config["summary"] = {"content": summary}
    out = {"schema": "2.0", "config": config,
           "body": {"vertical_spacing": "0px", "elements": elements}}
    if header:
        out["header"] = header
    return out


def build_monitor_intraday_chart_spec(*, stock: dict, tick: dict) -> dict:
    """生成分时图的 chart_spec，用于 build_multi_stock_summary_card 多股嵌入。"""
    points = tick.get("intraday_points") or []
    if not points:
        raise ValueError("missing intraday points")

    values = [float(p["close"]) for p in points]
    low, high = min(values), max(values)
    span = high - low
    pad = max(span * 0.04, 0.2)
    axis_min = round(max(0.0, low - pad), 2)
    axis_max = round(high + pad, 2)
    price = float(tick["price"])
    change = float(tick.get("change_ratio_acc", 0))
    title = stock.get("name") or stock["code"]
    subtitle = f"{stock['code']} · {change:+.2f}% · {points[0]['label']} - {points[-1]['label']}"

    return {
        "type": "line",
        "height": 118,
        "background": "#FFFFFF",
        "padding": {"top": 28, "right": 12, "bottom": 6, "left": 26},
        "data": [{"id": "price", "values": points}],
        "xField": "label",
        "yField": "close",
        "label": {"visible": False},
        "axes": [
            {"orient": "left", "visible": True, "type": "linear", "min": axis_min, "max": axis_max, "nice": False, "zero": False, "tickCount": 3, "tick": {"visible": True, "style": {"stroke": "rgba(17,17,17,0.20)", "lineWidth": 1}}, "domainLine": {"visible": True, "style": {"stroke": "rgba(17,17,17,0.20)", "lineWidth": 1}}, "grid": {"visible": True, "style": {"stroke": "rgba(17,17,17,0.12)", "lineWidth": 1, "lineDash": [2, 3]}}, "label": {"visible": True, "style": {"fill": "#7A7F87", "fontSize": 10, "fontWeight": "normal"}}},
            {"orient": "bottom", "visible": True, "tickCount": 4, "label": {"visible": True, "style": {"fill": "#7A7F87", "fontSize": 9, "fontWeight": "normal"}, "autoHide": True, "autoRotate": False, "minGap": 24, "sampling": True}, "tick": {"visible": False}, "domainLine": {"visible": False}, "grid": {"visible": False}},
        ],
        "legends": {"visible": False},
        "line": {"style": {"stroke": "#00C805", "lineWidth": 1.8, "curveType": "monotone"}},
        "point": {"style": {"size": 0, "fill": "#00C805"}, "state": {"dimension_hover": {"size": 4, "stroke": "#FFFFFF", "lineWidth": 2, "fill": "#00C805"}}},
        "crosshair": {"xField": {"visible": True, "label": {"visible": False}, "line": {"style": {"stroke": "rgba(17,17,17,0.20)", "lineWidth": 1, "lineDash": [2, 3]}}}, "yField": {"visible": True, "label": {"visible": False}, "line": {"style": {"stroke": "rgba(17,17,17,0.12)", "lineWidth": 1, "lineDash": [2, 3]}}}},
        "tooltip": {"visible": True, "trigger": "hover", "dimension": {"updateContent": True}},
        "title": {
            "visible": True,
            "text": f"{title}\n¥ {price:.2f}",
            "subtext": subtitle,
            "textStyle": {"fill": "#111111", "fontSize": 20, "fontWeight": "bold"},
            "subtextStyle": {"fill": "#5F6368", "fontSize": 12, "fontWeight": "normal"},
        },
    }


def _summarize_tech_item(stock: dict, data: dict) -> str:
    if data.get("_no_tech"):
        return f"**{stock.get('name', stock['code'])}** `{stock['code']}`\n- ETF/指数，暂无技术指标"

    ma5, ma10, ma20 = data.get("MA5"), data.get("MA10"), data.get("MA20")
    diff, dea = data.get("MACD_DIFF"), data.get("MACD_DEA")
    rsi = data.get("RSI6")
    lb = data.get("LB5")

    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            trend = "均线多头"
        elif ma5 < ma10 < ma20:
            trend = "均线空头"
        else:
            trend = "均线缠绕"
    else:
        trend = "均线未知"

    if diff is not None and dea is not None:
        macd = "MACD偏强" if diff > dea else "MACD偏弱"
    else:
        macd = "MACD未知"

    if rsi is not None:
        if rsi > 70:
            rsi_text = f"RSI超买 {rsi:.1f}"
        elif rsi < 30:
            rsi_text = f"RSI超卖 {rsi:.1f}"
        else:
            rsi_text = f"RSI {rsi:.1f}"
    else:
        rsi_text = "RSI未知"

    lb_text = f"量比 {lb:.2f}" if lb is not None else "量比未知"
    return f"**{stock.get('name', stock['code'])}** `{stock['code']}`\n- {trend} · {macd} · {rsi_text} · {lb_text}"


def build_multi_stock_summary_card(
    tech_items: list,
    disclaimer: str,
    startup: bool = False,
    show_chart: bool = True,
    now: Optional[datetime] = None,
) -> dict:
    """15 分钟技术汇总卡片：支持多股分时图嵌入。now 参数由调用方传入（带时区）。"""
    now = now or datetime.now()  # 调用方应传入 _now() 以支持 replay 模式
    now_str = now.strftime("%Y-%m-%d %H:%M")
    heading = (
        f"**监控已启动**\n{now_str}\n多股技术快照"
        if startup
        else f"**技术指标汇总**\n{now_str}\n多股趋势卡片"
    )
    elements = [{"tag": "markdown", "content": heading}]

    for item in tech_items:
        stock = item["stock"]
        data = item["data"]
        tick = item.get("tick")
        if show_chart and tick and tick.get("intraday_points"):
            elements.append({"tag": "chart", "chart_spec": build_monitor_intraday_chart_spec(stock=stock, tick=tick)})
        elements.append({"tag": "markdown", "content": _summarize_tech_item(stock, data)})

    elements.append({"tag": "markdown", "content": disclaimer})
    return {"schema": "2.0", "body": {"elements": elements}}
