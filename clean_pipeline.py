"""订单清洗 Pipeline：保留原始业务含义，只修复能够安全确定的问题。"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from order_schema import (
    normalize_status_series,
    parse_datetime_series,
    parse_number_series,
)


def _coalesce_duplicate_columns(df):
    """同名列按从左到右取每行第一个非空值。"""
    if df is None or df.empty or df.columns.is_unique:
        return df
    out = pd.DataFrame(index=df.index)
    for name in pd.unique(df.columns):
        columns = df.loc[:, df.columns == name]
        out[name] = columns.iloc[:, 0] if columns.shape[1] == 1 else columns.bfill(axis=1).iloc[:, 0]
    return out


def _blank_mask(series):
    return series.isna() | series.astype(str).str.strip().str.lower().isin(
        {"", "nan", "none", "null", "unknown", "未知"}
    )


def _main_category_value(value):
    """将类目路径压缩为主类目；主类目为空时再回退到后续小类目。"""
    if value is None or pd.isna(value):
        return "未分类"

    text = str(value).strip()
    if not text:
        return "未分类"

    # 常见后台会导出“家居生活/厨房餐具/水杯”一类完整类目路径。
    # 品类分析只保留第一个有效层级，避免把二、三级类目拆成大量碎片。
    parts = re.split(r"\s*(?:/|＞|>|→|\|)\s*", text)
    invalid = {"", "nan", "none", "null", "unknown", "未知", "未分类"}
    for part in parts:
        candidate = part.strip()
        if candidate.lower() not in invalid:
            return candidate
    return "未分类"


def normalize_main_category_series(series):
    """批量提取主类目。"""
    return series.apply(_main_category_value)


def clean_pipeline(df_orders, df_products=None, df_users=None, anomaly_threshold=None):
    """
    清洗单 Sheet 订单数据，返回 ``(清洗后数据, 清洗报告)``。

    原则：
    - 可确定的格式问题自动修复；
    - 负数、零值等可能具有业务含义的数据只标记，不擅自取绝对值；
    - 0 元订单保留，只有真正缺失的金额才尝试用数量×单价补齐。
    """
    if df_orders is None:
        return pd.DataFrame(), ["未读取到订单数据"]

    df = _coalesce_duplicate_columns(df_orders.copy())
    report = []

    # 1. 数值字段解析
    for column in ["quantity", "unit_price", "total_amount"]:
        if column not in df.columns:
            continue
        before_valid = int(df[column].notna().sum())
        df[column] = parse_number_series(df[column])
        invalid = max(before_valid - int(df[column].notna().sum()), 0)
        if invalid:
            report.append(f"{column} 有 {invalid} 条无法解析，已保留为空值并标记检查")

    if "quantity" not in df.columns:
        df["quantity"] = 1.0
        report.append("缺少 quantity → 默认每行数量为 1")
    else:
        missing_quantity = int(df["quantity"].isna().sum())
        if missing_quantity:
            df["quantity"] = df["quantity"].fillna(1.0)
            report.append(f"quantity 缺失 {missing_quantity} 条 → 默认数量为 1")

    if "is_anomaly" in df.columns:
        df["is_anomaly"] = parse_number_series(df["is_anomaly"]).fillna(0)
    else:
        df["is_anomaly"] = 0

    # 2. 状态保留原值，同时生成统一分析状态
    if "status" in df.columns:
        df["status"] = df["status"].where(df["status"].notna(), "未知").astype(str).str.strip()
        df["status_norm"] = normalize_status_series(df["status"])
        unknown_count = int((df["status_norm"] == "unknown").sum())
        if unknown_count:
            report.append(f"订单状态有 {unknown_count} 条未识别，可在分析页决定是否纳入")
    else:
        df["status"] = "未提供状态"
        df["status_norm"] = "completed"

    # 3. 安全的缺失值处理
    if "payment_method" in df.columns:
        missing = int(_blank_mask(df["payment_method"]).sum())
        if missing:
            df.loc[_blank_mask(df["payment_method"]), "payment_method"] = "未知"
            report.append(f"payment_method 缺失 {missing} 条 → 填充“未知”")

    if "city" in df.columns:
        missing_city = _blank_mask(df["city"])
        missing_count = int(missing_city.sum())
        if (
            missing_count and df_users is not None and not df_users.empty
            and {"user_id", "city"}.issubset(df_users.columns) and "user_id" in df.columns
        ):
            user_city = (
                df_users.dropna(subset=["user_id"]).drop_duplicates("user_id")
                .set_index("user_id")["city"]
            )
            df.loc[missing_city, "city"] = df.loc[missing_city, "user_id"].map(user_city)
            report.append(f"city 缺失 {missing_count} 条 → 已尝试用本次提供的用户表补充")
        df.loc[_blank_mask(df["city"]), "city"] = "未知"

    # 品类分析优先使用商品主类目。
    # 例如“家居生活/厨房餐具/水杯”统一归为“家居生活”；
    # 当前层级为空或未分类时，才回退到后续小类目。
    if "category" in df.columns:
        original_category = df["category"].copy()
        df["category"] = normalize_main_category_series(df["category"])
        simplified_count = int(
            original_category.fillna("").astype(str).str.strip().ne(df["category"].astype(str)).sum()
        )
        if simplified_count:
            report.append(
                f"category 有 {simplified_count} 条完整类目路径 → 已按商品主类目汇总"
            )

    # 4. 只删除完全相同的重复明细，不误删同一订单中的合法商品行
    duplicate_subset = [c for c in df.columns if c not in {"is_anomaly", "status_norm"}]
    duplicate_mask = df.duplicated(subset=duplicate_subset, keep="first") if duplicate_subset else pd.Series(False, index=df.index)
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        df = df.loc[~duplicate_mask].copy()
        report.append(f"完全重复的订单明细 {duplicate_count} 条 → 已删除")

    # 5. 日期格式统一
    if "order_date" in df.columns:
        df["order_date"] = parse_datetime_series(df["order_date"])
        invalid_date = int(df["order_date"].isna().sum())
        if invalid_date:
            df = df.loc[df["order_date"].notna()].copy()
            report.append(f"无效订单时间 {invalid_date} 条 → 已从分析数据中排除")

    # 6. 仅在价格真正缺失时，尝试使用本次提供的商品表补充
    if "unit_price" not in df.columns:
        df["unit_price"] = np.nan
    missing_price = df["unit_price"].isna()
    if (
        missing_price.any() and df_products is not None and not df_products.empty
        and {"product_id", "price"}.issubset(df_products.columns) and "product_id" in df.columns
    ):
        product_price = (
            df_products.dropna(subset=["product_id"]).drop_duplicates("product_id")
            .set_index("product_id")["price"].apply(lambda value: parse_number_series(pd.Series([value])).iloc[0])
        )
        df.loc[missing_price, "unit_price"] = df.loc[missing_price, "product_id"].map(product_price)
        filled = int((missing_price & df["unit_price"].notna()).sum())
        if filled:
            report.append(f"unit_price 缺失值中有 {filled} 条通过商品表补充")

    # 7. 金额只补空值，合法的0元订单不改写
    if "total_amount" not in df.columns:
        df["total_amount"] = df["quantity"] * df["unit_price"]
        report.append("缺少 total_amount → 已按 quantity × unit_price 计算")
    else:
        missing_amount = df["total_amount"].isna()
        computable = missing_amount & df["quantity"].notna() & df["unit_price"].notna()
        if computable.any():
            df.loc[computable, "total_amount"] = df.loc[computable, "quantity"] * df.loc[computable, "unit_price"]
            report.append(f"total_amount 缺失值中有 {int(computable.sum())} 条按 quantity × unit_price 补齐")

    unresolved_amount = int(df["total_amount"].isna().sum())
    if unresolved_amount:
        df.loc[df["total_amount"].isna(), "is_anomaly"] = 1
        df["total_amount"] = df["total_amount"].fillna(0)
        report.append(f"仍有 {unresolved_amount} 条金额无法计算 → 金额暂记0并标记异常")

    # 8. 补齐分析标识，但不伪装成真实业务字段
    if "order_id" not in df.columns:
        df["order_id"] = [f"ROW{i:07d}" for i in range(1, len(df) + 1)]
        report.append("缺少 order_id → 已生成临时行ID，每行暂按一笔订单计算")
    else:
        missing_order_id = _blank_mask(df["order_id"])
        if missing_order_id.any():
            replacements = [f"ROW{i:07d}" for i in range(1, int(missing_order_id.sum()) + 1)]
            df.loc[missing_order_id, "order_id"] = replacements
            report.append(f"order_id 缺失 {int(missing_order_id.sum())} 条 → 已生成临时行ID")

    distinct_orders = int(df["order_id"].nunique(dropna=True))
    if distinct_orders < len(df):
        report.append(
            f"识别为订单明细表：{len(df):,} 行商品明细对应 {distinct_orders:,} 个去重订单，"
            "订单数和客单价将按订单ID计算"
        )
        if "status_norm" in df.columns:
            mixed_status_orders = int(df.groupby("order_id")["status_norm"].nunique().gt(1).sum())
            if mixed_status_orders:
                report.append(f"有 {mixed_status_orders} 个订单包含多种明细状态，请确认平台状态口径")

    if "product_id" not in df.columns:
        if "product_name" in df.columns:
            df["product_id"] = df["product_name"].astype(str)
        else:
            df["product_id"] = "unknown_product"
    elif "product_name" in df.columns:
        missing_product_id = _blank_mask(df["product_id"])
        df.loc[missing_product_id, "product_id"] = df.loc[missing_product_id, "product_name"].astype(str)

    # 9. 异常只标记，不擅自修改业务值
    if anomaly_threshold is None:
        positive_quantity = df.loc[df["quantity"] > 0, "quantity"]
        if len(positive_quantity) >= 2 and positive_quantity.std() > 0:
            anomaly_threshold = max(round(positive_quantity.mean() + 3 * positive_quantity.std()), 10)
        else:
            anomaly_threshold = 20

    abnormal_quantity = (df["quantity"] <= 0) | (df["quantity"] > anomaly_threshold)
    abnormal_price = df["unit_price"].notna() & (df["unit_price"] < 0)
    abnormal_amount = df["total_amount"] < 0
    anomaly_mask = abnormal_quantity | abnormal_price | abnormal_amount
    if anomaly_mask.any():
        df.loc[anomaly_mask, "is_anomaly"] = 1
        report.append(
            f"业务异常值 {int(anomaly_mask.sum())} 条 → 已标记，未自动改变正负号或删除"
        )

    df["is_anomaly"] = df["is_anomaly"].fillna(0).astype(int)
    return df.reset_index(drop=True), report