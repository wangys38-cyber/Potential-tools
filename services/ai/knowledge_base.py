"""
智能知识库服务 v3.0 - 检索质量终局版
- 混合检索：向量语义 + BM25关键词 + 语义触发
- 上下文感知分块：表格/甘特图整块保留
- 查询改写：LLM自动扩展查询意图
- 引用溯源：精确到chunk
- 中文Embedding (bge-small-zh-v1.5)
- Rerank重排序
- 对话历史 + 回答缓存
"""
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

import logging
import hashlib
import math
import re
import time
from collections import Counter
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

KB_DIR = os.path.join(os.environ.get('DB_DIR', r'D:\app\data'), 'knowledge_base')
os.makedirs(KB_DIR, exist_ok=True)

# 全局缓存
_embedding_model = None
_rerank_model = None
_answer_cache: Dict[str, Dict] = {}
_chat_history: Dict[int, List[Dict]] = {}
_bm25_index = None  # BM25索引 {user_id: (docs, bm25_obj)}

CACHE_TTL = 24 * 3600
MAX_HISTORY_TURNS = 5


def get_embedding_func():
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        logger.info("加载中文Embedding模型: bge-small-zh-v1.5")
        _embedding_model = lambda texts: model.encode(texts, normalize_embeddings=True).tolist()
        return _embedding_model
    except Exception as e:
        logger.warning(f"bge-small-zh加载失败: {e}")
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
    global _rerank_model
    if _rerank_model is not None:
        return _rerank_model
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        logger.info("加载Rerank模型: ms-marco-MiniLM-L-6-v2")
        _rerank_model = model
        return _rerank_model
    except Exception as e:
        logger.warning(f"Rerank模型加载失败: {e}")
        return None


def classify_document(title: str, content: str) -> str:
    text = (title + " " + content[:500]).lower()
    if any(kw in text for kw in ['cr分析', 'cr问题', 'bug', '问题总数', '解决率', 'cr trend']):
        return 'CR数据'
    if any(kw in text for kw in ['sop', '操作步骤', '升级流程', '日志拉取']):
        return 'SOP操作指南'
    if any(kw in text for kw in ['schedule', '计划', '排期', 'gantt', 'cp1', 'cp2', 'dvt', 'evt', 'evb', 'ok2p']):
        return '项目计划'
    if any(kw in text for kw in ['hld', '设计文档', '架构', '接口定义']):
        return '技术文档'
    if any(kw in text for kw in ['截图', 'bug截图', 'error']):
        return '图片资料'
    if any(kw in text for kw in ['测试报告', '测试用例']):
        return '测试文档'
    return '其他'


def get_llm_response(prompt: str, system: str = None, temperature: float = 0.3) -> str:
    from services.ai.factory import get_ai_service
    from services.ai.base import ChatMessage
    ai = get_ai_service()
    if not ai:
        return "AI 服务未配置。"
    try:
        sys_msg = system or "你是一个专业的研发知识库助手。"
        messages = [
            ChatMessage(role="system", content=sys_msg),
            ChatMessage(role="user", content=prompt)
        ]
        resp = ai.chat(messages, temperature=temperature, max_tokens=2000)
        return resp.content
    except Exception as e:
        logger.error(f"AI 调用失败: {e}")
        return f"AI 回答失败: {str(e)}"


def get_ai_config():
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
                return {'api_key': row[0], 'base_url': row[1] or 'https://open.bigmodel.cn/api/paas/v4', 'model': row[2] or 'glm-4-plus'}
    except Exception as e:
        logger.error(f"获取AI配置失败: {e}")
    return None


def analyze_image_with_ai(image_bytes: bytes, image_format: str = 'png') -> str:
    import base64, requests
    config = get_ai_config()
    if not config:
        return "AI 服务未配置。"
    b64 = base64.b64encode(image_bytes).decode('utf-8')
    url = config['base_url'].rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {config["api_key"]}', 'Content-Type': 'application/json'}
    payload = {
        'model': 'glm-4v-plus',
        'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': f'data:image/{image_format};base64,{b64}'}},
            {'type': 'text', 'text': '请详细描述这张图片的内容，包括：1.图片类型 2.所有文字内容(OCR) 3.如果是Bug截图描述错误 4.如果是图表描述数据 5.如果是流程图描述步骤。用结构化方式输出。'}
        ]}],
        'temperature': 0.3, 'max_tokens': 2000
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"图片识别失败: {e}"


