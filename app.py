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
import re
import json
from datetime import datetime

import duckdb
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from openai import OpenAI

# 导入清洗 Pipeline
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_pipeline import clean_pipeline


# =========================
# 页面配置
# =========================
st.set_page_config(
    page_title="AI 电商分析助手",
    page_icon="🛒",
    layout="wide"
)

conn = duckdb.connect(database=":memory:")

# Matplotlib 全局配置：使用静态图，减少移动端/Safari 前端模块加载失败的概率
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


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
    """统一订单状态字段为标准值：completed, cancelled, refunded, pending, failed, unknown。"""
    if series is None or series.empty:
        return pd.Series([], dtype=str)

    completed_aliases = {
        "已完成", "完成", "成功", "交易成功", "支付成功", "已支付",
        "paid", "completed", "complete", "finished", "success", "succeeded"
    }
    cancelled_aliases = {"取消", "已取消", "已关闭", "关闭", "cancelled", "canceled", "closed"}
    refunded_aliases = {"退款", "已退款", "退货退款", "refunded", "refund"}
    pending_aliases = {"待支付", "待付款", "pending", "未支付", "未付款", "unpaid"}
    failed_aliases = {"失败", "支付失败", "failed", "fail"}

    def norm(val):
        if pd.isna(val):
            return "unknown"
        s = str(val).strip().lower()
        if s in {a.lower() for a in refunded_aliases}:
            return "refunded"
        if s in {a.lower() for a in cancelled_aliases}:
            return "cancelled"
        if s in {a.lower() for a in pending_aliases}:
            return "pending"
        if s in {a.lower() for a in failed_aliases}:
            return "failed"
        if s in {a.lower() for a in completed_aliases}:
            return "completed"
        return "unknown"

    return series.apply(norm)



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


def load_uploaded_file(uploaded_file):
    """加载用户上传的 CSV / Excel 文件。"""
    if uploaded_file is None:
        return None
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".csv"):
            return pd.read_csv(uploaded_file)
        return pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"❌ 文件解析失败：{e}")
        return None


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
def basic_rule_column_mapping(df):
    """基于规则的中文/常见字段名兜底映射。尽量避免多个原始列映射到同一标准列。"""
    mapping = {}
    used_targets = set()

    def add(col, target, replace=False):
        if col in mapping:
            return
        if target in used_targets and not replace:
            return
        mapping[col] = target
        used_targets.add(target)

    # 第一轮：优先级最高的明确字段
    for col in df.columns:
        c = str(col).strip().lower()
        if ("订单" in c and ("号" in c or "id" in c)) or "order id" in c:
            add(col, "order_id")
        elif ("商品" in c and ("id" in c or "编号" in c)) or "product id" in c:
            add(col, "product_id")
        elif c in ["商品名", "商品名称", "产品名", "产品名称", "sku名称"] or "product name" in c:
            add(col, "product_name")
        elif "实付" in c or "实际到账" in c or "actual pay" in c or "actual amount" in c:
            add(col, "total_amount")
        elif "交易日期" in c or "订单日期" in c or "下单日期" in c or "trade date" in c or "order date" in c:
            add(col, "order_date")
        elif "支付方式" in c or "付款方式" in c or "payment_method" in c or "payment method" in c:
            add(col, "payment_method")
        elif "客户编号" in c or "客户id" in c or "用户id" in c or "user id" in c or "customer id" in c:
            add(col, "user_id")
        elif "客户姓名" in c or "客户名" in c or "用户名" in c or "customer name" in c:
            # 没有客户编号时，用客户姓名作为用户标识，方便做聚合；不等同于真实 ID
            add(col, "user_id")

    # 第二轮：普通字段，只有目标列尚未存在时才映射
    for col in df.columns:
        if col in mapping:
            continue
        c = str(col).strip().lower()
        if "数量" in c or "件数" in c or "销量" in c or "qty" in c or c == "quantity":
            add(col, "quantity")
        elif "单价" in c or "unit price" in c or c == "price" or "售价" in c:
            add(col, "unit_price")
        elif "营业收入" in c or "销售额" in c or "gmv" in c or "总价" in c or "金额" in c or "实付金额" in c or "支付金额" in c or "订单金额" in c or "成交金额" in c:
            add(col, "total_amount")
        elif "日期" in c or "下单" in c:
            # 避免把“支付时间”误识别成订单日期
            if "支付" not in c and "付款" not in c:
                add(col, "order_date")
        elif "状态" in c or "status" in c or "交易状态" in c or "支付状态" in c or "订单状态" in c:
            add(col, "status")
        elif "城市" in c or "地区" in c or "所在城市" in c:
            add(col, "city")
        elif "品类" in c or "分类" in c or "类目" in c or "category" in c or "商品分类" in c:
            add(col, "category")
        elif "用户等级" in c or "会员等级" in c or "客户等级" in c or "会员级别" in c or "用户级别" in c:
            add(col, "user_level")

    if mapping:
        df = df.rename(columns=mapping)
    return coalesce_duplicate_columns(df)

