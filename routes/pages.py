"""页面路由 Blueprint — 简单的模板渲染路由"""
from flask import Blueprint


def create_pages_blueprint(cached_render):
    """创建页面路由 Blueprint

    Args:
        cached_render: 从 app.py 传入的缓存渲染函数
    """
    bp = Blueprint('pages', __name__)

    @bp.route('/')
    def index():
        return cached_render('index.html')

    @bp.route('/test-report')
    def test_report():
        return cached_render('test_report.html')

    @bp.route('/excel-analysis')
    def excel_analysis():
        return cached_render('excel_analysis.html')

    @bp.route('/project-info')
    def project_info():
        return cached_render('project_info.html')

    @bp.route('/md2pdf')
    def md2pdf():
        return cached_render('md2pdf.html')

    @bp.route('/merit')
    def merit():
        return cached_render('merit.html')

    @bp.route('/plan-generator')
    def plan_generator():
        return cached_render('plan_generator.html')

    @bp.route('/bug-trend')
    def bug_trend():
        return cached_render('bug_trend.html')

    @bp.route('/release-checklist')
    def release_checklist():
        return cached_render('release_checklist.html')

    @bp.route('/log-analyzer')
    def log_analyzer():
        return cached_render('log_analyzer.html')

    @bp.route('/mttf-dashboard')
    def mttf_dashboard():
        return cached_render('mttf_dashboard.html')

    @bp.route('/dashboard')
    def dashboard():
        return cached_render('dashboard.html')

    @bp.route('/daily-standup')
    def daily_standup():
        return cached_render('daily_standup.html')

    @bp.route('/email-assistant')
    def email_assistant():
        return cached_render('email_assistant.html')

    @bp.route('/data-viz')
    def data_viz():
        return cached_render('data_viz.html')

    @bp.route('/meeting-minutes')
    def meeting_minutes():
        return cached_render('meeting_minutes.html')

    @bp.route('/weekly-report')
    def weekly_report():
        return cached_render('weekly_report.html')

    @bp.route('/settings')
    def settings():
        return cached_render('settings.html')

    @bp.route('/translator')
    def translator():
        return cached_render('translator.html', nav_title='IT 翻译器')

    @bp.route('/knowledge-graph')
    def knowledge_graph():
        return cached_render('knowledge_graph.html', nav_title='研发知识图谱')

    @bp.route('/my-activity')
    def my_activity():
        return cached_render('my_activity.html', nav_title='我的活动')

    @bp.route('/teams')
    def teams_list():
        return cached_render('teams.html', nav_title='团队')

    @bp.route('/teams/<team_code>')
    def team_detail(team_code):
        return cached_render('team_detail.html', nav_title='团队详情', team_code=team_code)

    return bp
