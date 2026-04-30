#!/usr/bin/env python3
"""测试微信聊天记录解析器"""

import sys
sys.path.insert(0, 'C:\\Users\\gch20\\Documents\\memory-lens')

from ingestion.wx_parser import parse_wechat_chat

# 测试解析
file_path = 'C:\\Users\\gch20\\Documents\\memory-lens\\data\\bronze\\wx_chat_sample.txt'
df = parse_wechat_chat(file_path)

print("\n前10条消息预览:")
print(df.head(10).to_string())

print(f"\n总共解析了 {len(df)} 条消息")
print(f"发送者: {df['sender'].unique().tolist()}")
