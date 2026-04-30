"""
Memory Lens - Streamlit 前端应用
阶段 6：前端交互界面

功能：
- 上传聊天记录文件
- 展示数据处理流程
- Galgame 风格叙事展示
- 分支选择交互
- 存档/读档功能
- 数据洞察面板
"""

import streamlit as st
import json
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ingestion.wx_parser_simple import WeChatParser
from cleaning.data_cleaner import DataCleaner
from extraction.feature_extractor import FeatureExtractor
from embedding.vector_store import VectorStore
from narrative.story_generator import StoryGenerator

# 页面配置
st.set_page_config(
    page_title="回忆放大镜 | Memory Lens",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义样式
st.markdown("""
<style>
    .main-title {
        font-size: 2.5rem;
        font-weight: bold;
        color: #FF6B9D;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1rem;
        color: #888;
        text-align: center;
        margin-bottom: 2rem;
    }
    .scene-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        color: white;
        margin: 1rem 0;
    }
    .dialogue-box {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
        border-left: 4px solid #FF6B9D;
    }
    .choice-btn {
        background: #FF6B9D;
        color: white;
        border: none;
        padding: 0.75rem 1.5rem;
        border-radius: 25px;
        cursor: pointer;
        margin: 0.5rem;
        transition: all 0.3s;
    }
    .choice-btn:hover {
        background: #FF8FB0;
        transform: scale(1.05);
    }
    .stat-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        text-align: center;
    }
    .stat-number {
        font-size: 2rem;
        font-weight: bold;
        color: #667eea;
    }
    .stat-label {
        color: #888;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """初始化会话状态"""
    if 'messages' not in st.session_state:
        st.session_state.messages = None
    if 'sessions' not in st.session_state:
        st.session_state.sessions = None
    if 'story_gen' not in st.session_state:
        st.session_state.story_gen = None
    if 'current_scene' not in st.session_state:
        st.session_state.current_scene = None
    if 'game_started' not in st.session_state:
        st.session_state.game_started = False
    if 'processing_done' not in st.session_state:
        st.session_state.processing_done = False


def process_data(file_path):
    """处理数据管道"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 阶段 1: 解析
    status_text.text("📥 阶段 1/5: 解析聊天记录...")
    parser = WeChatParser(file_path)
    messages = parser.parse()
    progress_bar.progress(20)
    
    # 阶段 2: 清洗
    status_text.text("🧹 阶段 2/5: 数据清洗...")
    cleaner = DataCleaner(messages, session_gap_minutes=120)
    cleaned_messages = cleaner.clean(anonymize=True)
    sessions = cleaner.get_sessions()
    progress_bar.progress(40)
    
    # 阶段 3: 特征提取
    status_text.text("🔍 阶段 3/5: 提取情感特征...")
    extractor = FeatureExtractor(cleaned_messages)
    extractor.extract(sessions)
    progress_bar.progress(60)
    
    # 阶段 4: 向量化
    status_text.text("🔄 阶段 4/5: 生成向量表示...")
    store = VectorStore()
    store.add_messages(cleaned_messages)
    progress_bar.progress(80)
    
    # 阶段 5: 初始化叙事生成器
    status_text.text("📖 阶段 5/5: 准备叙事引擎...")
    session_features = extractor.features
    story_gen = StoryGenerator(cleaned_messages, session_features)
    progress_bar.progress(100)
    
    status_text.text("✅ 数据处理完成！")
    
    return cleaned_messages, sessions, story_gen


def render_home():
    """渲染首页"""
    st.markdown('<div class="main-title">🔍 回忆放大镜</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Memory Lens - AI 驱动的分支叙事体验</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="stat-card">
            <div class="stat-number">5</div>
            <div class="stat-label">数据处理阶段</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class="stat-card">
            <div class="stat-number">AI</div>
            <div class="stat-label">智能叙事生成</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class="stat-card">
            <div class="stat-number">∞</div>
            <div class="stat-label">分支剧情可能</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # 文件上传
    st.subheader("📁 上传聊天记录")
    uploaded_file = st.file_uploader(
        "选择微信聊天记录文件 (.txt)",
        type=['txt'],
        help="支持微信导出的 txt 格式聊天记录"
    )
    
    # 使用示例数据
    use_sample = st.checkbox("使用示例数据（小雨和阿杰的故事）")
    
    if st.button("🚀 开始处理", type="primary", use_container_width=True):
        if uploaded_file:
            # 保存上传的文件
            save_path = project_root / 'data' / 'uploads' / uploaded_file.name
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(uploaded_file.getvalue())
            file_path = save_path
        elif use_sample:
            file_path = project_root / 'data' / 'bronze' / 'wx_chat_sample.txt'
        else:
            st.warning("请上传文件或选择使用示例数据")
            return
        
        # 处理数据
        with st.spinner("正在处理数据..."):
            messages, sessions, story_gen = process_data(file_path)
            st.session_state.messages = messages
            st.session_state.sessions = sessions
            st.session_state.story_gen = story_gen
            st.session_state.processing_done = True
            st.session_state.game_started = False
        
        st.success("数据处理完成！请切换到'开始故事'页面")
        st.balloons()


def render_data_insights():
    """渲染数据洞察面板"""
    st.header("📊 数据洞察")
    
    if not st.session_state.processing_done:
        st.info("请先上传数据并完成处理")
        return
    
    messages = st.session_state.messages
    sessions = st.session_state.sessions
    
    # 基础统计
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总消息数", len(messages))
    with col2:
        st.metric("会话数", len(sessions))
    with col3:
        senders = set(m.get('sender', 'Unknown') for m in messages)
        st.metric("参与者", len(senders))
    with col4:
        avg_msg = len(messages) // len(sessions) if sessions else 0
        st.metric("平均每会话消息", avg_msg)
    
    st.markdown("---")
    
    # 情感分布
    st.subheader("😊 情感分布")
    sentiments = {'positive': 0, 'negative': 0, 'neutral': 0}
    for msg in messages:
        label = msg.get('features', {}).get('sentiment_label', 'neutral')
        sentiments[label] = sentiments.get(label, 0) + 1
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("😊 积极", sentiments.get('positive', 0))
    with col2:
        st.metric("😐 中性", sentiments.get('neutral', 0))
    with col3:
        st.metric("😢 消极", sentiments.get('negative', 0))
    
    st.markdown("---")
    
    # 场景分布
    st.subheader("🎭 场景分布")
    scenes = {}
    for msg in messages:
        scene = msg.get('features', {}).get('scene', '日常')
        if scene:
            scenes[scene] = scenes.get(scene, 0) + 1
    
    for scene, count in sorted(scenes.items(), key=lambda x: x[1], reverse=True):
        st.write(f"{scene}: {count} 条消息")
        st.progress(count / len(messages))
    
    st.markdown("---")
    
    # 原始消息预览
    st.subheader("💬 消息预览")
    for msg in messages[:10]:
        with st.expander(f"[{msg.get('timestamp', '')[:16]}] {msg.get('sender', '')}"):
            st.write(msg.get('content', ''))
            features = msg.get('features', {})
            st.caption(f"情感: {features.get('sentiment_label', 'unknown')} | 场景: {features.get('scene', 'unknown')}")


def render_story():
    """渲染故事页面"""
    st.header("📖 你的故事")
    
    if not st.session_state.processing_done:
        st.info("请先上传数据并完成处理")
        return
    
    story_gen = st.session_state.story_gen
    
    # 游戏控制按钮
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🎮 开始新故事"):
            st.session_state.current_scene = story_gen.generate_scene()
            st.session_state.game_started = True
    with col2:
        if st.button("💾 存档"):
            save_path = story_gen.save_game(slot=0)
            st.success(f"已存档: {save_path}")
    with col3:
        if st.button("📂 读档"):
            if story_gen.load_game(slot=0):
                st.session_state.current_scene = story_gen.generate_scene()
                st.session_state.game_started = True
                st.success("读档成功！")
            else:
                st.error("没有找到存档")
    
    if not st.session_state.game_started:
        st.info("点击'开始新故事'开始你的回忆之旅")
        return
    
    # 显示当前场景
    scene = st.session_state.current_scene
    
    if scene.get('type') == 'ending':
        st.markdown("""
        <div class="scene-box" style="text-align: center;">
            <h2>🎬 故事结束</h2>
            <p>{}</p>
        </div>
        """.format(scene.get('content', '')), unsafe_allow_html=True)
        
        # 显示故事摘要
        summary = story_gen.get_story_summary()
        st.markdown("---")
        st.subheader("📋 故事摘要")
        st.json(summary)
        return
    
    # 场景描述
    st.markdown(f"""
    <div class="scene-box">
        {scene.get('description', '').replace(chr(10), '<br>')}
    </div>
    """, unsafe_allow_html=True)
    
    # 对话
    st.subheader("💭")
    for dialogue in scene.get('dialogue', []):
        emotion_emoji = {'positive': '😊', 'negative': '😢', 'neutral': '😐'}.get(dialogue.get('emotion'), '')
        st.markdown(f"""
        <div class="dialogue-box">
            <strong>{emotion_emoji} {dialogue.get('speaker', '')}</strong><br>
            {dialogue.get('text', '')}
        </div>
        """, unsafe_allow_html=True)
    
    # 选择
    st.markdown("---")
    st.subheader("你的选择")
    
    choices = scene.get('choices', [])
    cols = st.columns(len(choices))
    
    for i, (col, choice) in enumerate(zip(cols, choices)):
        with col:
            if st.button(f"{choice.get('text', '')}", key=f"choice_{i}", use_container_width=True):
                next_scene = story_gen.make_choice(i)
                st.session_state.current_scene = next_scene
                st.rerun()
    
    # 进度
    summary = story_gen.get_story_summary()
    st.markdown("---")
    st.progress(summary['current_session'] / summary['total_sessions'])
    st.caption(f"进度: {summary['progress']}")


def render_about():
    """渲染关于页面"""
    st.header("关于回忆放大镜")
    
    st.markdown("""
    ### 🎯 项目简介
    
    **回忆放大镜（Memory Lens）** 是一个基于真实聊天记录的 AI 分支叙事系统。
    
    通过完整的数据工程管道，将平凡的聊天记录转化为独特的交互式叙事体验。
    
    ### 🏗️ 技术架构
    
    ```
    微信聊天记录
         ↓
    [Bronze] 原始数据摄取
         ↓
    [Silver] 数据清洗（去重、去噪、分段）
         ↓
    [Gold] 特征提取（情感分析、场景识别）
         ↓
    [Embedding] 向量化存储
         ↓
    [Narrative] AI 叙事生成
         ↓
    [Streamlit] 交互式体验
    ```
    
    ### 🛠️ 技术栈
    
    - **数据处理**: Python, Pandas
    - **特征提取**: 自定义 NLP 管道
    - **向量存储**: ChromaDB (模拟)
    - **叙事生成**: 基于规则的 AI 引擎
    - **前端展示**: Streamlit
    
    ### 📊 数据流程
    
    1. **摄取**: 解析微信聊天记录格式
    2. **清洗**: 去除噪声，分割会话
    3. **提取**: 情感分析、关键词提取、场景识别
    4. **存储**: 生成 Embedding，构建语义检索
    5. **生成**: 基于场景模板生成 Galgame 风格叙事
    6. **交互**: 分支选择、存档读档
    
    ### 📝 使用说明
    
    1. 在首页上传微信聊天记录文件（.txt 格式）
    2. 或使用提供的示例数据
    3. 等待数据处理完成
    4. 在"开始故事"页面体验交互式叙事
    5. 在"数据洞察"页面查看数据分析结果
    
    ---
    
    *Made with 💖 by Memory Lens Team*
    """)


def main():
    """主函数"""
    init_session_state()
    
    # 侧边栏导航
    with st.sidebar:
        st.markdown("### 🔍 Memory Lens")
        st.markdown("---")
        
        page = st.radio(
            "导航",
            ["🏠 首页", "📊 数据洞察", "📖 开始故事", "ℹ️ 关于"]
        )
        
        st.markdown("---")
        
        # 状态显示
        if st.session_state.processing_done:
            st.success("✅ 数据已加载")
        else:
            st.info("⏳ 等待数据")
    
    # 页面路由
    if page == "🏠 首页":
        render_home()
    elif page == "📊 数据洞察":
        render_data_insights()
    elif page == "📖 开始故事":
        render_story()
    elif page == "ℹ️ 关于":
        render_about()


if __name__ == '__main__':
    main()
