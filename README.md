# AI 电商数据分析助手

一个基于 **Streamlit + Pandas + DuckDB + Altair + GLM-4-Flash** 的订单数据分析工具。

用户上传单个 CSV 或 Excel 文件后，系统会自动定位表头、识别业务字段，并让用户确认字段对应关系，再执行数据清洗、经营指标计算、异常检测和 AI 商业分析。

## 核心能力

- 支持 CSV、XLSX、XLS，Excel 仅读取第一个 Sheet
- CSV 自动尝试 UTF-8、GB18030、GBK、Big5 等常见编码
- 自动识别文件中的真实表头行，兼容顶部带报表标题或说明的文件
- 覆盖订单号、买家 UID、SKU 编码、支付时间、订单实收金额等常见业务字段
- 自动识别后提供字段确认页面，用户可通过下拉框纠正映射
- 兼容人民币符号、千分位、`1.2万`、Excel 日期序列和时间戳
- 统一识别完成、退款、取消、处理中、失败和未知状态
- 允许用户自行选择哪些订单状态参与 GMV 分析
- 自动判断一笔订单包含多行商品明细，订单数统一按订单 ID 去重
- 使用 DuckDB 执行本地 SQL 分析
- 使用 Altair 生成交互式图表
- 支持异常订单识别与 GLM-4-Flash 商业报告生成

## 数据导入流程

1. 上传一个 CSV 或 Excel 文件。
2. 系统读取 CSV 或 Excel 的第一个 Sheet，并自动定位表头。
3. 页面展示原始数据前 10 行。
4. 系统给出字段匹配建议，用户重点确认：
   - 订单 ID
   - 订单时间或支付时间（没有时可不选择）
   - 实付金额
   - 订单状态
5. 确认后执行数据校验和清洗。
6. 用户选择参与分析的订单状态，再查看 Dashboard。

这种方式避免完全依赖固定字段名或 AI 猜测。即使是新的业务后台导出格式，也可以通过一次人工确认完成分析。

## 支持的标准字段

|标准字段|业务含义|是否关键|
|---|---|---|
|`order_id`|订单号或交易号|建议提供|
|`order_date`|下单、支付或成交时间|可选；缺失时跳过趋势与环比|
|`total_amount`|实付金额、订单实收或 GMV|必须，或同时提供数量和单价|
|`status`|订单状态|建议提供|
|`user_id`|用户、买家或会员 ID|用户分析需要|
|`product_id`|商品、SKU 或货品 ID|商品分析建议提供|
|`product_name`|商品名称或商品标题|商品分析建议提供|
|`quantity`|购买数量或成交件数|可选，默认 1|
|`unit_price`|商品单价|可选|
|`payment_method`|支付方式|可选|
|`city`|城市或地区|可选|
|`category`|品类或类目|可选|
|`user_level`|用户或会员等级|可选|

## 关键统计口径

- **订单数**：`COUNT(DISTINCT order_id)`
- **GMV**：所选有效状态下的 `SUM(total_amount)`
- **客单价**：GMV ÷ 去重订单数
- **用户数**：`COUNT(DISTINCT user_id)`
- **复购用户**：去重订单数大于等于 2 的用户
- **商品销量**：`SUM(quantity)`

如果原文件没有订单 ID，系统会生成临时行 ID，并明确提示“每行暂按一笔订单计算”。

## 数据清洗原则

- 只自动修复能够安全确定的格式问题
- 负价格、负金额、异常数量只标记，不擅自取绝对值
- 合法的 0 元订单不会被自动改写
- 只有金额为空时，才尝试用“数量 × 单价”补齐
- 只删除完全相同的重复明细，不删除同一订单中的不同商品行
- 无法解析的日期会从分析数据中排除，并展示数量
- 上传自定义订单时不会关联项目自带的模拟商品表或用户表

## 项目结构

```text
AI-Ecommerce-Analytics-Assistant/
├── app.py                         # Streamlit 主程序
├── order_schema.py                # 文件读取、表头定位、字段与状态识别
├── clean_pipeline.py              # 数据清洗 Pipeline
├── requirements.txt               # Python 依赖
├── README.md                      # 项目说明
├── orders_cleaned.csv             # 模拟订单明细
├── products.csv                   # 模拟商品数据
├── users.csv                      # 模拟用户数据
├── .gitignore
└── .streamlit/
    └── secrets.toml.example       # 密钥配置示例
```

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 配置 GLM API

复制示例配置：

```text
.streamlit/secrets.toml.example
```

并重命名为：

```text
.streamlit/secrets.toml
```

填写：

```toml
ZHIPU_API_KEY = "your_api_key_here"
```

也可以使用环境变量 `ZHIPU_API_KEY`。真实密钥不能提交到 GitHub。

未配置 API Key 时，订单上传、字段识别、数据清洗和 Dashboard 均可正常使用，仅无法生成 AI 商业报告。

## 注意事项

1. Excel 文件只读取第一个 Sheet。
2. 上传真实业务数据前，建议删除姓名、手机号、地址等非分析必需字段。
3. 点击生成 AI 报告时，汇总后的分析结果会发送给 GLM API；原始完整订单不会被发送。
4. AI 报告仅用于辅助判断，不能替代财务或经营口径确认。
5. 示例数据为模拟数据，不包含真实用户隐私。

## 后续可扩展方向

- 保存不同业务后台的字段模板
- 增加退款金额、净 GMV 和售后分析
- 增加 RFM 用户分层与留存分析
- 支持大文件分块读取
- 增加自动化单元测试和字段识别测试集