def smart_column_mapping(df):
    """使用规则 + GLM 识别上传数据表头。没有 API Key 时只使用规则映射。"""
    df = coalesce_duplicate_columns(basic_rule_column_mapping(df))

    standard_columns = [
        "order_id", "user_id", "product_id", "product_name", "order_date",
        "quantity", "unit_price", "total_amount", "payment_method", "status",
        "city", "category", "user_level"
    ]

    api_key = get_zhipu_api_key()
    if not api_key:
        st.warning("⚠️ 未找到 ZHIPU_API_KEY，已跳过 AI 表头识别，仅使用规则映射。")
        return df

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )

        columns_list = df.columns.tolist()
        sample_data = df.head(3).to_json(orient="records", force_ascii=False)

        prompt = f"""你是一个数据工程专家。用户上传的电商订单数据中包含以下列名：
{json.dumps(columns_list, ensure_ascii=False)}

数据样本（前3行）：
{sample_data}

请将上述列名映射到以下标准列名，只输出能确认的映射关系：
{json.dumps(standard_columns, ensure_ascii=False)}

要求：
1. 基于列名语义和样本数据判断。
2. 无法确认的列不要输出。
3. 严格只输出 JSON，不要输出解释。
4. 不要把两个不同的原始列映射到同一个标准列。

输出格式：
{{"mapping": {{"原列名1": "标准列名1", "原列名2": "标准列名2"}}}}
"""

        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {"role": "system", "content": "你擅长数据表字段识别和 Schema Mapping。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=800,
        )

        result = json.loads(response.choices[0].message.content)
        mapping = result.get("mapping", {})

        # 避免覆盖已经标准化的列；避免重复映射造成重名冲突
        valid_mapping = {}
        existing_standard_cols = set([c for c in df.columns if c in standard_columns])
        used_targets = set(existing_standard_cols)
        for raw_col, target_col in mapping.items():
            if raw_col in df.columns and target_col in standard_columns:
                if raw_col == target_col:
                    continue
                if target_col not in used_targets:
                    valid_mapping[raw_col] = target_col
                    used_targets.add(target_col)

        if valid_mapping:
            df = coalesce_duplicate_columns(df.rename(columns=valid_mapping))
            st.success(
                "✅ AI 表头识别完成：" +
                ", ".join([f"{k} → {v}" for k, v in valid_mapping.items()])
            )
        else:
            st.info("ℹ️ AI 未发现新的可确认映射，继续使用当前列名。")

        return coalesce_duplicate_columns(df)

    except Exception as e:
        st.warning(f"⚠️ AI 表头识别失败：{e}。已继续使用当前列名。")
        return df


