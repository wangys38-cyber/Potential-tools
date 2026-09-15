"""
知识库路由
"""
import os
import csv
import io
import logging
import sqlite3
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, g
from services.ai.knowledge_base import get_knowledge_base, analyze_image_with_ai, get_llm_response

logger = logging.getLogger(__name__)

DB_PATH = r'D:\app\data\users.db'

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def save_doc_meta(doc_id, title, category, tags='', file_hash='', chunk_count=0, user_id=1):
    conn = _get_db()
    c = conn.cursor()
    c.execute('SELECT version FROM knowledge_docs WHERE doc_id=?', (doc_id,))
    row = c.fetchone()
    if row:
        c.execute('UPDATE knowledge_docs SET title=?, category=?, tags=?, file_hash=?, chunk_count=?, updated_at=? WHERE doc_id=?',
                  (title, category, tags, file_hash, chunk_count, datetime.now(), doc_id))
    else:
        c.execute('INSERT INTO knowledge_docs (doc_id, title, category, tags, file_hash, chunk_count, user_id) VALUES (?,?,?,?,?,?,?)',
                  (doc_id, title, category, tags, file_hash, chunk_count, user_id))
    conn.commit()
    conn.close()

def save_chat_history(user_id, question, answer):
    conn = _get_db()
    c = conn.cursor()
    c.execute('INSERT INTO kb_chat_history (user_id, question, answer) VALUES (?,?,?)', (user_id, question, answer))
    conn.commit()
    conn.close()

