"""
向量化与存储模块
阶段 4：向量化与存储

功能：
- 生成文本 Embedding（简化版）
- 模拟 ChromaDB 向量数据库操作
- 支持语义检索
- Metadata 过滤（时间、情感、场景等）
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class SimpleEmbedding:
    """简化版 Embedding 生成器（基于关键词特征）"""
    
    def __init__(self, dim: int = 64):
        self.dim = dim
    
    def embed(self, text: str) -> List[float]:
        """生成文本的 Embedding 向量"""
        text = text.lower()
        vector = []
        
        # 情感维度
        vector.append(1.0 if any(w in text for w in ['喜欢', '爱', '开心']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['讨厌', '难过', '不好']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['哈哈', '高兴']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['生气', '烦']) else 0.0)
        
        # 场景维度
        vector.append(1.0 if any(w in text for w in ['在一起', '告白', '心动']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['见面', '吃饭', '公园']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['注意', '休息', '身体']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['再见', '走了']) else 0.0)
        
        # 主题维度
        vector.append(1.0 if any(w in text for w in ['吃', '饭', '菜']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['工作', '项目']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['天气', '下雨']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['感觉', '心情']) else 0.0)
        
        # 交互维度
        vector.append(1.0 if '？' in text else 0.0)
        vector.append(1.0 if any(w in text for w in ['好的', '行', '对']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['你好', '在吗']) else 0.0)
        vector.append(1.0 if any(w in text for w in ['拜拜', '晚安']) else 0.0)
        
        # 填充剩余维度
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        while len(vector) < self.dim:
            vector.append((hash_val % 100) / 100.0)
            hash_val = (hash_val * 31) % (2**32)
        
        return vector[:self.dim]
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成 Embedding"""
        return [self.embed(t) for t in texts]


class VectorStore:
    """简化版向量存储（模拟 ChromaDB）"""
    
    def __init__(self, collection_name: str = "chat_memories"):
        self.collection_name = collection_name
        self.documents: List[Dict] = []
        self.embedding_fn = SimpleEmbedding(dim=64)
    
    def add_messages(self, messages: List[Dict]):
        """添加消息到向量库"""
        print(f"🔄 正在生成 Embedding...")
        
        documents = []
        ids = []
        metadatas = []
        
        for i, msg in enumerate(messages):
            content = msg.get('content', '')
            if not content.strip():
                continue
            
            documents.append(content)
            ids.append(f"msg_{i}")
            
            # 构建 metadata
            features = msg.get('features', {})
            metadatas.append({
                'timestamp': msg.get('timestamp', ''),
                'sender': msg.get('sender', ''),
                'session_id': msg.get('session_id', 0),
                'sentiment_label': features.get('sentiment_label', 'neutral'),
                'sentiment_score': features.get('sentiment_score', 0),
                'scene': features.get('scene', '日常'),
                'keywords': ','.join(features.get('keywords', []))
            })
        
        # 生成 embeddings
        embeddings = self.embedding_fn.embed_batch(documents)
        
        # 存储
        for i, doc_id in enumerate(ids):
            self.documents.append({
                'id': doc_id,
                'document': documents[i],
                'embedding': embeddings[i],
                'metadata': metadatas[i]
            })
        
        print(f"✅ 已存储 {len(self.documents)} 条消息")
    
    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)
    
    def search(self, query: str, n_results: int = 5, 
               sentiment: Optional[str] = None,
               scene: Optional[str] = None) -> List[Dict]:
        """
        语义检索
        
        Args:
            query: 查询文本
            n_results: 返回结果数
            sentiment: 情感过滤
            scene: 场景过滤
            
        Returns:
            检索结果列表
        """
        if not self.documents:
            return []
        
        query_embedding = self.embedding_fn.embed(query)
        
        # 计算相似度并过滤
        scored = []
        for doc in self.documents:
            # Metadata 过滤
            if sentiment and doc['metadata'].get('sentiment_label') != sentiment:
                continue
            if scene and doc['metadata'].get('scene') != scene:
                continue
            
            score = self._cosine_similarity(query_embedding, doc['embedding'])
            scored.append({**doc, 'similarity': score})
        
        # 排序并返回 Top-K
        scored.sort(key=lambda x: x['similarity'], reverse=True)
        return scored[:n_results]
    
    def get_stats(self) -> Dict:
        """获取存储统计"""
        if not self.documents:
            return {'total_documents': 0}
        
        sentiments = {}
        scenes = {}
        for doc in self.documents:
            s = doc['metadata'].get('sentiment_label', 'unknown')
            sentiments[s] = sentiments.get(s, 0) + 1
            sc = doc['metadata'].get('scene', 'unknown')
            scenes[sc] = scenes.get(sc, 0) + 1
        
        return {
            'total_documents': len(self.documents),
            'sentiment_distribution': sentiments,
            'scene_distribution': scenes
        }
    
    def save(self, output_path: str):
        """保存向量库到文件"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                'collection_name': self.collection_name,
                'documents': self.documents,
                'stats': self.get_stats()
            }, f, ensure_ascii=False, indent=2)
        
        return str(output_path)


def build_vector_store(input_file: str, output_dir: str = None) -> VectorStore:
    """
    便捷的向量库构建函数
    
    Args:
        input_file: Gold 层数据文件路径
        output_dir: 输出目录
        
    Returns:
        VectorStore 实例
    """
    # 读取数据
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    messages = data.get('messages', [])
    
    # 构建向量库
    store = VectorStore(collection_name="chat_memories")
    store.add_messages(messages)
    
    # 保存
    if output_dir is None:
        output_dir = Path(input_file).parent
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = output_dir / f"vector_store_{timestamp}.json"
    store.save(output_file)
    
    print(f"\n💾 向量库已保存: {output_file}")
    
    # 测试检索
    print("\n🔍 测试语义检索:")
    results = store.search("第一次见面", n_results=3)
    for r in results:
        print(f"   [{r['similarity']:.3f}] {r['metadata']['sender']}: {r['document'][:30]}...")
    
    return store


if __name__ == '__main__':
    import sys
    
    default_file = Path(__file__).parent.parent / 'data' / 'gold' / 'wechat_gold.json'
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    elif default_file.exists():
        input_file = default_file
    else:
        print("请提供输入文件路径")
        sys.exit(1)
    
    print(f"正在构建向量库: {input_file}\n")
    store = build_vector_store(input_file)
    
    print("\n向量库统计:")
    print(store.get_stats())
