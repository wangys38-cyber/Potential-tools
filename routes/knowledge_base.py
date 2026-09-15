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
            result_parts.append(f"\n=== 字段统计 ===")
            for j, h in enumerate(headers):
                values = [row[j] for row in data_rows if j < len(row) and row[j].strip()]
                unique = len(set(values))
                result_parts.append(f"字段「{h}」: 共 {len(values)} 条有效数据，{unique} 个不同值")
        
        return "\n".join(result_parts)
    except Exception as e:
        logger.error(f"CSV 解析失败: {e}")
        # 降级为纯文本
        raw = file_obj.read()
        return raw.decode('utf-8', errors='ignore')

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
