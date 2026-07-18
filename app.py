"""
AI 电商分析助手 - Streamlit Dashboard

支持上传 CSV / Excel 数据，自动完成数据清洗、SQL 分析、异常检测与 AI 商业洞察生成。

运行方式：
    streamlit run app.py

API Key：
    请通过 .streamlit/secrets.toml 或环境变量配置 ZHIPU_API_KEY。
    不要将真实 API Key 提交到 GitHub。
"""

import os
import sys
import json
from datetime import datetime

import duckdb
import pandas as pd
import streamlit as st
import altair as alt
from openai import OpenAI

# 导入清洗 Pipeline
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_pipeline import clean_pipeline
from order_schema import (
    STANDARD_FIELDS,
    apply_column_mapping,
    normalize_status_series,
    read_single_sheet_order_file,
    suggest_column_mapping,
    validate_mapped_orders,
)


# =========================
# 页面配置
# =========================
st.set_page_config(
    page_title="AI 电商分析助手",
    page_icon="🛒",
    layout="wide"
)

conn = duckdb.connect(database=":memory:")

# Altair 图表使用浏览器字体渲染，中文标签更稳定，并且会随页面宽度自适应。


# =========================
# 基础工具函数
# =========================
def get_zhipu_api_key():
    """优先从 Streamlit secrets 读取，其次从环境变量读取。"""
    try:
        if "ZHIPU_API_KEY" in st.secrets:
            return st.secrets["ZHIPU_API_KEY"]
    except Exception:
        pass
    return os.getenv("ZHIPU_API_KEY")


def safe_int(value):
    try:
        if pd.isna(value):
            return 0
        return int(value)
    except Exception:
        return 0


def safe_float(value):
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def money_fmt(value):
    return f"¥{safe_float(value):,.2f}"


def pct_fmt(value):
    try:
        if pd.isna(value):
            return "—"
        return f"{float(value):.1f}%"
    except Exception:
        return "—"

def coalesce_duplicate_columns(df):
    """合并重复列名：同名列按从左到右取第一个非空值，避免 df['col'] 返回 DataFrame。"""
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
            # bfill(axis=1) 可取同名列中每行第一个非空值
            out[name] = cols.bfill(axis=1).iloc[:, 0]
    return out


def standardize_status(series):
    """统一订单状态字段为标准值。"""
    if series is None or series.empty:
        return pd.Series([], dtype=str)
    return normalize_status_series(series)



