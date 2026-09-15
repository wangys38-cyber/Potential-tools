"""
智能知识库服务 - 基于 LightRAG + ChromaDB
支持文档上传、向量存储、智能问答
"""
import os
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# 知识库数据目录
KB_DIR = os.path.join(os.environ.get('DB_DIR', r'D:\app\data'), 'knowledge_base')
os.makedirs(KB_DIR, exist_ok=True)

# LightRAG 实例缓存
_rag_instance = None
_rag_embedding_func = None


def get_embedding_func():
    """获取 embedding 函数（使用 AI 服务的 embedding）"""
    global _rag_embedding_func
    if _rag_embedding_func is not None:
        return _rag_embedding_func
    
    # 使用 sentence-transformers 的轻量 embedding
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        _rag_embedding_func = lambda texts: model.encode(texts).tolist()
        return _rag_embedding_func
    except ImportError:
        logger.warning("sentence-transformers 未安装，使用简单 hash embedding")
        # 降级方案：简单 hash 向量
        def simple_embed(texts):
            import hashlib
            vectors = []
            for text in texts:
                v = [0.0] * 384
                for i, ch in enumerate(text):
                    h = int(hashlib.md5(ch.encode()).hexdigest(), 16)
                    v[h % 384] += 1.0
                # 归一化
                norm = sum(x*x for x in v) ** 0.5 or 1.0
                vectors.append([x/norm for x in v])
            return vectors
        import hashlib
        _rag_embedding_func = simple_embed
        return _rag_embedding_func


def get_llm_response(prompt: str) -> str:
    """调用 AI 服务生成回答"""
    from services.ai.factory import get_ai_service
    from services.ai.base import ChatMessage
    
    ai = get_ai_service()
    if not ai:
        return "AI 服务未配置，请先在系统设置中配置 AI。"
    
    try:
        messages = [
            ChatMessage(role="system", content="你是一个专业的研发知识库助手，请根据提供的上下文回答问题。如果上下文中没有相关信息，请明确说明。"),
            ChatMessage(role="user", content=prompt)
        ]
        resp = ai.chat(messages, temperature=0.3, max_tokens=1500)
        return resp.content
    except Exception as e:
        logger.error(f"AI 调用失败: {e}")
        return f"AI 回答失败: {str(e)}"


def get_ai_config():
    """从数据库获取 AI 配置"""
    try:
        import os
        os.environ.setdefault('DB_DIR', r'D:\app\data')
        from db.base import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT api_key, base_url, model FROM ai_configs WHERE is_active=1 LIMIT 1"
            )).fetchone()
            if row:
                return {
                    'api_key': row[0],
                    'base_url': row[1] or 'https://open.bigmodel.cn/api/paas/v4',
                    'model': row[2] or 'glm-4-plus'
                }
    except Exception as e:
        logger.error(f"获取AI配置失败: {e}")
    return None


def analyze_image_with_ai(image_bytes: bytes, image_format: str = 'png') -> str:
    """使用多模态 AI 分析图片内容"""
    import base64
    import requests
    
    config = get_ai_config()
    if not config:
        return "AI 服务未配置，无法识别图片。"
    
    # 转为 base64
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 调用 GLM-4V 多模态接口
    url = config['base_url'].rstrip('/') + '/chat/completions'
    headers = {
        'Authorization': f'Bearer {config["api_key"]}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': 'glm-4v-plus',
        'messages': [
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:image/{image_format};base64,{b64_image}'
                        }
                    },
                    {
                        'type': 'text',
                        'text': '请详细描述这张图片的内容，包括：\n1. 图片类型（截图/照片/图表/流程图等）\n2. 所有文字内容（OCR识别）\n3. 如果是Bug截图，描述界面和错误信息\n4. 如果是图表，描述数据趋势\n5. 如果是流程图，描述流程步骤\n\n请用结构化的方式输出，方便存入知识库。'
                    }
                ]
            }
        ],
        'temperature': 0.3,
        'max_tokens': 2000
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"多模态AI识别失败: {e}")
        return f"图片识别失败: {str(e)}. 请确认 AI 模型支持多模态（如 glm-4v-plus）。"


