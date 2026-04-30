#!/usr/bin/env python3
"""完整管道测试脚本 - 生成详细报告"""

import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 导入所有模块
from ingestion.wx_parser_simple import WeChatParser
from cleaning.data_cleaner import DataCleaner
from extraction.feature_extractor import FeatureExtractor
from embedding.vector_store import VectorStore
from narrative.story_generator import StoryGenerator

# 测试报告
report = {
    'timestamp': datetime.now().isoformat(),
    'stages': {},
    'errors': []
}

print("=" * 70)
print("🔍 Memory Lens - 完整管道测试")
print("=" * 70)

# ========== 阶段 1: 数据摄取 ==========
print("\n📥 阶段 1: 数据摄取 (Bronze)")
print("-" * 70)

try:
    input_file = project_root / 'data' / 'bronze' / 'wx_chat_sample.txt'
    parser = WeChatParser(str(input_file))
    messages = parser.parse()
    stats = parser.get_stats()
    
    print(f"✅ 解析成功")
    print(f"   总消息数: {stats['total_messages']}")
    print(f"   发送者: {', '.join(stats['senders'])}")
    print(f"   时间范围: {stats['date_range']['start'][:10] if stats['date_range']['start'] else 'N/A'} ~ {stats['date_range']['end'][:10] if stats['date_range']['end'] else 'N/A'}")
    
    # 保存
    bronze_path = project_root / 'data' / 'bronze' / 'wechat_bronze_test.json'
    parser.save_to_json(str(bronze_path))
    print(f"   已保存: {bronze_path}")
    
    report['stages']['ingestion'] = {
        'status': 'success',
        'total_messages': stats['total_messages'],
        'senders': stats['senders'],
        'output_file': str(bronze_path)
    }
    
except Exception as e:
    print(f"❌ 失败: {e}")
    report['stages']['ingestion'] = {'status': 'failed', 'error': str(e)}
    report['errors'].append(f'阶段1: {e}')
    sys.exit(1)

# ========== 阶段 2: 数据清洗 ==========
print("\n🧹 阶段 2: 数据清洗 (Silver)")
print("-" * 70)

try:
    cleaner = DataCleaner(messages, session_gap_minutes=120)
    cleaned_messages = cleaner.clean(anonymize=True)
    clean_stats = cleaner.get_stats_report()
    sessions = cleaner.get_sessions()
    
    print(f"✅ 清洗成功")
    print(f"   原始消息: {clean_stats['original_count']}")
    print(f"   去重移除: {clean_stats['duplicates_removed']}")
    print(f"   去噪移除: {clean_stats['noise_removed']}")
    print(f"   最终消息: {clean_stats['final_count']}")
    print(f"   会话数: {clean_stats['session_count']}")
    print(f"   移除率: {clean_stats['removal_rate']}%")
    
    # 显示会话详情
    print(f"\n   会话详情:")
    for idx, session in enumerate(sessions):
        start = session[0]['timestamp'][:16] if session else 'N/A'
        end = session[-1]['timestamp'][:16] if session else 'N/A'
        print(f"   - 会话 {idx+1}: {len(session)} 条消息 ({start} ~ {end})")
    
    # 保存
    silver_path = project_root / 'data' / 'silver' / 'wechat_silver_test.json'
    cleaner.save_cleaned_data(str(silver_path))
    print(f"\n   已保存: {silver_path}")
    
    report['stages']['cleaning'] = {
        'status': 'success',
        **clean_stats,
        'output_file': str(silver_path)
    }
    
except Exception as e:
    print(f"❌ 失败: {e}")
    report['stages']['cleaning'] = {'status': 'failed', 'error': str(e)}
    report['errors'].append(f'阶段2: {e}')

# ========== 阶段 3: 特征提取 ==========
print("\n🔍 阶段 3: 特征提取 (Gold)")
print("-" * 70)

