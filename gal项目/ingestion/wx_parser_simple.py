"""
微信聊天记录解析器（纯 Python，无依赖版本）
阶段 1：数据摄取模块

功能：
- 解析微信导出的 .txt 格式聊天记录
- 提取时间戳、发送者、消息内容
- 过滤系统消息
- 输出 JSON 格式（不依赖 pandas）
"""

import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class WeChatParser:
    """微信聊天记录解析器"""
    
    # 微信消息正则模式：匹配 "YYYY-MM-DD HH:MM:SS 发送者"
    MESSAGE_PATTERN = re.compile(
        r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(.+)$'
    )
    
    # 需要过滤的系统消息关键词
    SYSTEM_KEYWORDS = [
        '撤回了一条消息',
        '消息已发出，但被对方拒收了',
        '开启了朋友验证',
        '拍一拍',
        '拍了拍',
        '[语音]',
        '[图片]',
        '[视频]',
        '[文件]',
        '[位置]',
        '[链接]',
        '[动画表情]',
        '微信聊天记录',
    ]
    
    def __init__(self, file_path: str):
        """
        初始化解析器
        
        Args:
            file_path: 微信聊天记录文件路径
        """
        self.file_path = Path(file_path)
        self.raw_messages: List[Dict] = []
        
    def _is_system_message(self, content: str) -> bool:
        """判断是否为系统消息"""
        content = content.strip()
        for keyword in self.SYSTEM_KEYWORDS:
            if keyword in content:
                return True
        # 过滤纯表情符号（长度小于2的纯符号）
        if len(content) <= 2 and not any(c.isalnum() for c in content):
            return True
        return False
    
    def _parse_timestamp(self, ts_str: str) -> Optional[str]:
        """解析时间戳字符串，返回 ISO 格式"""
        try:
            dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            return dt.isoformat()
        except ValueError:
            return None
    
    def parse(self) -> List[Dict]:
        """
        解析聊天记录文件
        
        Returns:
            消息列表，每条消息包含：timestamp, sender, content, platform
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_message = None
        
        for line in lines:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            
            # 尝试匹配消息头
            match = self.MESSAGE_PATTERN.match(line)
            
            if match:
                # 保存上一条消息
                if current_message and not self._is_system_message(current_message['content']):
                    self.raw_messages.append(current_message)
                
                # 创建新消息
                timestamp_str = match.group(1)
                sender = match.group(2).strip()
                timestamp = self._parse_timestamp(timestamp_str)
                
                current_message = {
                    'timestamp': timestamp,
                    'sender': sender,
                    'content': '',
                    'platform': 'wechat'
                }
            else:
                # 当前行是消息内容（多行消息）
                if current_message is not None:
                    if current_message['content']:
                        current_message['content'] += '\n'
                    current_message['content'] += line
        
        # 保存最后一条消息
        if current_message and not self._is_system_message(current_message['content']):
            self.raw_messages.append(current_message)
        
        # 过滤掉内容为空的消息
        self.raw_messages = [
            msg for msg in self.raw_messages 
            if msg['content'].strip() != ''
        ]
        
        return self.raw_messages
    
    def get_stats(self) -> Dict:
        """获取解析统计信息"""
        if not self.raw_messages:
            self.parse()
        
        senders = list(set(msg['sender'] for msg in self.raw_messages))
        timestamps = [msg['timestamp'] for msg in self.raw_messages if msg['timestamp']]
        
        return {
            'total_messages': len(self.raw_messages),
            'unique_senders': len(senders),
            'senders': senders,
            'date_range': {
                'start': min(timestamps) if timestamps else None,
                'end': max(timestamps) if timestamps else None,
            },
            'platform': 'wechat'
        }
    
    def save_to_json(self, output_path: str) -> str:
        """
        将解析结果保存为 JSON 格式
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            保存的文件路径
        """
        if not self.raw_messages:
            self.parse()
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.raw_messages, f, ensure_ascii=False, indent=2)
        
        return str(output_path)


def parse_wechat_chat(file_path: str, save_json: bool = True, 
                      output_dir: str = None) -> List[Dict]:
    """
    便捷的微信聊天记录解析函数
    
    Args:
        file_path: 聊天记录文件路径
        save_json: 是否保存为 JSON 格式
        output_dir: JSON 文件输出目录，默认为 data/bronze
        
    Returns:
        解析后的消息列表
    """
    parser = WeChatParser(file_path)
    messages = parser.parse()
    stats = parser.get_stats()
    
    print(f"✅ 解析完成！")
    print(f"   总消息数: {stats['total_messages']}")
    print(f"   发送者: {', '.join(stats['senders'])}")
    if stats['date_range']['start']:
        print(f"   时间范围: {stats['date_range']['start'][:10]} ~ {stats['date_range']['end'][:10]}")
    
    if save_json:
        if output_dir is None:
            # 默认保存到项目 data/bronze 目录
            output_dir = Path(file_path).parent
        else:
            output_dir = Path(output_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"wechat_bronze_{timestamp}.json"
        saved_path = parser.save_to_json(output_file)
        print(f"   已保存: {saved_path}")
    
    return messages


if __name__ == '__main__':
    # 测试解析器
    import sys
    
    # 默认使用项目中的示例数据
    default_file = Path(__file__).parent.parent / 'data' / 'bronze' / 'wx_chat_sample.txt'
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = default_file
    
    print(f"正在解析: {file_path}\n")
    messages = parse_wechat_chat(file_path)
    
    print("\n前5条消息预览:")
    for msg in messages[:5]:
        print(f"[{msg['timestamp'][:19]}] {msg['sender']}: {msg['content'][:50]}...")
