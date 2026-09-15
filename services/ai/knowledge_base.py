"""
智能知识库服务 v2.0 - 优化版
- 中文Embedding模型 (bge-small-zh-v1.5)
- Rerank重排序
- 对话历史
- 回答缓存
- 文档自动分类
"""
import os
# 配置HuggingFace国内镜像
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

import logging
import hashlib
import time
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# 知识库数据目录
KB_DIR = os.path.join(os.environ.get('DB_DIR', r'D:\app\data'), 'knowledge_base')
os.makedirs(KB_DIR, exist_ok=True)

# 全局缓存
_embedding_model = None
_rerank_model = None
_answer_cache: Dict[str, Dict] = {}  # question_hash -> {answer, contexts, timestamp}
_chat_history: Dict[int, List[Dict]] = {}  # user_id -> [{question, answer}]

CACHE_TTL = 24 * 3600  # 24小时过期
MAX_HISTORY_TURNS = 5  # 最近5轮对话


def get_embedding_func():
    """获取中文 embedding 模型"""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    try:
        from sentence_transformers import SentenceTransformer
        # 中文优化模型，512维，支持中英文混合
        model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        logger.info("加载中文Embedding模型: bge-small-zh-v1.5")
        _embedding_model = lambda texts: model.encode(texts, normalize_embeddings=True).tolist()
        return _embedding_model
    except Exception as e:
        logger.warning(f"bge-small-zh加载失败，回退到all-MiniLM-L6-v2: {e}")
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('all-MiniLM-L6-v2')
            _embedding_model = lambda texts: model.encode(texts).tolist()
            return _embedding_model
        except Exception as e2:
            logger.warning(f"sentence-transformers加载失败: {e2}")
            def simple_embed(texts):
                vectors = []
                for text in texts:
                    v = [0.0] * 512
                    for i, ch in enumerate(text):
                        h = int(hashlib.md5(ch.encode()).hexdigest(), 16)
                        v[h % 512] += 1.0
                    norm = sum(x*x for x in v) ** 0.5 or 1.0
                    vectors.append([x/norm for x in v])
                return vectors
            _embedding_model = simple_embed
            return _embedding_model


def get_rerank_model():
    """获取Rerank模型"""
    global _rerank_model
    if _rerank_model is not None:
        return _rerank_model

    try:
        from sentence_transformers import CrossEncoder
        # 轻量级cross-encoder，中文优化
        model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        logger.info("加载Rerank模型: ms-marco-MiniLM-L-6-v2")
        _rerank_model = model
        return _rerank_model
    except Exception as e:
        logger.warning(f"Rerank模型加载失败: {e}，跳过重排序")
        return None


