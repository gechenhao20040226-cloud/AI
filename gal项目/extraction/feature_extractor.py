"""
情感与特征提取模块
阶段 3：情感与特征提取

功能：
- 关键词提取：jieba 分词 + TF-IDF
- 情感分析：基于规则 + 情感词典
- 对话节奏分析：消息频率、回复时长
- 关键场景识别：情绪高潮场景检测
- 输出带标签的 Gold 层数据
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class FeatureExtractor:
    """对话特征提取器"""
    
    # 情感词典（简化版）
    POSITIVE_WORDS = {
        '好', '棒', '喜欢', '爱', '开心', '快乐', '幸福', '感谢', '谢谢', '赞',
        '美', '漂亮', '好看', '好吃', '好喝', '好玩', '有趣', '舒服', '满意',
        '期待', '想', '愿意', '可以', '行', '好呀', '好啊', '好的', '嗯', '哦',
        '哈哈', '嘿嘿', '嘻嘻', '呵呵', '嘿嘿', '开心', '高兴', '兴奋', '激动',
        '惊喜', '感动', '温暖', '甜蜜', '浪漫', '贴心', '温柔', '可爱'
    }
    
    NEGATIVE_WORDS = {
        '坏', '差', '讨厌', '恨', '难过', '伤心', '痛苦', '烦', '累', '困',
        '不好', '不行', '不要', '不能', '没', '没有', '无', '差劲', '糟糕',
        '失望', '生气', '愤怒', '郁闷', '烦躁', '焦虑', '担心', '害怕', '恐惧',
        '孤独', '寂寞', '无聊', '尴尬', '无奈', '遗憾', '可惜', '抱歉', '对不起'
    }
    
    # 场景关键词
    SCENE_KEYWORDS = {
        '告白': ['喜欢', '爱', '在一起', '表白', '心意', '感觉', '心动'],
        '约会': ['见面', '吃饭', '电影', '公园', '散步', '逛街', '出去玩'],
        '争吵': ['生气', '不对', '错了', '误会', '解释', '冷静', '别这样'],
        '关心': ['注意', '身体', '休息', '吃饭', '睡觉', '照顾好', '担心'],
        '告别': ['再见', '走了', '保重', '联系', '想你了', '舍不得'],
        '日常': ['在干嘛', '忙', '工作', '学习', '天气', '今天', '明天']
    }
    
    def __init__(self, messages: List[Dict]):
        """
        初始化特征提取器
        
        Args:
            messages: 清洗后的消息列表（Silver 层数据）
        """
        self.messages = messages
        self.features: List[Dict] = []
        
    def _tokenize(self, text: str) -> List[str]:
        """
        简易中文分词（基于规则）
        实际项目中可替换为 jieba
        """
        # 去除标点
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
        # 简单按空格和常见词分割
        words = []
        i = 0
        while i < len(text):
            # 尝试匹配 2-4 字词
            matched = False
            for length in [4, 3, 2, 1]:
                if i + length <= len(text):
                    word = text[i:i+length].strip()
                    if word and not word.isspace():
                        words.append(word)
                        i += length
                        matched = True
                        break
            if not matched:
                i += 1
        return words
    
    def extract_keywords(self, text: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        提取关键词（简化版 TF-IDF）
        
        Args:
            text: 输入文本
            top_k: 返回前 k 个关键词
            
        Returns:
            [(关键词, 权重), ...]
        """
        words = self._tokenize(text)
        
        # 过滤停用词
        stopwords = {'的', '了', '在', '是', '我', '你', '他', '她', '它', '们',
                     '这', '那', '有', '和', '就', '都', '而', '及', '与', '或',
                     '一个', '没有', '我们', '你们', '他们', '这个', '那个'}
        words = [w for w in words if w not in stopwords and len(w) >= 2]
        
        # 统计词频
        word_counts = Counter(words)
        total = sum(word_counts.values())
        
        # 计算 TF（词频）
        keywords = [(word, count/total) for word, count in word_counts.most_common(top_k)]
        
        return keywords
    
    def analyze_sentiment(self, text: str) -> Dict:
        """
        情感分析
        
        Args:
            text: 输入文本
            
        Returns:
            {'label': 'positive'/'negative'/'neutral', 'score': float}
        """
        words = self._tokenize(text)
        
        pos_count = sum(1 for w in words if w in self.POSITIVE_WORDS)
        neg_count = sum(1 for w in words if w in self.NEGATIVE_WORDS)
        
        total = len(words) if words else 1
        
        # 计算情感得分 (-1 ~ 1)
        score = (pos_count - neg_count) / max(total * 0.3, 1)
        
        # 标签判断
        if score > 0.1:
            label = 'positive'
        elif score < -0.1:
            label = 'negative'
        else:
            label = 'neutral'
        
        return {
            'label': label,
            'score': round(score, 3),
            'positive_words': pos_count,
            'negative_words': neg_count
        }
    
    def detect_scene(self, text: str) -> Optional[str]:
        """
        检测场景类型
        
        Args:
            text: 输入文本
            
        Returns:
            场景类型或 None
        """
        text = text.lower()
        scores = {}
        
        for scene, keywords in self.SCENE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[scene] = score
        
        if scores:
            return max(scores, key=scores.get)
        return None
    
    def analyze_conversation_rhythm(self, session_messages: List[Dict]) -> Dict:
        """
        分析对话节奏
        
        Args:
            session_messages: 一个会话的消息列表
            
        Returns:
            节奏特征
        """
        if len(session_messages) < 2:
            return {'message_count': len(session_messages), 'avg_response_time': None}
        
        # 计算回复间隔
        response_times = []
        for i in range(1, len(session_messages)):
            try:
                t1 = datetime.fromisoformat(session_messages[i-1]['timestamp'])
                t2 = datetime.fromisoformat(session_messages[i]['timestamp'])
                delta = (t2 - t1).total_seconds() / 60  # 分钟
                response_times.append(delta)
            except:
                continue
        
        if response_times:
            avg_time = sum(response_times) / len(response_times)
            max_time = max(response_times)
            min_time = min(response_times)
        else:
            avg_time = max_time = min_time = None
        
        return {
            'message_count': len(session_messages),
            'avg_response_time_minutes': round(avg_time, 2) if avg_time else None,
            'max_response_time_minutes': round(max_time, 2) if max_time else None,
            'min_response_time_minutes': round(min_time, 2) if min_time else None,
            'total_duration_minutes': round(sum(response_times), 2) if response_times else 0
        }
    
    def extract_session_features(self, session_messages: List[Dict], session_id: int) -> Dict:
        """
        提取单个会话的特征
        
        Args:
            session_messages: 会话消息列表
            session_id: 会话 ID
            
        Returns:
            会话特征
        """
        # 合并所有消息文本
        all_text = ' '.join([m.get('content', '') for m in session_messages])
        
        # 关键词提取
        keywords = self.extract_keywords(all_text, top_k=10)
        
        # 情感分析
        sentiments = [self.analyze_sentiment(m.get('content', '')) for m in session_messages]
        avg_sentiment = sum(s['score'] for s in sentiments) / len(sentiments) if sentiments else 0
        
        # 主导情感
        labels = [s['label'] for s in sentiments]
        dominant_sentiment = Counter(labels).most_common(1)[0][0] if labels else 'neutral'
        
        # 场景检测
        scenes = [self.detect_scene(m.get('content', '')) for m in session_messages]
        scenes = [s for s in scenes if s]
        dominant_scene = Counter(scenes).most_common(1)[0][0] if scenes else '日常'
        
        # 对话节奏
        rhythm = self.analyze_conversation_rhythm(session_messages)
        
        # 发送者统计
        sender_counts = Counter([m.get('sender', 'Unknown') for m in session_messages])
        
        return {
            'session_id': session_id,
            'message_count': len(session_messages),
            'keywords': keywords,
            'sentiment': {
                'average_score': round(avg_sentiment, 3),
                'dominant_label': dominant_sentiment,
                'distribution': dict(Counter(labels))
            },
            'scene': dominant_scene,
            'rhythm': rhythm,
            'sender_distribution': dict(sender_counts),
            'start_time': session_messages[0].get('timestamp') if session_messages else None,
            'end_time': session_messages[-1].get('timestamp') if session_messages else None
        }
    
    def extract(self, sessions: List[List[Dict]]) -> List[Dict]:
        """
        执行完整特征提取
        
        Args:
            sessions: 分段后的会话列表
            
        Returns:
            带特征的消息列表（Gold 层数据）
        """
        print("🔍 开始特征提取...")
        
        session_features = []
        
        for idx, session in enumerate(sessions):
            print(f"   处理会话 {idx+1}/{len(sessions)}...")
            
            # 提取会话级特征
            features = self.extract_session_features(session, idx)
            session_features.append(features)
            
            # 为每条消息添加特征标签
            for msg in session:
                sentiment = self.analyze_sentiment(msg.get('content', ''))
                scene = self.detect_scene(msg.get('content', ''))
                keywords = self.extract_keywords(msg.get('content', ''), top_k=3)
                
                msg['features'] = {
                    'sentiment_label': sentiment['label'],
                    'sentiment_score': sentiment['score'],
                    'scene': scene,
                    'keywords': [k[0] for k in keywords],
                    'session_sentiment': features['sentiment']['dominant_label'],
                    'session_scene': features['scene']
                }
        
        self.features = session_features
        
        print(f"\n✅ 特征提取完成！")
        print(f"   会话数: {len(sessions)}")
        print(f"   场景分布: {dict(Counter([f['scene'] for f in session_features]))}")
        print(f"   情感分布: {dict(Counter([f['sentiment']['dominant_label'] for f in session_features]))}")
        
        return self.messages
    
    def get_feature_summary(self) -> Dict:
        """获取特征摘要"""
        if not self.features:
            return {}
        
        all_keywords = []
        for f in self.features:
            all_keywords.extend([k[0] for k in f['keywords']])
        
        return {
            'total_sessions': len(self.features),
            'scene_distribution': dict(Counter([f['scene'] for f in self.features])),
            'sentiment_distribution': dict(Counter([f['sentiment']['dominant_label'] for f in self.features])),
            'top_keywords': Counter(all_keywords).most_common(10),
            'avg_messages_per_session': sum(f['message_count'] for f in self.features) / len(self.features)
        }
    
    def save_gold_data(self, output_path: str) -> str:
        """
        保存 Gold 层数据
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            保存的文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'messages': self.messages,
            'session_features': self.features,
            'summary': self.get_feature_summary()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return str(output_path)


def extract_features(input_file: str, output_dir: str = None) -> Dict:
    """
    便捷的特征提取函数
    
    Args:
        input_file: 输入的 Silver 层 JSON 文件路径
        output_dir: 输出目录
        
    Returns:
        特征摘要
    """
    # 读取数据
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 可能是直接的消息列表，也可能是带会话结构的数据
    if isinstance(data, list):
        messages = data
        # 重新组织为会话
        sessions_dict = {}
        for msg in messages:
            sid = msg.get('session_id', 0)
            if sid not in sessions_dict:
                sessions_dict[sid] = []
            sessions_dict[sid].append(msg)
        sessions = [sessions_dict[k] for k in sorted(sessions_dict.keys())]
    else:
        messages = data.get('messages', [])
        sessions = data.get('sessions', [])
    
    # 提取特征
    extractor = FeatureExtractor(messages)
    extractor.extract(sessions)
    
    # 保存
    if output_dir is None:
        output_dir = Path(input_file).parent.parent / 'gold'
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = output_dir / f"wechat_gold_{timestamp}.json"
    extractor.save_gold_data(output_file)
    
    print(f"\n💾 Gold 数据已保存: {output_file}")
    
    return extractor.get_feature_summary()


if __name__ == '__main__':
    import sys
    
    # 默认使用项目中的 silver 数据
    default_file = Path(__file__).parent.parent / 'data' / 'silver' / 'wechat_silver.json'
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    elif default_file.exists():
        input_file = default_file
    else:
        print("请提供输入文件路径")
        print(f"默认路径不存在: {default_file}")
        sys.exit(1)
    
    print(f"正在处理: {input_file}\n")
    summary = extract_features(input_file)
    
    print("\n特征摘要:")
    for key, value in summary.items():
        print(f"   {key}: {value}")
