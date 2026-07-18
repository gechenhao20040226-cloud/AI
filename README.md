"""单 Sheet 订单文件读取、表头定位、字段识别与基础类型解析。"""

from __future__ import annotations

import io
import re
from collections import OrderedDict
from datetime import datetime

import numpy as np
import pandas as pd


STANDARD_FIELDS = OrderedDict([
    ("order_id", "订单ID"),
    ("user_id", "用户ID"),
    ("product_id", "商品ID / SKU ID"),
    ("product_name", "商品名称"),
    ("order_date", "订单时间 / 支付时间"),
    ("quantity", "商品数量"),
    ("unit_price", "商品单价"),
    ("total_amount", "实付金额 / GMV"),
    ("payment_method", "支付方式"),
    ("status", "订单状态"),
    ("city", "城市 / 地区"),
    ("category", "商品品类"),
    ("user_level", "用户等级"),
])


FIELD_ALIASES = {
    "order_id": [
        "order_id", "orderid", "订单id", "订单号", "订单编号", "订单号码", "订单编码",
        "交易订单号", "商家订单号", "主订单号", "子订单号", "业务订单号", "原订单号",
        "外部订单号", "平台订单号", "流水号", "交易号", "订单流水号",
    ],
    "user_id": [
        "user_id", "userid", "customer_id", "customerid", "用户id", "客户id", "买家id",
        "买家uid", "用户uid", "会员id", "会员编号", "客户编号", "用户编号", "买家编号",
        "消费者id", "客户账号", "买家账号", "会员账号", "用户账号",
    ],
    "product_id": [
        "product_id", "productid", "sku_id", "skuid", "spu_id", "spuid", "商品id",
        "商品编号", "商品编码", "货品id", "货品编号", "货品编码", "sku编码", "sku编号",
        "spu编码", "spu编号", "商家编码", "商品款号", "商品货号", "货号",
    ],
    "product_name": [
        "product_name", "productname", "商品名称", "商品名", "产品名称", "产品名", "货品名称",
        "货品名", "sku名称", "spu名称", "商品标题", "宝贝名称", "宝贝标题", "标题",
    ],
    "order_date": [
        "order_date", "orderdate", "order_time", "ordertime", "订单日期", "订单时间", "下单日期",
        "下单时间", "创建时间", "订单创建时间", "支付时间", "付款时间", "支付成功时间",
        "成交时间", "交易时间", "结算时间", "完成时间", "统计日期", "日期", "时间",
    ],
    "quantity": [
        "quantity", "qty", "商品数量", "购买数量", "下单数量", "成交数量", "支付件数", "成交件数",
        "销售数量", "销量", "件数", "数量", "商品件数", "sku数量",
    ],
    "unit_price": [
        "unit_price", "unitprice", "商品单价", "成交单价", "销售单价", "支付单价", "实付单价",
        "折后单价", "sku单价", "价格", "售价", "单价",
    ],
    "total_amount": [
        "total_amount", "totalamount", "gmv", "实付金额", "用户实付", "买家实付", "客户实付",
        "用户支付金额", "买家支付金额", "实际支付金额", "支付金额", "付款金额",
        "订单实付", "订单实收", "实收金额", "成交金额", "交易金额", "订单金额", "订单总额",
        "销售金额", "销售额", "商品金额", "结算金额", "应收金额", "收入金额", "营业收入",
        "含税金额", "折后金额", "总价", "总金额", "金额",
    ],
    "payment_method": [
        "payment_method", "paymentmethod", "支付方式", "付款方式", "支付渠道", "付款渠道",
        "支付类型", "付款类型", "支付工具",
    ],
    "status": [
        "status", "order_status", "orderstatus", "订单状态", "交易状态", "支付状态", "付款状态",
        "订单完成状态", "售后状态", "状态",
    ],
    "city": [
        "city", "城市", "所在城市", "收货城市", "用户城市", "客户城市", "地区", "区域",
        "收货地区", "省市", "城市名称",
    ],
    "category": [
        "category", "商品分类", "商品品类", "品类", "类目", "一级类目", "一级品类",
        "产品分类", "商品类目", "主营类目", "分类",
    ],
    "user_level": [
        "user_level", "userlevel", "用户等级", "客户等级", "会员等级", "会员级别", "用户级别",
        "会员层级", "客户层级", "用户分层",
    ],
}


