"""
清洗 Pipeline 封装
用于 app.py 上传链路：处理缺失值、重复订单、日期、金额、数量、异常订单等。
重点：对脏 Excel 中的金额字符串（¥7,999、7999元、-99、空值）做强制数值化，避免比较时报错。
"""
import pandas as pd
import numpy as np


def _coalesce_duplicate_columns(df):
    """合并重复列名，避免 df['col'] 返回 DataFrame。"""
    if df is None or df.empty:
        return df
    if df.columns.is_unique:
        return df
    out = pd.DataFrame(index=df.index)
    for name in pd.unique(df.columns):
        cols = df.loc[:, df.columns == name]
        if cols.shape[1] == 1:
            out[name] = cols.iloc[:, 0]
        else:
            out[name] = cols.bfill(axis=1).iloc[:, 0]
    return out


def _series(df, col):
    """安全取列：即使有重复列名，也返回一维 Series。"""
    obj = df[col]
    if isinstance(obj, pd.DataFrame):
        return obj.bfill(axis=1).iloc[:, 0]
    return obj


def _to_number(series, default=0.0):
    """把金额/数量字段强制转为数字：支持 ¥、￥、逗号、中文单位、空值等。"""
    if series is None:
        return series
    s = series.copy()
    if s.dtype == object:
        s = (
            s.astype(str)
            .str.strip()
            .str.replace('，', ',', regex=False)
            .str.replace(',', '', regex=False)
            .str.replace('￥', '', regex=False)
            .str.replace('¥', '', regex=False)
            .str.replace('元', '', regex=False)
            .str.replace('件', '', regex=False)
            .str.replace(r'[^0-9\.\-]', '', regex=True)
        )
        s = s.replace({'': np.nan, 'nan': np.nan, 'None': np.nan})
    return pd.to_numeric(s, errors='coerce').fillna(default)


