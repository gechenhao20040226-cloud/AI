[README.md](https://github.com/user-attachments/files/27337954/README.md)
# AI 电商分析助手

一个基于 **Streamlit + DuckDB + Plotly + GLM-4-Flash** 的电商数据分析 Dashboard。  
项目支持上传 CSV / Excel 订单数据，自动完成数据清洗、SQL 指标分析、异常检测、可视化展示，并生成 AI 商业洞察报告。

---

## 项目亮点

* 支持 CSV / Excel 文件上传
* 自动识别常见中文/英文电商字段
* 清洗脏数据，包括金额、日期、重复订单、异常数量等
* 使用 DuckDB 执行本地 SQL 分析
* 使用 Plotly 生成交互式图表
* 支持销售趋势、Top 商品、品类分布、用户消费行为分析
* 支持异常订单检测
* 接入 GLM-4-Flash 自动生成商业洞察报告
* 支持 商业分析报告下载

---

## 技术栈

|模块|技术|
|-|-|
|前端展示|Streamlit|
|数据处理|Pandas / NumPy|
|SQL 分析|DuckDB|
|数据可视化|Plotly|
|商业分析报告|GLM-4-Flash API|
|API 调用方式|OpenAI SDK Compatible API|

---

## 项目结构

```text
AI-Ecommerce-Analytics-Assistant/
├── app.py                 # Streamlit Dashboard 主程序
├── clean_pipeline.py      # 数据清洗 Pipeline
├── requirements.txt       # Python 依赖
├── README.md              # 项目说明文档
├── orders_cleaned.csv     # 示例订单数据
├── products.csv           # 示例商品数据
├── users.csv              # 示例用户数据
└── .gitignore             # Git 忽略配置
```

---

## 快速开始

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd AI-Ecommerce-Analytics-Assistant
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

本项目使用智谱 GLM API 生成 AI 商业洞察。

你可以选择以下任意一种方式配置 `ZHIPU_API_KEY`。

#### 方式一：使用 Streamlit secrets

在项目根目录创建：

```text
.streamlit/secrets.toml
```

写入：

```toml
ZHIPU_API_KEY = "your_api_key_here"
```

#### 方式二：使用环境变量

Windows PowerShell:

```powershell
$env:ZHIPU_API_KEY="your_api_key_here"
```

macOS / Linux:

```bash
export ZHIPU_API_KEY="your_api_key_here"
```

> 注意：不要将真实 API Key 上传到 GitHub。

### 4. 启动项目

```bash
streamlit run app.py
```

启动后，在浏览器中打开 Streamlit 显示的本地地址即可使用。

---

## 功能说明

### 数据上传

用户可以上传 CSV / Excel 格式的订单数据。系统会自动进行字段识别与标准化，兼容常见字段名，例如：

* 订单号 / order_id
* 用户ID / user_id
* 商品ID / product_id
* 商品名称 / product_name
* 订单日期 / order_date
* 数量 / quantity
* 单价 / unit_price
* 总金额 / total_amount
* 订单状态 / status
* 城市 / city
* 品类 / category

---

### 数据清洗

`clean_pipeline.py` 会对上传数据进行自动清洗，包括：

* 合并重复列名
* 金额字段数值化，例如 `¥7,999`、`7999元`
* 数量字段数值化
* 订单状态标准化
* 缺失支付方式填充
* 缺失城市字段补充
* 重复订单删除
* 日期格式统一
* 负数价格修正
* `total_amount` 自动补齐
* 超大数量订单标记为异常
* 空商品字段过滤

---

### SQL 指标分析

项目使用 DuckDB 在内存中执行 SQL 分析，核心指标包括：

* 总订单数
* 总用户数
* 总 GMV
* 客单价
* GMV 环比
* 销售趋势
* Top 商品
* 品类销售分布
* 用户消费排行
* 订单状态分布
* 异常订单检测

---

### 可视化 Dashboard

系统使用 Plotly 展示图表，包括：

* 销售趋势图
* Top 商品销售额排行
* 品类销售额占比
* 各品类 GMV 对比
* 用户消费金额 Top 10
* 用户订单数分布

图表右上角保留 PNG 下载按钮，便于保存分析结果。

---

### 商业分析

项目接入 GLM-4-Flash，根据 SQL 分析结果自动生成中文商业分析报告，包括：

* 核心销售结论
* Top 商品与品类表现
* 异常订单与数据质量提醒
* 用户分析
* 下一步经营建议

系统会尽量避免 AI 基于缺失字段或默认值生成误导性结论。

---

## 注意事项

1. 本项目示例数据为模拟数据，不包含真实用户隐私。
2. 上传真实业务数据前，请先进行脱敏处理。
3. AI 报告仅作为辅助分析参考，不能替代人工业务判断。
4. 请勿将 `.streamlit/secrets.toml`、`.env` 或任何真实 API Key 提交到 GitHub。

---

## 后续可扩展方向

* 增加多 Sheet Excel 自动识别
* 增加用户留存 / 复购分析
* 增加 RFM 用户分层
* 增加退款率、取消率分析
* 增加自动生成 PDF 报告
* 增加数据库连接能力
* 增加部署到 Streamlit Cloud 的在线 Demo

---

## 项目说明

该项目主要用于展示数据清洗、SQL 分析、可视化 Dashboard 和 AI 分析的完整流程。  
开发过程中使用了 AI 工具辅助代码生成与调试，但项目结构设计、业务逻辑整合、数据处理规则和最终功能实现由本人完成。