# ========== BM25 实现 ==========
class SimpleBM25:
    """轻量BM25，不依赖外部库"""
    def __init__(self, documents: List[str]):
        self.docs = documents
        self.corpus = [self._tokenize(d) for d in documents]
        self.doc_len = [len(c) for c in self.corpus]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.df = Counter()
        for tokens in self.corpus:
            for t in set(tokens):
                self.df[t] += 1
        self.idf = {}
        N = len(self.corpus)
        for term, df in self.df.items():
            self.idf[term] = math.log(1 + (N - df + 0.5) / (df + 0.5))
        self.k1 = 1.5
        self.b = 0.75

    def _tokenize(self, text: str) -> List[str]:
        # 中文按字+英文按词
        text = text.lower()
        # 提取英文单词和数字
        en_words = re.findall(r'[a-z0-9]+', text)
        # 中文按2-gram
        cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
        cn_bigrams = [cn_chars[i] + cn_chars[i+1] for i in range(len(cn_chars)-1)]
        return en_words + cn_bigrams

    def search(self, query: str, top_k: int = 20) -> List[tuple]:
        q_tokens = self._tokenize(query)
        scores = []
        for i, doc_tokens in enumerate(self.corpus):
            if not doc_tokens:
                continue
            tf = Counter(doc_tokens)
            score = 0.0
            dl = self.doc_len[i]
            for t in q_tokens:
                if t not in tf:
                    continue
                f = tf[t]
                idf = self.idf.get(t, 0)
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1)))
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return scores[:top_k]


# ========== 查询改写 ==========
def rewrite_query(question: str) -> str:
    """用LLM改写查询，扩展同义词和专业术语"""
    try:
        prompt = f"""请将以下用户问题改写为更适合知识库检索的查询。
要求：
1. 保留原始语义
2. 补充可能的同义词和专业术语（中文+英文）
3. 不要加废话，直接输出改写后的查询，用空格分隔关键词

用户问题：{question}

改写后的检索关键词："""
        result = get_llm_response(prompt, system="你是查询改写专家，只输出关键词，不要解释。", temperature=0.1)
        if result and len(result) > 5:
            return result.strip()
    except Exception as e:
        logger.warning(f"查询改写失败: {e}")
    return question


