"""
AI 叙事生成模块
阶段 5：AI 叙事生成

功能：
- 基于聊天记录生成 Galgame 风格叙事
- 自动生成分支选项
- 维护剧情状态
- 支持存档/读档
"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


class StoryGenerator:
    """故事生成器"""
    
    # 预设场景模板
    SCENE_TEMPLATES = {
        '约会': {
            'descriptions': [
                "阳光透过树叶洒在你们身上，空气中弥漫着淡淡的花香。",
                "你们并肩走在小路上，偶尔肩膀轻轻碰在一起。",
                "微风拂过，带来远处咖啡馆的香气。"
            ],
            'moods': ['浪漫', '温馨', '轻松']
        },
        '告白': {
            'descriptions': [
                "时间仿佛静止了，你能听到自己的心跳声。",
                "夕阳的余晖映照在TA的脸上，让这一刻变得格外珍贵。",
                "所有的勇气在这一刻汇聚成一句话。"
            ],
            'moods': ['紧张', '期待', '幸福']
        },
        '日常': {
            'descriptions': [
                "平凡的一天，但因为有了对方而变得特别。",
                "窗外的风景依旧，但此刻的心情却不同以往。",
                "生活中的小确幸，往往就藏在这些简单的对话里。"
            ],
            'moods': ['平静', '温暖', '舒适']
        },
        '关心': {
            'descriptions': [
                "虽然相隔两地，但牵挂却从未停止。",
                "一句简单的问候，却包含了最深的在意。",
                "在这个忙碌的世界里，有人记得关心你。"
            ],
            'moods': ['感动', '温暖', '安心']
        }
    }
    
    def __init__(self, messages: List[Dict], sessions: List[Dict]):
        """
        初始化故事生成器
        
        Args:
            messages: Gold 层消息数据
            sessions: 会话特征数据
        """
        self.messages = messages
        self.sessions = sessions
        self.current_session_idx = 0
        self.current_message_idx = 0
        self.story_history: List[Dict] = []
        self.player_choices: List[str] = []
        
    def _get_current_context(self) -> Dict:
        """获取当前剧情上下文"""
        if self.current_session_idx >= len(self.sessions):
            return None
        
        session = self.sessions[self.current_session_idx]
        scene_type = session.get('scene', '日常')
        sentiment = session.get('sentiment', {}).get('dominant_label', 'neutral')
        
        # 获取当前会话的消息
        session_messages = [
            m for m in self.messages 
            if m.get('session_id') == self.current_session_idx
        ]
        
        return {
            'session': session,
            'scene_type': scene_type,
            'sentiment': sentiment,
            'messages': session_messages,
            'keywords': session.get('keywords', [])
        }
    
    def _generate_scene_description(self, context: Dict) -> str:
        """生成场景描述"""
        scene_type = context['scene_type']
        template = self.SCENE_TEMPLATES.get(scene_type, self.SCENE_TEMPLATES['日常'])
        
        # 随机选择描述
        desc = random.choice(template['descriptions'])
        mood = random.choice(template['moods'])
        
        # 获取关键消息
        messages = context['messages']
        if messages:
            key_msg = messages[0]['content'][:50]
        else:
            key_msg = ""
        
        return f"【{scene_type}·{mood}】\n\n{desc}\n\n回忆片段：\"{key_msg}...\""
    
    def _generate_dialogue(self, context: Dict) -> List[Dict]:
        """生成对话内容"""
        messages = context['messages']
        dialogue = []
        
        # 选取 2-3 条代表性消息
        if len(messages) <= 3:
            selected = messages
        else:
            # 选取开头、中间、结尾
            selected = [
                messages[0],
                messages[len(messages)//2],
                messages[-1]
            ]
        
        for msg in selected:
            sender = msg.get('sender', 'Unknown')
            content = msg.get('content', '')
            features = msg.get('features', {})
            
            dialogue.append({
                'speaker': sender,
                'text': content,
                'emotion': features.get('sentiment_label', 'neutral')
            })
        
        return dialogue
    
    def _generate_choices(self, context: Dict) -> List[Dict]:
        """生成分支选项"""
        scene_type = context['scene_type']
        sentiment = context['sentiment']
        
        choices = []
        
        if scene_type == '告白':
            choices = [
                {'text': '接受这份心意', 'emotion': 'positive', 'next_scene': 'happy_ending'},
                {'text': '需要更多时间', 'emotion': 'neutral', 'next_scene': 'continue'},
                {'text': '委婉拒绝', 'emotion': 'negative', 'next_scene': 'sad_ending'}
            ]
        elif scene_type == '约会':
            choices = [
                {'text': '主动牵起TA的手', 'emotion': 'positive', 'next_scene': 'closer'},
                {'text': '聊聊最近的趣事', 'emotion': 'neutral', 'next_scene': 'chat'},
                {'text': '安静地享受此刻', 'emotion': 'neutral', 'next_scene': 'peaceful'}
            ]
        elif scene_type == '关心':
            choices = [
                {'text': '表达感谢', 'emotion': 'positive', 'next_scene': 'grateful'},
                {'text': '也关心对方', 'emotion': 'positive', 'next_scene': 'mutual'},
                {'text': '转移话题', 'emotion': 'neutral', 'next_scene': 'change'}
            ]
        else:  # 日常
            choices = [
                {'text': '分享你的想法', 'emotion': 'positive', 'next_scene': 'share'},
                {'text': '询问对方的近况', 'emotion': 'neutral', 'next_scene': 'ask'},
                {'text': '提议见面', 'emotion': 'positive', 'next_scene': 'meet'}
            ]
        
        return choices
    
    def generate_scene(self) -> Dict:
        """
        生成当前场景
        
        Returns:
            场景数据
        """
        context = self._get_current_context()
        if context is None:
            return {'type': 'ending', 'content': '故事已结束'}
        
        scene = {
            'session_id': self.current_session_idx,
            'type': 'scene',
            'description': self._generate_scene_description(context),
            'dialogue': self._generate_dialogue(context),
            'choices': self._generate_choices(context)
        }
        
        return scene
    
    def make_choice(self, choice_idx: int) -> Dict:
        """
        处理玩家选择
        
        Args:
            choice_idx: 选择的索引
            
        Returns:
            下一个场景
        """
        context = self._get_current_context()
        if context is None:
            return {'type': 'ending', 'content': '故事已结束'}
        
        choices = self._generate_choices(context)
        if choice_idx < 0 or choice_idx >= len(choices):
            return {'error': '无效的选择'}
        
        selected = choices[choice_idx]
        
        # 记录选择
        self.player_choices.append({
            'session_id': self.current_session_idx,
            'choice': selected['text'],
            'emotion': selected['emotion']
        })
        
        # 推进剧情
        self.current_session_idx += 1
        
        # 返回下一个场景
        return self.generate_scene()
    
    def get_story_summary(self) -> Dict:
        """获取故事摘要"""
        return {
            'total_sessions': len(self.sessions),
            'current_session': self.current_session_idx,
            'progress': f"{self.current_session_idx}/{len(self.sessions)}",
            'choices_made': len(self.player_choices),
            'choice_history': self.player_choices
        }
    
    def save_game(self, slot: int = 0) -> str:
        """
        存档
        
        Args:
            slot: 存档槽位
            
        Returns:
            存档文件路径
        """
        save_data = {
            'timestamp': datetime.now().isoformat(),
            'current_session_idx': self.current_session_idx,
            'current_message_idx': self.current_message_idx,
            'player_choices': self.player_choices,
            'story_summary': self.get_story_summary()
        }
        
        save_dir = Path(__file__).parent.parent / 'data' / 'saves'
        save_dir.mkdir(parents=True, exist_ok=True)
        
        save_file = save_dir / f"save_slot_{slot}.json"
        with open(save_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        
        return str(save_file)
    
    def load_game(self, slot: int = 0) -> bool:
        """
        读档
        
        Args:
            slot: 存档槽位
            
        Returns:
            是否成功
        """
        save_file = Path(__file__).parent.parent / 'data' / 'saves' / f"save_slot_{slot}.json"
        
        if not save_file.exists():
            return False
        
        with open(save_file, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
        
        self.current_session_idx = save_data.get('current_session_idx', 0)
        self.current_message_idx = save_data.get('current_message_idx', 0)
        self.player_choices = save_data.get('player_choices', [])
        
        return True


def create_story(gold_file: str) -> StoryGenerator:
    """
    便捷的故事创建函数
    
    Args:
        gold_file: Gold 层数据文件路径
        
    Returns:
        StoryGenerator 实例
    """
    with open(gold_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    messages = data.get('messages', [])
    sessions = data.get('session_features', [])
    
    return StoryGenerator(messages, sessions)


if __name__ == '__main__':
    import sys
    
    default_file = Path(__file__).parent.parent / 'data' / 'gold' / 'wechat_gold.json'
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    elif default_file.exists():
        input_file = default_file
    else:
        print("请提供 Gold 层数据文件路径")
        sys.exit(1)
    
    print("=" * 60)
    print("回忆放大镜 - 叙事生成测试")
    print("=" * 60)
    
    generator = create_story(input_file)
    
    print("\n📖 故事开始\n")
    
    # 生成第一个场景
    scene = generator.generate_scene()
    
    while scene.get('type') == 'scene':
        print(f"\n{scene['description']}\n")
        
        print("对话：")
        for d in scene['dialogue']:
            emotion_emoji = {'positive': '😊', 'negative': '😢', 'neutral': '😐'}.get(d['emotion'], '')
            print(f"  {emotion_emoji} {d['speaker']}: {d['text']}")
        
        print("\n选择：")
        for i, choice in enumerate(scene['choices']):
            print(f"  [{i}] {choice['text']}")
        
        # 模拟选择第一个选项
        print("\n> 选择 [0]\n")
        scene = generator.make_choice(0)
    
    print("\n" + "=" * 60)
    print("故事摘要：")
    summary = generator.get_story_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
