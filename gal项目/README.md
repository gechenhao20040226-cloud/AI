# 回忆放大镜（Memory Lens）

基于真实聊天记录，利用 AI 自动生成可交互的分支叙事游戏（Galgame）。

## 项目定位

**求职导向的数据工程 + AI 应用项目**

核心亮点：
- 完整的端到端数据管道（Bronze → Silver → Gold）
- 向量数据库语义检索
- LLM 动态叙事生成
- 可交互的产品级 Demo

## 项目结构

```
memory-lens/
├── data/
│   ├── bronze/        # 原始聊天记录（原始数据）
│   ├── silver/        # 清洗后文本（清洗数据）
│   └── gold/          # 带情感标签的故事素材（特征数据）
├── ingestion/         # 数据摄取模块（阶段1）
│   └── wx_parser.py   # 微信聊天记录解析器
├── cleaning/          # 数据清洗模块（阶段2）
│   └── data_cleaner.py # 数据清洗器
├── extraction/        # 情感/特征提取（阶段3）
├── embedding/         # 向量化与存储（阶段4）
├── narrative/         # AI 叙事生成（阶段5）
├── app/               # Streamlit 前端（阶段6）
└── config/            # 配置文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 阶段1：数据摄取

解析微信聊天记录：

```bash
python ingestion/wx_parser.py data/bronze/wx_chat_sample.txt
```

输出：`data/bronze/wechat_bronze_*.json`

### 3. 阶段2：数据清洗

清洗并分段对话：

```bash
python cleaning/data_cleaner.py data/bronze/wechat_bronze_*.json
```

输出：`data/silver/wechat_silver_*.json`

## 数据管道架构

```
┌─────────────────┐
│   Bronze 层     │  ← 原始聊天记录（JSON/TXT）
│   原始数据       │
└────────┬────────┘
         │
         ▼ 解析、提取
┌─────────────────┐
│   Silver 层     │  ← 清洗后文本（去重、去噪、分段）
│   清洗数据       │
└────────┬────────┘
         │
         ▼ 特征提取、Embedding
┌─────────────────┐
│    Gold 层      │  ← 带情感标签的故事素材
│   特征数据       │     存入 ChromaDB
└─────────────────┘
```

## 技术栈

| 技术 | 用途 |
|------|------|
| Python | 核心开发语言 |
| Pandas | 数据处理、ETL |
| ChromaDB | 向量数据库、语义检索 |
| OpenAI API | LLM 叙事生成 |
| LangChain | RAG 架构实现 |
| Streamlit | 前端交互界面 |

## 开发进度

- [x] 阶段0：项目初始化
- [x] 阶段1：数据摄取（微信解析器）
- [x] 阶段2：数据清洗（去重、去噪、分段）
- [ ] 阶段3：情感与特征提取
- [ ] 阶段4：向量化与存储
- [ ] 阶段5：AI 叙事生成
- [ ] 阶段6：前端交互
- [ ] 阶段7：项目包装

## 简历描述

**回忆放大镜（Memory Lens）** | 个人项目

基于真实聊天记录开发 AI 分支叙事系统，实现从聊天数据摄取、清洗、情感分析、向量化到 LLM 动态生成的完整数据与 AI 工作流。

- 构建三层数据湖架构（Bronze/Silver/Gold），使用 Pandas 完成 ETL 流程
- 实现基于时间间隔的对话分段算法，将连续聊天记录切分为独立会话
- 使用 ChromaDB 构建语义检索系统，支持基于 Embedding 的对话片段检索
- 通过 Streamlit 实现可交互 Galgame 式叙事体验

---

*项目开发中...*
