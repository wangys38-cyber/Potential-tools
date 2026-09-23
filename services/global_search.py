# -*- coding: utf-8 -*-
"""
Potential-tools 9.0 - 全局搜索
跨工具统一搜索：项目、笔记、知识库、CR、文档
"""
import os
import json
import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class GlobalSearchEngine:
    """全局搜索引擎"""

    # 搜索源定义
    SEARCH_SOURCES = [
        {'key': 'project', 'name': '项目状态', 'icon': '📊', 'weight': 1.0},
        {'key': 'notes', 'name': '牛马笔记', 'icon': '📝', 'weight': 0.9},
        {'key': 'knowledge', 'name': '知识库', 'icon': '📚', 'weight': 0.8},
        {'key': 'cr', 'name': 'CR分析', 'icon': '🐛', 'weight': 0.7},
        {'key': 'documents', 'name': '文档', 'icon': '📄', 'weight': 0.6},
    ]

    def search(self, query: str, sources: Optional[List[str]] = None,
               limit: int = 20) -> Dict[str, Any]:
        """
        全局搜索
        query: 搜索关键词
        sources: 指定搜索源，None表示全部
        limit: 每个源最多返回结果数
        """
        if not query or not query.strip():
            return {'query': query, 'total': 0, 'results': [], 'by_source': {}}

        query = query.strip().lower()
        all_results = []
        by_source = {}

        active_sources = self.SEARCH_SOURCES
        if sources:
            active_sources = [s for s in self.SEARCH_SOURCES if s['key'] in sources]

        for source in active_sources:
            try:
                source_results = self._search_source(source['key'], query, limit)
                # 加权排序
                for r in source_results:
                    r['_score'] = r.get('score', 0) * source['weight']
                source_results.sort(key=lambda x: x.get('_score', 0), reverse=True)
                by_source[source['key']] = {
                    'name': source['name'],
                    'icon': source['icon'],
                    'count': len(source_results)
                }
                all_results.extend(source_results[:limit])
            except Exception as e:
                logger.warning(f"搜索源 {source['key']} 失败: {e}")
                by_source[source['key']] = {'name': source['name'], 'icon': source['icon'], 'count': 0, 'error': str(e)}

        # 全局排序
        all_results.sort(key=lambda x: x.get('_score', 0), reverse=True)

        return {
            'query': query,
            'total': len(all_results),
            'results': all_results[:limit * len(active_sources)],
            'by_source': by_source
        }

    def _search_source(self, source: str, query: str, limit: int) -> List[Dict[str, Any]]:
        """搜索单个数据源"""
        results = []

        if source == 'project':
            results = self._search_projects(query, limit)
        elif source == 'notes':
            results = self._search_notes(query, limit)
        elif source == 'knowledge':
            results = self._search_knowledge(query, limit)
        elif source == 'cr':
            results = self._search_cr(query, limit)
        elif source == 'documents':
            results = self._search_documents(query, limit)

        return results

    def _search_projects(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """搜索项目状态"""
        results = []
        try:
            from services.project_assistant import _snap_path
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'project_cache')
            if os.path.exists(data_dir):
                for filename in os.listdir(data_dir):
                    if filename.endswith('.json'):
                        project_key = filename.replace('.json', '')
                        score = 0
                        if query in project_key.lower():
                            score = 100
                        if score > 0:
                            results.append({
                                'type': 'project',
                                'title': project_key,
                                'url': f'/project-assistant?project={project_key}',
                                'score': score,
                                'snippet': f'项目状态快照: {project_key}'
                            })
        except Exception as e:
            logger.warning(f"搜索项目失败: {e}")
        return results[:limit]

    def _search_notes(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """搜索牛马笔记"""
        results = []
        try:
            notes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'notes')
            if os.path.exists(notes_dir):
                for filename in os.listdir(notes_dir):
                    if filename.endswith('.json'):
                        filepath = os.path.join(notes_dir, filename)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                note = json.load(f)
                            title = note.get('title', '')
                            content = note.get('content', '')
                            score = 0
                            if query in title.lower():
                                score += 80
                            if query in content.lower():
                                score += 40
                            if score > 0:
                                results.append({
                                    'type': 'notes',
                                    'title': title or '未命名笔记',
                                    'url': '/notes',
                                    'score': score,
                                    'snippet': content[:150]
                                })
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"搜索笔记失败: {e}")
        return results[:limit]

    def _search_knowledge(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """搜索知识库"""
        results = []
        try:
            from services.knowledge_base_service import search as kb_search
            kb_results = kb_search(query, top_k=limit)
            for r in kb_results:
                results.append({
                    'type': 'knowledge',
                    'title': r.get('title', r.get('filename', '未知文档')),
                    'url': '/knowledge-base',
                    'score': r.get('score', 50) * 100,
                    'snippet': r.get('content', r.get('snippet', ''))[:150]
                })
        except Exception as e:
            logger.warning(f"搜索知识库失败: {e}")
        return results[:limit]

    def _search_cr(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """搜索CR分析历史"""
        results = []
        try:
            cr_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'cr_analysis')
            if os.path.exists(cr_dir):
                for filename in os.listdir(cr_dir):
                    if filename.endswith('.json'):
                        filepath = os.path.join(cr_dir, filename)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            project = data.get('project_name', data.get('project_key', ''))
                            score = 0
                            if query in str(project).lower():
                                score = 90
                            if score > 0:
                                results.append({
                                    'type': 'cr',
                                    'title': f'CR分析: {project}',
                                    'url': '/excel-analysis',
                                    'score': score,
                                    'snippet': f'CR分析历史记录: {project}'
                                })
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"搜索CR失败: {e}")
        return results[:limit]

    def _search_documents(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """搜索上传文档"""
        results = []
        try:
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
            if os.path.exists(uploads_dir):
                for root, dirs, files in os.walk(uploads_dir):
                    for filename in files:
                        if query in filename.lower():
                            filepath = os.path.join(root, filename)
                            results.append({
                                'type': 'documents',
                                'title': filename,
                                'url': '#',
                                'score': 70,
                                'snippet': f'上传文档: {filename}'
                            })
                            if len(results) >= limit:
                                return results
        except Exception as e:
            logger.warning(f"搜索文档失败: {e}")
        return results[:limit]

    def get_search_suggestions(self, query: str) -> List[str]:
        """获取搜索建议（基于历史搜索和热门关键词）"""
        suggestions = []
        popular = ['项目状态', 'CR分析', '日报', 'Bug趋势', '知识库', '牛马笔记', '邮件', '过点风险']
        for p in popular:
            if query.lower() in p.lower() or p.lower() in query.lower():
                suggestions.append(p)
        return suggestions[:5]


# 全局搜索引擎实例
global_search = GlobalSearchEngine()
