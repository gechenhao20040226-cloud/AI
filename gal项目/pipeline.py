"""
Memory Lens - 完整数据处理管道
一键运行所有阶段
"""

import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ingestion.wx_parser_simple import WeChatParser
from cleaning.data_cleaner import DataCleaner
from extraction.feature_extractor import FeatureExtractor
from embedding.vector_store import VectorStore
from narrative.story_generator import StoryGenerator


def run_pipeline(input_file: str, output_dir: str = None):
    """
    运行完整数据管道
    
    Args:
        input_file: 输入的微信聊天记录文件路径
        output_dir: 输出目录
    """
    if output_dir is None:
        output_dir = project_root / 'data'
    else:
        output_dir = Path(output_dir)
    
    print("=" * 60)
    print("🔍 Memory Lens - 数据处理管道")
    print("=" * 60)
    print(f"\n输入文件: {input_file}")
    print(f"输出目录: {output_dir}\n")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # ========== 阶段 1: 数据摄取 ==========
    print("\n" + "=" * 60)
    print("📥 阶段 1: 数据摄取 (Bronze)")
    print("=" * 60)
    
    parser = WeChatParser(input_file)
    messages = parser.parse()
    stats = parser.get_stats()
    
    print(f"✅ 解析完成!")
    print(f"   总消息数: {stats['total_messages']}")
    print(f"   发送者: {', '.join(stats['senders'])}")
    print(f"   时间范围: {stats['date_range']['start'][:10] if stats['date_range']['start'] else 'N/A'} ~ {stats['date_range']['end'][:10] if stats['date_range']['end'] else 'N/A'}")
    
    # 保存 Bronze 数据
    bronze_path = output_dir / 'bronze' / f"wechat_bronze_{timestamp}.json"
    parser.save_to_json(bronze_path)
    print(f"   已保存: {bronze_path}")
    
    # ========== 阶段 2: 数据清洗 ==========
    print("\n" + "=" * 60)
    print("🧹 阶段 2: 数据清洗 (Silver)")
    print("=" * 60)
    
    cleaner = DataCleaner(messages, session_gap_minutes=120)
    cleaned_messages = cleaner.clean(anonymize=True)
    report = cleaner.get_stats_report()
    
    print(f"✅ 清洗完成!")
    print(f"   原始消息: {report['original_count']}")
    print(f"   去重移除: {report['duplicates_removed']}")
    print(f"   去噪移除: {report['noise_removed']}")
    print(f"   最终消息: {report['final_count']}")
    print(f"   会话数: {report['session_count']}")
    print(f"   移除率: {report['removal_rate']}%")
    
    sessions = cleaner.get_sessions()
    
    # 保存 Silver 数据
    silver_path = output_dir / 'silver' / f"wechat_silver_{timestamp}.json"
    cleaner.save_cleaned_data(silver_path)
    print(f"   已保存: {silver_path}")
    
    sessions_path = output_dir / 'silver' / f"wechat_silver_sessions_{timestamp}.json"
    cleaner.save_sessions(sessions_path)
    print(f"   已保存: {sessions_path}")
    
    # ========== 阶段 3: 特征提取 ==========
    print("\n" + "=" * 60)
    print("🔍 阶段 3: 特征提取 (Gold)")
    print("=" * 60)
    
    extractor = FeatureExtractor(cleaned_messages)
    extractor.extract(sessions)
    summary = extractor.get_feature_summary()
    
    print(f"✅ 特征提取完成!")
    print(f"   会话数: {summary['total_sessions']}")
    print(f"   场景分布: {summary['scene_distribution']}")
    print(f"   情感分布: {summary['sentiment_distribution']}")
    print(f"   热门关键词: {[k[0] for k in summary['top_keywords'][:5]]}")
    
    # 保存 Gold 数据
    gold_path = output_dir / 'gold' / f"wechat_gold_{timestamp}.json"
    extractor.save_gold_data(gold_path)
    print(f"   已保存: {gold_path}")
    
    # ========== 阶段 4: 向量化 ==========
    print("\n" + "=" * 60)
    print("🔄 阶段 4: 向量化存储")
    print("=" * 60)
    
    store = VectorStore(collection_name="chat_memories")
    store.add_messages(cleaned_messages)
    stats = store.get_stats()
    
    print(f"✅ 向量存储完成!")
    print(f"   文档数: {stats['total_documents']}")
    print(f"   情感分布: {stats['sentiment_distribution']}")
    print(f"   场景分布: {stats['scene_distribution']}")
    
    # 测试检索
    print(f"\n   测试检索 '第一次见面':")
    results = store.search("第一次见面", n_results=3)
    for r in results:
        print(f"   [{r['similarity']:.3f}] {r['metadata']['sender']}: {r['document'][:40]}...")
    
    # 保存向量库
    vector_path = output_dir / 'gold' / f"vector_store_{timestamp}.json"
    store.save(vector_path)
    print(f"\n   已保存: {vector_path}")
    
    # ========== 阶段 5: 叙事引擎 ==========
    print("\n" + "=" * 60)
    print("📖 阶段 5: 叙事引擎初始化")
    print("=" * 60)
    
    session_features = extractor.features
    story_gen = StoryGenerator(cleaned_messages, session_features)
    
    print(f"✅ 叙事引擎就绪!")
    print(f"   总会话: {len(session_features)}")
    print(f"   可生成场景数: {len(session_features)}")
    
    # 生成第一个场景预览
    print(f"\n   第一个场景预览:")
    scene = story_gen.generate_scene()
    print(f"   {scene['description'][:100]}...")
    
    print("\n" + "=" * 60)
    print("🎉 所有阶段处理完成!")
    print("=" * 60)
    print(f"\n📁 输出文件:")
    print(f"   Bronze: {bronze_path}")
    print(f"   Silver: {silver_path}")
    print(f"   Gold:   {gold_path}")
    print(f"   Vector: {vector_path}")
    print(f"\n🚀 运行 Streamlit 应用:")
    print(f"   streamlit run app/app.py")
    
    return {
        'bronze': bronze_path,
        'silver': silver_path,
        'gold': gold_path,
        'vector': vector_path,
        'story_gen': story_gen
    }


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Memory Lens 数据处理管道')
    parser.add_argument('input_file', nargs='?', 
                        default=str(project_root / 'data' / 'bronze' / 'wx_chat_sample.txt'),
                        help='输入的微信聊天记录文件路径')
    parser.add_argument('-o', '--output', 
                        default=str(project_root / 'data'),
                        help='输出目录')
    
    args = parser.parse_args()
    
    run_pipeline(args.input_file, args.output)
