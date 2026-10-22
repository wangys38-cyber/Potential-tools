# -*- coding: utf-8 -*-
"""
向量检索服务

使用 TF-IDF + 余弦相似度实现轻量级向量检索，无需外部数据库。
支持中英文混合分词。
"""
import math
import re
import logging
from typing import Dict, List, Tuple, Optional
from collections import Counter

logger = logging.getLogger(__name__)


class VectorStore:
    """向量存储与检索"""

    def __init__(self):
        self.documents: List[Dict] = []
        self.doc_vectors: List[Dict] = []
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self._built = False

    def add_documents(self, documents: List[Dict]):
        """添加文档"""
        self.documents.extend(documents)
        self._built = False

    def clear(self):
        """清空所有文档"""
        self.documents = []
        self.doc_vectors = []
        self.vocabulary = {}
        self.idf = {}
        self._built = False

    def build_index(self):
        """构建索引"""
        if not self.documents:
            return

        # 分词并构建词汇表
        all_tokens = []
        doc_token_lists = []

        for doc in self.documents:
            text = doc.get('content', '') + ' ' + doc.get('title', '')
            tokens = self._tokenize(text)
            doc_token_lists.append(tokens)
            all_tokens.extend(tokens)

        # 构建词汇表
        self.vocabulary = {}
        for token in set(all_tokens):
            self.vocabulary[token] = len(self.vocabulary)

        # 计算IDF
        doc_count = len(self.documents)
        self.idf = {}
        for term in self.vocabulary:
            doc_freq = sum(1 for tokens in doc_token_lists if term in tokens)
            self.idf[term] = math.log((doc_count + 1) / (doc_freq + 1)) + 1

        # 计算文档TF-IDF向量
        self.doc_vectors = []
        for tokens in doc_token_lists:
            tf = Counter(tokens)
            vector = {}
            for term, count in tf.items():
                if term in self.vocabulary:
                    tf_idf = count * self.idf.get(term, 0)
                    vector[self.vocabulary[term]] = tf_idf
            self.doc_vectors.append(vector)

        self._built = True
        logger.info(f'向量索引构建完成: {len(self.documents)} 个文档, {len(self.vocabulary)} 个词')

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """搜索相关文档"""
        if not self._built:
            self.build_index()

        if not self.documents:
            return []

        # 查询向量化
        query_tokens = self._tokenize(query)
        query_tf = Counter(query_tokens)
        query_vector = {}
        for term, count in query_tf.items():
            if term in self.vocabulary:
                query_vector[self.vocabulary[term]] = count * self.idf.get(term, 0)

        # 计算余弦相似度
        scores = []
        for i, doc_vector in enumerate(self.doc_vectors):
            score = self._cosine_similarity(query_vector, doc_vector)
            if score > 0:
                scores.append((i, score))

        # 排序并返回top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in scores[:top_k]:
            doc = self.documents[idx].copy()
            doc['score'] = score
            results.append(doc)

        return results

    def _tokenize(self, text: str) -> List[str]:
        """中英文混合分词"""
        tokens = []
        # 英文单词
        english_words = re.findall(r'[a-zA-Z]+', text.lower())
        tokens.extend(english_words)

        # 中文单字 + 二元组
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        tokens.extend(chinese_chars)
        # 中文二元组
        for i in range(len(chinese_chars) - 1):
            bigram = chinese_chars[i] + chinese_chars[i + 1]
            tokens.append(bigram)

        # 数字
        numbers = re.findall(r'\d+', text)
        tokens.extend(numbers)

        return tokens

    def _cosine_similarity(self, vec1: Dict, vec2: Dict) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2:
            return 0.0

        dot_product = sum(vec1.get(k, 0) * vec2.get(k, 0) for k in set(vec1.keys()) & set(vec2.keys()))
        norm1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
        norm2 = math.sqrt(sum(v ** 2 for v in vec2.values()))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


_vector_store_instance = None


def get_vector_store() -> VectorStore:
    """获取向量存储单例"""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore()
    return _vector_store_instance