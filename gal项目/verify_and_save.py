import json
from pathlib import Path
import re
from datetime import datetime, timedelta

# ========== 阶段 1：解析 ==========
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

# 保存 bronze
bronze_path = Path('C:/Users/gch20/Documents/memory-lens/data/bronze/wechat_bronze.json')
with open(bronze_path, 'w', encoding='utf-8') as f:
    json.dump(messages, f, ensure_ascii=False, indent=2)

# 阶段 1 报告
report1 = {
    'stage': '阶段 1：数据摄取',
    'total_messages': len(messages),
    'senders': list(set(m['sender'] for m in messages)),
    'sample_messages': messages[:5]
}

# ========== 阶段 2：清洗 ==========
# 去重
seen = set()
unique_messages = []
for msg in messages:
    key = (msg['timestamp'], msg['sender'], msg['content'])
    if key not in seen:
        seen.add(key)
        unique_messages.append(msg)

duplicates_removed = len(messages) - len(unique_messages)

# 去噪
clean_messages = []
for msg in unique_messages:
    content = msg['content'].strip()
    if len(content) < 2:
        continue
    if not re.search(r'[\u4e00-\u9fa5a-zA-Z]', content):
        if not re.search(r'\d', content):
            continue
    clean_messages.append(msg)

noise_removed = len(unique_messages) - len(clean_messages)

# 分段
session_gap = timedelta(minutes=120)
sorted_messages = sorted(clean_messages, key=lambda x: x['timestamp'])

sessions = []
current_session = []
last_ts = None

for msg in sorted_messages:
    try:
        current_ts = datetime.strptime(msg['timestamp'], '%Y-%m-%d %H:%M:%S')
    except:
        continue
    
    if last_ts is None or (current_ts - last_ts) > session_gap:
        if current_session:
            sessions.append(current_session)
        current_session = [msg]
    else:
        current_session.append(msg)
    
    last_ts = current_ts

if current_session:
    sessions.append(current_session)

# 添加 session_id
for idx, session in enumerate(sessions):
    for msg in session:
        msg['session_id'] = idx

# 匿名化
senders = list(set(m['sender'] for m in clean_messages))
sender_map = {s: f"角色{chr(65+i)}" for i, s in enumerate(sorted(senders))}
for msg in clean_messages:
    msg['sender_anon'] = sender_map.get(msg['sender'], 'Unknown')

# 保存 silver
silver_path = Path('C:/Users/gch20/Documents/memory-lens/data/silver/wechat_silver.json')
silver_path.parent.mkdir(parents=True, exist_ok=True)
with open(silver_path, 'w', encoding='utf-8') as f:
    json.dump(clean_messages, f, ensure_ascii=False, indent=2)

# 保存会话
sessions_data = [{'session_id': i, 'message_count': len(s), 'messages': s} for i, s in enumerate(sessions)]
sessions_path = Path('C:/Users/gch20/Documents/memory-lens/data/silver/wechat_silver_sessions.json')
with open(sessions_path, 'w', encoding='utf-8') as f:
    json.dump(sessions_data, f, ensure_ascii=False, indent=2)

# 阶段 2 报告
report2 = {
    'stage': '阶段 2：数据清洗',
    'original_count': len(messages),
    'duplicates_removed': duplicates_removed,
    'noise_removed': noise_removed,
    'final_count': len(clean_messages),
    'session_count': len(sessions),
    'removal_rate': round((len(messages) - len(clean_messages)) / len(messages) * 100, 2),
    'sender_mapping': sender_map,
    'sessions_summary': [{'session_id': i, 'message_count': len(s)} for i, s in enumerate(sessions)]
}

# 保存完整报告
report_path = Path('C:/Users/gch20/Documents/memory-lens/test_report.json')
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump({'stage1': report1, 'stage2': report2}, f, ensure_ascii=False, indent=2)

print("验证完成！")