# =========================
# 数据加载与注册
# =========================
def load_default_data():
    """加载项目自带示例数据。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        df_orders = pd.read_csv(os.path.join(base_dir, "orders_cleaned.csv"))
        df_products = pd.read_csv(os.path.join(base_dir, "products.csv"))
        df_users = pd.read_csv(os.path.join(base_dir, "users.csv"))
        return df_orders, df_products, df_users
    except FileNotFoundError:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


def register_data(df_orders, df_products, df_users):
    """将 DataFrame 注册到 DuckDB。"""
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.execute("DROP TABLE IF EXISTS products")
    conn.execute("DROP TABLE IF EXISTS users")

    conn.register("orders", df_orders)

    if df_products is not None and not df_products.empty:
        # 字段兜底：确保 products 表有必需列
        for col, default in [("product_id", "unknown"), ("product_name", "unknown"), ("category", "未分类"), ("cost", None)]:
            if col not in df_products.columns:
                df_products[col] = default
        conn.register("products", df_products)
    else:
        conn.execute("""
            CREATE TABLE products (
                product_id VARCHAR,
                product_name VARCHAR,
                category VARCHAR,
                brand VARCHAR,
                price DOUBLE,
                cost DOUBLE
            )
        """)

    if df_users is not None and not df_users.empty:
        conn.register("users", df_users)
    else:
        conn.execute("""
            CREATE TABLE users (
                user_id VARCHAR,
                user_level VARCHAR,
                city VARCHAR
            )
        """)


# =========================
# 上传数据预处理
# =========================
def detect_missing_dimensions(upload_df):
    """判断上传数据是否缺失关键业务维度。"""
    upload_df = coalesce_duplicate_columns(upload_df)
    missing = []

    if "user_id" not in upload_df.columns:
        missing.append("user_id（用户维度）")
    else:
        s = upload_df["user_id"].astype(str).str.strip().str.lower()
        empty_ratio = s.isin(["", "nan", "none", "null", "unknown", "未知"]).mean()
        if empty_ratio > 0.9:
            missing.append("user_id（用户维度）")

    if "product_id" not in upload_df.columns and "product_name" not in upload_df.columns:
        missing.append("product_id/product_name（商品维度）")
    elif "product_id" in upload_df.columns:
        s = upload_df["product_id"].astype(str).str.strip().str.lower()
        empty_ratio = s.isin(["", "nan", "none", "null", "unknown", "未知"]).mean()
        if empty_ratio > 0.9 and "product_name" not in upload_df.columns:
            missing.append("product_id/product_name（商品维度）")

    if "order_date" not in upload_df.columns:
        missing.append("order_date（时间维度）")

    amount_can_be_calculated = {"quantity", "unit_price"}.issubset(upload_df.columns)
    if "total_amount" not in upload_df.columns and not amount_can_be_calculated:
        missing.append("total_amount（金额维度）")
    elif "total_amount" in upload_df.columns:
        amount_series = upload_df["total_amount"]
        if amount_series.dtype == object:
            amount_series = amount_series.astype(str).str.replace(r"[^\d\.-]", "", regex=True)
        amount_numeric = pd.to_numeric(amount_series, errors="coerce")
        valid_amount_ratio = ((amount_numeric.notna()) & (amount_numeric > 0)).mean()
        if valid_amount_ratio < 0.1 and not amount_can_be_calculated:
            missing.append("total_amount（金额维度）")

    if "category" not in upload_df.columns:
        missing.append("category（品类维度）")

    return missing


def prepare_orders_dataframe(df_orders):
    """防御性补全订单表必需字段，避免 SQL 崩溃。"""
    if df_orders is None or df_orders.empty:
        df_orders = pd.DataFrame()

    df = coalesce_duplicate_columns(df_orders.copy())

    required_defaults = {
        "is_anomaly": 0,
        "status": "completed",
        "user_id": "unknown",
        "product_id": "unknown",
        "order_date": pd.NaT,
        "total_amount": 0.0,
        "quantity": 1,
        "city": "未知",
        "order_id": "unknown",
        "unit_price": 0.0,
        "product_name": None,
        "category": "未分类",
        "user_level": "未知",
    }

    for col, default in required_defaults.items():
        if col not in df.columns:
            df[col] = default
        else:
            if isinstance(default, (int, float)):
                if df[col].dtype == object:
                    df[col] = df[col].astype(str).str.replace(r"[^\d\.-]", "", regex=True)
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)
            elif col == "order_date":
                df[col] = pd.to_datetime(df[col], errors="coerce")

    # 如果没有 total_amount 但有 quantity 和 unit_price，则计算总金额
    if "total_amount" in df.columns and (df["total_amount"].fillna(0) == 0).all():
        if "quantity" in df.columns and "unit_price" in df.columns:
            df["total_amount"] = df["quantity"] * df["unit_price"]

    # 优先保留清洗 Pipeline 已生成的状态；默认示例数据再从原始状态生成。
    allowed_statuses = {"completed", "cancelled", "refunded", "pending", "failed", "unknown"}
    if "status_norm" in df.columns:
        normalized = df["status_norm"].astype(str).str.strip().str.lower()
        invalid_status = ~normalized.isin(allowed_statuses)
        df["status_norm"] = normalized
        if invalid_status.any() and "status" in df.columns:
            df.loc[invalid_status, "status_norm"] = standardize_status(df.loc[invalid_status, "status"])
    elif "status" in df.columns:
        df["status_norm"] = standardize_status(df["status"])
    else:
        df["status_norm"] = "completed"

    # 日期无法识别的行会导致趋势图无意义，直接过滤
    df = df.dropna(subset=["order_date"]).copy()

    return df


# =========================
# SQL 分析
# =========================
def get_status_condition(selected_statuses=None):
    """根据页面选择生成安全的状态过滤条件。"""
    allowed = {"completed", "cancelled", "refunded", "pending", "failed", "unknown"}
    selected = [status for status in (selected_statuses or ["completed"]) if status in allowed]
    if not selected:
        return "1 = 0", "1 = 0"
    values = ", ".join(f"'{status}'" for status in selected)
    return f"status_norm IN ({values})", f"o.status_norm IN ({values})"


def run_analysis(granularity="月", selected_statuses=None):
    """执行核心经营分析。"""
    results = {}
    s_cond, o_s_cond = get_status_condition(selected_statuses)

    period_expr = (
        "SUBSTRING(CAST(order_date AS VARCHAR), 1, 7)"
        if granularity == "月"
        else "SUBSTRING(CAST(order_date AS VARCHAR), 1, 10)"
    )

    results["summary"] = conn.execute(f"""
        SELECT
            COUNT(DISTINCT order_id) AS total_orders,
            COUNT(DISTINCT user_id) AS unique_users,
            COUNT(DISTINCT product_id) AS products_sold,
            SUM(total_amount) AS total_gmv,
            SUM(total_amount) / NULLIF(COUNT(DISTINCT order_id), 0) AS avg_order_value
        FROM orders
        WHERE {s_cond}
    """).fetchdf().to_dict("records")[0]

    results["monthly"] = conn.execute(f"""
        SELECT
            {period_expr} AS period,
            COUNT(DISTINCT order_id) AS orders,
            SUM(total_amount) AS gmv,
            COUNT(DISTINCT user_id) AS users
        FROM orders
        WHERE {s_cond}
        GROUP BY 1
        ORDER BY 1
    """).df()

    results["top_products"] = conn.execute(f"""
        SELECT
            o.product_id,
            COALESCE(NULLIF(CAST(o.product_name AS VARCHAR), ''), p.product_name, o.product_id, '未知商品') AS product_name,
            COALESCE(NULLIF(CAST(o.category AS VARCHAR), ''), p.category, '未分类') AS category,
            SUM(o.quantity) AS total_qty,
            SUM(o.total_amount) AS revenue
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.product_id
        WHERE {o_s_cond}
        GROUP BY 1, 2, 3
        ORDER BY revenue DESC
        LIMIT 10
    """).df().to_dict("records")

    results["categories"] = conn.execute(f"""
        SELECT
            COALESCE(NULLIF(CAST(o.category AS VARCHAR), ''), p.category, '未分类') AS category,
            COUNT(DISTINCT o.order_id) AS orders,
            SUM(o.total_amount) AS gmv,
            SUM(o.quantity) AS qty
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.product_id
        WHERE {o_s_cond}
        GROUP BY 1
        ORDER BY gmv DESC
    """).df()

    # 用户分析：始终基于 orders 表聚合。
    # user_level 来自 orders 表本身（prepare_orders_dataframe 默认填充为"未知"，上传数据自带则有真实值）。
    # 不在 SQL 里 LEFT JOIN users 表，避免 user_id 格式不匹配导致等级永远是"未知"。
    results["users"] = conn.execute(f"""
        SELECT
            user_id,
            COALESCE(NULLIF(CAST(user_level AS VARCHAR), ''), '未知') AS user_level,
            COALESCE(NULLIF(CAST(city AS VARCHAR), ''), '未知') AS city,
            COUNT(DISTINCT order_id) AS order_count,
            COALESCE(SUM(total_amount), 0) AS total_spend
        FROM orders
        WHERE {s_cond}
          AND user_id IS NOT NULL
          AND LOWER(CAST(user_id AS VARCHAR)) NOT IN ('', 'unknown', 'nan', 'none', 'null', '未知')
        GROUP BY 1, 2, 3
        ORDER BY total_spend DESC NULLS LAST
        LIMIT 20
    """).df()

    results["repurchase"] = conn.execute(f"""
        SELECT
            user_level,
            COUNT(*) AS users,
            AVG(order_count) AS avg_orders,
            AVG(total_spend) AS avg_spend,
            SUM(CASE WHEN order_count >= 2 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) AS repurchase_rate
        FROM (
            SELECT
                user_id,
                COALESCE(NULLIF(CAST(user_level AS VARCHAR), ''), '未知') AS user_level,
                COUNT(DISTINCT order_id) AS order_count,
                COALESCE(SUM(total_amount), 0) AS total_spend
            FROM orders
            WHERE {s_cond}
              AND user_id IS NOT NULL
              AND LOWER(CAST(user_id AS VARCHAR)) NOT IN ('', 'unknown', 'nan', 'none', 'null', '未知')
            GROUP BY 1, 2
        ) t
        GROUP BY 1
        ORDER BY avg_spend DESC
    """).df()

    results["order_status"] = conn.execute("""
        SELECT
            status_norm AS status,
            COUNT(DISTINCT order_id) AS orders,
            COUNT(DISTINCT order_id) * 100.0
                / NULLIF((SELECT COUNT(DISTINCT order_id) FROM orders), 0) AS pct
        FROM orders
        GROUP BY 1
        ORDER BY orders DESC
    """).df()

    results["anomalies"] = {
        "high_value_orders": conn.execute(f"""
            WITH order_totals AS (
                SELECT
                    order_id,
                    ANY_VALUE(user_id) AS user_id,
                    MIN(order_date) AS order_date,
                    SUM(quantity) AS quantity,
                    SUM(total_amount) AS total_amount,
                    STRING_AGG(DISTINCT status_norm, ', ') AS status_norm,
                    MAX(is_anomaly) AS is_anomaly
                FROM orders
                WHERE {s_cond}
                GROUP BY order_id
            ), threshold AS (
                SELECT AVG(total_amount) * 3 AS value FROM order_totals
            )
            SELECT order_totals.*
            FROM order_totals, threshold
            WHERE order_totals.total_amount > threshold.value
            ORDER BY total_amount DESC
            LIMIT 10
        """).df().to_dict("records"),
        "flagged_orders": conn.execute(f"""
            SELECT COUNT(DISTINCT order_id) AS count
            FROM orders
            WHERE is_anomaly = 1 AND {s_cond}
        """).fetchdf().to_dict("records")[0],
    }

    return results


def calc_gmv_change(monthly_df):
    """计算最新一期 GMV 环比。"""
    if monthly_df is None or len(monthly_df) < 2:
        return "—", None

    df = monthly_df.sort_values("period").tail(2)
    current = safe_float(df.iloc[-1]["gmv"])
    previous = safe_float(df.iloc[-2]["gmv"])

    if previous <= 0:
        return "—", None

    change = (current - previous) / previous * 100
    return f"{change:+.1f}%", change


def get_recommended_granularity():
    try:
        distinct_dates = conn.execute("""
            SELECT COUNT(DISTINCT SUBSTRING(CAST(order_date AS VARCHAR), 1, 10))
            FROM orders
            WHERE order_date IS NOT NULL
        """).fetchone()[0]
        return "日" if distinct_dates and int(distinct_dates) <= 31 else "月"
    except Exception:
        return "月"


def build_margin_df(selected_statuses=None):
    """当 products 表存在 cost 字段且不为全空时，计算品类毛利。"""
    try:
        columns = conn.execute("DESCRIBE products").df()["column_name"].tolist()
        if "cost" not in columns:
            return pd.DataFrame()
        # 检查 cost 是否全为 NULL
        cost_count = conn.execute("SELECT COUNT(*) FROM products WHERE cost IS NOT NULL").fetchone()[0]
        if cost_count == 0:
            return pd.DataFrame()

        _, o_s_cond = get_status_condition(selected_statuses)
        return conn.execute(f"""
            SELECT
                COALESCE(NULLIF(CAST(o.category AS VARCHAR), ''), p.category, '未分类') AS category,
                SUM(o.total_amount) AS revenue,
                SUM(p.cost * o.quantity) AS total_cost,
                SUM(o.total_amount) - SUM(p.cost * o.quantity) AS gross_profit,
                (SUM(o.total_amount) - SUM(p.cost * o.quantity))
                    / NULLIF(SUM(o.total_amount), 0) * 100 AS gross_margin_pct
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.product_id
            WHERE {o_s_cond} AND p.cost IS NOT NULL
            GROUP BY 1
            ORDER BY gross_profit DESC
        """).df()
    except Exception:
        return pd.DataFrame()


# =========================
# 商业分析
# =========================
def make_json_safe(obj):
    """让 DataFrame / numpy / Timestamp 类型可以被 json.dumps 处理。"""
    # DataFrame / Series 先递归转换，避免 Timestamp 残留
    if isinstance(obj, pd.DataFrame):
        return make_json_safe(obj.to_dict("records"))
    if isinstance(obj, pd.Series):
        return make_json_safe(obj.to_dict())

    # dict / list / tuple 递归处理
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_json_safe(v) for v in obj]

    # pandas / numpy 的时间类型
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat() if not pd.isna(obj) else None

    # numpy 标量
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
    except Exception:
        pass

    # NaN / NaT / None
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass

    # 最后兜底：如果不是 JSON 基础类型，就转字符串
    if not isinstance(obj, (str, int, float, bool, type(None))):
        return str(obj)
    return obj


def get_ai_insights(analysis_data, missing_dimensions=None):
    """调用 GLM-4-Flash 生成商业报告。"""
    api_key = get_zhipu_api_key()
    if not api_key:
        return "❌ 未找到 ZHIPU_API_KEY。请在 .streamlit/secrets.toml 或环境变量中配置。"

    missing_dimensions = missing_dimensions or []
    missing_context = "无"
    if missing_dimensions:
        missing_context = json.dumps(missing_dimensions, ensure_ascii=False, indent=2)

    safe_data = make_json_safe(analysis_data)

    prompt = f"""你是一个专业的电商数据分析师。请基于下面真实统计数据，生成一份简洁但有业务价值的中文分析报告。

