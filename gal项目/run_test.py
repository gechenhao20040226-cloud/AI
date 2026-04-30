#!/usr/bin/env python3
"""测试脚本：验证阶段1和阶段2"""

import sys
sys.path.insert(0, 'C:\\Users\\gch20\\Documents\\memory-lens')

from ingestion.wx_parser_simple import WeChatParser
from cleaning.data_cleaner import DataCleaner
import json
from pathlib import Path

print("=" * 60)
print("Memory Lens 测试脚本")
print("=" * 60)

# ========== 阶段 1：数据摄取 ==========
print("\n📥 阶段 1：数据摄取")
print("-" * 40)

file_path = 'C:\\Users\\gch20\\Documents\\memory-lens\\data\\bronze\\wx_chat_sample.txt'
print(f"解析文件: {file_path}")

parser = WeChatParser(file_path)
messages = parser.parse()
stats = parser.get_stats()

print(f"\n✅ 解析完成！")
print(f"   总消息数: {stats['total_messages']}")
print(f"   发送者: {', '.join(stats['senders'])}")
print(f"   时间范围: {stats['date_range']['start'][:10] if stats['date_range']['start'] else 'N/A'} ~ {stats['date_range']['end'][:10] if stats['date_range']['end'] else 'N/A'}")

print("\n前5条消息预览:")
for msg in messages[:5]:
    content = msg['content'][:40] + "..." if len(msg['content']) > 40 else msg['content']
    print(f"   [{msg['timestamp'][:16]}] {msg['sender']}: {content}")

# 保存 bronze 数据
bronze_path = 'C:\\Users\\gch20\\Documents\\memory-lens\\data\\bronze\\wechat_bronze_test.json'
saved = parser.save_to_json(bronze_path)
print(f"\n💾 Bronze 数据已保存: {saved}")

# ========== 阶段 2：数据清洗 ==========
print("\n\n🧹 阶段 2：数据清洗")
print("-" * 40)

cleaner = DataCleaner(messages, session_gap_minutes=120)
cleaned_messages = cleaner.clean(anonymize=True)

# 获取统计报告
report = cleaner.get_stats_report()
print("\n📊 清洗统计报告:")
for key, value in report.items():
    print(f"   {key}: {value}")

# 获取会话
sessions = cleaner.get_sessions()
print(f"\n💬 会话详情:")
for idx, session in enumerate(sessions):
    start_time = session[0]['timestamp'][:16] if session else 'N/A'
    end_time = session[-1]['timestamp'][:16] if session else 'N/A'
    print(f"   会话 {idx+1}: {len(session)} 条消息 ({start_time} ~ {end_time})")

# 保存 silver 数据
silver_path = 'C:\\Users\\gch20\\Documents\\memory-lens\\data\\silver\\wechat_silver_test.json'
saved_silver = cleaner.save_cleaned_data(silver_path)
print(f"\n💾 Silver 数据已保存: {saved_silver}")

# 保存会话数据
sessions_path = 'C:\\Users\\gch20\\Documents\\memory-lens\\data\\silver\\wechat_silver_sessions_test.json'
saved_sessions = cleaner.save_sessions(sessions_path)
print(f"💾 会话数据已保存: {saved_sessions}")

print("\n" + "=" * 60)
print("✅ 所有测试通过！")
print("=" * 60)