STATUS_ALIASES = {
    "completed": {
        "已完成", "完成", "订单完成", "交易完成", "交易成功", "支付成功", "付款成功", "已支付",
        "已付款", "已成交", "已收货", "确认收货", "已结算", "结算成功", "成功", "paid",
        "completed", "complete", "finished", "success", "succeeded", "settled", "received",
    },
    "cancelled": {
        "已取消", "取消", "订单取消", "交易取消", "已关闭", "交易关闭", "订单关闭", "关闭",
        "cancelled", "canceled", "cancel", "closed",
    },
    "refunded": {
        "退款", "已退款", "退款中", "退货退款", "退款成功", "全部退款", "部分退款",
        "售后退款", "refunded", "refund", "refunding", "partiallyrefunded",
    },
    "pending": {
        "待支付", "待付款", "未支付", "未付款", "待处理", "处理中", "待确认", "待发货",
        "已发货", "运输中", "pending", "unpaid", "processing", "shipped",
    },
    "failed": {"失败", "支付失败", "付款失败", "交易失败", "failed", "fail"},
}


def normalize_name(value) -> str:
    """把字段名压缩成适合规则匹配的形式。"""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().lower()
    return re.sub(r"[\s_\-—/\\|（）()\[\]{}【】<>《》:：,.，。]+", "", text)


NORMALIZED_ALIASES = {
    field: {normalize_name(alias) for alias in aliases}
    for field, aliases in FIELD_ALIASES.items()
}


def _field_match_score(column, field) -> int:
    name = normalize_name(column)
    if not name:
        return 0
    aliases = NORMALIZED_ALIASES[field]
    if name in aliases:
        return 100

    best = 0
    for alias in aliases:
        if len(alias) < 2:
            continue
        if alias in name:
            best = max(best, 70 + min(len(alias), 20))
        elif name in alias and len(name) >= 3:
            best = max(best, 45 + min(len(name), 20))

    # 避免把“商品金额/订单金额”误判为单价。
    if field == "unit_price" and "金额" in name and "单价" not in name:
        best = 0
    # 总金额优先于宽泛的“价格”。
    if field == "total_amount" and any(token in name for token in ["单价", "价格"]):
        best = 0
    return best


def suggest_column_mapping(columns) -> dict:
    """根据字段名生成一对一映射建议，最终仍由用户确认。"""
    candidates = []
    for column in columns:
        for field in STANDARD_FIELDS:
            score = _field_match_score(column, field)
            if score:
                candidates.append((score, str(column), field))

    mapping = {}
    used_columns = set()
    used_fields = set()
    for score, column, field in sorted(candidates, reverse=True):
        if score < 50 or column in used_columns or field in used_fields:
            continue
        mapping[field] = column
        used_columns.add(column)
        used_fields.add(field)
    return mapping


def _row_header_score(row) -> tuple[int, int]:
    values = [v for v in row.tolist() if not pd.isna(v) and str(v).strip()]
    if not values:
        return (-1, 0)
    fields = set()
    exact_hits = 0
    for value in values:
        scores = {field: _field_match_score(value, field) for field in STANDARD_FIELDS}
        if scores:
            field, score = max(scores.items(), key=lambda item: item[1])
            if score >= 50:
                fields.add(field)
            if score == 100:
                exact_hits += 1
    text_cells = sum(not _looks_numeric(v) for v in values)
    score = len(fields) * 30 + exact_hits * 8 + min(len(values), 20) + text_cells
    return score, len(fields)


def detect_header_row(raw_df: pd.DataFrame, max_rows: int = 30) -> int:
    """在文件前若干行中定位最可能的表头。"""
    if raw_df is None or raw_df.empty:
        return 0

    scored = []
    limit = min(max_rows, len(raw_df))
    for idx in range(limit):
        score, matched_fields = _row_header_score(raw_df.iloc[idx])
        scored.append((score, matched_fields, idx))

    strong = [item for item in scored if item[1] >= 2]
    if strong:
        return max(strong)[2]

    # 完全陌生的字段名：优先选择后续数据行列数基本一致的最早一行。
    row_counts = []
    for idx in range(limit):
        values = [v for v in raw_df.iloc[idx].tolist() if not pd.isna(v) and str(v).strip()]
        row_counts.append(len(values))
    for idx, count in enumerate(row_counts):
        if count < 2:
            continue
        following = [value for value in row_counts[idx + 1:idx + 4] if value > 0]
        if following and sum(abs(value - count) <= 1 for value in following) >= max(1, len(following) - 1):
            return idx
    return next((idx for idx, count in enumerate(row_counts) if count >= 2), 0)