def parse_order_date_series(series):
    """兼容 20260501、5月1日、2026年5月1日、2026/5/1 等格式。"""
    current_year = datetime.now().year

    def parse_one(value):
        if pd.isna(value):
            return value
        s = str(value).strip()
        s = re.sub(r"\.0$", "", s)

        if re.match(r"^\d{8}$", s):
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", s):
            return s.replace("/", "-")

        m1 = re.match(r"^(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*$", s)
        if m1:
            return f"{current_year}-{int(m1.group(1))}-{int(m1.group(2))}"

        m2 = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
        if m2:
            return f"{m2.group(1)}-{int(m2.group(2))}-{int(m2.group(3))}"

        return s

    return pd.to_datetime(series.apply(parse_one), errors="coerce")


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

    if "total_amount" not in upload_df.columns:
        missing.append("total_amount（金额维度）")
    else:
        amount_series = upload_df["total_amount"]
        if amount_series.dtype == object:
            amount_series = amount_series.astype(str).str.replace(r"[^\d\.-]", "", regex=True)
        amount_numeric = pd.to_numeric(amount_series, errors="coerce")
        valid_amount_ratio = ((amount_numeric.notna()) & (amount_numeric > 0)).mean()
        if valid_amount_ratio < 0.1:
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
        "status_norm": "completed",
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

    # 统一状态字段：必须在清洗后再次生成，避免 clean_pipeline 丢失 status_norm
    if "status" in df.columns:
        df["status_norm"] = standardize_status(df["status"])
    else:
        df["status_norm"] = "completed"

    # 日期无法识别的行会导致趋势图无意义，直接过滤
    df = df.dropna(subset=["order_date"]).copy()

    return df


# =========================
# SQL 分析
# =========================
def get_status_condition():
    """统一只分析 completed 订单；没有 status 的数据已在 prepare_orders_dataframe 中默认置为 completed。"""
    return "status_norm = 'completed'", "o.status_norm = 'completed'"