class KnowledgeBase:
    """智能知识库 - 轻量实现（基于 ChromaDB）"""
    
    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        self.db_path = os.path.join(KB_DIR, f'user_{user_id}')
        os.makedirs(self.db_path, exist_ok=True)
        self._client = None
        self._collection = None
    
    @property
    def client(self):
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=self.db_path)
        return self._client
    
    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name="knowledge_docs",
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection
    
    def add_document(self, doc_id: str, title: str, content: str, metadata: Dict = None) -> bool:
        """添加文档到知识库"""
        try:
            # 分块
            chunks = self._split_text(content, chunk_size=800, overlap=100)
            if not chunks:
                return False
            
            # 每个 chunk 开头都加上文档标题，确保检索时能命中
            chunks = [f"【文档：{title}】\n{c}" for c in chunks]
            
            # 生成 embedding
            embeddings = get_embedding_func()(chunks)
            
            # 元数据
            metadatas = []
            for i in range(len(chunks)):
                m = {
                    "doc_id": doc_id,
                    "title": title,
                    "chunk_index": i,
                    **(metadata or {})
                }
                metadatas.append(m)
            
            ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            
            self.collection.upsert(
                ids=ids,
                documents=chunks,
                embeddings=embeddings,
                metadatas=metadatas
            )
            return True
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return False
    
    def query(self, question: str, top_k: int = 5) -> List[Dict]:
        """查询知识库：embedding检索 + 关键词匹配 双通道"""
        try:
            # 1. embedding 检索
            q_embedding = get_embedding_func()([question])
            results = self.collection.query(
                query_embeddings=q_embedding,
                n_results=top_k
            )
            
            docs = []
            seen_ids = set()
            if results and results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    doc_id = results['ids'][0][i] if results['ids'] else f"emb_{i}"
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        docs.append({
                            "content": doc,
                            "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                            "distance": results['distances'][0][i] if results['distances'] else 0
                        })
            
            # 2. 关键词匹配补充：把问题拆成关键词，在所有文档中搜索
            all_data = self.collection.get()
            if all_data and all_data['documents']:
                # 简单分词：按空格和常见标点拆分
                keywords = [w.strip() for w in question.replace('？', ' ').replace('?', ' ').replace('的', ' ').replace('怎么', ' ').split() if len(w.strip()) >= 2]
                
                if keywords:
                    # 计算每个文档的关键词命中数
                    scored = []
                    for idx, doc in enumerate(all_data['documents']):
                        doc_lower = doc.lower()
                        hits = sum(1 for kw in keywords if kw.lower() in doc_lower)
                        if hits >= 2:  # 至少命中2个关键词
                            scored.append((hits, idx))
                    
                    # 按命中数排序，取前10个补充
                    scored.sort(reverse=True)
                    for hits, idx in scored[:10]:
                        doc_id = all_data['ids'][idx]
                        if doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            docs.append({
                                "content": all_data['documents'][idx],
                                "metadata": all_data['metadatas'][idx] if all_data['metadatas'] else {},
                                "distance": 0  # 关键词命中，距离设为0
                            })
            
            return docs
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []
    
    def ask(self, question: str) -> Dict[str, Any]:
        """智能问答"""
        # 1. 检索相关上下文（增加到15个，确保CR数据完整）
        contexts = self.query(question, top_k=15)
        if not contexts:
            return {
                "answer": "知识库中没有找到相关信息，请先上传文档。",
                "contexts": []
            }
        
        # 2. 构建 prompt
        context_text = "\n\n---\n\n".join([
            f"[来源: {c['metadata'].get('title', '未知')}]\n{c['content']}"
            for c in contexts
        ])
        
        prompt = f"""请根据以下知识库内容回答用户的问题。

## 知识库内容：
{context_text}

## 用户问题：
{question}

## 要求：
1. **优先使用CR分析数据**：如果知识库中有"CR分析最新数据"，里面的总问题数、未解决数、解决率等数字直接引用，不要说"无法确定"
2. **主动从数据中统计和计算**：如果问题涉及数量、比例、统计，请仔细阅读知识库中的数据，自己计算出答案
3. 基于知识库内容回答，不要编造数据
4. 如果知识库中确实没有相关信息，请明确说明
5. 回答简洁明了，重点突出
6. 如果是表格/CSV数据，逐行统计后给出数字
7. 引用相关文档标题"""
        
        # 3. 调用 AI
        answer = get_llm_response(prompt)
        
        # 4. 按标题去重 context，避免重复显示同一个文档
        seen_titles = set()
        unique_contexts = []
        for c in contexts:
            title = c['metadata'].get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_contexts.append({
                    "title": title,
                    "content": c['content'][:200]
                })
        
        return {
            "answer": answer,
            "contexts": unique_contexts
        }
    
    def list_documents(self) -> List[Dict]:
        """列出所有文档"""
        try:
            data = self.collection.get()
            docs_map = {}
            if data and data['metadatas']:
                for meta in data['metadatas']:
                    doc_id = meta.get('doc_id')
                    if doc_id and doc_id not in docs_map:
                        docs_map[doc_id] = {
                            "doc_id": doc_id,
                            "title": meta.get('title', '未命名'),
                            "chunk_count": 0
                        }
                    if doc_id:
                        docs_map[doc_id]['chunk_count'] += 1
            return list(docs_map.values())
        except Exception as e:
            logger.error(f"列出文档失败: {e}")
            return []
    
    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        try:
            data = self.collection.get(where={"doc_id": doc_id})
            if data and data['ids']:
                self.collection.delete(ids=data['ids'])
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return False
    
    def _split_text(self, text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
        """文本分块"""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                # 尝试在句号/换行处分割
                for sep in ['。', '！', '？', '\n\n', '\n', '.', '!', '?']:
                    last_sep = text.rfind(sep, start, end)
                    if last_sep > start + chunk_size // 2:
                        end = last_sep + len(sep)
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap
            if start >= len(text):
                break
        return chunks


# 全局实例缓存
_kb_instances: Dict[int, KnowledgeBase] = {}

def get_knowledge_base(user_id: int = 1) -> KnowledgeBase:
    """获取知识库实例"""
    if user_id not in _kb_instances:
        _kb_instances[user_id] = KnowledgeBase(user_id)
    return _kb_instances[user_id]