def _looks_numeric(value) -> bool:
    if isinstance(value, (int, float, np.number)) and not pd.isna(value):
        return True
    text = str(value).strip()
    return bool(re.fullmatch(r"[¥￥$€£]?\s*\(?[-+]?\d[\d,，]*(?:\.\d+)?\)?\s*[元件万千亿]?", text))


def _dedupe_columns(values) -> list[str]:
    result = []
    counts = {}
    for index, value in enumerate(values, start=1):
        base = str(value).strip() if not pd.isna(value) and str(value).strip() else f"未命名列_{index}"
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")
    return result


def _read_csv_raw(file_bytes: bytes) -> tuple[pd.DataFrame, str]:
    errors = []
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "gbk", "big5"]:
        try:
            text = file_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
            continue

        candidates = []
        for sep in [None, ",", "\t", ";", "|"]:
            try:
                frame = pd.read_csv(
                    io.StringIO(text), header=None, sep=sep, engine="python",
                    dtype=object, on_bad_lines="skip",
                )
                if frame.empty:
                    continue
                header_index = detect_header_row(frame)
                header_score, matched_fields = _row_header_score(frame.iloc[header_index])
                # 先看能识别出的业务字段，再看保留下来的数据行数；自动嗅探结果作为轻微加分。
                candidate_score = (
                    matched_fields,
                    header_score,
                    min(len(frame), 10_000),
                    1 if sep is None else 0,
                    -abs(frame.shape[1] - 12),
                )
                candidates.append((candidate_score, frame))
            except Exception:
                continue
        if candidates:
            return max(candidates, key=lambda item: item[0])[1], encoding
    raise ValueError("CSV编码或分隔符无法识别，请另存为 UTF-8 CSV 或 Excel 后重试。")


def read_single_sheet_order_file(uploaded_file) -> tuple[pd.DataFrame, dict]:
    """读取 CSV 或 Excel 的第一个 Sheet，并自动定位表头。"""
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        raw, encoding = _read_csv_raw(file_bytes)
        source_info = {"file_type": "CSV", "encoding": encoding, "sheet": None}
    elif filename.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None, dtype=object)
        source_info = {"file_type": "Excel", "encoding": None, "sheet": "第一个Sheet"}
    else:
        raise ValueError("仅支持 CSV、XLSX 和 XLS 文件。")

    raw = raw.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if raw.empty:
        raise ValueError("文件中没有可读取的数据。")

    header_row = detect_header_row(raw)
    columns = _dedupe_columns(raw.iloc[header_row].tolist())
    df = raw.iloc[header_row + 1:].copy()
    df.columns = columns
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all").reset_index(drop=True)

    # 删除导出文件中夹带的重复表头行。
    if not df.empty:
        repeated_header = pd.Series(True, index=df.index)
        comparable = 0
        for column in df.columns:
            if column.startswith("未命名列_"):
                continue
            comparable += 1
            repeated_header &= df[column].astype(str).str.strip().eq(str(column).strip())
        if comparable:
            df = df.loc[~repeated_header].reset_index(drop=True)

    source_info.update({
        "header_row": int(header_row + 1),
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
    })
    return df, source_info


def apply_column_mapping(df: pd.DataFrame, field_to_source: dict) -> pd.DataFrame:
    """应用用户确认后的“标准字段 -> 原字段”映射。"""
    selected = {field: source for field, source in field_to_source.items() if source and source in df.columns}
    sources = list(selected.values())
    if len(sources) != len(set(sources)):
        raise ValueError("同一个原始字段不能同时映射到多个标准字段。")
    rename_map = {source: field for field, source in selected.items()}
    return df.rename(columns=rename_map).copy()