class KnowledgeBase:
    """智能知识库 v3.0"""

    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        self.db_path = os.path.join(KB_DIR, f'user_{user_id}')
        os.makedirs(self.db_path, exist_ok=True)
        self._client = None
        self._collection = None
        self._bm25 = None

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

    def _rebuild_bm25(self):
        """重建BM25索引"""
        try:
            data = self.collection.get()
            if data and data['documents']:
                self._bm25 = SimpleBM25(data['documents'])
                logger.info(f"BM25索引重建: {len(data['documents'])} 个chunk")
        except Exception as e:
            logger.error(f"BM25重建失败: {e}")

    def add_document(self, doc_id: str, title: str, content: str, metadata: Dict = None) -> bool:
        try:
            chunks = self._split_text(content, chunk_size=800, overlap=150)
            if not chunks:
                return False
            doc_category = classify_document(title, content)
            chunks = [f"【文档：{title}】【分类：{doc_category}】\n{c}" for c in chunks]
            embeddings = get_embedding_func()(chunks)

            metadatas = []
            for i in range(len(chunks)):
                m = {
                    "doc_id": doc_id, "title": title, "category": doc_category,
                    "chunk_index": i, **(metadata or {})
                }
                metadatas.append(m)

            ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            self.collection.upsert(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
            logger.info(f"文档已添加: {title} ({doc_category}), {len(chunks)} chunks")

            # 重建BM25
            self._rebuild_bm25()
            return True
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return False

    def query(self, question: str, top_k: int = 8, category: str = None) -> List[Dict]:
        """混合检索：向量 + BM25 + 语义触发"""
        try:
            all_data = self.collection.get()
            if not all_data or not all_data['documents']:
                return []

            # 1. 向量检索
            q_embedding = get_embedding_func()([question])
            vec_results = self.collection.query(
                query_embeddings=q_embedding, n_results=50,
                where={"category": category} if category else None
            )

            candidates = []
            seen_ids = set()

            if vec_results and vec_results['documents'] and vec_results['documents'][0]:
                for i, doc in enumerate(vec_results['documents'][0]):
                    did = vec_results['ids'][0][i]
                    if did not in seen_ids:
                        seen_ids.add(did)
                        candidates.append({
                            "content": doc,
                            "metadata": vec_results['metadatas'][0][i] or {},
                            "score": 1 - (vec_results['distances'][0][i] if vec_results['distances'] else 0),
                            "source": "vector"
                        })

            # 2. BM25关键词检索
            if self._bm25 is None:
                self._rebuild_bm25()
            if self._bm25:
                bm25_hits = self._bm25.search(question, top_k=20)
                for score, idx in bm25_hits:
                    did = all_data['ids'][idx]
                    if did not in seen_ids:
                        seen_ids.add(did)
                        candidates.append({
                            "content": all_data['documents'][idx],
                            "metadata": all_data['metadatas'][idx] or {},
                            "score": score / 10,  # 归一化
                            "source": "bm25"
                        })

            # 3. 语义触发：排期类查询强制拉甘特图chunk
            q_lower = question.lower()
            schedule_triggers = ['schedule', '排期', '计划', '甘特', '时间节点', '进度', 'cwv', '什么时候', '几号', '节点', 'plan']
            if any(kw in q_lower for kw in schedule_triggers):
                for idx, doc in enumerate(all_data['documents']):
                    if '甘特图' in doc or '- Plan】' in doc or '- CWV】' in doc or 'Bring up finish' in doc:
                        did = all_data['ids'][idx]
                        if did not in seen_ids:
                            seen_ids.add(did)
                            candidates.append({
                                "content": doc,
                                "metadata": all_data['metadatas'][idx] or {},
                                "score": 2.0,  # 最高优先级
                                "source": "boosted"
                            })

            # 4. Rerank
            boosted = [c for c in candidates if c.get('score', 0) >= 2.0]
            normal = [c for c in candidates if c.get('score', 0) < 2.0]

            if len(normal) > top_k - len(boosted):
                reranker = get_rerank_model()
                if reranker:
                    pairs = [(question, c["content"]) for c in normal]
                    scores = reranker.predict(pairs)
                    for i, c in enumerate(normal):
                        c["rerank_score"] = float(scores[i])
                    normal.sort(key=lambda x: x["rerank_score"], reverse=True)
                    normal = normal[:max(0, top_k - len(boosted))]
                else:
                    normal.sort(key=lambda x: x["score"], reverse=True)
                    normal = normal[:max(0, top_k - len(boosted))]

            return boosted + normal
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []

    def ask(self, question: str, use_cache: bool = True) -> Dict[str, Any]:
        # 0. 缓存
        cache_key = hashlib.md5(question.encode()).hexdigest()
        if use_cache and cache_key in _answer_cache:
            cached = _answer_cache[cache_key]
            if time.time() - cached['timestamp'] < CACHE_TTL:
                return {"answer": cached['answer'], "contexts": cached['contexts'], "cached": True}

        # 1. 查询改写
        rewritten = rewrite_query(question)
        logger.info(f"查询改写: '{question}' -> '{rewritten}'")

        # 2. 检索（用改写后的查询）
        contexts = self.query(rewritten, top_k=8)
        if not contexts:
            contexts = self.query(question, top_k=8)  # 回退原始查询

        if not contexts:
            return {"answer": "知识库中没有找到相关信息，请先上传文档。", "contexts": []}

        # 3. 对话历史
        history_context = ""
        if self.user_id in _chat_history and _chat_history[self.user_id]:
            recent = _chat_history[self.user_id][-MAX_HISTORY_TURNS:]
            lines = []
            for h in recent:
                lines.append(f"用户之前问：{h['question']}")
                lines.append(f"之前回答：{h['answer'][:150]}...")
            history_context = "\n## 对话历史：\n" + "\n".join(lines) + "\n"

        # 4. 构建prompt
        context_text = "\n\n---\n\n".join([
            f"[来源{i+1}: {c['metadata'].get('title', '未知')} | {c['metadata'].get('category', '其他')}]\n{c['content']}"
            for i, c in enumerate(contexts)
        ])

        prompt = f"""请根据以下知识库内容回答用户的问题。

## 知识库内容：
{context_text}
{history_context}
## 用户问题：
{question}

## 要求：
1. 语言一致：中文问用中文答，英文问用英文答
2. 专业术语保留原文（CP1, DVT, TR, EVB, OTA等不翻译）
3. 优先使用知识库中的具体数字和日期，不要说"无法确定"
4. 主动从数据中统计计算
5. 基于知识库内容回答，不要编造
6. 如果确实没有相关信息，明确说明
7. 回答简洁，重点突出
8. 引用来源用[来源1][来源2]标注"""

        answer = get_llm_response(prompt)

        # 5. 保存历史
        if self.user_id not in _chat_history:
            _chat_history[self.user_id] = []
        _chat_history[self.user_id].append({"question": question, "answer": answer})
        if len(_chat_history[self.user_id]) > MAX_HISTORY_TURNS * 2:
            _chat_history[self.user_id] = _chat_history[self.user_id][-MAX_HISTORY_TURNS*2:]

        # 6. 去重context
        seen_titles = set()
        unique_contexts = []
        for c in contexts:
            t = c['metadata'].get('title', '')
            if t and t not in seen_titles:
                seen_titles.add(t)
                unique_contexts.append({
                    "title": t,
                    "category": c['metadata'].get('category', '其他'),
                    "content": c['content'][:200]
                })

        _answer_cache[cache_key] = {"answer": answer, "contexts": unique_contexts, "timestamp": time.time()}

        return {"answer": answer, "contexts": unique_contexts, "cached": False}

    def list_documents(self) -> List[Dict]:
        try:
            data = self.collection.get()
            docs_map = {}
            if data and data['metadatas']:
                for meta in data['metadatas']:
                    did = meta.get('doc_id')
                    if did and did not in docs_map:
                        docs_map[did] = {
                            "doc_id": did, "title": meta.get('title', '未命名'),
                            "category": meta.get('category', '其他'), "chunk_count": 0
                        }
                    if did:
                        docs_map[did]['chunk_count'] += 1
            return list(docs_map.values())
        except Exception as e:
            logger.error(f"列出文档失败: {e}")
            return []

    def delete_document(self, doc_id: str) -> bool:
        try:
            data = self.collection.get(where={"doc_id": doc_id})
            if data and data['ids']:
                self.collection.delete(ids=data['ids'])
            self._rebuild_bm25()
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return False

    def full_text_search(self, keyword: str, top_k: int = 20) -> List[Dict]:
        """全文精确搜索（不经过AI）"""
        try:
            data = self.collection.get()
            if not data or not data['documents']:
                return []
            kw = keyword.lower()
            results = []
            for i, doc in enumerate(data['documents']):
                if kw in doc.lower():
                    results.append({
                        "content": doc[:500],
                        "title": data['metadatas'][i].get('title', '') if data['metadatas'] else '',
                        "category": data['metadatas'][i].get('category', '其他') if data['metadatas'] else '其他'
                    })
                    if len(results) >= top_k:
                        break
            return results
        except Exception as e:
            logger.error(f"全文搜索失败: {e}")
            return []

    def clear_history(self):
        global _chat_history
        if self.user_id in _chat_history:
            del _chat_history[self.user_id]

    def clear_cache(self):
        global _answer_cache
        _answer_cache.clear()

    def _split_text(self, text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
        """上下文感知分块：表格/甘特图整块保留，普通文本按段落切"""
        # 检测是否是表格/甘特图类内容
        is_table = any(kw in text for kw in ['=== 工作表', '甘特图', '【文档：', '【分类：', '【CSV', '【Excel'])

        if is_table and len(text) <= 3000:
            # 表格类内容如果不太长，整块保留
            return [text]

        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                # 优先在段落边界切
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


_kb_instances: Dict[int, KnowledgeBase] = {}

def get_knowledge_base(user_id: int = 1) -> KnowledgeBase:
    if user_id not in _kb_instances:
        _kb_instances[user_id] = KnowledgeBase(user_id)
    return _kb_instances[user_id]