def clean_pipeline(df_orders, df_products=None, df_users=None, anomaly_threshold=None):
    """
    对上传的订单数据执行清洗，返回 (清洗后DataFrame, 清洗报告list)。
    anomaly_threshold: 可选，每行订单 quantity 超过此值则标记异常；
                       若不传，则动态计算为 mean + 3 * std（最低 10）。
    """
    df = _coalesce_duplicate_columns(df_orders.copy())
    report = []

    # 0. 先强制数值化，避免 'str' 和 int 比较时报错
    numeric_defaults = {
        'quantity': 1,
        'unit_price': 0.0,
        'total_amount': 0.0,
        'is_anomaly': 0,
    }
    for col, default in numeric_defaults.items():
        if col in df.columns:
            raw_col = _series(df, col)
            before_na = int(raw_col.isna().sum())
            df[col] = _to_number(raw_col, default=default)
            after_zero_or_default = int((df[col] == default).sum()) if col != 'is_anomaly' else 0
            if before_na > 0:
                report.append(f"{col} 存在空值 {before_na} 条 → 已按默认值处理")

    # 1. 计算动态异常阈值
    if anomaly_threshold is None:
        if len(df) > 0 and 'quantity' in df.columns:
            q_mean = df['quantity'].mean()
            q_std = df['quantity'].std()
            if pd.notna(q_std) and q_std > 0:
                computed = round(q_mean + 3 * q_std)
                anomaly_threshold = max(computed, 10)
            else:
                anomaly_threshold = 20
        else:
            anomaly_threshold = 20

    # 2. 标准化 status 列
    if 'status' in df.columns:
        df['status'] = (
            df['status'].astype(str)
            .str.strip()
            .str.replace('：', ':', regex=False)
            .str.replace(' ', '', regex=False)
            .str.lower()
        )

        done_variants = {'已完成', '完成', 'paid', 'completed', 'success', '已支付', '交易完成', '成功'}
        cancel_variants = {'已取消', '取消', 'cancelled', 'canceled', 'cancel'}
        refund_variants = {'退款', '已退款', '退款中', 'refunded', 'refund'}

        done_count = int(df['status'].isin(done_variants).sum())
        cancel_count = int(df['status'].isin(cancel_variants).sum())
        refund_count = int(df['status'].isin(refund_variants).sum())

        df.loc[df['status'].isin(done_variants), 'status'] = '已完成'
        df.loc[df['status'].isin(cancel_variants), 'status'] = '已取消'
        df.loc[df['status'].isin(refund_variants), 'status'] = '退款中'

        if done_count > 0:
            report.append(f"status 列标准化：{done_count} 条记录统一为'已完成'")
        if cancel_count > 0 or refund_count > 0:
            report.append(f"status 列识别取消/退款订单：{cancel_count + refund_count} 条")

    # 3. 缺失值
    if 'payment_method' in df.columns and df['payment_method'].isna().sum() > 0:
        n = int(df['payment_method'].isna().sum())
        df['payment_method'] = df['payment_method'].fillna('未知')
        report.append(f"payment_method 缺失 {n} 条 → 填充'未知'")

    if 'city' in df.columns and df['city'].isna().sum() > 0:
        n = int(df['city'].isna().sum())
        if df_users is not None and not df_users.empty and 'user_id' in df.columns and 'user_id' in df_users.columns and 'city' in df_users.columns:
            user_city_map = df_users.set_index('user_id')['city'].to_dict()
            na_mask = df['city'].isna()
            df.loc[na_mask, 'city'] = df.loc[na_mask, 'user_id'].map(user_city_map)
            report.append(f"city 缺失 {n} 条 → 尝试通过用户表关联补充")
        df['city'] = df['city'].fillna('未知')

    # 4. 重复订单
    dedup_cols = [c for c in ['order_id', 'user_id', 'product_id', 'order_date', 'quantity'] if c in df.columns]
    if dedup_cols:
        before = len(df)
        df = df.drop_duplicates(subset=dedup_cols, keep='first').copy()
        removed = before - len(df)
        if removed > 0:
            report.append(f"重复订单 {removed} 条 → 已删除")

    # 5. 时间格式统一
    if 'order_date' in df.columns:
        def normalize_datetime(x):
            if pd.isna(x):
                return x
            x = str(x).strip().replace('：', ':').replace('/', '-')
            return x

        df['order_date'] = df['order_date'].apply(normalize_datetime)
        df['order_date'] = pd.to_datetime(df['order_date'], errors='coerce')
        invalid = int(df['order_date'].isna().sum())
        if invalid > 0:
            df = df[df['order_date'].notna()].copy()
            report.append(f"无效日期 {invalid} 条 → 已删除")

    # 6. 异常价格
    if 'unit_price' in df.columns:
        negative = int((df['unit_price'] < 0).sum())
        if negative > 0:
            df['unit_price'] = df['unit_price'].abs()
            report.append(f"负数价格 {negative} 条 → 取绝对值")

        zero_mask = df['unit_price'] == 0
        zero = int(zero_mask.sum())
        if zero > 0 and df_products is not None and not df_products.empty and 'product_id' in df.columns and 'product_id' in df_products.columns and 'price' in df_products.columns:
            price_map = df_products.set_index('product_id')['price'].to_dict()
            for idx in df[zero_mask].index:
                pid = df.loc[idx, 'product_id']
                if pid in price_map:
                    df.loc[idx, 'unit_price'] = price_map[pid]
            report.append(f"零价格 {zero} 条 → 尝试用商品原价填充")

    # 7. 重新计算/补齐 total_amount
    if 'quantity' in df.columns and 'unit_price' in df.columns:
        # 如果 total_amount 不存在或全为 0，使用 quantity * unit_price；否则保留上传表里的实付金额/营业收入
        if 'total_amount' not in df.columns:
            df['total_amount'] = df['quantity'] * df['unit_price']
            report.append("total_amount 缺失 → 已按 quantity × unit_price 计算")
        else:
            zero_or_missing = df['total_amount'].isna() | (df['total_amount'] == 0)
            if zero_or_missing.any():
                df.loc[zero_or_missing, 'total_amount'] = df.loc[zero_or_missing, 'quantity'] * df.loc[zero_or_missing, 'unit_price']
                report.append(f"total_amount 空值/零值 {int(zero_or_missing.sum())} 条 → 已按 quantity × unit_price 补齐")

        large_mask = df['quantity'] > anomaly_threshold
        large_qty = int(large_mask.sum())
        if 'is_anomaly' not in df.columns:
            df['is_anomaly'] = 0
        if large_qty > 0:
            df.loc[large_mask, 'is_anomaly'] = 1
            report.append(f"超大数量(>{anomaly_threshold}) {large_qty} 条 → 标记 is_anomaly=1")

    # 8. 空 product_id
    if 'product_id' in df.columns:
        missing_mask = df['product_id'].isna() | (df['product_id'].astype(str).str.strip() == '')
        missing_pid = int(missing_mask.sum())
        if missing_pid > 0:
            df = df[~missing_mask].copy()
            report.append(f"空 product_id {missing_pid} 条 → 已删除")

    return df, report