def parse_number(value):
    """解析货币、千分位、中文数量单位和括号负数。"""
    if value is None or pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.number)):
        return float(value)

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "n/a", "na", "--", "-"}:
        return np.nan

    negative = text.startswith("(") and text.endswith(")")
    multiplier = 1.0
    if "亿" in text:
        multiplier = 100_000_000.0
    elif "万" in text:
        multiplier = 10_000.0
    elif "千" in text:
        multiplier = 1_000.0

    cleaned = (
        text.replace("，", ",").replace(",", "")
        .replace("￥", "").replace("¥", "").replace("$", "")
        .replace("元", "").replace("件", "")
        .replace("亿", "").replace("万", "").replace("千", "")
        .replace("(", "").replace(")", "").strip()
    )
    cleaned = re.sub(r"[^0-9.+\-]", "", cleaned)
    try:
        number = float(cleaned) * multiplier
        return -abs(number) if negative else number
    except (TypeError, ValueError):
        return np.nan


def parse_number_series(series: pd.Series) -> pd.Series:
    return series.apply(parse_number).astype(float)


def parse_datetime_value(value):
    """兼容文本日期、Excel序列日期以及秒/毫秒时间戳。"""
    if value is None or pd.isna(value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value)

    if isinstance(value, (int, float, np.number)):
        number = float(value)
        if 20_000 <= number <= 80_000:
            return pd.Timestamp("1899-12-30") + pd.to_timedelta(number, unit="D")
        if 1_000_000_000 <= number < 10_000_000_000:
            return pd.to_datetime(number, unit="s", errors="coerce")
        if 1_000_000_000_000 <= number < 10_000_000_000_000:
            return pd.to_datetime(number, unit="ms", errors="coerce")

    text = re.sub(r"\.0$", "", str(value).strip())
    if re.fullmatch(r"\d{8}", text):
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if re.fullmatch(r"\d{5}(?:\.\d+)?", text):
        number = float(text)
        if 20_000 <= number <= 80_000:
            return pd.Timestamp("1899-12-30") + pd.to_timedelta(number, unit="D")
    if re.fullmatch(r"\d{10}", text):
        return pd.to_datetime(int(text), unit="s", errors="coerce")
    if re.fullmatch(r"\d{13}", text):
        return pd.to_datetime(int(text), unit="ms", errors="coerce")

    text = (
        text.replace("年", "-").replace("月", "-").replace("日", " ")
        .replace("/", "-").replace(".", "-").replace("：", ":").strip()
    )
    month_day = re.fullmatch(r"(\d{1,2})-(\d{1,2})(?:\s+.*)?", text)
    if month_day:
        text = f"{datetime.now().year}-{text}"
    return pd.to_datetime(text, errors="coerce")


def parse_datetime_series(series: pd.Series) -> pd.Series:
    return series.apply(parse_datetime_value)


def normalize_status_value(value) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    text = normalize_name(value)
    if not text:
        return "unknown"
    for status, aliases in STATUS_ALIASES.items():
        normalized_aliases = {normalize_name(alias) for alias in aliases}
        if text in normalized_aliases:
            return status
    # 对带前后缀的业务状态做保守包含匹配。
    for status, aliases in STATUS_ALIASES.items():
        for alias in aliases:
            token = normalize_name(alias)
            if len(token) >= 2 and token in text:
                return status
    return "unknown"


def normalize_status_series(series: pd.Series) -> pd.Series:
    return series.apply(normalize_status_value)


def validate_mapped_orders(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """返回阻断性错误和可继续处理的警告。"""
    errors = []
    warnings = []
    if df is None or df.empty:
        return ["文件中没有订单数据。"], warnings

    if "order_date" not in df.columns:
        warnings.append("缺少订单时间，仍可生成整体分析，但无法计算时间趋势和GMV环比。")
    if "total_amount" not in df.columns and not {"quantity", "unit_price"}.issubset(df.columns):
        errors.append("没有匹配实付金额，也没有同时匹配数量和单价，无法计算GMV。")
    if "order_id" not in df.columns:
        warnings.append("缺少订单ID，将把每一行暂时视为一笔订单，订单数和客单价可能不准确。")
    if "status" not in df.columns:
        warnings.append("缺少订单状态，将默认所有记录都参与分析。")
    if "user_id" not in df.columns:
        warnings.append("缺少用户ID，无法进行用户数和复购分析。")
    if "product_id" not in df.columns and "product_name" not in df.columns:
        warnings.append("缺少商品ID和商品名称，无法进行商品排行分析。")
    return errors, warnings