def classify_document(title: str, content: str) -> str:
    """自动分类文档类型"""
    text = (title + " " + content[:500]).lower()

    if any(kw in text for kw in ['cr分析', 'cr问题', 'bug', '问题总数', '解决率']):
        return 'CR数据'
    if any(kw in text for kw in ['sop', '操作步骤', '升级流程', '日志拉取']):
        return 'SOP操作指南'
    if any(kw in text for kw in ['schedule', '计划', '排期', 'gantt', 'cp1', 'cp2', 'dvt', 'evt', 'tr', 'evb']):
        return '项目计划'
    if any(kw in text for kw in ['hld', '设计文档', '架构', '接口定义', 'harmony-fr']):
        return '技术文档'
    if any(kw in text for kw in ['截图', 'bug截图', 'error']):
        return '图片资料'
    if any(kw in text for kw in ['测试报告', '测试用例']):
        return '测试文档'
    return '其他'


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

    b64_image = base64.b64encode(image_bytes).decode('utf-8')

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
    """智能知识库 v2.0 - 优化版"""

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
                name="knowledge_docs_v2",
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def add_document(self, doc_id: str, title: str, content: str, metadata: Dict = None) -> bool:
        """添加文档到知识库"""
        try:
            # 分块：800字符 + 150重叠，更精准
            chunks = self._split_text(content, chunk_size=800, overlap=150)
            if not chunks:
                return False

            # 自动分类
            doc_category = classify_document(title, content)

            # 每个 chunk 开头加上文档标题和分类
            chunks = [f"【文档：{title}】【分类：{doc_category}】\n{c}" for c in chunks]

            # 生成 embedding
            embeddings = get_embedding_func()(chunks)

            # 元数据
            metadatas = []
            for i in range(len(chunks)):
                m = {
                    "doc_id": doc_id,
                    "title": title,
                    "category": doc_category,
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
            logger.info(f"文档已添加: {title} ({doc_category}), {len(chunks)} chunks")
            return True
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return False

    def query(self, question: str, top_k: int = 8) -> List[Dict]:
        """查询知识库：embedding检索 + 2-gram关键词 + Rerank重排序"""
        try:
            # 1. embedding 检索
            q_embedding = get_embedding_func()([question])
            results = self.collection.query(
                query_embeddings=q_embedding,
                n_results=50  # 多检索一些，后面rerank
            )

            candidates = []
            seen_ids = set()
            if results and results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    doc_id = results['ids'][0][i] if results['ids'] else f"emb_{i}"
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        candidates.append({
                            "content": doc,
                            "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                            "distance": results['distances'][0][i] if results['distances'] else 0
                        })

            # 2. 语义触发：query包含排期相关词时，强制拉取甘特图chunk
            schedule_triggers = ['schedule', '排期', '计划', '甘特', '时间节点', '进度', 'cwv', 'plan日期', '什么时候', '几号', '节点']
            q_lower = question.lower()
            if any(kw in q_lower for kw in schedule_triggers):
                all_data = self.collection.get()
                if all_data and all_data['documents']:
                    gantt_hits = []
                    for idx, doc in enumerate(all_data['documents']):
                        # 甘特图chunk特征：包含"甘特图"或"- Plan】"或"- CWV】"
                        if '甘特图' in doc or '- Plan】' in doc or '- CWV】' in doc or 'Bring up finish' in doc:
                            gantt_hits.append(idx)
                    for idx in gantt_hits:
                        doc_id = all_data['ids'][idx]
                        if doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            candidates.append({
                                "content": all_data['documents'][idx],
                                "metadata": all_data['metadatas'][idx] if all_data['metadatas'] else {},
                                "distance": 0.1  # 高优先级
                            })
                    logger.info(f"排期触发: 强制加入 {len(gantt_hits)} 个甘特图chunk")

            # 3. 关键词匹配补充：中文2-gram
            all_data = self.collection.get()
            if all_data and all_data['documents']:
                question_clean = question.strip()
                keywords = []
                for i in range(len(question_clean) - 1):
                    kw = question_clean[i:i+2]
                    if kw.strip() and not kw.isspace():
                        keywords.append(kw)

                keywords = list(set(keywords))

                if keywords:
                    scored = []
                    for idx, doc in enumerate(all_data['documents']):
                        doc_lower = doc.lower()
                        hits = sum(1 for kw in keywords if kw.lower() in doc_lower)
                        if hits >= 2:
                            scored.append((hits, idx))

                    scored.sort(reverse=True)
                    for hits, idx in scored[:15]:
                        doc_id = all_data['ids'][idx]
                        if doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            candidates.append({
                                "content": all_data['documents'][idx],
                                "metadata": all_data['metadatas'][idx] if all_data['metadatas'] else {},
                                "distance": 0.5
                            })

            # 3. Rerank重排序
            # 语义触发的chunk（distance=0.1）直接排在最前面，不被rerank压下去
            boosted = [c for c in candidates if c.get('distance', 1) == 0.1]
            normal = [c for c in candidates if c.get('distance', 1) != 0.1]

            if len(normal) > top_k - len(boosted):
                reranker = get_rerank_model()
                if reranker:
                    pairs = [(question, c["content"]) for c in normal]
                    scores = reranker.predict(pairs)
                    for i, c in enumerate(normal):
                        c["rerank_score"] = float(scores[i])
                    normal.sort(key=lambda x: x["rerank_score"], reverse=True)
                    normal = normal[:top_k - len(boosted)]
                    logger.info(f"Rerank完成: {len(boosted)} 个触发chunk + {len(normal)} 个rerank chunk")
                else:
                    normal.sort(key=lambda x: x["distance"])
                    normal = normal[:top_k - len(boosted)]

            candidates = boosted + normal
            return candidates
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []

    def ask(self, question: str, use_cache: bool = True) -> Dict[str, Any]:
        """智能问答（带缓存和对话历史）"""
        global _answer_cache, _chat_history

        # 0. 检查缓存
        if use_cache:
            cache_key = hashlib.md5(question.encode()).hexdigest()
            if cache_key in _answer_cache:
                cached = _answer_cache[cache_key]
                if time.time() - cached['timestamp'] < CACHE_TTL:
                    logger.info("命中缓存，直接返回")
                    return {
                        "answer": cached['answer'],
                        "contexts": cached['contexts'],
                        "cached": True
                    }

        # 1. 检索相关上下文
        contexts = self.query(question, top_k=8)
        if not contexts:
            return {
                "answer": "知识库中没有找到相关信息，请先上传文档。",
                "contexts": []
            }

        # 2. 构建对话历史
        history_context = ""
        if self.user_id in _chat_history and _chat_history[self.user_id]:
            recent = _chat_history[self.user_id][-MAX_HISTORY_TURNS:]
            history_lines = []
            for h in recent:
                history_lines.append(f"用户之前问过：{h['question']}")
                history_lines.append(f"之前回答：{h['answer'][:200]}...")
            history_context = "\n## 对话历史（最近几轮）：\n" + "\n".join(history_lines) + "\n"

        # 3. 构建 prompt
        context_text = "\n\n---\n\n".join([
            f"[来源{i+1}: {c['metadata'].get('title', '未知')}]\n{c['content']}"
            for i, c in enumerate(contexts)
        ])

        prompt = f"""请根据以下知识库内容回答用户的问题。

## 知识库内容：
{context_text}
{history_context}
## 用户问题：
{question}

## 要求：
1. **语言一致**：用和用户问题相同的语言回答（中文问就用中文答，英文问就用英文答）
2. **专业术语保留原文**：知识库中的英文专业术语（如CP1, DVT, TR, EVB, OTA, ADB等）不要翻译，直接保留原文
3. **优先使用CR分析数据**：如果知识库中有"CR分析最新数据"，里面的总问题数、未解决数、解决率等数字直接引用，不要说"无法确定"
4. **主动从数据中统计和计算**：如果问题涉及数量、比例、统计，请仔细阅读知识库中的数据，自己计算出答案
5. 基于知识库内容回答，不要编造数据
6. 如果知识库中确实没有相关信息，请明确说明
7. 回答简洁明了，重点突出
8. 如果是表格/CSV数据，逐行统计后给出数字
9. 引用相关文档标题，用[来源1][来源2]标注"""

        # 4. 调用 AI
        answer = get_llm_response(prompt)

        # 5. 保存对话历史
        if self.user_id not in _chat_history:
            _chat_history[self.user_id] = []
        _chat_history[self.user_id].append({"question": question, "answer": answer})
        # 只保留最近N轮
        if len(_chat_history[self.user_id]) > MAX_HISTORY_TURNS * 2:
            _chat_history[self.user_id] = _chat_history[self.user_id][-MAX_HISTORY_TURNS*2:]

        # 6. 按标题去重 context，加上分类
        seen_titles = set()
        unique_contexts = []
        for c in contexts:
            title = c['metadata'].get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_contexts.append({
                    "title": title,
                    "category": c['metadata'].get('category', '其他'),
                    "content": c['content'][:200]
                })

        # 7. 存入缓存
        _answer_cache[cache_key] = {
            "answer": answer,
            "contexts": unique_contexts,
            "timestamp": time.time()
        }

        return {
            "answer": answer,
            "contexts": unique_contexts,
            "cached": False
        }

    def list_documents(self) -> List[Dict]:
        """列出所有文档（带分类）"""
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
                            "category": meta.get('category', '其他'),
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

    def clear_history(self):
        """清空对话历史"""
        global _chat_history
        if self.user_id in _chat_history:
            del _chat_history[self.user_id]

    def clear_cache(self):
        """清空回答缓存"""
        global _answer_cache
        _answer_cache.clear()

    def _split_text(self, text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
        """文本分块：按段落边界切分"""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                # 尝试在段落/句号处分割
                for sep in ['\n\n', '。', '！', '？', '\n', '.', '!', '?']:
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