【关键要求】
1. 只能基于给出的统计结果分析，不能编造数据。
2. 如果出现 unknown、未知、未分类，必须把它当作数据质量问题提示，不能强行做用户画像或商品判断。
3. 如果缺失维度里包含 user_id（用户维度），用户分析部分必须明确写：原数据缺乏用户维度，无法分析。
4. 建议要具体，不要写空话。
5. 语气像企业内部数据分析报告，不要太学术。

【缺失维度】
{missing_context}

【分析数据】
{json.dumps(safe_data, ensure_ascii=False, indent=2, default=str)}

请严格按以下结构输出：

### 1. 核心销售结论
- 用 2-4 条 bullet 总结 GMV、订单数、客单价、趋势。

### 2. Top 商品与品类表现
- 说明销售贡献最高的商品/品类。
- 如果商品或品类为 unknown/未分类，要指出这是数据质量问题。

### 3. 异常订单与数据质量提醒
- 解释异常订单数量、高价值订单情况。
- 指出可能影响分析准确性的字段缺失问题。

### 4. 用户分析
- 如果用户维度缺失，直接说明无法分析。
- 如果用户维度存在，分析高价值用户、复购或用户等级表现。

### 5. 下一步经营建议
- 给 3 条具体建议。
"""

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {"role": "system", "content": "你是严谨、务实的电商数据分析师。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.45,
            max_tokens=2200,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"API 调用失败：{e}"


# =========================
# Session State
# =========================
if "upload_success" not in st.session_state:
    st.session_state["upload_success"] = False
if "missing_dimensions" not in st.session_state:
    st.session_state["missing_dimensions"] = []
if "clean_report" not in st.session_state:
    st.session_state["clean_report"] = []
if "upload_has_user_level" not in st.session_state:
    st.session_state["upload_has_user_level"] = False


# =========================
# 数据初始化
# =========================
df_orders, df_products, df_users = load_default_data()

if st.session_state.get("upload_success") and "uploaded_df" in st.session_state:
    df_orders = st.session_state["uploaded_df"]
    # 自定义订单不能与项目自带的模拟商品/用户表混用，否则相同ID会造成错误补数。
    df_products = pd.DataFrame()
    df_users = pd.DataFrame()

# 补全示例/上传后的订单数据
if df_orders is not None and not df_orders.empty:
    df_orders = prepare_orders_dataframe(df_orders)
else:
    df_orders = prepare_orders_dataframe(pd.DataFrame())

if df_orders.empty:
    st.warning("⚠️ 当前没有可分析的有效订单数据，请上传包含有效日期的订单表。")

register_data(df_orders, df_products, df_users)


# =========================
# 主界面：标题与上传
# =========================
st.title("🛒 AI 电商分析助手")
st.caption("上传订单数据后，系统会自动完成数据清洗、SQL 指标分析、异常检测与 AI 商业洞察生成。")
st.markdown("---")

if not st.session_state.get("upload_success"):
    st.markdown("""
    <div style='text-align: center; padding: 18px 0 10px 0;'>
        <h3 style='color: #333;'>📂 上传您的订单数据，立即生成分析报表</h3>
        <p style='color: #888; font-size: 15px;'>支持 CSV、Excel (.xlsx / .xls) 格式；不上传也可直接预览默认示例数据。</p>
    </div>
    """, unsafe_allow_html=True)

    _, upload_col, _ = st.columns([1, 2, 1])
    with upload_col:
        uploaded_orders = st.file_uploader(
            "拖拽文件到此处，或点击选择文件",
            type=["csv", "xlsx", "xls"],
            label_visibility="visible"
        )

        if uploaded_orders is not None:
            st.markdown(f"**已选择文件：** `{uploaded_orders.name}`")
            try:
                raw_upload_df, source_info = read_single_sheet_order_file(uploaded_orders)
                suggested_mapping = suggest_column_mapping(raw_upload_df.columns)

                source_text = (
                    f"已读取 {source_info['rows']:,} 行、{source_info['columns']} 列，"
                    f"识别第 {source_info['header_row']} 行为表头"
                )
                if source_info.get("encoding"):
                    source_text += f"，编码 {source_info['encoding']}"
                st.success("✅ " + source_text)

                with st.expander("预览原始数据（前10行）", expanded=False):
                    st.dataframe(raw_upload_df.head(10), width="stretch", hide_index=True)

                st.markdown("#### 确认字段对应关系")
                st.caption("系统已自动选择最可能的字段。请重点确认订单时间、实付金额和订单ID；不需要的字段保持“不使用”。")

                source_columns = [str(column) for column in raw_upload_df.columns]
                options = ["不使用"] + source_columns
                field_to_source = {}

                with st.form("field_mapping_form"):
                    left_col, right_col = st.columns(2)
                    for index, (field, label) in enumerate(STANDARD_FIELDS.items()):
                        suggested_source = suggested_mapping.get(field)
                        default_index = options.index(suggested_source) if suggested_source in options else 0
                        target_col = left_col if index % 2 == 0 else right_col
                        with target_col:
                            selected = st.selectbox(
                                f"{label}  →  `{field}`",
                                options=options,
                                index=default_index,
                                key=f"mapping_{field}_{uploaded_orders.name}",
                            )
                            field_to_source[field] = None if selected == "不使用" else selected

                    submitted = st.form_submit_button(
                        "✅ 确认字段并开始分析", type="primary", width="stretch"
                    )

                if submitted:
                    try:
                        mapped_df = apply_column_mapping(raw_upload_df, field_to_source)
                        validation_errors, validation_warnings = validate_mapped_orders(mapped_df)

                        if validation_errors:
                            for message in validation_errors:
                                st.error("❌ " + message)
                        else:
                            missing_dimensions = detect_missing_dimensions(mapped_df)
                            cleaned_df, clean_report = clean_pipeline(
                                mapped_df,
                                df_products=pd.DataFrame(),
                                df_users=pd.DataFrame(),
                            )
                            cleaned_df = prepare_orders_dataframe(cleaned_df)

                            if cleaned_df.empty:
                                st.error("❌ 清洗后没有有效订单。请重新检查订单时间字段是否选择正确。")
                            else:
                                st.session_state["upload_success"] = True
                                st.session_state["upload_count"] = len(cleaned_df)
                                st.session_state["upload_order_count"] = int(cleaned_df["order_id"].nunique())
                                st.session_state["upload_name"] = uploaded_orders.name
                                st.session_state["uploaded_df"] = cleaned_df
                                st.session_state["clean_report"] = validation_warnings + clean_report
                                st.session_state["missing_dimensions"] = missing_dimensions
                                st.session_state["upload_has_user_level"] = "user_level" in mapped_df.columns
                                st.session_state["source_info"] = source_info
                                st.session_state["confirmed_mapping"] = {
                                    field: source for field, source in field_to_source.items() if source
                                }
                                st.rerun()
                    except ValueError as exc:
                        st.error(f"❌ 字段设置有问题：{exc}")
                    except Exception as exc:
                        st.error(f"❌ 数据清洗失败：{exc}")
            except Exception as exc:
                st.error(f"❌ 文件读取失败：{exc}")

    st.markdown("---")
    st.markdown("<div style='text-align:center;color:#aaa;font-size:13px;'>当前展示默认示例数据</div>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
else:
    info_col, reset_col = st.columns([5, 1])
    with info_col:
        st.success(
            f"✅ 已加载：**{st.session_state.get('upload_name', '自定义数据')}** | "
            f"共 **{st.session_state.get('upload_count', 0):,}** 条有效明细，"
            f"对应 **{st.session_state.get('upload_order_count', 0):,}** 个去重订单"
        )
    with reset_col:
        if st.button("🔄 重新上传", width="stretch"):
            for key in ["upload_success", "uploaded_df", "upload_count", "upload_order_count", "upload_name", "clean_report", "missing_dimensions", "upload_has_user_level", "last_insights", "data_quality_report", "source_info", "confirmed_mapping"]:
                st.session_state.pop(key, None)
            st.rerun()

    clean_report = st.session_state.get("clean_report", [])
    missing_dimensions = st.session_state.get("missing_dimensions", [])

    with st.expander("查看数据清洗报告 / 数据质量提醒", expanded=False):
        confirmed_mapping = st.session_state.get("confirmed_mapping", {})
        if confirmed_mapping:
            mapping_display = pd.DataFrame([
                {"标准字段": field, "原始字段": source}
                for field, source in confirmed_mapping.items()
            ])
            st.markdown("**本次字段对应关系**")
            st.dataframe(mapping_display, width="stretch", hide_index=True)

        if clean_report:
            for item in clean_report:
                st.write(f"- {item}")
        else:
            st.write("- 未发现明显需要修复的脏数据，或清洗脚本未返回报告。")

        if missing_dimensions:
            st.warning("关键维度缺失：" + "、".join(missing_dimensions))

    st.markdown("---")


# =========================
# 粒度选择与分析执行
# =========================
recommended_granularity = get_recommended_granularity()
control_col1, control_col2 = st.columns([1, 2])
with control_col1:
    granularity = st.radio(
        "📅 趋势图",
        options=["月", "日"],
        index=0 if recommended_granularity == "月" else 1,
        horizontal=True,
        help="数据跨度较短时建议选择「日」，长期数据建议选择「月」。"
    )

status_labels = {
    "completed": "已完成 / 已支付",
    "pending": "处理中 / 已发货",
    "refunded": "退款",
    "cancelled": "取消 / 关闭",
    "failed": "失败",
    "unknown": "未识别状态",
}
available_statuses = conn.execute(
    "SELECT DISTINCT status_norm FROM orders WHERE status_norm IS NOT NULL ORDER BY status_norm"
).df()["status_norm"].astype(str).tolist()
default_statuses = ["completed"] if "completed" in available_statuses else available_statuses[:1]
with control_col2:
    selected_statuses = st.multiselect(
        "✅ 参与GMV分析的订单状态",
        options=available_statuses,
        default=default_statuses,
        format_func=lambda value: status_labels.get(value, value),
        help="不同业务对有效订单的定义不同，请按实际口径选择。退款、取消默认不计入GMV。",
    )

if not selected_statuses:
    st.warning("⚠️ 当前没有选择任何有效订单状态，分析结果将为空。")

results = run_analysis(granularity=granularity, selected_statuses=selected_statuses)
summary = results["summary"]
monthly = results["monthly"]
gmv_change_text, gmv_change_value = calc_gmv_change(monthly)


# =========================
# KPI 指标卡
# =========================
# 判断关键维度是否缺失
missing_dimensions = st.session_state.get("missing_dimensions", [])
user_missing = "user_id（用户维度）" in missing_dimensions

# 检查全表是否存在有效金额，不能只看第一行
try:
    amount_stats = conn.execute("""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN total_amount IS NOT NULL AND total_amount > 0 THEN 1 ELSE 0 END) AS valid_amount_rows
        FROM orders
    """).df()
    valid_amount_rows = safe_int(amount_stats.loc[0, "valid_amount_rows"]) if not amount_stats.empty else 0
    amount_actually_missing = valid_amount_rows == 0
except Exception:
    amount_actually_missing = True

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
with kpi1:
    st.metric("总订单数", f"{safe_int(summary.get('total_orders')):,}")
with kpi2:
    if user_missing:
        st.metric("总用户数", "—")
    else:
        st.metric("总用户数", f"{safe_int(summary.get('unique_users')):,}")
with kpi3:
    if amount_actually_missing:
        st.metric("总 GMV", "—")
    else:
        st.metric("总 GMV", money_fmt(summary.get("total_gmv")))
with kpi4:
    if amount_actually_missing:
        st.metric("客单价", "—")
    else:
        st.metric("客单价", money_fmt(summary.get("avg_order_value")))
with kpi5:
    if amount_actually_missing:
        st.metric("GMV 环比", "—")
    else:
        st.metric("GMV 环比", gmv_change_text, delta=gmv_change_text if gmv_change_value is not None else None)


st.markdown("---")


# =========================
# 三个主 Tab
# =========================
tab_overview, tab_product, tab_insight = st.tabs([
    "📊 销售总览",
    "🏆 商品分析",
    "🤖 商业分析"
])


# -------------------------
# Tab 1：销售总览
# -------------------------
with tab_overview:
    period_label = "日" if granularity == "日" else "月"
    st.subheader(f"📈 销售趋势（按{period_label}汇总）")

    if len(monthly) > 0 and all(c in monthly.columns for c in ["period", "gmv", "orders"]):
        monthly_plot = monthly.copy()
        monthly_plot["period"] = monthly_plot["period"].astype(str)

        st.subheader("GMV 趋势")
        st.caption("展示每个时间周期的销售额变化，用折线图观察整体增长或下滑趋势。")
        gmv_chart = (
            alt.Chart(monthly_plot)
            .mark_line(point=True)
            .encode(
                x=alt.X("period:N", title="时间", sort=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("gmv:Q", title="销售额 GMV"),
                tooltip=[
                    alt.Tooltip("period:N", title="时间"),
                    alt.Tooltip("gmv:Q", title="销售额 GMV", format=",.2f"),
                    alt.Tooltip("orders:Q", title="订单数"),
                    alt.Tooltip("users:Q", title="用户数"),
                ],
            )
            .properties(height=360)
        )
        st.altair_chart(gmv_chart, width="stretch")

        st.subheader("订单数趋势")
        st.caption("展示每个时间周期的订单数量变化，用折线图观察订单量趋势。")
        orders_chart = (
            alt.Chart(monthly_plot)
            .mark_line(point=True)
            .encode(
                x=alt.X("period:N", title="时间", sort=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("orders:Q", title="订单数"),
                tooltip=[
                    alt.Tooltip("period:N", title="时间"),
                    alt.Tooltip("orders:Q", title="订单数"),
                    alt.Tooltip("gmv:Q", title="销售额 GMV", format=",.2f"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(orders_chart, width="stretch")
    else:
        st.info("ℹ️ 暂无销售趋势数据。")

    st.subheader(f"{period_label}度数据明细")
    monthly_display = monthly.copy()
    if "gmv" in monthly_display.columns:
        monthly_display["gmv"] = monthly_display["gmv"].apply(money_fmt)
    monthly_display = monthly_display.rename(columns={
        "period": "时间",
        "orders": "订单数",
        "gmv": "销售额 GMV",
        "users": "用户数",
    })
    st.dataframe(monthly_display, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("订单状态分布")
    status_df = results.get("order_status", pd.DataFrame())
    if len(status_df) > 0:
        status_display = status_df.copy()
        status_display["pct"] = status_display["pct"].apply(pct_fmt)
        status_display = status_display.rename(columns={
            "status": "订单状态",
            "orders": "订单数",
            "pct": "占比",
        })
        st.dataframe(status_display, width="stretch", hide_index=True)
    else:
        st.info("ℹ️ 暂无订单状态数据。")


# -------------------------
# Tab 2：商品分析
# -------------------------
with tab_product:
    top_df = pd.DataFrame(results["top_products"])
    cat_df = results["categories"]

    st.subheader("🔥 Top 10 商品（按销售额）")
    if len(top_df) > 0 and "revenue" in top_df.columns:
        top_plot_df = top_df.sort_values("revenue", ascending=False).copy()
        top_plot_df["product_name"] = top_plot_df["product_name"].astype(str)
        top_plot_df["category"] = top_plot_df["category"].astype(str)

        st.caption("按销售额排序，展示贡献最高的商品。")
        top_chart = (
            alt.Chart(top_plot_df)
            .mark_bar()
            .encode(
                x=alt.X("revenue:Q", title="销售额"),
                y=alt.Y("product_name:N", title="商品名称", sort="-x"),
                color=alt.Color("category:N", title="品类"),
                tooltip=[
                    alt.Tooltip("product_name:N", title="商品名称"),
                    alt.Tooltip("category:N", title="品类"),
                    alt.Tooltip("revenue:Q", title="销售额", format=",.2f"),
                    alt.Tooltip("total_qty:Q", title="销量"),
                ],
            )
            .properties(height=max(320, min(520, len(top_plot_df) * 36)))
        )
        st.altair_chart(top_chart, width="stretch")

        top_display = top_df.copy()
        top_display["revenue"] = top_display["revenue"].apply(money_fmt)
        top_display = top_display.rename(columns={
            "product_id": "商品ID",
            "product_name": "商品名称",
            "category": "品类",
            "total_qty": "销量",
            "revenue": "销售额",
        })
        st.dataframe(top_display, width="stretch", hide_index=True)
    else:
        st.info("ℹ️ 暂无商品销售数据。")

    st.markdown("---")
    st.subheader("📦 品类销售分布")
    if len(cat_df) > 0 and all(c in cat_df.columns for c in ["category", "gmv"]):
        cat_plot_df = cat_df.copy()
        cat_plot_df = cat_plot_df[cat_plot_df["gmv"].fillna(0) > 0].sort_values("gmv", ascending=False)

        if len(cat_plot_df) > 0:
            cat_plot_df["category"] = cat_plot_df["category"].astype(str)
            st.markdown("**品类销售额占比**")
            st.caption("展示各品类在总 GMV 中的占比。")
            pie_chart = (
                alt.Chart(cat_plot_df)
                .mark_arc(innerRadius=55)
                .encode(
                    theta=alt.Theta("gmv:Q", title="销售额 GMV"),
                    color=alt.Color("category:N", title="品类"),
                    tooltip=[
                        alt.Tooltip("category:N", title="品类"),
                        alt.Tooltip("gmv:Q", title="销售额 GMV", format=",.2f"),
                        alt.Tooltip("orders:Q", title="订单数"),
                        alt.Tooltip("qty:Q", title="销量"),
                    ],
                )
                .properties(height=430)
            )
            st.altair_chart(pie_chart, width="stretch")

            st.markdown("**各品类 GMV 对比**")
            st.caption("用于对比不同品类的绝对销售额大小。")
            category_bar = (
                alt.Chart(cat_plot_df)
                .mark_bar()
                .encode(
                    x=alt.X("category:N", title="品类", sort="-y", axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("gmv:Q", title="销售额 GMV"),
                    tooltip=[
                        alt.Tooltip("category:N", title="品类"),
                        alt.Tooltip("gmv:Q", title="销售额 GMV", format=",.2f"),
                        alt.Tooltip("orders:Q", title="订单数"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(category_bar, width="stretch")
        else:
            st.info("ℹ️ 当前品类 GMV 均为空或小于等于 0，无法绘制品类图。")

        cat_display = cat_df.copy()
        cat_display["gmv"] = cat_display["gmv"].apply(money_fmt)
        cat_display = cat_display.rename(columns={
            "category": "品类",
            "orders": "订单数",
            "gmv": "销售额 GMV",
            "qty": "销量",
        })
        st.subheader("品类明细")
        st.dataframe(cat_display, width="stretch", hide_index=True)
    else:
        st.info("ℹ️ 暂无品类数据。")

    margin_df = build_margin_df(selected_statuses)
    if len(margin_df) > 0:
        st.markdown("---")
        st.subheader("💹 品类毛利分析")
        margin_display = margin_df.copy()
        for col in ["revenue", "total_cost", "gross_profit"]:
            if col in margin_display.columns:
                margin_display[col] = margin_display[col].apply(money_fmt)
        if "gross_margin_pct" in margin_display.columns:
            margin_display["gross_margin_pct"] = margin_display["gross_margin_pct"].apply(pct_fmt)
        margin_display = margin_display.rename(columns={
            "category": "品类",
            "revenue": "销售额",
            "total_cost": "总成本",
            "gross_profit": "毛利",
            "gross_margin_pct": "毛利率",
        })
        st.dataframe(margin_display, width="stretch", hide_index=True)


# -------------------------
# Tab 3：商业分析
# -------------------------
with tab_insight:
    missing_dimensions = st.session_state.get("missing_dimensions", [])
    user_missing = "user_id（用户维度）" in missing_dimensions
    upload_has_user_level = st.session_state.get("upload_has_user_level", False)
    repurchase_df = results["repurchase"]
    users_df = results["users"]

    # 判断 user_level 是否有效：优先用上传时的检测标志（上传数据本身有字段则为真），
    # 若上传数据无 user_level 则切换为消费行为分析。
    has_valid_user_level = False
    if not user_missing and upload_has_user_level and len(repurchase_df) > 0 and "user_level" in repurchase_df.columns:
        non_unknown_count = repurchase_df[repurchase_df["user_level"] != "未知"].shape[0]
        if non_unknown_count > 0:
            has_valid_user_level = True

    # 兜底判断：即使 upload_has_user_level=True，若 avg_spend 全为 0 或 order_count 全为 0，
    # 说明等级与订单无法匹配，强制切换为消费行为分析。
    switch_to_consumption = False
    if has_valid_user_level and len(repurchase_df) > 0:
        avg_spend_all_zero = (repurchase_df["avg_spend"].fillna(0) == 0).all()
        order_count_all_zero = (repurchase_df["avg_orders"].fillna(0) == 0).all()
        if avg_spend_all_zero or order_count_all_zero:
            switch_to_consumption = True
    elif not user_missing and not upload_has_user_level:
        # 上传数据无 user_level 字段时，直接切换为消费行为分析
        switch_to_consumption = True

    if user_missing:
        st.subheader("👥 用户消费行为分析")
        st.warning("⚠️ 原数据缺乏用户维度，无法进行用户分析。")
    elif has_valid_user_level and not switch_to_consumption:
        # 有有效 user_level 时：显示等级分析
        st.subheader("👥 用户等级分析")
        u_col1, u_col2 = st.columns(2)
        with u_col1:
            spend_chart = (
                alt.Chart(repurchase_df)
                .mark_bar()
                .encode(
                    x=alt.X("user_level:N", title="用户等级", sort="-y", axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("avg_spend:Q", title="平均消费金额"),
                    tooltip=[
                        alt.Tooltip("user_level:N", title="用户等级"),
                        alt.Tooltip("avg_spend:Q", title="平均消费金额", format=",.2f"),
                        alt.Tooltip("users:Q", title="用户数"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(spend_chart, width="stretch")
        with u_col2:
            repurchase_chart = (
                alt.Chart(repurchase_df)
                .mark_bar()
                .encode(
                    x=alt.X("user_level:N", title="用户等级", sort="-y", axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("repurchase_rate:Q", title="复购率"),
                    tooltip=[
                        alt.Tooltip("user_level:N", title="用户等级"),
                        alt.Tooltip("repurchase_rate:Q", title="复购率", format=".1f"),
                        alt.Tooltip("users:Q", title="用户数"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(repurchase_chart, width="stretch")
        repurchase_display = repurchase_df.copy()
        repurchase_display["avg_spend"] = repurchase_display["avg_spend"].apply(money_fmt)
        repurchase_display["repurchase_rate"] = repurchase_display["repurchase_rate"].apply(pct_fmt)
        repurchase_display = repurchase_display.rename(columns={
            "user_level": "用户等级",
            "users": "用户数",
            "avg_orders": "平均订单数",
            "avg_spend": "平均消费金额",
            "repurchase_rate": "复购率",
        })
        st.dataframe(repurchase_display, width="stretch", hide_index=True)
    else:
        # 切换为订单用户消费行为分析
        st.subheader("👥 用户消费行为分析")
        if switch_to_consumption:
            st.info("ℹ️ 当前数据未提供有效用户等级，已展示订单用户消费分析。")

        if len(users_df) > 0 and "total_spend" in users_df.columns:
            top10_df = users_df.head(10).copy()
            top10_plot = top10_df.sort_values("total_spend", ascending=False).copy()
            top10_plot["user_id"] = top10_plot["user_id"].astype(str)

            st.caption("按用户累计消费金额排序，展示高价值用户。")
            user_spend_chart = (
                alt.Chart(top10_plot)
                .mark_bar()
                .encode(
                    x=alt.X("total_spend:Q", title="消费金额"),
                    y=alt.Y("user_id:N", title="用户ID", sort="-x"),
                    tooltip=[
                        alt.Tooltip("user_id:N", title="用户ID"),
                        alt.Tooltip("total_spend:Q", title="消费金额", format=",.2f"),
                        alt.Tooltip("order_count:Q", title="订单数"),
                    ],
                )
                .properties(height=max(320, min(520, len(top10_plot) * 36)))
            )
            st.altair_chart(user_spend_chart, width="stretch")

        if len(users_df) > 0 and "order_count" in users_df.columns:
            st.subheader("📊 用户订单次数分布")
            st.caption("展示下单 1 次、2 次、3 次等不同订单次数的用户数量，适合观察用户复购情况。")

            order_dist = (
                users_df.groupby("order_count", as_index=False)
                .agg(users=("user_id", "nunique"))
                .sort_values("order_count")
            )
            order_dist["order_count_label"] = order_dist["order_count"].astype(int).astype(str) + " 单"

            order_count_chart = (
                alt.Chart(order_dist)
                .mark_bar()
                .encode(
                    x=alt.X(
                        "order_count_label:N",
                        title="订单次数",
                        sort=order_dist["order_count_label"].tolist(),
                        axis=alt.Axis(labelAngle=0),
                    ),
                    y=alt.Y("users:Q", title="用户数"),
                    tooltip=[
                        alt.Tooltip("order_count_label:N", title="订单次数"),
                        alt.Tooltip("users:Q", title="用户数"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(order_count_chart, width="stretch")

        if len(users_df) > 0:
            st.subheader("💰 高价值用户 Top 20 明细")
            users_display = users_df.head(20).copy()
            users_display["total_spend"] = users_display["total_spend"].apply(money_fmt)
            users_display = users_display.rename(columns={
                "user_id": "用户ID",
                "user_level": "用户等级",
                "city": "城市",
                "order_count": "订单数",
                "total_spend": "累计消费金额",
            })
            st.dataframe(users_display, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("⚠️ 异常订单检测")
    anomalies = results["anomalies"]
    flagged_count = anomalies.get("flagged_orders", {}).get("count", 0)
    high_value_orders = anomalies.get("high_value_orders") or []

    a_col1, a_col2 = st.columns(2)
    with a_col1:
        st.metric("被规则标记异常订单", f"{safe_int(flagged_count):,}")
    with a_col2:
        st.metric("高价值订单（>3倍均值）", f"{len(high_value_orders):,}")

    if high_value_orders:
        high_value_display = pd.DataFrame(high_value_orders)
        if "total_amount" in high_value_display.columns:
            high_value_display["total_amount"] = high_value_display["total_amount"].apply(money_fmt)
        high_value_display = high_value_display.rename(columns={
            "order_id": "订单ID",
            "user_id": "用户ID",
            "product_id": "商品ID",
            "product_name": "商品名称",
            "category": "品类",
            "order_date": "订单时间",
            "quantity": "数量",
            "unit_price": "单价",
            "total_amount": "订单金额",
            "status": "原始状态",
            "status_norm": "标准状态",
            "city": "城市",
            "is_anomaly": "是否异常",
        })
        st.dataframe(high_value_display, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("🚀 商业报告生成")
    st.info("点击按钮后，系统会基于当前统计结果生成销售结论、商品/品类表现、异常检测、用户分析与经营建议。")

    if st.button("🚀 生成 AI 报告", type="primary", width="stretch"):
        with st.spinner("AI 正在分析当前数据..."):
            safe_results = dict(results)

            if user_missing:
                safe_results["summary"] = dict(results["summary"])
                safe_results["summary"]["unique_users"] = None
                safe_results["users"] = [{"message": "原数据缺乏用户维度，无法分析"}]
                safe_results["repurchase"] = pd.DataFrame([{"message": "原数据缺乏用户维度，无法分析"}])

            insights = get_ai_insights(safe_results, missing_dimensions)
            st.session_state["last_insights"] = insights
            st.markdown("---")
            st.markdown(insights)
            st.download_button(
                label="⬇️ 下载 AI 洞察报告",
                data=insights,
                file_name=f"ai_insights_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                width="stretch",
            )


# =========================
# 页脚
# =========================
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "AI 电商分析助手 | Streamlit + DuckDB + Altair + GLM-4-Flash"
    "</div>",
    unsafe_allow_html=True,
)
