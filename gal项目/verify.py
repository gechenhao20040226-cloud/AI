import json
from pathlib import Path

# 手动验证解析器
import re
from datetime import datetime

file_path = Path('C:/Users/gch20/Documents/memory-lens/data/bronze/wx_chat_sample.txt')

MESSAGE_PATTERN = re.compile(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(.+)$')

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

messages = []
current_message = None

for line in lines:
    line = line.rstrip('\n')
    if not line.strip():
        continue
    
    match = MESSAGE_PATTERN.match(line)
    
    if match:
        if current_message and current_message['content'].strip():
            messages.append(current_message)
        
        timestamp_str = match.group(1)
        sender = match.group(2).strip()
        
        current_message = {
            'timestamp': timestamp_str,
            'sender': sender,
            'content': '',
            'platform': 'wechat'
        }
    else:
        if current_message is not None:
            if current_message['content']:
                current_message['content'] += '\n'
            current_message['content'] += line

if current_message and current_message['content'].strip():
    messages.append(current_message)

print(f"解析完成！共 {len(messages)} 条消息\n")

for msg in messages[:10]:
    content = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
    print(f"[{msg['timestamp']}] {msg['sender']}: {content}")

# 保存
output_path = Path('C:/Users/gch20/Documents/memory-lens/data/bronze/wechat_bronze.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(messages, f, ensure_ascii=False, indent=2)

print(f"\n已保存到: {output_path}")