def run_analysis(granularity="月"):
    """执行核心经营分析。"""
    results = {}
    s_cond, o_s_cond = get_status_condition()

    period_expr = (
        "SUBSTRING(CAST(order_date AS VARCHAR), 1, 7)"
        if granularity == "月"
        else "SUBSTRING(CAST(order_date AS VARCHAR), 1, 10)"
    )

    results["summary"] = conn.execute(f"""
        SELECT
            COUNT(*) AS total_orders,
            COUNT(DISTINCT user_id) AS unique_users,
            COUNT(DISTINCT product_id) AS products_sold,
            SUM(total_amount) AS total_gmv,
            AVG(total_amount) AS avg_order_value
        FROM orders
        WHERE {s_cond}
    """).fetchdf().to_dict("records")[0]

    results["monthly"] = conn.execute(f"""
        SELECT
            {period_expr} AS period,
            COUNT(*) AS orders,
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
            COUNT(*) AS orders,
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
            COUNT(order_id) AS order_count,
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
                COUNT(order_id) AS order_count,
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
            COUNT(*) AS orders,
            COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM orders), 0) AS pct
        FROM orders
        GROUP BY 1
        ORDER BY orders DESC
    """).df()

    results["anomalies"] = {
        "high_value_orders": conn.execute(f"""
            SELECT *
            FROM orders
            WHERE total_amount > (
                SELECT AVG(total_amount) * 3 FROM orders WHERE {s_cond}
            )
            ORDER BY total_amount DESC
            LIMIT 10
        """).df().to_dict("records"),
        "flagged_orders": conn.execute("""
            SELECT COUNT(*) AS count
            FROM orders
            WHERE is_anomaly = 1
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


def build_margin_df():
    """当 products 表存在 cost 字段且不为全空时，计算品类毛利。"""
    try:
        columns = conn.execute("DESCRIBE products").df()["column_name"].tolist()
        if "cost" not in columns:
            return pd.DataFrame()
        # 检查 cost 是否全为 NULL
        cost_count = conn.execute("SELECT COUNT(*) FROM products WHERE cost IS NOT NULL").fetchone()[0]
        if cost_count == 0:
            return pd.DataFrame()

        _, o_s_cond = get_status_condition()
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
            if st.button("✅ 确认上传并开始分析", type="primary", use_container_width=True):
                with st.spinner("正在解析并清洗数据..."):
                    upload_df = load_uploaded_file(uploaded_orders)

                    if upload_df is None or upload_df.empty:
                        st.error("❌ 文件为空或解析失败，请检查后重试。")
                    else:
                        with st.spinner("🤖 正在识别字段并规范化数据表头..."):
                            upload_df = smart_column_mapping(upload_df)

                        # 检测上传数据是否真的有 user_level 字段
                        upload_has_user_level = "user_level" in upload_df.columns
                        st.session_state["upload_has_user_level"] = upload_has_user_level
                        if upload_has_user_level:
                            st.info("ℹ️ 检测到 user_level 字段，将按用户等级进行分析。")

                        # 日期解析
                        if "order_date" in upload_df.columns:
                            upload_df["order_date"] = parse_order_date_series(upload_df["order_date"])

                        # 商品字段兜底：有商品名但没有 product_id 时，用商品名充当 product_id
                        if "product_id" not in upload_df.columns and "product_name" in upload_df.columns:
                            upload_df["product_id"] = upload_df["product_name"].astype(str)
                            st.info("ℹ️ 未检测到 product_id，已使用 product_name 作为商品标识。")

                        # 状态字段标准化：统一状态值，没有 status 时默认视为 completed
                        if "status" in upload_df.columns:
                            upload_df["status_norm"] = standardize_status(upload_df["status"])
                        else:
                            upload_df["status_norm"] = "completed"
                            st.info("ℹ️ 未检测到 status 列，已默认全部视为 completed（已完成），请在分析时留意。")

                        # 缺失维度必须在防御性补列之前检测
                        missing_dimensions = detect_missing_dimensions(upload_df)
                        st.session_state["missing_dimensions"] = missing_dimensions

                        if missing_dimensions:
                            st.warning("⚠️ 检测到关键维度缺失：" + "、".join(missing_dimensions))

                        cleaned_df, clean_report = clean_pipeline(upload_df, df_products, df_users)
                        cleaned_df = prepare_orders_dataframe(cleaned_df)

                        st.session_state["upload_success"] = True
                        st.session_state["upload_count"] = len(cleaned_df)
                        st.session_state["upload_name"] = uploaded_orders.name
                        st.session_state["uploaded_df"] = cleaned_df
                        st.session_state["clean_report"] = clean_report
                        st.rerun()

    st.markdown("---")
    st.markdown("<div style='text-align:center;color:#aaa;font-size:13px;'>当前展示默认示例数据</div>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
else:
    info_col, reset_col = st.columns([5, 1])
    with info_col:
        st.success(
            f"✅ 已加载：**{st.session_state.get('upload_name', '自定义数据')}** | "
            f"共 **{st.session_state.get('upload_count', 0):,}** 条有效订单"
        )
    with reset_col:
        if st.button("🔄 重新上传", use_container_width=True):
            for key in ["upload_success", "uploaded_df", "upload_count", "upload_name", "clean_report", "missing_dimensions", "upload_has_user_level", "last_insights", "data_quality_report"]:
                st.session_state.pop(key, None)
            st.rerun()

    clean_report = st.session_state.get("clean_report", [])
    missing_dimensions = st.session_state.get("missing_dimensions", [])

    with st.expander("查看数据清洗报告 / 数据质量提醒", expanded=False):
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
granularity = st.radio(
    "📅 趋势图",
    options=["月", "日"],
    index=0 if recommended_granularity == "月" else 1,
    horizontal=True,
    help="数据跨度较短时建议选择「日」，长期数据建议选择「月」。"
)

results = run_analysis(granularity=granularity)
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
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(monthly_plot["period"], monthly_plot["gmv"], marker="o")
        ax.set_xlabel("Period")
        ax.set_ylabel("GMV")
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        st.subheader("订单数趋势")
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.bar(monthly_plot["period"], monthly_plot["orders"])
        ax.set_xlabel("Period")
        ax.set_ylabel("Orders")
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("ℹ️ 暂无销售趋势数据。")

    st.subheader(f"{period_label}度数据明细")
    monthly_display = monthly.copy()
    if "gmv" in monthly_display.columns:
        monthly_display["gmv"] = monthly_display["gmv"].apply(money_fmt)
    st.dataframe(monthly_display, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("订单状态分布")
    status_df = results.get("order_status", pd.DataFrame())
    if len(status_df) > 0:
        status_display = status_df.copy()
        status_display["pct"] = status_display["pct"].apply(pct_fmt)
        st.dataframe(status_display, use_container_width=True, hide_index=True)
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
        top_plot_df = top_df.sort_values("revenue", ascending=True)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.barh(top_plot_df["product_name"].astype(str), top_plot_df["revenue"])
        ax.set_xlabel("Revenue")
        ax.set_ylabel("Product")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        top_display = top_df.copy()
        top_display["revenue"] = top_display["revenue"].apply(money_fmt)
        st.dataframe(top_display, use_container_width=True, hide_index=True)
    else:
        st.info("ℹ️ 暂无商品销售数据。")

    st.markdown("---")
    st.subheader("📦 品类销售分布")
    if len(cat_df) > 0 and all(c in cat_df.columns for c in ["category", "gmv"]):
        cat_plot_df = cat_df.copy()
        cat_plot_df = cat_plot_df[cat_plot_df["gmv"].fillna(0) > 0].sort_values("gmv", ascending=False)

        if len(cat_plot_df) > 0:
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.pie(
                cat_plot_df["gmv"],
                labels=cat_plot_df["category"].astype(str),
                autopct="%1.1f%%",
                startangle=90,
            )
            ax.set_title("品类销售额占比")
            ax.axis("equal")
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        else:
            st.info("ℹ️ 当前品类 GMV 均为空或小于等于 0，无法绘制饼图。")

        cat_display = cat_df.copy()
        cat_display["gmv"] = cat_display["gmv"].apply(money_fmt)
        st.subheader("品类明细")
        st.dataframe(cat_display, use_container_width=True, hide_index=True)
    else:
        st.info("ℹ️ 暂无品类数据。")

    margin_df = build_margin_df()
    if len(margin_df) > 0:
        st.markdown("---")
        st.subheader("💹 品类毛利分析")
        margin_display = margin_df.copy()
        for col in ["revenue", "total_cost", "gross_profit"]:
            if col in margin_display.columns:
                margin_display[col] = margin_display[col].apply(money_fmt)
        if "gross_margin_pct" in margin_display.columns:
            margin_display["gross_margin_pct"] = margin_display["gross_margin_pct"].apply(pct_fmt)
        st.dataframe(margin_display, use_container_width=True, hide_index=True)


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
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.bar(repurchase_df["user_level"].astype(str), repurchase_df["avg_spend"])
            ax.set_xlabel("User Level")
            ax.set_ylabel("Avg Spend")
            ax.tick_params(axis="x", rotation=30)
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        with u_col2:
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.bar(repurchase_df["user_level"].astype(str), repurchase_df["repurchase_rate"])
            ax.set_xlabel("User Level")
            ax.set_ylabel("Repurchase Rate")
            ax.tick_params(axis="x", rotation=30)
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        repurchase_display = repurchase_df.copy()
        repurchase_display["avg_spend"] = repurchase_display["avg_spend"].apply(money_fmt)
        repurchase_display["repurchase_rate"] = repurchase_display["repurchase_rate"].apply(pct_fmt)
        st.dataframe(repurchase_display, use_container_width=True, hide_index=True)
    else:
        # 切换为订单用户消费行为分析
        st.subheader("👥 用户消费行为分析")
        if switch_to_consumption:
            st.warning("⚠️ 当前上传数据无法与用户等级表匹配，已切换为订单用户消费分析。")

        if len(users_df) > 0 and "total_spend" in users_df.columns:
            top10_df = users_df.head(10).copy()
            top10_plot = top10_df.sort_values("total_spend", ascending=True)
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.barh(top10_plot["user_id"].astype(str), top10_plot["total_spend"])
            ax.set_xlabel("Total Spend")
            ax.set_ylabel("User ID")
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

        if len(users_df) > 0 and "order_count" in users_df.columns:
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.hist(users_df["order_count"], bins=15)
            ax.set_xlabel("Order Count")
            ax.set_ylabel("Users")
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

        if len(users_df) > 0:
            st.subheader("💰 高价值用户 Top 20 明细")
            users_display = users_df.head(20).copy()
            users_display["total_spend"] = users_display["total_spend"].apply(money_fmt)
            st.dataframe(users_display, use_container_width=True, hide_index=True)

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
        st.dataframe(high_value_display, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("🚀 商业报告生成")
    st.info("点击按钮后，系统会基于当前统计结果生成销售结论、商品/品类表现、异常检测、用户分析与经营建议。")

    if st.button("🚀 生成 AI 报告", type="primary", use_container_width=True):
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
                use_container_width=True,
            )


# =========================
# 页脚
# =========================
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "AI 电商分析助手 | Streamlit + DuckDB + Matplotlib + GLM-4-Flash"
    "</div>",
    unsafe_allow_html=True,
)
