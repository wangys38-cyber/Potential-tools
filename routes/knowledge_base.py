"""
知识库路由
"""
import os
import csv
import io
import logging
from flask import Blueprint, request, jsonify, render_template, g
from services.ai.knowledge_base import get_knowledge_base, analyze_image_with_ai

logger = logging.getLogger(__name__)


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
    """列出所有文档"""
    try:
        user_id = getattr(g, 'user_id', 1) or 1
        kb = get_knowledge_base(user_id)
        docs = kb.list_documents()
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
