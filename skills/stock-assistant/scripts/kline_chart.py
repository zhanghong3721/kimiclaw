#!/usr/bin/env python3
"""
K线 / 分时完整图生成
日K线：python3 scripts/kline_chart.py 600519.SH [days]
分时图：python3 scripts/kline_chart.py 600519.SH --intraday [today|YYYYMMDD]
输出：图片路径到 stdout

公开函数：
  build_full_chart(code, days=120, annotation_func=None, dark=False) -> str
  build_intraday_full(code, date="today", n_min=5, annotation_func=None, dark=False) -> str
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyBboxPatch, Rectangle
    import matplotlib.ticker as mticker
    import numpy as np
except ImportError as e:
    print(f"[kline_chart] 缺少依赖: {e}", file=sys.stderr)
    sys.exit(1)

matplotlib.rcParams["font.family"] = [
    "WenQuanYi Micro Hei", "Noto Sans CJK SC", "Noto Serif CJK SC",
    "Arial Unicode MS", "STHeiti", "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# scripts 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))
from data_fetch import get_kline, get_intraday  # noqa: E402

# 图片输出到 ~/.openclaw/workspace，供 openclaw send 动作直接引用
OUTPUT_DIR = Path.home() / ".openclaw" / "workspace"


# ─────────────────────────────────────────────────────────────
#  通用指标计算工具（仅依赖 numpy，无 pandas 依赖）
# ─────────────────────────────────────────────────────────────

def _ma(a: np.ndarray, w: int) -> np.ndarray:
    n = len(a)
    r = np.full(n, np.nan)
    for i in range(w - 1, n):
        r[i] = a[i - w + 1:i + 1].mean()
    return r


def _ema(a: np.ndarray, s: int) -> np.ndarray:
    n = len(a)
    r = np.zeros(n)
    k = 2 / (s + 1)
    r[0] = a[0]
    for i in range(1, n):
        r[i] = a[i] * k + r[i - 1] * (1 - k)
    return r


def _rsi(a: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(a)
    delta = np.diff(a, prepend=a[0])
    gain = np.maximum(delta, 0)
    loss = np.maximum(-delta, 0)
    ag = np.full(n, np.nan)
    al = np.full(n, np.nan)
    ag[period] = gain[1:period + 1].mean()
    al[period] = loss[1:period + 1].mean()
    for i in range(period + 1, n):
        ag[i] = (ag[i - 1] * (period - 1) + gain[i]) / period
        al[i] = (al[i - 1] * (period - 1) + loss[i]) / period
    rs = np.where(al == 0, np.inf, ag / al)
    return np.where(al == 0, 100, 100 - 100 / (1 + rs))


def _kdj(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 9):
    n = len(c)
    k = np.full(n, 50.0)
    d = np.full(n, 50.0)
    j = np.zeros(n)
    for i in range(period - 1, n):
        hh = h[i - period + 1:i + 1].max()
        ll = l[i - period + 1:i + 1].min()
        rsv = (c[i] - ll) / (hh - ll) * 100 if hh != ll else 50
        k[i] = k[i - 1] * 2 / 3 + rsv / 3
        d[i] = d[i - 1] * 2 / 3 + k[i] / 3
        j[i] = 3 * k[i] - 2 * d[i]
    k[:period - 1] = np.nan
    d[:period - 1] = np.nan
    j[:period - 1] = np.nan
    return k, d, j


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return _ma(tr, period)


def _avoid_overlap(labels: list, min_gap: float) -> list:
    """右侧价格标签统一避让（按价格排序后迭代推开）。"""
    labels = sorted(labels, key=lambda x: x[0])
    for _ in range(40):
        changed = False
        for i in range(1, len(labels)):
            if labels[i][0] - labels[i - 1][0] < min_gap:
                m = (labels[i][0] + labels[i - 1][0]) / 2
                labels[i - 1][0] = m - min_gap / 2
                labels[i][0] = m + min_gap / 2
                changed = True
        if not changed:
            break
    return labels


def _avoid_y(items: list, min_gap: float, direction: int = 1) -> list:
    """阶段框标签 y 轴避让。"""
    items = sorted(items, key=lambda x: x[0])
    result = []
    last_x = -999
    last_y = None
    for mx, ty, txt, fc, ec in items:
        if last_y is not None and abs(mx - last_x) < 12:
            ty = last_y + direction * min_gap
        result.append((mx, ty, txt, fc, ec))
        last_x = mx
        last_y = ty
    return result


def _find_swings(highs: np.ndarray, lows: np.ndarray, n: int, window: int = 5) -> list:
    """寻找并清理摆动点（高点/低点交替）。"""
    pivots = []
    for i in range(window, n - window):
        if highs[i] == highs[max(0, i - window):i + window + 1].max():
            pivots.append((i, highs[i], 'high'))
        elif lows[i] == lows[max(0, i - window):i + window + 1].min():
            pivots.append((i, lows[i], 'low'))
    cleaned = []
    for p in pivots:
        if cleaned and cleaned[-1][2] == p[2]:
            if p[2] == 'high' and p[1] > cleaned[-1][1]:
                cleaned[-1] = p
            elif p[2] == 'low' and p[1] < cleaned[-1][1]:
                cleaned[-1] = p
        else:
            cleaned.append(p)
    return cleaned


def _volume_profile(highs: np.ndarray, lows: np.ndarray, vols: np.ndarray,
                    nb: int = 40):
    """计算 Volume Profile，返回 (edges, mid, bvol, poc, poc_price)。"""
    n = len(highs)
    pmin = lows.min()
    pmax = highs.max()
    edges = np.linspace(pmin, pmax, nb + 1)
    mid = (edges[:-1] + edges[1:]) / 2
    bvol = np.zeros(nb)
    for i in range(n):
        for b in range(nb):
            ov = min(highs[i], edges[b + 1]) - max(lows[i], edges[b])
            if ov > 0:
                bvol[b] += vols[i] * ov / max(highs[i] - lows[i], 0.001)
    poc = int(np.argmax(bvol))
    poc_price = mid[poc]
    return edges, mid, bvol, poc, poc_price


# ─────────────────────────────────────────────────────────────
#  颜色主题
# ─────────────────────────────────────────────────────────────

def _theme(dark: bool = False) -> dict:
    if dark:
        return dict(
            fig_face="#0d1117",
            ax_face="#161b22",
            up="#ef5350",
            down="#26a69a",
            vol_up="#ef9a9a",
            vol_down="#80cbc4",
            grid="#30363d",
            tick="#adbac7",
        )
    return dict(
        fig_face="#FAFAFA",
        ax_face="#FFFFFF",
        up="#D32F2F",
        down="#388E3C",
        vol_up="#EF9A9A",
        vol_down="#A5D6A7",
        grid="#EEEEEE",
        tick="#555555",
    )


# ─────────────────────────────────────────────────────────────
#  build_full_chart — 完整5面板日K图
# ─────────────────────────────────────────────────────────────

def build_full_chart(
    code: str,
    days: int = 120,
    annotation_func: Optional[Callable] = None,
    dark: bool = False,
) -> Optional[str]:
    """
    生成完整 5 面板日K图（K线、成交量、MACD、RSI/KDJ、信息栏）。

    参数
    ----
    code            股票代码，如 600519.SH
    days            获取最近多少个交易日
    annotation_func 可选钩子：def annotate(ax_k, ctx: dict) -> None
                    ctx 包含所有已计算好的变量（见文档）
    dark            True 时使用深色主题

    返回
    ----
    图片绝对路径字符串，失败返回 None
    """
    rows = get_kline(code, days)
    if not rows:
        print(f"[kline_chart] 无K线数据: {code}", file=sys.stderr)
        return None

    # ── 原始数据 ──────────────────────────────────────────────
    dates = [r["date"] for r in rows]
    opens = np.array([r["open"] for r in rows])
    highs = np.array([r["high"] for r in rows])
    lows = np.array([r["low"] for r in rows])
    closes = np.array([r["close"] for r in rows])
    vols = np.array([r["volume"] for r in rows])
    n = len(rows)
    xs = np.arange(n)
    pr = highs.max() - lows.min()
    pr = max(pr, closes[-1] * 0.001)  # 极值保护
    off = pr * 0.015

    # ── 技术指标 ──────────────────────────────────────────────
    ma5 = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    dif = _ema(closes, 12) - _ema(closes, 26)
    dea = _ema(dif, 9)
    hist = (dif - dea) * 2
    rsi14 = _rsi(closes, 14)

    boll_mid = _ma(closes, 20)
    boll_std = np.array([
        closes[max(0, i - 19):i + 1].std() if i >= 19 else np.nan
        for i in range(n)
    ])
    boll_upper = boll_mid + 2 * boll_std
    boll_lower = boll_mid - 2 * boll_std
    boll_width = (boll_upper - boll_lower) / np.where(boll_mid == 0, 1, boll_mid)
    boll_squeeze = np.zeros(n, dtype=bool)
    for i in range(50, n):
        if not np.isnan(boll_width[i]):
            boll_squeeze[i] = boll_width[i] < np.nanpercentile(
                boll_width[max(0, i - 50):i], 20
            )

    kdj_k, kdj_d, kdj_j = _kdj(highs, lows, closes)
    atr14 = _atr(highs, lows, closes)
    atr_stop = closes - 2 * atr14

    avg_vol = vols.mean()
    big_vol = [i for i in range(n) if vols[i] > avg_vol * 2]

    # 跳空缺口
    gaps = []
    for i in range(1, n):
        if lows[i] > highs[i - 1]:
            gaps.append(("up", i, highs[i - 1], lows[i]))
        elif highs[i] < lows[i - 1]:
            gaps.append(("down", i, lows[i - 1], highs[i]))

    # ── Volume Profile ─────────────────────────────────────────
    nb = 40
    edges, mid, bvol, poc, poc_price = _volume_profile(highs, lows, vols, nb)
    pmin = lows.min()
    pmax = highs.max()

    # ── 摆动点 & 五级价位 ──────────────────────────────────────
    pivots = _find_swings(highs, lows, n)
    all_pts = [(0, closes[0], 'start')] + pivots + [(n - 1, closes[-1], 'end')]

    curr = closes[-1]
    sh = sorted([p[1] for p in pivots if p[2] == 'high'], reverse=True)
    sl = sorted([p[1] for p in pivots if p[2] == 'low'])
    ca = sorted(set([
        p for p in sh + [ma60[-1], boll_upper[-1]]
        if not np.isnan(p) and p > curr * 1.005
    ]))
    cb = sorted(set([
        p for p in sl + [ma60[-1], boll_lower[-1], poc_price, atr_stop[-1]]
        if not np.isnan(p) and p < curr * 0.995
    ]), reverse=True)
    strong_res = ca[1] if len(ca) > 1 else (ca[0] * 1.03 if ca else curr * 1.05)
    res = ca[0] if ca else curr * 1.02
    sup = cb[0] if cb else curr * 0.98
    sec_sup = cb[1] if len(cb) > 1 else (cb[0] * 0.97 if cb else curr * 0.95)

    # ── 蜡烛形态检测（最近30根）──────────────────────────────
    candle_signals = []
    for i in range(max(2, n - 30), n):
        body = abs(closes[i] - opens[i])
        rng = highs[i] - lows[i] + 0.001
        us = highs[i] - max(closes[i], opens[i])
        ls = min(closes[i], opens[i]) - lows[i]
        if ls > body * 2 and us < body * 0.5 and rng > pr * 0.005:
            candle_signals.append((i, '锤子', '#27AE60', 'bottom'))
        elif us > body * 2 and ls < body * 0.5 and rng > pr * 0.005:
            candle_signals.append((i, '射击之星', '#E74C3C', 'top'))
        elif body < rng * 0.1 and rng > pr * 0.004:
            candle_signals.append((i, '十字', '#FF8F00', 'top'))
    for i in range(max(1, n - 30), n):
        if (closes[i - 1] < opens[i - 1] and closes[i] > opens[i]
                and closes[i] > opens[i - 1] and opens[i] < closes[i - 1]):
            candle_signals.append((i, '吞没↑', '#27AE60', 'bottom'))
        elif (closes[i - 1] > opens[i - 1] and closes[i] < opens[i]
              and closes[i] < opens[i - 1] and opens[i] > closes[i - 1]):
            candle_signals.append((i, '吞没↓', '#E74C3C', 'top'))

    # ── RSI 背离检测 ────────────────────────────────────────────
    rsi_div = []
    for i in range(20, n - 2):
        if highs[i] == highs[max(0, i - 5):i + 3].max():
            prev = [
                j for j in range(max(0, i - 25), i - 3)
                if highs[j] == highs[max(0, j - 3):j + 4].max()
            ]
            if prev and highs[i] > highs[prev[-1]] and rsi14[i] < rsi14[prev[-1]] - 3:
                rsi_div.append((i, '顶背离', '#E74C3C'))
        if lows[i] == lows[max(0, i - 5):i + 3].min():
            prev = [
                j for j in range(max(0, i - 25), i - 3)
                if lows[j] == lows[max(0, j - 3):j + 4].min()
            ]
            if prev and lows[i] < lows[prev[-1]] and rsi14[i] > rsi14[prev[-1]] + 3:
                rsi_div.append((i, '底背离', '#27AE60'))

    # ── J 信号限频（每段 ≥8 根取首个）──────────────────────────
    j_signals = []
    last_j = -99
    for i in range(n):
        if np.isnan(kdj_j[i]):
            continue
        if kdj_j[i] > 100 and i - last_j >= 8:
            j_signals.append((i, kdj_j[i], 'over', 'J>100', '#D32F2F'))
            last_j = i
        elif kdj_j[i] < 0 and i - last_j >= 8:
            j_signals.append((i, kdj_j[i], 'under', 'J<0', '#27AE60'))
            last_j = i

    # ── 趋势通道 ───────────────────────────────────────────────
    hi_pts = [(p[0], p[1]) for p in pivots if p[2] == 'high']
    lo_pts = [(p[0], p[1]) for p in pivots if p[2] == 'low']

    # ── 主题色 ─────────────────────────────────────────────────
    T = _theme(dark)

    # ── 画布（5面板） ──────────────────────────────────────────
    fig = plt.figure(figsize=(22, 12), facecolor=T["fig_face"])
    gs = fig.add_gridspec(5, 1, height_ratios=[5, 0.9, 0.9, 0.85, 0.2], hspace=0.0)
    ax_k, ax_vol, ax_mac, ax_rsi, ax_inf = [fig.add_subplot(gs[i]) for i in range(5)]
    fig.subplots_adjust(left=0.06, right=0.88, top=0.93, bottom=0.04, hspace=0.0)
    for ax in [ax_k, ax_vol, ax_mac, ax_rsi, ax_inf]:
        ax.set_facecolor(T["ax_face"])
        ax.tick_params(colors=T["tick"], labelsize=8)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)

    # ── K 线本体 ───────────────────────────────────────────────
    for i in range(n):
        c = T["up"] if closes[i] >= opens[i] else T["down"]
        ax_k.plot([i, i], [lows[i], highs[i]], color=c, lw=0.9)
        ax_k.add_patch(plt.Rectangle(
            (i - 0.36, min(opens[i], closes[i])),
            0.72, max(abs(closes[i] - opens[i]), 0.001),
            color=c, zorder=3,
        ))

    # MA 线
    ax_k.plot(xs, ma5, color="#FF8F00", lw=1.0, label="MA5")
    ax_k.plot(xs, ma20, color="#4ECDC4", lw=1.2, label="MA20")
    ax_k.plot(xs, ma60, color="#9B59B6", lw=1.5, label="MA60")

    # 布林带
    ax_k.plot(xs, boll_upper, color="#7B68EE", lw=0.9, ls="--", alpha=0.6, label="BOLL")
    ax_k.plot(xs, boll_lower, color="#7B68EE", lw=0.9, ls="--", alpha=0.6)
    ax_k.fill_between(xs, boll_upper, boll_lower, alpha=0.04, color="#7B68EE", interpolate=True)
    for i in range(n):
        if boll_squeeze[i]:
            ax_k.axvline(i, color="#FF8F00", lw=0.5, alpha=0.15)

    # ATR 止损线
    ax_k.plot(xs, atr_stop, color="#E74C3C", lw=0.8, ls="-.", alpha=0.4, label="ATR止损")

    # 趋势通道线
    if len(hi_pts) >= 2:
        hx = [p[0] for p in hi_pts[-3:]]
        hy = [p[1] for p in hi_pts[-3:]]
        hfit = np.polyfit(hx, hy, 1)
        ch_x = np.array([hi_pts[-min(3, len(hi_pts))][0], n + 3])
        ax_k.plot(ch_x, np.polyval(hfit, ch_x), color="#E74C3C",
                  lw=1.2, ls="--", alpha=0.55, label="压力通道")
    if len(lo_pts) >= 2:
        lx = [p[0] for p in lo_pts[-3:]]
        ly = [p[1] for p in lo_pts[-3:]]
        lfit = np.polyfit(lx, ly, 1)
        cl_x = np.array([lo_pts[-min(3, len(lo_pts))][0], n + 3])
        ax_k.plot(cl_x, np.polyval(lfit, cl_x), color="#27AE60",
                  lw=1.2, ls="--", alpha=0.55, label="支撑通道")

    # 蜡烛形态标注
    for ci, clbl, ccol, pos in candle_signals:
        y = lows[ci] - pr * 0.02 if pos == 'bottom' else highs[ci] + pr * 0.01
        ax_k.text(
            ci, y, clbl, fontsize=7, color=ccol, ha='center',
            va='top' if pos == 'bottom' else 'bottom',
            bbox=dict(boxstyle='round,pad=0.2', fc='white', ec=ccol, alpha=0.85, lw=0.8),
        )

    # ── 成交量面板 ─────────────────────────────────────────────
    vol_scale, vol_unit = (1e8, "亿") if vols.max() > 5e7 else (1e4, "万")
    vc = [T["vol_up"] if closes[i] >= opens[i] else T["vol_down"] for i in range(n)]
    ax_vol.bar(xs, vols / vol_scale, color=vc, width=0.8, alpha=0.85)
    ax_vol.plot(xs, _ma(vols, 5) / vol_scale, color="#FF8F00", lw=0.8, alpha=0.8)
    ax_vol.set_ylabel(f"成交量({vol_unit})", fontsize=8)
    ax_vol.set_xticks([])
    for i in big_vol:
        ax_vol.axvline(i, color="#FF8F00", lw=0.6, alpha=0.35)

    # ── MACD 面板 ──────────────────────────────────────────────
    ax_mac.plot(xs, dif, color="#FF8F00", lw=1.0)
    ax_mac.plot(xs, dea, color="#4ECDC4", lw=1.0)
    for i in range(n):
        ax_mac.bar(i, hist[i], color="#D32F2F" if hist[i] > 0 else "#388E3C",
                   alpha=0.7, width=0.8)
    ax_mac.axhline(0, color="#AAAAAA", lw=0.6)
    ax_mac.set_ylabel("MACD", fontsize=8)
    ax_mac.set_xticks([])
    macd_range = abs(dif).max()
    for i in range(1, n):
        cross_y = (dif[i] + dea[i]) / 2
        if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
            above = dif[i] > 0
            lbl = "轴上\n金叉" if above else "轴下\n金叉"
            col = "#1B5E20" if above else "#27AE60"
            ax_mac.axvline(i, color=col, lw=0.8, ls="--", alpha=0.5)
            ax_mac.annotate(
                lbl, xy=(i, cross_y), xytext=(i, cross_y + macd_range * 0.35),
                fontsize=6, color=col, ha="center",
                bbox=dict(boxstyle='round,pad=0.15', fc='white', ec=col, alpha=0.85, lw=0.7),
                arrowprops=dict(arrowstyle='-', color=col, lw=0.8),
            )
        elif dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]:
            above = dif[i] > 0
            lbl = "轴上\n死叉" if above else "轴下\n死叉"
            col = "#B71C1C" if above else "#E74C3C"
            ax_mac.axvline(i, color=col, lw=0.8, ls="--", alpha=0.5)
            ax_mac.annotate(
                lbl, xy=(i, cross_y), xytext=(i, cross_y - macd_range * 0.35),
                fontsize=6, color=col, ha="center",
                bbox=dict(boxstyle='round,pad=0.15', fc='white', ec=col, alpha=0.85, lw=0.7),
                arrowprops=dict(arrowstyle='-', color=col, lw=0.8),
            )

    # ── RSI + KDJ 面板 ─────────────────────────────────────────
    ax_rsi.plot(xs, rsi14, color="#9C27B0", lw=1.2, label="RSI(14)", zorder=4)
    for lvl, c, ls_ in [(70, "#E74C3C", "--"), (50, "#AAAAAA", ":"), (30, "#27AE60", "--")]:
        ax_rsi.axhline(lvl, color=c, lw=0.8, ls=ls_, alpha=0.7)
    ax_rsi.fill_between(xs, rsi14, 70, where=(rsi14 >= 70), alpha=0.12,
                        color="#E74C3C", interpolate=True)
    ax_rsi.fill_between(xs, rsi14, 30, where=(rsi14 <= 30), alpha=0.12,
                        color="#27AE60", interpolate=True)
    ax_rsi.plot(xs, kdj_k, color="#FF8F00", lw=0.9, alpha=0.75, label="K")
    ax_rsi.plot(xs, kdj_d, color="#4ECDC4", lw=0.9, alpha=0.75, label="D")
    ax_rsi.plot(xs, np.clip(kdj_j, -10, 110), color="#E74C3C", lw=0.8,
                ls="--", alpha=0.6, label="J")
    for ji, jv, jtype, jlbl, jcol in j_signals:
        jvc = min(108, max(-8, jv))
        joff = 8 if jtype == 'over' else -8
        ax_rsi.annotate(
            jlbl, xy=(ji, jvc), xytext=(ji, jvc + joff),
            fontsize=7, color=jcol, ha='center', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', fc='white', ec=jcol, alpha=0.9, lw=0.8),
            arrowprops=dict(arrowstyle='-|>', color=jcol, lw=1, mutation_scale=8),
        )
    for di, dlbl, dcol in rsi_div:
        doff = 12 if dcol == "#E74C3C" else -12
        ax_rsi.annotate(
            dlbl, xy=(di, rsi14[di]),
            xytext=(di, min(110, max(-10, rsi14[di] + doff))),
            fontsize=7, color=dcol, ha='center', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', fc='white', ec=dcol, alpha=0.85),
            arrowprops=dict(arrowstyle='-|>', color=dcol, lw=1.2, mutation_scale=10),
        )
    ax_rsi.text(n - 1, 72, "超买", color="#E74C3C", fontsize=7, va="bottom")
    ax_rsi.text(n - 1, 28, "超卖", color="#27AE60", fontsize=7, va="top")
    ax_rsi.set_ylabel("RSI/KDJ", fontsize=7)
    ax_rsi.set_ylim(-15, 115)
    ax_rsi.legend(loc="upper left", fontsize=6, ncol=4, framealpha=0.7)
    tick_step = max(1, n // 10)
    ax_rsi.set_xticks(xs[::tick_step])
    ax_rsi.set_xticklabels(
        [dates[i] for i in range(0, n, tick_step)], rotation=25, ha="right", fontsize=7
    )

    # ── Volume Profile 左侧嵌入 ────────────────────────────────
    ax_vp = ax_k.inset_axes([0.0, 0.0, 0.06, 1.0])
    bc = [
        "#FF8F00" if b == poc else ("#E67E22" if bvol[b] > bvol.mean() * 1.5 else "#BBBBBB")
        for b in range(nb)
    ]
    ax_vp.barh(mid, bvol / bvol.max(), height=(pmax - pmin) / nb * 0.85,
               color=bc, alpha=0.2)
    ax_vp.axhline(poc_price, color="#FF8F00", lw=1.0, ls="--", alpha=0.4)
    ax_vp.set_ylim(ax_k.get_ylim())
    ax_vp.axis("off")

    # ── 阶段框 & 标签 ─────────────────────────────────────────
    phase_labels_top = []
    phase_labels_bot = []
    label_above = True
    for idx in range(len(all_pts) - 1):
        xi, pi, _ = all_pts[idx]
        xj, pj, _ = all_pts[idx + 1]
        if xj - xi < 4:
            continue
        seg_lo = lows[xi:xj + 1].min()
        seg_hi = highs[xi:xj + 1].max()
        pct = (pj - pi) / pi * 100
        if abs(pct) < 3:
            lbl, fc, ec = "整理", "#FFFDE7", "#F57F17"
        elif pct > 0:
            lbl, fc, ec = ("反弹" if pct < 10 else "上涨"), "#E8F5E9", "#27AE60"
        else:
            lbl, fc, ec = ("急跌" if pct < -12 else "下跌"), "#FFEBEE", "#E74C3C"
        ax_k.add_patch(Rectangle(
            (xi, seg_lo - pr * 0.003), xj - xi, seg_hi - seg_lo + pr * 0.006,
            fc=fc, ec=ec, lw=1.5, alpha=0.25, zorder=2,
        ))
        mx = (xi + xj) / 2
        if label_above:
            phase_labels_top.append((mx, seg_hi + pr * 0.012, f"{lbl} {pct:+.1f}%", fc, ec))
        else:
            phase_labels_bot.append((mx, seg_lo - pr * 0.020, f"{lbl} {pct:+.1f}%", fc, ec))
        label_above = not label_above
    for mx, ty, txt, fc, ec in _avoid_y(phase_labels_top, pr * 0.04, 1):
        ax_k.text(mx, ty, txt, fontsize=10, color=ec, ha="center",
                  fontweight="bold", va="bottom",
                  bbox=dict(boxstyle="round,pad=0.25", fc=fc, ec=ec, alpha=0.88, lw=1.2))
    for mx, ty, txt, fc, ec in _avoid_y(phase_labels_bot, pr * 0.04, -1):
        ax_k.text(mx, ty, txt, fontsize=10, color=ec, ha="center",
                  fontweight="bold", va="top",
                  bbox=dict(boxstyle="round,pad=0.25", fc=fc, ec=ec, alpha=0.88, lw=1.2))

    # ── 大框层：趋势/高低点/近期整理/巨量 ────────────────────
    hi_i = int(np.argmax(highs))
    lo_i = int(np.argmin(lows))
    trend = "上升" if closes[-1] > closes[0] else "下降"
    tc = "#27AE60" if trend == "上升" else "#C62828"
    tf = "#E8F5E9" if trend == "上升" else "#FFEBEE"
    te = "#27AE60" if trend == "上升" else "#E74C3C"
    ma_desc = (
        '多头' if ma5[-1] > ma20[-1] > ma60[-1] else
        '空头' if ma5[-1] < ma20[-1] < ma60[-1] else '纠缠'
    )
    ax_k.text(
        n // 2, highs.max() - pr * 0.04,
        f"  {trend}趋势  MA{ma_desc}排列  ",
        fontsize=13, color=tc, ha="center", fontweight="bold", va="top",
        bbox=dict(boxstyle="round,pad=0.45", fc=tf, ec=te, alpha=0.93),
    )
    ax_k.annotate(
        f"区间高  {highs[hi_i]:.2f}  {dates[hi_i][5:]}",
        xy=(hi_i, highs[hi_i]),
        xytext=(max(5, hi_i - 8), highs[hi_i] - pr * 0.04),
        fontsize=11, color="#C62828", ha="center", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.35", fc="#FFEBEE", ec="#C62828", alpha=0.93),
        arrowprops=dict(arrowstyle="-|>", color="#C62828", lw=2, mutation_scale=15),
    )
    ax_k.annotate(
        f"区间低  {lows[lo_i]:.2f}  {dates[lo_i][5:]}",
        xy=(lo_i, lows[lo_i]),
        xytext=(min(n - 8, lo_i + 8), lows[lo_i] + pr * 0.05),
        fontsize=11, color="#2E7D32", ha="center", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.35", fc="#E8F5E9", ec="#2E7D32", alpha=0.93),
        arrowprops=dict(arrowstyle="-|>", color="#2E7D32", lw=2, mutation_scale=15),
    )
    rb_lo = lows[n - 25:].min()
    rb_hi = highs[n - 25:].max()
    ax_k.add_patch(FancyBboxPatch(
        (n - 25, rb_lo - pr * 0.008), 24, rb_hi - rb_lo + pr * 0.016,
        boxstyle="square,pad=0", fill=False,
        edgecolor="#F0C040", lw=2, ls="--", alpha=0.9, zorder=5,
    ))
    ax_k.text(
        n - 13, rb_lo - pr * 0.016,
        f"近期整理  {rb_lo:.1f}—{rb_hi:.1f}",
        fontsize=10, color="#B8860B", ha="center", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", fc="#FFFDE7", ec="#F0C040", alpha=0.9),
    )
    if big_vol:
        bv_i = max(big_vol, key=lambda i: vols[i])
        side = (highs[bv_i] + pr * 0.04 if closes[bv_i] > opens[bv_i]
                else lows[bv_i] - pr * 0.07)
        ax_k.annotate(
            f"巨量  {vols[bv_i] / 1e8:.2f}亿",
            xy=(bv_i, closes[bv_i]),
            xytext=(min(bv_i + 9, n - 6), side),
            fontsize=10, color="#E65100", ha="center", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc="#FFF3E0", ec="#E67E22", alpha=0.93),
            arrowprops=dict(arrowstyle="-|>", color="#E67E22", lw=2, mutation_scale=13),
        )
        ax_vol.add_patch(FancyBboxPatch(
            (bv_i - 1.5, 0), 3, vols[bv_i] / vol_scale,
            boxstyle="square,pad=0", fill=False,
            edgecolor="#E67E22", lw=2, zorder=5,
        ))

    # ── 用户自定义标注钩子 ─────────────────────────────────────
    ctx = {
        # 基础数据
        'xs': xs, 'dates': dates, 'n': n,
        'opens': opens, 'highs': highs, 'lows': lows, 'closes': closes, 'vols': vols,
        'pr': pr, 'off': off,
        # 技术指标
        'ma5': ma5, 'ma20': ma20, 'ma60': ma60,
        'dif': dif, 'dea': dea, 'hist': hist,
        'rsi14': rsi14,
        'boll_upper': boll_upper, 'boll_mid': boll_mid, 'boll_lower': boll_lower,
        'kdj_k': kdj_k, 'kdj_d': kdj_d, 'kdj_j': kdj_j,
        'atr_stop': atr_stop, 'poc_price': poc_price,
        # 价位
        'strong_res': strong_res, 'res': res, 'curr': curr, 'sup': sup, 'sec_sup': sec_sup,
        # 摆动点
        'pivots': pivots,
        # 坐标轴
        'ax_k': ax_k, 'ax_vol': ax_vol, 'ax_mac': ax_mac, 'ax_rsi': ax_rsi,
    }
    if annotation_func is not None:
        annotation_func(ax_k, ctx)

    # ── 五级价位线 + Fibonacci + MA 右侧标签 ─────────────────
    price_lines = [
        [strong_res, f"强压 {strong_res:.2f}", "#B71C1C", 1.8, "--"],
        [res,        f"压力 {res:.2f}",        "#E74C3C", 1.2, "--"],
        [curr,       f"现价 {curr:.2f}",       "#1565C0", 1.5, "-."],
        [sup,        f"支撑 {sup:.2f}",        "#27AE60", 1.2, "--"],
        [sec_sup,    f"次支 {sec_sup:.2f}",    "#81C784", 1.0, ":"],
    ]
    for orig, lbl, col, lw, ls in price_lines:
        ax_k.axhline(orig, color=col, lw=lw, ls=ls, alpha=0.85, zorder=2)

    all_right = [
        [p[0], p[1], p[2], 8, "bold" if "现价" in p[1] else "normal"]
        for p in price_lines
    ]
    for ratio, fc in [(0.382, "#1565C0"), (0.5, "#F57F17"), (0.618, "#2E7D32")]:
        price = lows.min() + (highs.max() - lows.min()) * (1 - ratio)
        ax_k.axhline(price, color=fc, lw=0.6, ls="--", alpha=0.3)
        all_right.append([price, f"Fib{ratio * 100:.0f}% {price:.1f}", fc, 6.5, "normal"])
    for val, col, lbl in [
        (ma5[-1], "#FF8F00", "MA5"),
        (ma20[-1], "#4ECDC4", "MA20"),
        (ma60[-1], "#9B59B6", "MA60"),
    ]:
        if not np.isnan(val):
            all_right.append([val, f"{lbl} {val:.1f}", col, 7, "normal"])
    for dp, lbl, col, fs, fw in _avoid_overlap(all_right, pr * 0.035):
        ax_k.text(n + 0.4, dp, f" {lbl}", color=col, fontsize=fs,
                  va="center", fontweight=fw)

    # 跳空缺口标注（最近4个）
    for gtype, gi, g1, g2 in gaps[-4:]:
        col = "#FFCCBC" if gtype == "up" else "#BBDEFB"
        ax_k.add_patch(mpatches.FancyBboxPatch(
            (gi - 2, g1), 4, g2 - g1,
            boxstyle="square,pad=0", fc=col, ec="none", alpha=0.3, zorder=1,
        ))
        ax_k.text(gi, (g1 + g2) / 2, "缺口", color="#666", fontsize=6,
                  ha="center", va="center")
    for i in big_vol:
        ax_k.axvline(i, color="#FF8F00", lw=0.5, alpha=0.1)

    # ── 收尾：范围 / 图例 / 标题 ──────────────────────────────
    ax_k.set_xlim(-1, n + 8)
    ax_k.set_ylim(lows.min() - pr * 0.06, highs.max() + pr * 0.08)
    handles, labels = ax_k.get_legend_handles_labels()
    if ax_k.get_legend():
        ax_k.get_legend().remove()
    fig.legend(
        handles, labels, loc="upper center", ncol=len(handles),
        fontsize=7.5, framealpha=0.85,
        bbox_to_anchor=(0.47, 0.97), bbox_transform=fig.transFigure,
    )
    ax_k.set_ylabel("价格", fontsize=9)
    ax_k.set_xticks([])
    ax_k.grid(axis="y", color=T["grid"], lw=0.5)
    for _ax in [ax_vol, ax_mac, ax_rsi]:
        _ax.set_xlim(-1, n + 8)
    ax_inf.axis("off")
    ax_vp.set_ylim(ax_k.get_ylim())

    # 标题
    pct_now = (closes[-1] - closes[-2]) / closes[-2] * 100 if n >= 2 else 0.0
    sign = "▲" if pct_now >= 0 else "▼"
    macd_state = '多头↑' if dif[-1] > dea[-1] else '空头↓'
    fig.suptitle(
        f"{code}  {days}天    现价 {curr:.2f}  {sign}{abs(pct_now):.2f}%    "
        f"MA5 {ma5[-1]:.1f}  MA20 {ma20[-1]:.1f}  MA60 {ma60[-1]:.1f}    "
        f"RSI {rsi14[-1]:.1f}    MACD DIF{dif[-1]:.2f} DEA{dea[-1]:.2f} {macd_state}    "
        f"量 {vols[-1] / 1e8:.2f}亿",
        fontsize=11, fontweight="bold", x=0.47,
    )
    fig.text(
        0.5, 0.005,
        f"强压:{strong_res:.2f} | 压力:{res:.2f} | 现价:{curr:.2f} | "
        f"支撑:{sup:.2f} | 次支:{sec_sup:.2f} | ATR止损:{atr_stop[-1]:.2f} | "
        f"POC:{poc_price:.2f} | MA{ma_desc}排列 | MACD:{macd_state}",
        ha="center", fontsize=9, color="#333",
        bbox=dict(boxstyle="round,pad=0.3", fc="#F5F5F5", alpha=0.9),
    )

    # ── 保存 ────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"kline_{code.replace('.', '_')}_annotated.png"
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out)


# ─────────────────────────────────────────────────────────────
#  build_intraday_full — 完整分时图（聚合 N 分钟 K 线）
# ─────────────────────────────────────────────────────────────

def build_intraday_full(
    code: str,
    date: str = "today",
    n_min: int = 5,
    annotation_func: Optional[Callable] = None,
    dark: bool = False,
) -> Optional[str]:
    """
    生成完整分时图（聚合 N 分钟 K 线，含 VWAP、Volume Profile 等）。

    参数
    ----
    code            股票代码，如 600519.SH
    date            交易日期，"today" 或 "YYYYMMDD"
    n_min           聚合粒度（分钟），如 1/3/5/15
    annotation_func 可选钩子：def annotate(ax_k, ctx: dict) -> None
    dark            True 时使用深色主题

    返回
    ----
    图片绝对路径字符串，失败返回 None
    """
    data = get_intraday(code, date)
    if not data or not data.get("rows"):
        print(f"[kline_chart] 分时无数据: {code}", file=sys.stderr)
        return None

    all_rows = data["rows"]
    pre_close = data["pre_close"]
    trade_date = data["date"]

    # 过滤空量 tick 和非交易时段
    is_hk = code.upper().endswith(".HK")
    end_time = "1600" if is_hk else "1500"
    rows = [r for r in all_rows if not (r["vol"] == 0 and r.get("cum_vol", 1) == 0)]
    rows = [r for r in rows if "0930" <= r["time"] <= end_time]
    if not rows:
        print(f"[kline_chart] 交易时间内无分时数据: {code}", file=sys.stderr)
        return None

    # ── 聚合 N 分钟 K 线 ──────────────────────────────────────
    bars = []
    for i in range(0, len(rows), n_min):
        chunk = rows[i:i + n_min]
        if not chunk:
            continue
        bars.append({
            "label": chunk[0]["time"],
            "open": chunk[0]["price"],
            "close": chunk[-1]["price"],
            "high": max(r["price"] for r in chunk),
            "low": min(r["price"] for r in chunk),
            "vol": sum(r["vol"] for r in chunk),
            "vwap": chunk[-1]["vwap"],
        })

    n = len(bars)
    xs = np.arange(n)
    opens = np.array([b["open"] for b in bars])
    closes = np.array([b["close"] for b in bars])
    highs = np.array([b["high"] for b in bars])
    lows = np.array([b["low"] for b in bars])
    vols = np.array([b["vol"] for b in bars])
    vwaps = np.array([b["vwap"] for b in bars])
    labels = [b["label"] for b in bars]

    pr = highs.max() - lows.min()
    pr = max(pr, closes[-1] * 0.001)
    off = pr * 0.015
    pct_now = (closes[-1] - pre_close) / pre_close * 100 if pre_close else 0.0
    avg_vol_pos = vols[vols > 0].mean() if np.any(vols > 0) else 1.0
    big_vol = [i for i in range(n) if vols[i] > avg_vol_pos * 1.8]

    hi_i = int(np.argmax(highs))
    lo_i = int(np.argmin(lows))
    aft_start = next((i for i, b in enumerate(bars) if b["label"] >= "1300"), n)

    # VWAP 穿越点自动检测
    vwap_cross = []
    for i in range(1, n):
        if closes[i - 1] >= vwaps[i - 1] and closes[i] < vwaps[i]:
            vwap_cross.append(("down", i))
        elif closes[i - 1] < vwaps[i - 1] and closes[i] >= vwaps[i]:
            vwap_cross.append(("up", i))

    # Volume Profile（分时）
    nb_intra = 30
    _, mid_i, bvol_i, poc_i, poc_price = _volume_profile(highs, lows, vols, nb_intra)
    pmin_i = lows.min()
    pmax_i = highs.max()

    def _ma_v(a: np.ndarray, w: int) -> np.ndarray:
        r = np.full(n, np.nan)
        for ii in range(w - 1, n):
            r[ii] = a[ii - w + 1:ii + 1].mean()
        return r

    # ── 主题色 ─────────────────────────────────────────────────
    T = _theme(dark)

    # ── 画布（3面板：主图 + 量 + 信息栏） ────────────────────
    fig = plt.figure(figsize=(20, 10), facecolor=T["fig_face"])
    gs = fig.add_gridspec(3, 1, height_ratios=[5, 1.2, 0.2], hspace=0.0)
    ax_k, ax_vol, ax_inf = [fig.add_subplot(gs[i]) for i in range(3)]
    fig.subplots_adjust(left=0.06, right=0.88, top=0.95, bottom=0.04, hspace=0.0)
    for ax in [ax_k, ax_vol, ax_inf]:
        ax.set_facecolor(T["ax_face"])
        ax.tick_params(colors=T["tick"], labelsize=8)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)

    # ── K 线本体 ───────────────────────────────────────────────
    for i in range(n):
        c = T["up"] if closes[i] >= opens[i] else T["down"]
        ax_k.plot([i, i], [lows[i], highs[i]], color=c, lw=0.9)
        ax_k.add_patch(plt.Rectangle(
            (i - 0.36, min(opens[i], closes[i])),
            0.72, max(abs(closes[i] - opens[i]), 0.001),
            color=c, zorder=3,
        ))

    # VWAP + 上下着色
    ax_k.plot(xs, vwaps, color="#FF8F00", lw=1.3, ls="--", label="VWAP", zorder=4)
    ax_k.fill_between(xs, closes, vwaps,
                      where=(closes >= vwaps), alpha=0.07, color="#D32F2F", interpolate=True)
    ax_k.fill_between(xs, closes, vwaps,
                      where=(closes < vwaps), alpha=0.07, color="#388E3C", interpolate=True)

    # ── 成交量面板 ─────────────────────────────────────────────
    vol_scale, vol_unit = (1e8, "亿股") if vols.max() > 5e7 else (1e4, "万股")
    vc = [
        "#E67E22" if i in big_vol else (T["vol_up"] if closes[i] >= opens[i] else T["vol_down"])
        for i in range(n)
    ]
    ax_vol.bar(xs, vols / vol_scale, color=vc, width=0.8, alpha=0.85)
    ax_vol.plot(xs, _ma_v(vols, 5) / vol_scale, color="#FF8F00", lw=0.9, alpha=0.85)
    ax_vol.set_ylabel(f"成交量({vol_unit})", fontsize=8)
    ax_vol.set_xticks([])

    # ── Volume Profile 左侧嵌入 ────────────────────────────────
    ax_vp = ax_k.inset_axes([0.0, 0.0, 0.06, 1.0])
    bc_i = [
        "#FF8F00" if b == poc_i else ("#E67E22" if bvol_i[b] > bvol_i.mean() * 1.5 else "#DDDDDD")
        for b in range(nb_intra)
    ]
    ax_vp.barh(mid_i, bvol_i / bvol_i.max(),
               height=(pmax_i - pmin_i) / nb_intra * 0.85, color=bc_i, alpha=0.2)
    ax_vp.axhline(poc_price, color="#FF8F00", lw=1.5, ls="--", alpha=0.9)
    ax_vp.text(0.5, poc_price + off * 0.3, f"POC\n{poc_price:.2f}",
               ha="center", fontsize=6.5, color="#E65100", va="bottom")
    ax_vp.set_ylim(ax_k.get_ylim())
    ax_vp.axis("off")

    # ── 午休分割线 ─────────────────────────────────────────────
    for ax_ in [ax_k, ax_vol]:
        ax_.axvline(aft_start - 0.5, color="#BBBBBB", lw=1.2, ls="--", alpha=0.6)
    ax_k.text(aft_start - 0.3, lows.min() + off, "午休", color="#999", fontsize=8, ha="left")

    # ── 标准固定标注 ───────────────────────────────────────────

    # 昨收水平线
    ax_k.axhline(pre_close, color="#888", lw=1.0, ls="--", alpha=0.6)
    ax_k.text(n - 1, pre_close - off, f" 昨收 {pre_close:.2f}", color="#888",
              va="top", fontsize=8)

    # 开盘方向
    open_pct_val = (opens[0] - pre_close) / pre_close * 100 if pre_close else 0.0
    open_dir = "高开" if open_pct_val > 0.5 else ("低开" if open_pct_val < -0.5 else "平开")
    ax_k.text(
        2, pre_close + off * 1.5,
        f"{open_dir} {open_pct_val:+.2f}%",
        fontsize=9, color="#666",
        bbox=dict(boxstyle="round,pad=0.2", fc="#F5F5F5", ec="#888", alpha=0.85),
    )

    # 日高 / 日低标注
    ax_k.annotate(
        f"日高 {highs[hi_i]:.2f}\n{labels[hi_i]}",
        xy=(hi_i, highs[hi_i]),
        xytext=(hi_i + 2, highs[hi_i] + off * 2),
        arrowprops=dict(arrowstyle="->", color="#D32F2F", lw=1.5),
        color="#D32F2F", fontsize=8.5, ha="left",
        bbox=dict(boxstyle="round,pad=0.2", fc="#FEECEC", alpha=0.9, ec="#D32F2F"),
    )
    ax_k.annotate(
        f"日低 {lows[lo_i]:.2f}\n{labels[lo_i]}",
        xy=(lo_i, lows[lo_i]),
        xytext=(lo_i - 2, lows[lo_i] - off * 2),
        arrowprops=dict(arrowstyle="->", color="#27AE60", lw=1.5),
        color="#27AE60", fontsize=8.5, ha="right",
        bbox=dict(boxstyle="round,pad=0.2", fc="#E8F5E9", alpha=0.9, ec="#27AE60"),
    )

    # VWAP 穿越标记
    for direction, idx in vwap_cross:
        col = "#388E3C" if direction == "up" else "#E74C3C"
        sym = "↑VWAP" if direction == "up" else "↓VWAP"
        ax_k.axvline(idx, color=col, lw=0.8, ls=":", alpha=0.6)
        ax_k.text(
            idx, vwaps[idx] + (off if direction == "up" else -off),
            sym, color=col, fontsize=7.5, ha="center", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", alpha=0.85, ec=col),
        )

    # 巨量标注（最多3个）
    for i in big_vol[:3]:
        ax_k.axvline(i, color="#FF6F00", lw=0.6, alpha=0.25)
        pct_bar = (closes[i] - opens[i]) / opens[i] * 100 if opens[i] else 0.0
        ax_k.annotate(
            f"巨量\n{pct_bar:+.1f}%",
            xy=(i, highs[i]),
            xytext=(min(i + 2, n - 3), highs[i] + pr * 0.05),
            fontsize=7, color="#E65100",
            bbox=dict(boxstyle="round,pad=0.2", fc="#FFF3E0", alpha=0.85),
            arrowprops=dict(arrowstyle="->", color="#FF6F00", lw=0.8),
        )

    # 尾盘趋势线（最后6根）
    if n > 6:
        tail_start = max(0, n - 6)
        slope = (closes[-1] - closes[tail_start]) / (n - 1 - tail_start)
        tcol = "#27AE60" if slope > 0 else "#E74C3C"
        ax_k.plot(
            [tail_start, n - 1], [closes[tail_start], closes[-1]],
            color=tcol, lw=2.0, ls="--", alpha=0.7,
        )
        ax_k.text(
            (tail_start + n - 1) // 2,
            (closes[tail_start] + closes[-1]) / 2 + off,
            "尾盘走强" if slope > 0 else "尾盘走弱",
            color=tcol, fontsize=8, ha="center",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8, ec=tcol),
        )

    # ── 用户自定义标注钩子 ─────────────────────────────────────
    ctx = {
        # 基础数据
        'xs': xs, 'dates': labels, 'n': n,
        'opens': opens, 'highs': highs, 'lows': lows, 'closes': closes, 'vols': vols,
        'vwaps': vwaps, 'labels': labels,
        'pre_close': pre_close, 'trade_date': trade_date,
        'pr': pr, 'off': off,
        'poc_price': poc_price,
        'big_vol': big_vol, 'vwap_cross': vwap_cross,
        'aft_start': aft_start,
        # 坐标轴
        'ax_k': ax_k, 'ax_vol': ax_vol,
    }
    if annotation_func is not None:
        annotation_func(ax_k, ctx)

    # ── 收尾：范围 / 图例 / 标题 ──────────────────────────────
    ax_k.set_xlim(-1, n + 6)
    ax_k.set_ylim(lows.min() - pr * 0.04, highs.max() + pr * 0.06)
    handles, labels_leg = ax_k.get_legend_handles_labels()
    if ax_k.get_legend():
        ax_k.get_legend().remove()
    if handles:
        fig.legend(
            handles, labels_leg, loc="upper center", ncol=len(handles),
            fontsize=7.5, framealpha=0.85,
            bbox_to_anchor=(0.47, 0.955), bbox_transform=fig.transFigure,
        )
    ax_k.set_ylabel("价格", fontsize=9)
    ax_k.set_xticks([])
    ax_k.grid(axis="y", color=T["grid"], lw=0.5)
    ax_vol.set_xlim(-1, n + 6)
    ax_inf.axis("off")
    ax_vp.set_ylim(ax_k.get_ylim())

    # X 轴整点刻度（显示在成交量面板底部）
    key_times = ["0930", "0945", "1000", "1030", "1100", "1130",
                 "1300", "1330", "1400", "1430", "1500"]
    tick_xs = [i for i, b in enumerate(bars) if b["label"] in key_times]
    tick_ls = [b["label"][:2] + ":" + b["label"][2:] for b in bars if b["label"] in key_times]
    ax_vol.set_xticks(tick_xs)
    ax_vol.set_xticklabels(tick_ls, fontsize=8)

    # 标题
    pct_sign = "▲" if pct_now >= 0 else "▼"
    pct_color = "#D32F2F" if pct_now >= 0 else "#388E3C"
    open_dir2 = '高' if opens[0] > pre_close else '低'
    open_pct2 = abs((opens[0] - pre_close) / pre_close * 100) if pre_close else 0.0
    fig.suptitle(
        f"{code}  {n_min}分钟分时    "
        f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}    "
        f"现价 {closes[-1]:.2f}  {pct_sign}{abs(pct_now):.2f}%    "
        f"{open_dir2}开 {open_pct2:.2f}%    VWAP穿越 {len(vwap_cross)}次    "
        f"量 {vols.sum() / vol_scale:.1f}{vol_unit}",
        fontsize=11, fontweight="bold", color=pct_color, x=0.47,
    )
    aft_vol = vols[aft_start:].sum()
    morn_vol = max(vols[:aft_start].sum(), 1)
    fig.text(
        0.5, 0.005,
        f"日高:{highs[hi_i]:.2f}({labels[hi_i]}) | 日低:{lows[lo_i]:.2f}({labels[lo_i]}) | "
        f"昨收:{pre_close:.2f} | VWAP:{vwaps[-1]:.2f} | "
        f"午后量能:{aft_vol / morn_vol:.0%}上午 | POC:{poc_price:.2f}",
        ha="center", fontsize=8, color="#333",
        bbox=dict(boxstyle="round,pad=0.3", fc="#F5F5F5", alpha=0.9),
    )

    # ── 保存 ────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"intraday_{code.replace('.', '_')}_annotated.png"
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out)


# ─────────────────────────────────────────────────────────────
#  向后兼容的旧函数名（供已有调用方使用）
# ─────────────────────────────────────────────────────────────

def build_chart(code: str, days: int = 120) -> Optional[str]:
    """向后兼容：等价于 build_full_chart(code, days)。"""
    return build_full_chart(code, days)


def build_intraday_chart(code: str, date: str = "today") -> Optional[str]:
    """向后兼容：等价于 build_intraday_full(code, date)。"""
    return build_intraday_full(code, date)


# ─────────────────────────────────────────────────────────────
#  命令行入口
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="K线 / 分时完整图生成")
    parser.add_argument("code", help="股票代码，如 600519.SH")
    parser.add_argument(
        "days_or_date", nargs="?", default=None,
        help="日K线：天数（默认120）；分时：today 或 YYYYMMDD（默认today）",
    )
    parser.add_argument(
        "--intraday", metavar="DATE", nargs="?", const="today", default=None,
        help="生成分时图，可指定日期（默认today）",
    )
    parser.add_argument(
        "--nmin", type=int, default=5,
        help="分时K线聚合粒度（分钟），默认5",
    )
    parser.add_argument(
        "--dark", action="store_true", default=False,
        help="使用深色主题",
    )
    args = parser.parse_args()

    if args.intraday is not None:
        date_arg = args.intraday if args.intraday != "today" else (args.days_or_date or "today")
        path = build_intraday_full(args.code, date_arg, n_min=args.nmin, dark=args.dark)
    else:
        days_arg = int(args.days_or_date) if args.days_or_date else 120
        path = build_full_chart(args.code, days_arg, dark=args.dark)

    if path:
        print(path)
    else:
        sys.exit(1)
