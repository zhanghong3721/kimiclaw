"""
iFinD 技术指标解析 - 将三行原始数据合并为结构化字典
"""


def parse_ifind_tech_data(raw_data: list) -> dict:
    """
    解析 iFind 技术指标原始数据（3行）

    Returns:
        结构化技术指标字典
    """
    if not raw_data or len(raw_data) < 3:
        return {"error": "数据不足，期望3行数据"}

    result = {
        "thscode": raw_data[0].get("thscode"),
        "time": raw_data[0].get("time", [None])[0],
        "interval": "5min",
    }

    # 第1行: MA5, MACD_DIFF, EXPMA5, BBI, KDJ_K, RSI6, CCI14, ROC, LB5, OBV, BOLL_MID, ATR14
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

    # 第2行: MA10, MACD_DEA, KDJ_D, BOLL_UPPER
    row2 = raw_data[1].get("table", {})
    result["MA10"]      = row2.get("MA",   [None])[0]
    result["MACD_DEA"]  = row2.get("MACD", [None])[0]
    result["KDJ_D"]     = row2.get("KDJ",  [None])[0]
    result["BOLL_UPPER"]= row2.get("BOLL", [None])[0]

    # 第3行: MA20, KDJ_J, BOLL_LOWER
    row3 = raw_data[2].get("table", {})
    result["MA20"]      = row3.get("MA",   [None])[0]
    result["KDJ_J"]     = row3.get("KDJ",  [None])[0]
    result["BOLL_LOWER"]= row3.get("BOLL", [None])[0]

    # MACD 柱状图
    if result["MACD_DIFF"] is not None and result["MACD_DEA"] is not None:
        result["MACD_BAR"] = result["MACD_DIFF"] - result["MACD_DEA"]

    return result