def _get_chat_history_from_db(user_id, limit=20):
    conn = _get_db()
    c = conn.cursor()
    c.execute('SELECT question, answer, created_at FROM kb_chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?', (user_id, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def parse_csv_file(file_obj) -> str:
    """CSV 文件结构化解析，转为易理解的文本"""
    try:
        # 读取内容
        raw = file_obj.read()
        # 尝试多种编码
        for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try:
                text = raw.decode(encoding)
                break
            except:
                continue
        
        # 用 csv 模块解析
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        
        if len(rows) < 2:
            return f"CSV 文件内容:\n{text[:2000]}"
        
        headers = rows[0]
        data_rows = rows[1:]
        
        # 生成结构化描述
        result_parts = [
            f"【CSV 表格数据】",
            f"文件共 {len(data_rows)} 行数据，{len(headers)} 个字段",
            f"字段列表: {', '.join(headers)}",
            f"",
            f"=== 数据概览 ==="
        ]
        
        # 如果行数不多，逐行描述
        if len(data_rows) <= 50:
            for i, row in enumerate(data_rows[:50]):
                row_dict = {}
                for j, h in enumerate(headers):
                    if j < len(row):
                        row_dict[h] = row[j]
                # 转成易读格式
                line = " | ".join([f"{k}: {v}" for k, v in row_dict.items() if v.strip()])
                result_parts.append(f"第{i+1}行: {line}")
        else:
            # 行数多，统计关键字段分布
            result_parts.append(f"（数据较多，以下为前 20 行 + 字段统计）")
            for i, row in enumerate(data_rows[:20]):
                row_dict = {}
                for j, h in enumerate(headers):
                    if j < len(row):
                        row_dict[h] = row[j]
                line = " | ".join([f"{k}: {v}" for k, v in row_dict.items() if v.strip()])
                result_parts.append(f"第{i+1}行: {line}")
            
            # 统计每个字段的唯一值数量
            from collections import Counter
            for j, h in enumerate(headers):
                values = [row[j] for row in data_rows if j < len(row) and row[j].strip()]
                unique = len(set(values))
                result_parts.append(f"字段「{h}」: 共 {len(values)} 条有效数据，{unique} 个不同值")
                
                # 如果是分类字段（唯一值不多），统计每个值的数量
                if unique <= 20:
                    counter = Counter(values)
                    result_parts.append(f"  分布: " + "、".join([f"{k}={v}个" for k, v in counter.most_common()]))
        
        return "\n".join(result_parts)
    except Exception as e:
        logger.error(f"CSV 解析失败: {e}")
        # 降级为纯文本
        raw = file_obj.read()
        return raw.decode('utf-8', errors='ignore')



def parse_excel_file(file_obj) -> str:
    """Excel 文件结构化解析 - 识别甘特图/排计划格式"""
    try:
        import pandas as pd
        xls = pd.ExcelFile(file_obj)
        
        result_parts = [
            f"【Excel 表格数据】",
            f"文件包含 {len(xls.sheet_names)} 个工作表: {', '.join(xls.sheet_names)}",
            ""
        ]
        
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                result_parts.append(f"=== 工作表: {sheet_name} ===")
                
                if len(df) == 0:
                    result_parts.append("（空表，无数据）")
                    result_parts.append("")
                    continue
                
                # 尝试识别甘特图格式（前几行是时间节点表头）
                gantt_keywords = ['TR', 'EVB', 'EVT', 'DVT', 'PVT', 'CP1', 'CP2', 'SR5', 'SR6', 'Plan', 'CWV', 'Bring', 'launch', 'FC', 'CF', 'LC']
                header_row = None
                for i in range(min(5, len(df))):
                    row_vals = [str(v).strip() for v in df.iloc[i].values if pd.notna(v)]
                    match_count = sum(1 for kw in gantt_keywords if any(kw in v for v in row_vals))
                    if match_count >= 3:
                        header_row = i
                        break
                
                if header_row is not None:
                    # 甘特图格式：横向时间节点，纵向模块
                    file_name = os.path.basename(file_obj.name) if hasattr(file_obj, 'name') else 'Excel文件'
                    result_parts.append(f"【{file_name} - {sheet_name}工作表 - 项目计划/排期/Schedule】")
                    result_parts.append("（识别为甘特图/排计划格式）")
                    result_parts.append("")
                    
                    # 第一步：从表头行读取时间节点名
                    header_row_vals = df.iloc[header_row]
                    time_nodes = []  # [(col_idx, node_name)]
                    for j in range(2, df.shape[1]):
                        if pd.notna(header_row_vals.iloc[j]):
                            node_name = str(header_row_vals.iloc[j]).strip()
                            if node_name and node_name != 'nan':
                                time_nodes.append((j, node_name))
                    
                    # 第二步：逐行读取数据，模块名是合并单元格，向下继承
                    current_module = ""
                    
                    for i in range(header_row + 1, len(df)):
                        row = df.iloc[i]
                        
                        # 第一列：模块名（合并单元格，向下继承）
                        if pd.notna(row.iloc[0]):
                            current_module = str(row.iloc[0]).strip()
                            if current_module == 'nan':
                                current_module = ""
                        
                        # 第二列：Plan/CWV/Bring up 等行名
                        row_type = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else ""
                        if row_type == 'nan':
                            row_type = ""
                        
                        if not current_module:
                            continue
                        
                        # 第三列开始是日期值，用表头行的节点名对应
                        tasks = []
                        for col_idx, node_name in time_nodes:
                            if col_idx < len(row) and pd.notna(row.iloc[col_idx]):
                                val = row.iloc[col_idx]
                                # 格式化日期
                                if hasattr(val, 'strftime'):
                                    val_str = val.strftime('%Y-%m-%d')
                                else:
                                    val_str = str(val).strip()
                                if val_str and val_str != 'nan' and val_str != '':
                                    tasks.append(f"{node_name}: {val_str}")
                        
                        if tasks:
                            label = f"{current_module} - {row_type}" if row_type else current_module
                            result_parts.append(f"【{label}】")
                            result_parts.append("  " + "、".join(tasks))
                            result_parts.append("")
                else:
                    # 普通表格格式
                    result_parts.append(f"共 {len(df)} 行，{len(df.columns)} 列")
                    result_parts.append("")
                    
                    # 完整数据
                    result_parts.append("完整数据:")
                    for idx, row in df.iterrows():
                        row_str = " | ".join([f"{df.columns[j] if j < len(df.columns) else f'列{j}'}: {row.iloc[j]}" for j in range(len(row)) if pd.notna(row.iloc[j])])
                        if row_str.strip():
                            result_parts.append(f"第{idx+1}行: {row_str}")
                
                result_parts.append("")
            except Exception as sheet_err:
                result_parts.append(f"=== 工作表: {sheet_name}（读取失败: {str(sheet_err)[:50]}）===")
                result_parts.append("")
        
        return "\n".join(result_parts)
    except Exception as e:
        logger.error(f"Excel 解析失败: {e}")
        return f"Excel 解析失败: {str(e)}"

kb_bp = Blueprint('knowledge_base', __name__, url_prefix='/knowledge-base')


@kb_bp.route('/')
def index():
    """知识库主页"""
    return render_template('knowledge_base.html')


@kb_bp.route('/api/documents', methods=['GET'])
def list_documents():
    """列出所有文档（含版本/标签）"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        docs = kb.list_documents()
        # 合并数据库元数据
        conn = _get_db()
        c = conn.cursor()
        for d in docs:
            c.execute('SELECT version, tags, updated_at FROM knowledge_docs WHERE doc_id=?', (d['doc_id'],))
            row = c.fetchone()
            if row:
                d['version'] = row['version']
                d['tags'] = row['tags'] or ''
                d['updated_at'] = row['updated_at']
            else:
                d['version'] = 1
                d['tags'] = ''
        conn.close()
        return jsonify({"status": "success", "documents": docs})
    except Exception as e:
        logger.error(f"列出文档失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/documents', methods=['POST'])
def upload_document():
    """上传文档"""
    try:
        title = request.form.get('title', '')
        content = request.form.get('content', '')
        
        if not content:
            return jsonify({"status": "error", "error": "内容不能为空"}), 400
        
        if not title:
            title = f"文档_{len(content)}字"
        
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        doc_id = f"doc_{os.urandom(4).hex()}"
        success = kb.add_document(doc_id, title, content)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "文档上传成功",
                "doc_id": doc_id,
                "title": title
            })
        else:
            return jsonify({"status": "error", "error": "文档处理失败"}), 500
    except Exception as e:
        logger.error(f"上传文档失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """删除文档"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        success = kb.delete_document(doc_id)
        if success:
            return jsonify({"status": "success", "message": "删除成功"})
        else:
            return jsonify({"status": "error", "error": "删除失败"}), 500
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/ask', methods=['POST'])
def ask():
    """智能问答"""
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        
        if not question:
            return jsonify({"status": "error", "error": "问题不能为空"}), 400
        
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        result = kb.ask(question)
        
        return jsonify({
            "status": "success",
            "answer": result['answer'],
            "contexts": result['contexts']
        })
    except Exception as e:
        logger.error(f"问答失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/upload-file', methods=['POST'])
def upload_file():
    """上传文件"""
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "error": "没有文件"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"status": "error", "error": "没有选择文件"}), 400
        
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()
        
        # 图片文件 - 用多模态 AI 识别
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
            image_bytes = file.read()
            image_format = ext[1:]  # 去掉点号
            
            # 调用多模态 AI 识别图片内容
            recognized_content = analyze_image_with_ai(image_bytes, image_format)
            
            if not recognized_content or recognized_content.startswith('图片识别失败'):
                return jsonify({"status": "error", "error": recognized_content}), 500
            
            content = f"【图片识别结果】\n文件: {filename}\n\n{recognized_content}"
            title = os.path.splitext(filename)[0]
        elif ext == '.csv':
            # CSV 结构化解析
            content = parse_csv_file(file)
            title = os.path.splitext(filename)[0]
        elif ext in ['.xlsx', '.xls']:
            # Excel 结构化解析
            content = parse_excel_file(file)
            title = os.path.splitext(filename)[0]
        elif ext in ['.txt', '.md']:
            content = file.read().decode('utf-8', errors='ignore')
            title = os.path.splitext(filename)[0]
        elif ext == '.pdf':
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(file)
                content = "\n".join([page.extract_text() for page in reader.pages])
            except ImportError:
                return jsonify({"status": "error", "error": "PDF 解析库未安装"}), 500
        elif ext in ['.doc', '.docx']:
            try:
                from docx import Document
                doc = Document(file)
                content = "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                return jsonify({"status": "error", "error": "Word 解析库未安装"}), 500
        else:
            return jsonify({"status": "error", "error": f"不支持的文件格式: {ext}"}), 400
        
        if not content.strip():
            return jsonify({"status": "error", "error": "文件内容为空"}), 400
        
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        doc_id = f"doc_{os.urandom(4).hex()}"
        title = os.path.splitext(filename)[0]
        success = kb.add_document(doc_id, title, content)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "文件上传成功",
                "doc_id": doc_id,
                "title": title,
                "size": len(content)
            })
        else:
            return jsonify({"status": "error", "error": "文档处理失败"}), 500
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/sync-cr', methods=['POST'])
def sync_cr_to_kb():
    """将 CR 分析数据同步到知识库（每天更新，自动替换旧数据）"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "error": "没有数据"}), 400
        
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        
        # 固定的 CR 文档 ID，每天同步时先删除旧的
        cr_doc_id = "cr_analysis_latest"
        
        # 先删除旧的 CR 文档
        kb.delete_document(cr_doc_id)
        
        # 构建结构化的 CR 数据文本
        summary = data.get('summary', {})
        module_stats = data.get('module_stats', [])
        developer_stats = data.get('developer_stats', [])
        severity_stats = data.get('severity_stats', {})
        weekly_stats = data.get('weekly_stats', [])
        issues = data.get('issues', [])
        
        content_parts = [
            "【CR 分析最新数据】",
            f"更新时间: {data.get('update_time', '今天')}",
            "",
            "=== 总体概览 ===",
            f"总问题数: {summary.get('total_issues', 0)}",
            f"已解决: {summary.get('total_resolved', 0)}",
            f"未解决: {summary.get('total_unresolved', 0)}",
            f"解决率: {summary.get('resolution_rate', '0%')}%",
            "",
            "=== 严重程度分布 ===",
        ]
        
        for sev, count in severity_stats.items():
            content_parts.append(f"{sev}: {count} 个")
        
        content_parts.append("")
        content_parts.append("=== 模块问题分布（Top 10）===")
        for i, m in enumerate(module_stats[:10]):
            content_parts.append(f"{i+1}. {m.get('name', '')}: 共 {m.get('total', 0)} 个，未解决 {m.get('unresolved', 0)} 个")
        
        content_parts.append("")
        content_parts.append("=== 开发者问题分布 ===")
        for i, d in enumerate(developer_stats[:15]):
            content_parts.append(f"{i+1}. {d.get('name', '')}: 共 {d.get('total', 0)} 个，未解决 {d.get('unresolved', 0)} 个")
        
        if weekly_stats:
            content_parts.append("")
            content_parts.append("=== 每周趋势 ===")
            for w in weekly_stats[-8:]:
                content_parts.append(f"{w.get('week', '')}: 新增 {w.get('new', 0)}，解决 {w.get('resolved', 0)}，累计未解决 {w.get('cumulative_unresolved', 0)}")
        
        # 未解决问题列表
        resolved_keywords = ['resolved', 'fixed', 'closed', 'done', '已解决', '已关闭']
        unresolved = [i for i in issues if i.get('status', '').lower() not in resolved_keywords]
        
        content_parts.append("")
        content_parts.append("=== 未解决问题列表（前 50 个）===")
        for i, issue in enumerate(unresolved[:50]):
            content_parts.append(f"{i+1}. [{issue.get('severity', '')}] {issue.get('title', '')} - 模块: {issue.get('module', '')} - 负责人: {issue.get('developer', '')}")
        
        content = "\n".join(content_parts)
        
        # 添加到知识库
        success = kb.add_document(cr_doc_id, "CR分析最新数据（每日更新）", content, metadata={'type': 'cr_analysis'})
        
        if success:
            return jsonify({
                "status": "success",
                "message": "CR 数据已同步到知识库",
                "size": len(content)
            })
        else:
            return jsonify({"status": "error", "error": "同步失败"}), 500
    except Exception as e:
        logger.error(f"CR 同步失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500



@kb_bp.route('/api/chat-history', methods=['GET'])
def get_chat_history_api():
    """获取历史问答记录"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        history = _get_chat_history_from_db(user_id, limit=50)
        return jsonify({"status": "success", "history": history})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/export', methods=['GET'])
