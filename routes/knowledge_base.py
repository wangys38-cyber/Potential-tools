"""
知识库路由
"""
import os
import logging
from flask import Blueprint, request, jsonify, render_template, g
from services.ai.knowledge_base import get_knowledge_base

logger = logging.getLogger(__name__)

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
        
        # 读取文件内容
        if ext in ['.txt', '.md', '.csv']:
            content = file.read().decode('utf-8', errors='ignore')
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