try:
    extractor = FeatureExtractor(cleaned_messages)
    extractor.extract(sessions)
    summary = extractor.get_feature_summary()
    
    print(f"✅ 特征提取成功")
    print(f"   会话数: {summary['total_sessions']}")
    print(f"   场景分布: {summary['scene_distribution']}")
    print(f"   情感分布: {summary['sentiment_distribution']}")
    print(f"   热门关键词: {[k[0] for k in summary['top_keywords'][:5]]}")
    
    # 保存
    gold_path = project_root / 'data' / 'gold' / 'wechat_gold_test.json'
    extractor.save_gold_data(str(gold_path))
    print(f"   已保存: {gold_path}")
    
    report['stages']['extraction'] = {
        'status': 'success',
        **summary,
        'output_file': str(gold_path)
    }
    
except Exception as e:
    print(f"❌ 失败: {e}")
    report['stages']['extraction'] = {'status': 'failed', 'error': str(e)}
    report['errors'].append(f'阶段3: {e}')

# ========== 阶段 4: 向量化 ==========
print("\n🔄 阶段 4: 向量化存储")
print("-" * 70)

try:
    store = VectorStore(collection_name="chat_memories")
    store.add_messages(cleaned_messages)
    stats = store.get_stats()
    
    print(f"✅ 向量存储成功")
    print(f"   文档数: {stats['total_documents']}")
    print(f"   情感分布: {stats['sentiment_distribution']}")
    print(f"   场景分布: {stats['scene_distribution']}")
    
    # 测试检索
    print(f"\n   语义检索测试:")
    test_queries = ['第一次见面', '告白', '吃饭']
    for query in test_queries:
        results = store.search(query, n_results=2)
        print(f"   - '{query}':")
        for r in results:
            print(f"     [{r['similarity']:.3f}] {r['document'][:40]}...")
    
    # 保存
    vector_path = project_root / 'data' / 'gold' / 'vector_store_test.json'
    store.save(str(vector_path))
    print(f"\n   已保存: {vector_path}")
    
    report['stages']['embedding'] = {
        'status': 'success',
        **stats,
        'output_file': str(vector_path)
    }
    
except Exception as e:
    print(f"❌ 失败: {e}")
    report['stages']['embedding'] = {'status': 'failed', 'error': str(e)}
    report['errors'].append(f'阶段4: {e}')

# ========== 阶段 5: 叙事生成 ==========
print("\n📖 阶段 5: 叙事生成")
print("-" * 70)

try:
    session_features = extractor.features
    story_gen = StoryGenerator(cleaned_messages, session_features)
    
    print(f"✅ 叙事引擎就绪")
    print(f"   总会话: {len(session_features)}")
    
    # 生成前3个场景预览
    print(f"\n   场景预览:")
    for i in range(min(3, len(session_features))):
        scene = story_gen.generate_scene()
        print(f"\n   --- 场景 {i+1} ---")
        print(f"   {scene['description'][:100]}...")
        print(f"   对话:")
        for d in scene['dialogue'][:2]:
            print(f"     {d['speaker']}: {d['text'][:40]}...")
        print(f"   选项: {', '.join([c['text'] for c in scene['choices']])}")
        
        # 模拟选择
        if i < 2:
            story_gen.make_choice(0)
    
    # 保存游戏状态
    save_path = story_gen.save_game(slot=0)
    print(f"\n   已存档: {save_path}")
    
    report['stages']['narrative'] = {
        'status': 'success',
        'total_sessions': len(session_features),
        'save_file': save_path
    }
    
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()
    report['stages']['narrative'] = {'status': 'failed', 'error': str(e)}
    report['errors'].append(f'阶段5: {e}')

# ========== 测试报告 ==========
print("\n" + "=" * 70)
print("📋 测试报告")
print("=" * 70)

success_count = sum(1 for s in report['stages'].values() if s.get('status') == 'success')
total_count = len(report['stages'])

print(f"\n通过: {success_count}/{total_count} 个阶段")

if report['errors']:
    print(f"\n❌ 错误:")
    for error in report['errors']:
        print(f"   - {error}")
else:
    print(f"\n✅ 所有阶段测试通过!")

print(f"\n输出文件:")
for stage_name, stage_data in report['stages'].items():
    if 'output_file' in stage_data:
        print(f"   {stage_name}: {stage_data['output_file']}")

# 保存测试报告
report_path = project_root / 'test_report.json'
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n详细报告已保存: {report_path}")
print("\n" + "=" * 70)
print("🎉 测试完成!")
print("=" * 70)
