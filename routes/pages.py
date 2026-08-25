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
        return cached_render('test_report.html', nav_title='测试报告分析')

    @bp.route('/excel-analysis')
    def excel_analysis():
        return cached_render('excel_analysis.html', nav_title='CR 问题分析')

    @bp.route('/project-info')
    def project_info():
        return cached_render('project_info.html', nav_title='项目信息收集')

    @bp.route('/md2pdf')
    def md2pdf():
        return cached_render('md2pdf.html', nav_title='PDF 快转')

    @bp.route('/merit')
    def merit():
        return cached_render('merit.html', nav_title='电子木鱼')

    @bp.route('/plan-generator')
    def plan_generator():
        return cached_render('plan_generator.html', nav_title='软件计划生成器')

    @bp.route('/bug-trend')
    def bug_trend():
        return cached_render('bug_trend.html', nav_title='Bug 趋势看板')

    @bp.route('/release-checklist')
    def release_checklist():
        return cached_render('release_checklist.html', nav_title='发布检查清单')

    @bp.route('/log-analyzer')
    def log_analyzer():
        return cached_render('log_analyzer.html', nav_title='日志根因分析')

    @bp.route('/mttf-dashboard')
    def mttf_dashboard():
        return cached_render('mttf_dashboard.html', nav_title='MTTF 可靠性看板')

    @bp.route('/dashboard')
    def dashboard():
        return cached_render('dashboard.html', nav_title='研发健康度')

    @bp.route('/daily-standup')
    def daily_standup():
        return cached_render('daily_standup.html', nav_title='每日站会助手')

    @bp.route('/email-assistant')
    def email_assistant():
        return cached_render('email_assistant.html', nav_title='邮件助手')

    @bp.route('/data-viz')
    def data_viz():
        return cached_render('data_viz.html', nav_title='数据可视化')

    @bp.route('/meeting-minutes')
    def meeting_minutes():
        return cached_render('meeting_minutes.html', nav_title='会议纪要')

    @bp.route('/weekly-report')
    def weekly_report():
        return cached_render('weekly_report.html', nav_title='智能周报')

    @bp.route('/settings')
    def settings():
        return cached_render('settings.html', nav_title='系统设置')

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