def export_chat():
    """导出对话历史为Markdown"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        history = _get_chat_history_from_db(user_id, limit=100)
        md = "# 知识库问答记录\n\n"
        for h in reversed(history):
            md += f"## Q: {h['question']}\n\n{h['answer']}\n\n---\n\n"
        return md, 200, {'Content-Type': 'text/markdown; charset=utf-8',
                          'Content-Disposition': 'attachment; filename=chat_history.md'}
    except Exception as e:
        return str(e), 500


@kb_bp.route('/api/insights', methods=['GET'])
def get_insights():
    """知识洞察：谁擅长什么、问题集中在哪、缺什么文档"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        
        # 获取所有文档列表
        docs = kb.list_documents()
        if not docs:
            return jsonify({"status": "error", "error": "暂无文档"}), 400
        
        # 获取文档分类统计
        cat_count = {}
        for d in docs:
            cat = d.get('category', '其他')
            cat_count[cat] = cat_count.get(cat, 0) + 1
        
        # 用LLM生成洞察
        doc_list_text = "\n".join([f"- {d['title']} ({d['category']}, {d['chunk_count']}片段)" for d in docs])
        
        prompt = f"""你是研发知识库分析专家。根据以下已上传的文档列表，分析：

{doc_list_text}

请输出JSON格式：
{{
  "coverage": "一句话总结文档覆盖情况",
  "gaps": ["缺失的文档类型，比如没有SOP、没有测试报告等"],
  "suggestions": ["建议补充的文档"],
  "entities": [
    {{"type": "模块/负责人/项目", "name": "xxx", "doc": "来自哪个文档"}}
  ]
}}

只输出JSON，不要其他内容。"""
        
        from services.ai.knowledge_base import get_llm_response
        import json as json_lib
        result = get_llm_response(prompt, system="你是知识库分析专家，只输出JSON。", temperature=0.1)
        
        try:
            insights = json_lib.loads(result)
        except:
            insights = {"coverage": f"共{len(docs)}个文档", "gaps": [], "suggestions": [], "entities": []}
        
        insights['doc_count'] = len(docs)
        insights['categories'] = cat_count
        
        return jsonify({"status": "success", "insights": insights})
    except Exception as e:
        logger.error(f"洞察分析失败: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/stats', methods=['GET'])
def get_stats():
    """知识库统计看板"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        docs = kb.list_documents()
        total_chunks = sum(d.get('chunk_count', 0) for d in docs)
        
        # 问答数
        conn = _get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM kb_chat_history WHERE user_id=?', (user_id,))
        qa_count = c.fetchone()[0]
        conn.close()
        
        # 分类统计
        cats = {}
        for d in docs:
            cat = d.get('category', '其他')
            cats[cat] = cats.get(cat, 0) + 1
        
        return jsonify({
            "status": "success",
            "stats": {
                "doc_count": len(docs),
                "chunk_count": total_chunks,
                "qa_count": qa_count,
                "categories": cats
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/feedback', methods=['POST'])
def save_feedback():
    """用户反馈：点赞/点踩，影响后续检索权重"""
    try:
        data = request.get_json()
        user_id = getattr(g, 'user_id', 1) or 1
        question = data.get('question', '')
        feedback = data.get('feedback', '')
        
        # 记录反馈
        conn = _get_db()
        c = conn.cursor()
        c.execute('INSERT INTO kb_feedback (user_id, question, feedback) VALUES (?,?,?)', (user_id, question, feedback))
        conn.commit()
        conn.close()
        
        # 学习：点踩时降低相关chunk的权重
        if feedback == 'down' and question:
            try:
                kb = get_knowledge_base(user_id)
                # 找到和这个问题相关的chunk
                results = kb.query(question, top_k=5)
                for r in results:
                    did = r.get('_did', '')
                    if did:
                        meta = r.get('metadata', {})
                        old_score = meta.get('feedback_score', 0)
                        new_score = old_score - 1  # 每次点踩-1
                        # 更新metadata
                        kb.collection.update(
                            ids=[did],
                            metadatas=[{**meta, 'feedback_score': new_score}]
                        )
                logger.info(f"反馈学习: 问题'{question[:30]}...' 点踩，{len(results)}个chunk降权")
            except Exception as e:
                logger.warning(f"反馈学习失败: {e}")
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/export-report', methods=['GET'])
def export_weekly_report():
    """导出为周报格式（Markdown）"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        conn = _get_db()
        c = conn.cursor()
        c.execute('SELECT question, answer, created_at FROM kb_chat_history WHERE user_id=? ORDER BY id DESC LIMIT 20', (user_id,))
        rows = c.fetchall()
        conn.close()
        
        from datetime import datetime
        report = f"# 知识库周报\n\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        report += "## 近期问答摘要\n\n"
        for q, a, t in reversed(rows):
            report += f"### Q: {q}\n\n{a[:500]}\n\n---\n\n"
        
        return jsonify({"status": "success", "report": report})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/health', methods=['GET'])
def kb_health():
    """知识库健康度：过期文档/重复检测/统计"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        docs = kb.list_documents()
        
        import time
        now = time.time()
        stale_days = 30 * 86400
        stale_docs = []
        for d in docs:
            created = d.get('created_at', '')
            try:
                if isinstance(created, str):
                    ct = time.mktime(time.strptime(created[:19], '%Y-%m-%d %H:%M:%S'))
                else:
                    ct = float(created)
                if now - ct > stale_days:
                    stale_docs.append({
                        'title': d.get('title', ''),
                        'days_old': int((now - ct) / 86400)
                    })
            except:
                pass
        
        return jsonify({
            "status": "success",
            "health": {
                "total_docs": len(docs),
                "stale_docs": stale_docs,
                "stale_count": len(stale_docs),
                "categories": list(set(d.get('category', '其他') for d in docs))
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/daily-brief', methods=['GET'])
def daily_brief():
    """每日自动分析：生成CR简报"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        # 检索CR最新数据
        results = kb.query("CR问题总数 未解决 严重 性能 MTTF 本周新增", top_k=5)
        if not results:
            return jsonify({"status": "error", "error": "无CR数据"}), 400
        
        context = "\n".join([r['content'] for r in results[:3]])
        prompt = f"""根据以下知识库数据，生成今日CR简报：
1. 总体概览（总问题/未解决/解决率）
2. 严重问题未解决数
3. 性能/MTTF未解决数
4. 需要关注的Top3问题
5. 今日建议

内容：
{context}

简洁专业，不要废话。"""
        brief = get_llm_response(prompt, system="你是项目质量分析师。", temperature=0.3)
        
        # 存到对话历史
        save_chat_history(user_id, "[系统] 每日自动分析", brief)
        
        return jsonify({"status": "success", "brief": brief})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/graph', methods=['GET'])
def knowledge_graph():
    """知识图谱：提取实体和关系"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        docs = kb.list_documents()
        
        # 收集文档标题和分类作为节点
        nodes = []
        edges = []
        node_set = set()
        
        for d in docs:
            cat = d.get('category', '其他')
            # 分类节点
            if cat not in node_set:
                nodes.append({"id": cat, "type": "category", "label": cat})
                node_set.add(cat)
            # 文档节点
            title = d.get('title', '')
            if title not in node_set:
                nodes.append({"id": title, "type": "document", "label": title})
                node_set.add(title)
            edges.append({"source": cat, "target": title})
        
        # 用LLM提取关键实体
        if docs:
            doc_list = "\n".join([f"- {d['title']} ({d['category']})" for d in docs])
            prompt = f"""从以下文档列表中提取关键实体（人名、模块名、项目名），输出JSON：
{{
  "entities": [
    {{"name": "实体名", "type": "人/模块/项目", "from": "来源文档"}}
  ]
}}

文档：
{doc_list}

只输出JSON。"""
            result = get_llm_response(prompt, system="只输出JSON。", temperature=0.1)
            import json as j
            try:
                data = j.loads(result)
                for e in data.get('entities', []):
                    name = e.get('name', '')
                    if name and name not in node_set:
                        nodes.append({"id": name, "type": e.get('type', '其他'), "label": name})
                        node_set.add(name)
                        # 连到来源文档
                        frm = e.get('from', '')
                        if frm in node_set:
                            edges.append({"source": frm, "target": name})
            except:
                pass
        
        return jsonify({"status": "success", "graph": {"nodes": nodes, "edges": edges}})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/cr-summary', methods=['GET'])
def cr_summary():
    """从知识库提取CR周报摘要（供邮件助手/趋势看板调用）"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        # 检索CR数据
        results = kb.query("CR问题总数 未解决 严重 性能 MTTF", top_k=5)
        if not results:
            return jsonify({"status": "error", "error": "知识库中无CR数据"}), 400
        
        # 提取关键数字
        context = "\n".join([r['content'] for r in results[:3]])
        prompt = f"""从以下知识库内容提取CR周报关键数字，输出JSON：
{{
  "total": 总问题数,
  "unresolved": 未解决数,
  "resolved": 已解决数,
  "rate": 解决率,
  "critical_unresolved": 严重/致命未解决数,
  "performance_unresolved": 性能未解决数,
  "mttr_unresolved": MTTF未解决数,
  "top_issues": ["Top3未解决问题简述"]
}}

内容：
{context}

只输出JSON。"""
        result = get_llm_response(prompt, system="你是数据分析专家，只输出JSON。", temperature=0.1)
        import json as j
        try:
            data = j.loads(result)
        except:
            data = {"raw": result}
        return jsonify({"status": "success", "summary": data})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/feedback-report', methods=['GET'])
def feedback_report():
    """学习报告：分析用户反馈"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        conn = _get_db()
        c = conn.cursor()
        # 统计
        c.execute('SELECT feedback, COUNT(*) as cnt FROM kb_feedback WHERE user_id=? GROUP BY feedback', (user_id,))
        stats = {row[0]: row[1] for row in c.fetchall()}
        # 最近点踩的问题
        c.execute('SELECT question, created_at FROM kb_feedback WHERE user_id=? AND feedback=\'down\' ORDER BY id DESC LIMIT 10', (user_id,))
        down_questions = [{'question': row[0], 'time': row[1]} for row in c.fetchall()]
        conn.close()
        return jsonify({
            "status": "success",
            "report": {
                "total_up": stats.get('up', 0),
                "total_down": stats.get('down', 0),
                "down_questions": down_questions
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@kb_bp.route('/api/clear-history', methods=['POST'])
def clear_history():
    """清空对话历史"""
    kb = get_knowledge_base(g.user_id if hasattr(g, 'user_id') else 1)
    kb.clear_history()
    return jsonify({"status": "success", "message": "对话历史已清空"})


@kb_bp.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    """清空回答缓存"""
    kb = get_knowledge_base(g.user_id if hasattr(g, 'user_id') else 1)
    kb.clear_cache()
    return jsonify({"status": "success", "message": "缓存已清空"})

@kb_bp.route('/api/search', methods=['GET'])
def full_search():
    """全文精确搜索（不经过AI）"""
    keyword = request.args.get('q', '').strip()
    if not keyword:
        return jsonify({"status": "error", "error": "请输入搜索关键词"}), 400
    kb = get_knowledge_base(g.user_id if hasattr(g, 'user_id') else 1)
    results = kb.full_text_search(keyword, top_k=20)
    return jsonify({"status": "success", "results": results, "count": len(results)})

