"""
数据清洗模块
阶段 2：数据清洗

功能：
- 去重：基于 (timestamp, sender, content) 三元组
- 去噪：过滤过短消息、纯表情
- 对话分段：基于时间间隔切割会话
- 时间标准化：统一为 ISO 8601 格式
- 发送者匿名化（可选）
- 输出清洗统计报告
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import defaultdict


class DataCleaner:
    """数据清洗器"""
    
    def __init__(self, messages: List[Dict], session_gap_minutes: int = 120):
        """
        初始化清洗器
        
        Args:
            messages: 原始消息列表
            session_gap_minutes: 会话分割时间间隔（分钟），默认2小时
        """
        self.messages = messages
        self.session_gap = timedelta(minutes=session_gap_minutes)
        self.cleaned_messages: List[Dict] = []
        self.sessions: List[List[Dict]] = []
        
        # 统计信息
        self.stats = {
            'original_count': len(messages),
            'duplicates_removed': 0,
            'noise_removed': 0,
            'final_count': 0,
            'session_count': 0,
        }
    
    def _deduplicate(self, messages: List[Dict]) -> List[Dict]:
        """
        基于 (timestamp, sender, content) 去重
        """
        seen = set()
        unique_messages = []
        
        for msg in messages:
            key = (msg.get('timestamp'), msg.get('sender'), msg.get('content'))
            if key not in seen:
                seen.add(key)
                unique_messages.append(msg)
        
        self.stats['duplicates_removed'] = len(messages) - len(unique_messages)
        return unique_messages
    
    def _remove_noise(self, messages: List[Dict]) -> List[Dict]:
        """
        去噪：过滤过短消息、纯表情、纯符号
        """
        clean_messages = []
        
        for msg in messages:
            content = msg.get('content', '').strip()
            
            # 过滤空消息
            if not content:
                continue
            
            # 过滤过短消息（少于2个字符）
            if len(content) < 2:
                continue
            
            # 过滤纯表情/纯符号（没有字母或汉字）
            if not re.search(r'[\u4e00-\u9fa5a-zA-Z]', content):
                # 如果全是数字，也保留（可能是时间、价格等）
                if not re.search(r'\d', content):
                    continue
            
            # 过滤重复刷屏（连续重复字符超过10次）
            if re.match(r'^(.)\1{9,}$', content):
                continue
            
            clean_messages.append(msg)
        
        self.stats['noise_removed'] = len(messages) - len(clean_messages)
        return clean_messages
    
    def _parse_datetime(self, timestamp_str: str) -> Optional[datetime]:
        """解析时间戳"""
        if not timestamp_str:
            return None
        try:
            # 尝试 ISO 格式
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            try:
                # 尝试原始格式
                return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            except:
                return None
    
    def _segment_sessions(self, messages: List[Dict]) -> List[List[Dict]]:
        """
        基于时间间隔将消息分割为会话
        """
        if not messages:
            return []
        
        # 按时间排序
        sorted_messages = sorted(
            messages, 
            key=lambda x: x.get('timestamp') or ''
        )
        
        sessions = []
        current_session = []
        last_timestamp = None
        
        for msg in sorted_messages:
            current_ts = self._parse_datetime(msg.get('timestamp', ''))
            
            if current_ts is None:
                continue
            
            # 如果是第一条消息，或时间间隔超过阈值，开启新会话
            if last_timestamp is None or (current_ts - last_timestamp) > self.session_gap:
                if current_session:
                    sessions.append(current_session)
                current_session = [msg]
            else:
                current_session.append(msg)
            
            last_timestamp = current_ts
        
        # 添加最后一个会话
        if current_session:
            sessions.append(current_session)
        
        self.stats['session_count'] = len(sessions)
        return sessions
    
    def _anonymize_senders(self, messages: List[Dict]) -> List[Dict]:
        """
        发送者匿名化：将真实名字替换为 角色A、角色B...
        """
        # 收集所有发送者
        senders = list(set(msg.get('sender', 'Unknown') for msg in messages))
        
        # 创建映射
        sender_map = {}
        for i, sender in enumerate(sorted(senders)):
            sender_map[sender] = f"角色{chr(65 + i)}"  # A, B, C...
        
        # 替换
        for msg in messages:
            msg['sender_original'] = msg.get('sender')
            msg['sender'] = sender_map.get(msg.get('sender'), 'Unknown')
        
        return messages
    
    def clean(self, anonymize: bool = True) -> List[Dict]:
        """
        执行完整清洗流程
        
        Args:
            anonymize: 是否匿名化发送者名称
            
        Returns:
            清洗后的消息列表
        """
        print("🧹 开始数据清洗...")
        
        # Step 1: 去重
        messages = self._deduplicate(self.messages)
        print(f"   去重完成: 移除 {self.stats['duplicates_removed']} 条重复消息")
        
        # Step 2: 去噪
        messages = self._remove_noise(messages)
        print(f"   去噪完成: 移除 {self.stats['noise_removed']} 条噪声消息")
        
        # Step 3: 对话分段
        self.sessions = self._segment_sessions(messages)
        print(f"   分段完成: 划分为 {self.stats['session_count']} 个会话")
        
        # 将分段信息添加到每条消息
        for session_idx, session in enumerate(self.sessions):
            for msg in session:
                msg['session_id'] = session_idx
        
        # 合并所有消息
        self.cleaned_messages = []
        for session in self.sessions:
            self.cleaned_messages.extend(session)
        
        # Step 4: 匿名化（可选）
        if anonymize:
            self.cleaned_messages = self._anonymize_senders(self.cleaned_messages)
            print("   匿名化完成")
        
        self.stats['final_count'] = len(self.cleaned_messages)
        
        print(f"\n✅ 清洗完成！")
        print(f"   原始消息: {self.stats['original_count']}")
        print(f"   清洗后: {self.stats['final_count']}")
        print(f"   移除总计: {self.stats['original_count'] - self.stats['final_count']}")
        
        return self.cleaned_messages
    
    def get_stats_report(self) -> Dict:
        """获取清洗统计报告"""
        return {
            'original_count': self.stats['original_count'],
            'duplicates_removed': self.stats['duplicates_removed'],
            'noise_removed': self.stats['noise_removed'],
            'final_count': self.stats['final_count'],
            'session_count': self.stats['session_count'],
            'removal_rate': round(
                (self.stats['original_count'] - self.stats['final_count']) / self.stats['original_count'] * 100, 2
            ) if self.stats['original_count'] > 0 else 0
        }
    
    def get_sessions(self) -> List[List[Dict]]:
        """获取分段后的会话列表"""
        return self.sessions
    
    def save_cleaned_data(self, output_path: str) -> str:
        """
        保存清洗后的数据
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            保存的文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.cleaned_messages, f, ensure_ascii=False, indent=2)
        
        return str(output_path)
    
    def save_sessions(self, output_path: str) -> str:
        """
        保存分段后的会话数据
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            保存的文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        sessions_data = []
        for idx, session in enumerate(self.sessions):
            sessions_data.append({
                'session_id': idx,
                'message_count': len(session),
                'messages': session
            })
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sessions_data, f, ensure_ascii=False, indent=2)
        
        return str(output_path)


def clean_chat_data(input_file: str, output_dir: str = None, 
                    session_gap_minutes: int = 120, anonymize: bool = True) -> Dict:
    """
    便捷的清洗函数
    
    Args:
        input_file: 输入的 JSON 文件路径
        output_dir: 输出目录，默认为输入文件所在目录
        session_gap_minutes: 会话分割时间间隔
        anonymize: 是否匿名化
        
    Returns:
        清洗统计报告
    """
    # 读取数据
    with open(input_file, 'r', encoding='utf-8') as f:
        messages = json.load(f)
    
    # 清洗
    cleaner = DataCleaner(messages, session_gap_minutes=session_gap_minutes)
    cleaned_messages = cleaner.clean(anonymize=anonymize)
    
    # 确定输出路径
    if output_dir is None:
        output_dir = Path(input_file).parent
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存清洗后数据
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    cleaned_path = output_dir / f"wechat_silver_{timestamp}.json"
    cleaner.save_cleaned_data(cleaned_path)
    print(f"   清洗数据已保存: {cleaned_path}")
    
    # 保存会话数据
    sessions_path = output_dir / f"wechat_silver_sessions_{timestamp}.json"
    cleaner.save_sessions(sessions_path)
    print(f"   会话数据已保存: {sessions_path}")
    
    return cleaner.get_stats_report()


if __name__ == '__main__':
    import sys
    
    # 默认使用项目中的 bronze 数据
    default_file = Path(__file__).parent.parent / 'data' / 'bronze' / 'wechat_bronze.json'
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    elif default_file.exists():
        input_file = default_file
    else:
        print("请提供输入文件路径")
        sys.exit(1)
    
    print(f"正在清洗: {input_file}\n")
    report = clean_chat_data(input_file)
    
    print("\n清洗统计报告:")
    for key, value in report.items():
        print(f"   {key}: {value}")
