"""报告构建器模块 — 从 app.py 提取"""
import re
import json
from datetime import datetime, timezone, timedelta
from excel_analyzers import _match_severity_level

_CST = timezone(timedelta(hours=8))

def _is_resolved_status(status):
    """判断问题状态是否为已解决"""
    if not status:
        return False
    s = str(status).lower()
    return any(kw in s for kw in ['resolved', 'closed', 'done', 'fixed', 'verified', '已解决', '已关闭', '已完成', '已验证'])

def _build_cr_analysis_report_html(data, watermark, file_name, custom_title='', ai_analysis='', all_issues=None):
    """构建CR问题分析报告HTML（含Chart.js图表）"""
    # 类型检查和转换：如果是字符串，尝试解析为JSON
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    
    if all_issues is None:
        all_issues = []
    if isinstance(all_issues, str):
        try:
            all_issues = json.loads(all_issues)
        except (json.JSONDecodeError, ValueError):
            all_issues = []
    if not isinstance(all_issues, list):
        all_issues = []
    
    summary = data.get('summary', {})
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except (json.JSONDecodeError, ValueError):
            summary = {}
    if not isinstance(summary, dict):
        summary = {}
    
    module_stats = data.get('module_stats', {})
    if isinstance(module_stats, str):
        try:
            module_stats = json.loads(module_stats)
        except (json.JSONDecodeError, ValueError):
            module_stats = {}
    if not isinstance(module_stats, dict):
        module_stats = {}
    
    dev_stats = data.get('dev_stats', {})
    if isinstance(dev_stats, str):
        try:
            dev_stats = json.loads(dev_stats)
        except (json.JSONDecodeError, ValueError):
            dev_stats = {}
    if not isinstance(dev_stats, dict):
        dev_stats = {}
    
    daily_stats = data.get('daily_stats', [])
    if isinstance(daily_stats, str):
        try:
            daily_stats = json.loads(daily_stats)
        except (json.JSONDecodeError, ValueError):
            daily_stats = []
    if not isinstance(daily_stats, list):
        daily_stats = []
    
    suggestions = data.get('suggestions', [])
    if isinstance(suggestions, str):
        try:
            suggestions = json.loads(suggestions)
        except (json.JSONDecodeError, ValueError):
            suggestions = []
    if not isinstance(suggestions, list):
        suggestions = []
    
    resolved_unverified = data.get('resolved_unverified', [])
    if isinstance(resolved_unverified, str):
        try:
            resolved_unverified = json.loads(resolved_unverified)
        except (json.JSONDecodeError, ValueError):
            resolved_unverified = []
    if not isinstance(resolved_unverified, list):
        resolved_unverified = []
    
    stability_stats = data.get('stability_stats', {})
    if isinstance(stability_stats, str):
        try:
            stability_stats = json.loads(stability_stats)
        except (json.JSONDecodeError, ValueError):
            stability_stats = {}
    if not isinstance(stability_stats, dict):
        stability_stats = {}

    # 安全辅助函数：确保列表中的每个元素都是字典
    def _safe_dict_list(lst):
        if not isinstance(lst, list):
            return []
        result = []
        for item in lst:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict):
                        result.append(parsed)
                except (json.JSONDecodeError, ValueError):
                    pass
        return result

    # 安全处理列表中的嵌套元素
    suggestions = _safe_dict_list(suggestions)
    daily_stats = _safe_dict_list(daily_stats)
    resolved_unverified = _safe_dict_list(resolved_unverified)
    all_issues = _safe_dict_list(all_issues)

    # 水印 - 小水印，密度适中
    watermark_html = ''
    if watermark:
        # 生成多个水印，平铺在页面上
        watermark_items = ''.join([
            f'<div style="position:absolute;left:{x}px;top:{y}px;transform:rotate(-30deg);font-size:16px;font-weight:500;color:#0071e3;white-space:nowrap;">{watermark}</div>'
            for x in range(50, 600, 120)
            for y in range(80, 800, 120)
        ])
        watermark_html = f'''
        <div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;opacity:0.12;overflow:hidden;">
            {watermark_items}
        </div>
        '''

    # 概览卡片
    total = summary.get('total_issues', 0)
    resolved = summary.get('total_resolved', 0)
    unresolved = summary.get('total_unresolved', 0)
    rate = summary.get('resolution_rate', 0)

    overview_html = f'''
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px;">
        <div style="background:linear-gradient(135deg,#f0f7ff,#e8f1ff);border-radius:12px;padding:20px;text-align:center;border:1px solid #bae0ff;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">问题总数</div>
            <div style="font-size:32px;font-weight:700;color:#0071e3;">{total}</div>
        </div>
        <div style="background:linear-gradient(135deg,#e8f8f0,#d4f0e0);border-radius:12px;padding:20px;text-align:center;border:1px solid #a8e0b8;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">已解决</div>
            <div style="font-size:32px;font-weight:700;color:#34c759;">{resolved}</div>
        </div>
        <div style="background:linear-gradient(135deg,#fff5e8,#ffe8d4);border-radius:12px;padding:20px;text-align:center;border:1px solid #ffcc80;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">未解决</div>
            <div style="font-size:32px;font-weight:700;color:#ff9500;">{unresolved}</div>
        </div>
        <div style="background:linear-gradient(135deg,#f0e8ff,#e0d4ff);border-radius:12px;padding:20px;text-align:center;border:1px solid #b8a8ff;">
            <div style="font-size:13px;color:#6e6e73;margin-bottom:8px;">解决率</div>
            <div style="font-size:32px;font-weight:700;color:#5856d6;">{rate}%</div>
        </div>
    </div>
    '''

    # 智能建议（放在最前面）
    suggestions_html = ''
    if suggestions:
        sug_cards = ''
        for sug in suggestions:
            level = sug.get('level', 'info')
            icon = {'critical': '🚨', 'warning': '⚠️', 'info': '💡', 'success': '✅'}.get(level, '💡')
            color_map = {'critical': '#ff3b30', 'warning': '#ff9500', 'info': '#0071e3', 'success': '#34c759'}
            color = color_map.get(level, '#0071e3')
            title = sug.get('title', '')
            detail = sug.get('detail', '')
            desc = sug.get('desc', '')
            sug_cards += f'''
            <div style="background:white;border-radius:10px;padding:16px;margin-bottom:12px;border-left:4px solid {color};box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <div style="font-size:14px;font-weight:600;color:{color};margin-bottom:6px;display:flex;align-items:center;gap:6px;">
                    <span>{icon}</span> {title}
                </div>
                <div style="font-size:12px;color:#3c3c43;line-height:1.6;">{detail or desc}</div>
            </div>
            '''
        suggestions_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #34c759;">💡 智能分析建议</h2>
            {sug_cards}
        </div>
        '''

    # 严重程度分布（卡片样式）
    sev_html = ''
    if summary:
        total_issues = summary.get('total_issues', 1)
        sev_config = [
            ('blocker', 'Blocker', '#ff3b30'),
            ('critical', 'Critical', '#ff6b35'),
            ('major', 'Major', '#ff9500'),
            ('minor', 'Minor', '#34c759'),
            ('trivial', 'Trivial', '#5ac8fa'),
        ]
        # 计算B+C解决率
        blocker_total = summary.get('blocker_total', 0)
        critical_total = summary.get('critical_total', 0)
        blocker_resolved = summary.get('blocker_resolved', 0)
        critical_resolved = summary.get('critical_resolved', 0)
        bc_total = blocker_total + critical_total
        bc_resolved = blocker_resolved + critical_resolved
        bc_rate = round(bc_resolved / bc_total * 100, 1) if bc_total > 0 else 0
        
        sev_cards = ''
        for sev_name, label, color in sev_config:
            count = summary.get(f'{sev_name}_total', 0)
            pct = round(count / total_issues * 100, 1) if total_issues > 0 else 0
            sev_cards += f'''
            <div style="background:linear-gradient(135deg,{color}10,{color}20);border-radius:12px;padding:16px;text-align:center;border:1px solid {color}30;">
                <div style="font-size:28px;font-weight:700;color:{color};">{count}</div>
                <div style="font-size:12px;color:#3c3c43;margin-top:4px;">{label} {pct}%</div>
            </div>
            '''
        
        # B+C解决率卡片
        sev_cards += f'''
        <div style="background:linear-gradient(135deg,#5856d610,#5856d620);border-radius:12px;padding:16px;text-align:center;border:1px solid #5856d630;">
            <div style="font-size:28px;font-weight:700;color:#5856d6;">{bc_rate}%</div>
            <div style="font-size:12px;color:#3c3c43;margin-top:4px;">B+C解决率 ({bc_resolved})</div>
        </div>
        '''
        
        sev_html = f'''
        <div style="margin-bottom:28px;break-inside:avoid;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">🔴 严重程度分布</h2>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
                {sev_cards}
            </div>
        </div>
        '''

    # 模块分布（含饼图）
    module_html = ''
    module_chart_js = ''
    if module_stats:
        sorted_modules = sorted(module_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:10]
        module_labels = json.dumps([mod for mod, _ in sorted_modules], ensure_ascii=False)
        module_data = json.dumps([stats['total'] for _, stats in sorted_modules])
        
        module_html = f'''
        <div style="margin-bottom:28px;break-inside:avoid;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">📦 模块问题分布</h2>
            <div style="background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);border:1px solid #e5e5ea;">
                <canvas id="modulePieChart" style="max-height:300px;"></canvas>
            </div>
        </div>
        '''
        
        module_chart_js = f'''
        // 模块饼图
        (function() {{
            const ctx = document.getElementById('modulePieChart');
            if (!ctx) return;
            new Chart(ctx, {{
                type: 'doughnut',
                data: {{
                    labels: {module_labels},
                    datasets: [{{
                        data: {module_data},
                        backgroundColor: ['#0071e3','#34c759','#ff9500','#ff3b30','#af52de','#5856d6','#ff2d55','#5ac8fa','#4cd964','#ffcc00'],
                        borderWidth: 3,
                        borderColor: '#fff',
                        hoverOffset: 8
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    cutout: '45%',
                    plugins: {{
                        legend: {{
                            position: 'right',
                            labels: {{ font: {{ size: 11, family: '-apple-system, PingFang SC' }}, padding: 10, usePointStyle: true, pointStyle: 'circle' }}
                        }},
                        tooltip: {{
                            backgroundColor: 'rgba(29,29,31,0.9)',
                            titleFont: {{ size: 13, weight: '600' }},
                            bodyFont: {{ size: 12 }},
                            padding: 12,
                            cornerRadius: 8
                        }}
                    }}
                }}
            }});
        }})();
        '''

    # 每日趋势（含折线图+详细表格）
    daily_html = ''
    daily_chart_js = ''
    if daily_stats:
        display_data = daily_stats[-14:] if len(daily_stats) > 14 else daily_stats
        dates = json.dumps([d.get('date', '')[-5:] for d in display_data])
        new_counts = json.dumps([d.get('new_count', d.get('new', 0)) for d in display_data])
        resolved_counts = json.dumps([d.get('resolved_count', d.get('resolved', 0)) for d in display_data])
        
        # 计算最大值用于条形图缩放
        max_new = max((d.get('new_count', d.get('new', 0)) for d in daily_stats), default=0)
        max_resolved = max((d.get('resolved_count', d.get('resolved', 0)) for d in daily_stats), default=0)
        max_val = max(max_new, max_resolved, 1)
        
        # 表格数据 - 保持在线版UI样式，取最近30天
        display_table_daily = daily_stats[-30:] if len(daily_stats) > 30 else daily_stats
        daily_rows = ''
        for item in display_table_daily:
            d = item.get('date', '')
            new_count = item.get('new_count', item.get('new', 0))
            resolved_count = item.get('resolved_count', item.get('resolved', 0))
            net = new_count - resolved_count
            new_width = round(new_count / max_val * 100, 1) if max_val > 0 else 0
            resolved_width = round(resolved_count / max_val * 100, 1) if max_val > 0 else 0
            net_color = '#ff3b30' if net > 0 else ('#34c759' if net < 0 else '#8e8e93')
            net_text = f'+{net}' if net >= 0 else str(net)
            
            # 格式化日期 MM-DD
            date_short = d[5:] if len(d) >= 10 else d
            
            daily_rows += f'''
            <tr>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;white-space:nowrap;font-weight:500;">{date_short}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;color:#ff3b30;font-weight:600;">+{new_count}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;min-width:120px;">
                    <div style="background:#f0f0f3;border-radius:4px;height:10px;overflow:hidden;">
                        <div style="background:linear-gradient(90deg,#ff3b30,#ff9500);height:100%;width:{new_width}%;border-radius:4px;"></div>
                    </div>
                </td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;color:#34c759;font-weight:600;">-{resolved_count}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;min-width:120px;">
                    <div style="background:#f0f0f3;border-radius:4px;height:10px;overflow:hidden;">
                        <div style="background:linear-gradient(90deg,#34c759,#5ac8fa);height:100%;width:{resolved_width}%;border-radius:4px;"></div>
                    </div>
                </td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;color:{net_color};font-weight:600;">{net_text}</td>
            </tr>
            '''
        
        daily_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">📅 每日问题趋势 (共 {len(daily_stats)} 天)</h2>
            <div style="background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);border:1px solid #e5e5ea;margin-bottom:20px;">
                <canvas id="dailyLineChart" style="max-height:300px;"></canvas>
            </div>
            <div style="margin-bottom:12px;padding:10px 14px;background:#f0f7ff;border-radius:8px;font-size:12px;display:flex;gap:20px;align-items:center;">
                <div><span style="display:inline-block;width:10px;height:10px;background:linear-gradient(90deg,#ff3b30,#ff9500);border-radius:2px;margin-right:6px;"></span>新增问题 (最高 {max_new})</div>
                <div><span style="display:inline-block;width:10px;height:10px;background:linear-gradient(90deg,#34c759,#5ac8fa);border-radius:2px;margin-right:6px;"></span>解决问题 (最高 {max_resolved})</div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:11px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;">
                        <th style="padding:6px 8px;text-align:left;width:70px;">日期</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">新增</th>
                        <th style="padding:6px 8px;text-align:left;width:120px;">新增趋势</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">解决</th>
                        <th style="padding:6px 8px;text-align:left;width:120px;">解决趋势</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">净增</th>
                    </tr>
                </thead>
                <tbody>{daily_rows}</tbody>
            </table>
        </div>
        '''
        
        daily_chart_js = f'''
        // 每日趋势折线图
        (function() {{
            const ctx = document.getElementById('dailyLineChart');
            if (!ctx) return;
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {dates},
                    datasets: [{{
                        label: '新增问题',
                        data: {new_counts},
                        borderColor: '#ff3b30',
                        backgroundColor: 'rgba(255, 59, 48, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#ff3b30',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        borderWidth: 2.5
                    }}, {{
                        label: '解决问题',
                        data: {resolved_counts},
                        borderColor: '#34c759',
                        backgroundColor: 'rgba(52, 199, 89, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#34c759',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        borderWidth: 2.5
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    plugins: {{
                        legend: {{
                            position: 'top',
                            labels: {{ font: {{ size: 11, family: '-apple-system, PingFang SC' }}, padding: 12, usePointStyle: true, pointStyle: 'circle' }}
                        }},
                        tooltip: {{
                            backgroundColor: 'rgba(29,29,31,0.9)',
                            titleFont: {{ size: 13, weight: '600' }},
                            bodyFont: {{ size: 12 }},
                            padding: 12,
                            cornerRadius: 8
                        }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            grid: {{ color: 'rgba(0,0,0,0.04)' }},
                            ticks: {{ font: {{ size: 10 }} }}
                        }},
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ font: {{ size: 10 }} }}
                        }}
                    }}
                }}
            }});
        }})();
        '''

    # 研发分布
    dev_html = ''
    if dev_stats:
        dev_rows = ''
        sorted_devs = sorted(dev_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:20]
        for dev, stats in sorted_devs:
            dev_total = stats['total']
            dev_resolved = stats['resolved']
            dev_unresolved = stats['unresolved']
            dev_rate = round(dev_resolved / dev_total * 100, 1) if dev_total > 0 else 0
            dev_rows += f'''
            <tr>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;">{dev}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;">{dev_total}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#34c759;">{dev_resolved}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#ff9500;">{dev_unresolved}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;font-weight:600;">{dev_rate}%</td>
            </tr>
            '''
        dev_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #0071e3;">👥 研发问题分布 (Top {len(sorted_devs)})</h2>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;">
                        <th style="padding:10px 12px;text-align:left;">研发</th>
                        <th style="padding:10px 12px;text-align:center;">总数</th>
                        <th style="padding:10px 12px;text-align:center;">已解决</th>
                        <th style="padding:10px 12px;text-align:center;">未解决</th>
                        <th style="padding:10px 12px;text-align:center;">解决率</th>
                    </tr>
                </thead>
                <tbody>{dev_rows}</tbody>
            </table>
        </div>
        '''

    # 稳定性分析
    stability_html = ''
    if stability_stats:
        stab_rows = ''
        stab_total = sum(s['total'] for s in stability_stats.values())
        stab_resolved = sum(s['resolved'] for s in stability_stats.values())
        stab_unresolved = sum(s['unresolved'] for s in stability_stats.values())
        stab_rate = round(stab_resolved / stab_total * 100, 1) if stab_total > 0 else 0
        for mod, stats in stability_stats.items():
            stab_rows += f'''
            <tr>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;">{mod}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;">{stats['total']}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#34c759;">{stats['resolved']}</td>
                <td style="padding:10px 12px;border:1px solid #e5e5ea;text-align:center;color:#ff9500;">{stats['unresolved']}</td>
            </tr>
            '''
        stability_html = f'''
        <div style="margin-bottom:28px;background:linear-gradient(135deg,#fff,#f8f9fa);border-radius:12px;padding:20px;border:1px solid #bae0ff;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:12px;color:#1d1d1f;">🛡️ 稳定性模块分析</h2>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">模块数</div>
                    <div style="font-size:22px;font-weight:700;color:#0071e3;">{len(stability_stats)}</div>
                </div>
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">问题总数</div>
                    <div style="font-size:22px;font-weight:700;color:#ff3b30;">{stab_total}</div>
                </div>
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">已解决</div>
                    <div style="font-size:22px;font-weight:700;color:#34c759;">{stab_resolved}</div>
                </div>
                <div style="background:white;border-radius:8px;padding:12px;text-align:center;border:1px solid #e5e5ea;">
                    <div style="font-size:11px;color:#6e6e73;">解决率</div>
                    <div style="font-size:22px;font-weight:700;color:#5856d6;">{stab_rate}%</div>
                </div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;">
                        <th style="padding:10px 12px;text-align:left;">稳定性模块</th>
                        <th style="padding:10px 12px;text-align:center;">总数</th>
                        <th style="padding:10px 12px;text-align:center;">已解决</th>
                        <th style="padding:10px 12px;text-align:center;">未解决</th>
                    </tr>
                </thead>
                <tbody>{stab_rows}</tbody>
            </table>
        </div>
        '''

    # 待验证问题
    unverified_html = ''
    if resolved_unverified:
        unv_rows = ''
        for item in resolved_unverified[:50]:
            unv_rows += f'''
            <tr>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;text-align:center;font-family:monospace;">{item.get('issue_id', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;max-width:200px;overflow:hidden;text-overflow:ellipsis;">{item.get('title', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;">{item.get('developer', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;">{item.get('module', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;text-align:center;">{item.get('severity', '-')}</td>
                <td style="padding:8px 10px;border:1px solid #e5e5ea;text-align:center;">{item.get('resolution', '-')}</td>
            </tr>
            '''
        unverified_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#ff9500;padding-bottom:8px;border-bottom:2px solid #ff9500;">⚠️ 待验证问题 (共 {len(resolved_unverified)} 条，显示前 {min(len(resolved_unverified), 50)} 条)</h2>
            <p style="font-size:12px;color:#6e6e73;margin-bottom:12px;">以下问题的 Status 为 Verified，需要进行验证测试</p>
            <table style="width:100%;border-collapse:collapse;font-size:11px;">
                <thead>
                    <tr style="background:#ff9500;color:white;">
                        <th style="padding:8px 10px;text-align:center;">edartID</th>
                        <th style="padding:8px 10px;text-align:left;">标题</th>
                        <th style="padding:8px 10px;text-align:left;">研发</th>
                        <th style="padding:8px 10px;text-align:left;">模块</th>
                        <th style="padding:8px 10px;text-align:center;">严重性</th>
                        <th style="padding:8px 10px;text-align:center;">Resolution</th>
                    </tr>
                </thead>
                <tbody>{unv_rows}</tbody>
            </table>
        </div>
        '''

    # AI根因分析结果
    ai_html = ''
    if ai_analysis and ai_analysis.strip():
        # 将AI分析结果的markdown格式转为HTML
        ai_content = ai_analysis.replace('\n', '<br>')
        ai_html = f'''
        <div style="margin-bottom:28px;break-inside:avoid;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #5856d6;">AI 根因分析</h2>
            <div style="background:linear-gradient(135deg,#f8f7ff,#f0eeff);border-radius:12px;padding:20px;border:1px solid #d4ccff;font-size:13px;line-height:1.8;color:#3c3c43;">
                {ai_content}
            </div>
        </div>
        '''

    # 完整问题列表（未解决优先，全部展示）
    issues_html = ''
    if all_issues and len(all_issues) > 0:
        # 按状态分组：未解决在前
        unresolved_issues = [i for i in all_issues if not _is_resolved_status(i.get('status', ''))]
        resolved_issues = [i for i in all_issues if _is_resolved_status(i.get('status', ''))]
        sorted_issues = unresolved_issues + resolved_issues
        
        # 限制最多展示500条，避免PDF过大
        display_issues = sorted_issues[:500]
        issue_rows = ''
        for idx, item in enumerate(display_issues, 1):
            status = item.get('status', '-')
            severity = item.get('severity', '-')
            is_unresolved = not _is_resolved_status(status)
            row_bg = '#fff5f5' if is_unresolved else '#ffffff'
            issue_rows += f'''
            <tr style="background:{row_bg};">
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;font-size:10px;">{idx}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;font-family:monospace;font-size:10px;white-space:nowrap;">{item.get('issue_id', item.get('key', '-'))}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;font-size:10px;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{item.get('title', item.get('summary', '-'))}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;font-size:10px;">{item.get('module', item.get('component', '-'))}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;font-size:10px;">{item.get('developer', '-')}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;font-size:10px;font-weight:600;color:{'#ff3b30' if is_unresolved else '#34c759'};">{status}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;text-align:center;font-size:10px;">{severity}</td>
                <td style="padding:6px 8px;border:1px solid #e5e5ea;font-size:10px;white-space:nowrap;">{item.get('create_date', item.get('created', '-'))[:10] if item.get('create_date', item.get('created', '')) else '-'}</td>
            </tr>
            '''
        
        issues_html = f'''
        <div style="margin-bottom:28px;">
            <h2 style="font-size:16px;font-weight:700;margin-bottom:12px;color:#1d1d1f;padding-bottom:8px;border-bottom:2px solid #1d1d1f;">完整问题列表 (共 {len(all_issues)} 条，显示 {len(display_issues)} 条)</h2>
            <div style="font-size:11px;color:#6e6e73;margin-bottom:10px;">未解决问题 ({len(unresolved_issues)}) 以浅红色背景标注，按未解决→已解决排序</div>
            <div style="max-height:800px;overflow-y:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:10px;">
                <thead>
                    <tr style="background:#1d1d1f;color:white;position:sticky;top:0;">
                        <th style="padding:6px 8px;text-align:center;width:30px;">#</th>
                        <th style="padding:6px 8px;text-align:left;width:80px;">ID</th>
                        <th style="padding:6px 8px;text-align:left;">标题</th>
                        <th style="padding:6px 8px;text-align:left;width:80px;">模块</th>
                        <th style="padding:6px 8px;text-align:left;width:70px;">研发</th>
                        <th style="padding:6px 8px;text-align:center;width:60px;">状态</th>
                        <th style="padding:6px 8px;text-align:center;width:50px;">严重性</th>
                        <th style="padding:6px 8px;text-align:center;width:70px;">创建日期</th>
                    </tr>
                </thead>
                <tbody>{issue_rows}</tbody>
            </table>
            </div>
        </div>
        '''

    # 生成完整HTML（按新顺序：概览→智能建议→严重程度→模块饼图→每日折线图→研发→稳定性→待验证→AI分析→完整列表）
    now = datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')
    # 使用自定义标题或默认标题
    report_title = custom_title if custom_title else '📊 CR问题分析报告'
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report_title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        @page {{ size: A4; margin: 20mm 15mm; }}
        body {{
            font-family: -apple-system, "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
            padding: 40px;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            color: #1d1d1f;
        }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 12px; }}
        th {{ background: #1d1d1f; color: white; padding: 10px 12px; text-align: left; font-weight: 600; font-size: 12px; }}
        td {{ border: 1px solid #e5e5ea; padding: 8px 12px; }}
        .header {{ text-align: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #e5e5ea; }}
        .footer {{ text-align: center; font-size: 11px; color: #8e8e93; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e5ea; }}
        @media print {{ body {{ padding: 0; }} }}
    </style>
</head>
<body>
    {watermark_html}
    <div class="header">
        <h1 style="font-size:24px;font-weight:700;color:#1d1d1f;margin:0;">{report_title}</h1>
        <div style="font-size:13px;color:#6e6e73;margin-top:8px;">
            {f'文件: {file_name}' if file_name else ''} | 生成时间: {now}
        </div>
    </div>
    {overview_html}
    {suggestions_html}
    {sev_html}
    {module_html}
    {daily_html}
    {dev_html}
    {stability_html}
    {unverified_html}
    {ai_html}
    {issues_html}
    <div class="footer">
        📊 CR问题智能分析系统 — 自动生成报告
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            {module_chart_js}
            {daily_chart_js}
        }});
    </script>
</body>
</html>'''
# === 下载路由 ===


def _build_test_report_pdf_html(data, file_name, sheet_name, ai_analysis=''):
    """构建测试报告PDF的HTML — 高质感排版，内容与网页分析一致"""
    project_info = data.get('project_info', {})
    stats = data.get('stats', {})
    analysis = data.get('analysis', {})
    test_items = data.get('test_items', [])
    today = datetime.now(_CST).strftime('%Y-%m-%d')
    now_time = datetime.now(_CST).strftime('%Y-%m-%d %H:%M')

    # 水印文字
    watermark_text = f"Motorola {today}"

    # 水印HTML（平铺）
    watermark_items = []
    for x in range(0, 900, 220):
        for y in range(0, 1400, 160):
            watermark_items.append(
                f'<div style="position:absolute;left:{x}px;top:{y}px;transform:rotate(-30deg);'
                f'font-size:20px;font-weight:600;color:rgba(0,113,227,0.06);white-space:nowrap;'
                f'pointer-events:none;z-index:0;letter-spacing:2px;">{watermark_text}</div>'
            )
    watermark_html = '\n'.join(watermark_items)

    # ========== 项目信息 ==========
    info_rows = ''
    for k, v in project_info.items():
        if v and str(v).strip():
            info_rows += f'<div class="info-row"><div class="info-label">{k}</div><div class="info-val">{v}</div></div>'
    if not info_rows:
        info_rows = '<div class="info-row"><div class="info-val" style="color:#999;">无项目信息</div></div>'

    # ========== 统计数据（与网页一致） ==========
    total = stats.get('total', 0)
    pass_count = stats.get('pass', 0)
    fail_count = stats.get('fail', 0)
    blocked_count = stats.get('blocked', 0)
    delayed_count = stats.get('delayed', 0)
    unknown_count = stats.get('unknown', 0)
    executed_count = stats.get('executed', 0)
    pass_rate = stats.get('pass_rate', '0%')
    executed_pass_rate = stats.get('executed_pass_rate', '0%')
    overall_risk = analysis.get('overall_risk', '未知')
    severity = stats.get('severity', {})

    risk_color = {'高': '#dc2626', '中': '#f59e0b', '低': '#3b82f6', '无': '#10b981'}.get(overall_risk, '#6b7280')
    risk_bg = {'高': '#fef2f2', '中': '#fffbeb', '低': '#eff6ff', '无': '#ecfdf5'}.get(overall_risk, '#f9fafb')
    risk_icon = {'高': '🔴', '中': '🟡', '低': '🔵', '无': '🟢'}.get(overall_risk, '⚪')

    # 统计卡片
    stat_cards = f'''
        <div class="stat-card"><div class="num" style="color:#1e293b;">{total}</div><div class="lbl">总测试项</div></div>
        <div class="stat-card"><div class="num" style="color:#475569;">{executed_count}</div><div class="lbl">已执行</div></div>
        <div class="stat-card"><div class="num" style="color:#10b981;">{pass_count}</div><div class="lbl">通过</div></div>
        <div class="stat-card"><div class="num" style="color:#ef4444;">{fail_count}</div><div class="lbl">不通过</div></div>'''
    if blocked_count > 0:
        stat_cards += f'<div class="stat-card"><div class="num" style="color:#92400e;">{blocked_count}</div><div class="lbl">阻塞</div></div>'
    if delayed_count > 0:
        stat_cards += f'<div class="stat-card"><div class="num" style="color:#f59e0b;">{delayed_count}</div><div class="lbl">已延期</div></div>'
    if unknown_count > 0:
        stat_cards += f'<div class="stat-card"><div class="num" style="color:#6b7280;">{unknown_count}</div><div class="lbl">未识别</div></div>'
    stat_cards += f'<div class="stat-card highlight"><div class="num" style="color:#4f46e5;">{pass_rate}</div><div class="lbl">通过率</div></div>'
    if executed_count < total and executed_count > 0:
        stat_cards += f'<div class="stat-card highlight"><div class="num" style="color:#7c3aed;">{executed_pass_rate}</div><div class="lbl">已执行通过率</div></div>'

    # 严重级别统计
    severity_cards = ''
    sev_labels = {'blocker': 'Blocker', 'critical': 'Critical', 'major': 'Major', 'minor': 'Minor', 'trivial': 'Trivial'}
    sev_colors = {'blocker': '#991b1b', 'critical': '#dc2626', 'major': '#ea580c', 'minor': '#ca8a04', 'trivial': '#6b7280'}
    for level in ['blocker', 'critical', 'major', 'minor', 'trivial']:
        if severity.get(level):
            severity_cards += f'<div class="sev-tag" style="color:{sev_colors[level]};border-color:{sev_colors[level]}33;">{sev_labels[level]} <b>{severity[level]}</b></div>'

    # ========== 执行摘要 ==========
    exec_summary = analysis.get('executive_summary', '无摘要信息')

    # ========== 关键发现 ==========
    key_findings = analysis.get('key_findings', [])
    findings_html = ''
    if key_findings:
        for f in key_findings:
            f_cls = 'finding-normal'
            if '【高风险】' in f:
                f_cls = 'finding-high'
            elif '【中风险】' in f:
                f_cls = 'finding-medium'
            elif '【达标项】' in f:
                f_cls = 'finding-success'
            findings_html += f'<div class="finding-item {f_cls}">{f}</div>'
    else:
        findings_html = '<div style="color:#999;padding:8px 0;font-size:15px;">无关键发现</div>'

    # ========== 改进建议 ==========
    recommendations = analysis.get('recommendations', [])
    recs_html = ''
    if recommendations:
        for i, r in enumerate(recommendations, 1):
            recs_html += f'<div class="rec-item"><span class="rec-num">{i}</span><span class="rec-text">{r}</span></div>'
    else:
        recs_html = '<div style="color:#999;padding:8px 0;font-size:15px;">无改进建议</div>'

    # ========== 分类分析（含问题项） ==========
    sections = analysis.get('sections', [])
    sections_html = ''
    for s in sections:
        risk_cls = {'高': 'high', '中': 'medium', '低': 'low', '无': 'none'}.get(s.get('risk_level', ''), 'none')
        s_stats = f"通过率 {s.get('pass_rate', '')}"
        if s.get('fail', 0) > 0:
            s_stats += f" · 不通过 {s['fail']}"
        if s.get('delayed', 0) > 0:
            s_stats += f" · 延期 {s['delayed']}"
        if s.get('blocked', 0) > 0:
            s_stats += f" · 阻塞 {s['blocked']}"
        s_stats += f" · 共 {s.get('total', 0)} 项"

        # 问题项列表
        problem_items_html = ''
        problem_items = s.get('problem_items', [])
        if problem_items:
            problem_items_html = '<div class="problem-list">'
            for pi in problem_items:
                pi_result = pi.get('result', 'unknown')
                pi_labels = {'pass': '通过', 'fail': '不通过', 'blocked': '阻塞', 'delayed': '已延期', 'n_a': '不适用', 'unknown': '未识别'}
                pi_label = pi_labels.get(pi_result, pi_result)
                pi_name = pi.get('name', '')
                pi_reason = pi.get('reason', '')
                pi_target = pi.get('target', '') or '-'
                pi_actual = pi.get('actual', '') or '-'
                problem_items_html += f'''<div class="problem-item">
                    <span class="pdf-badge {pi_result}">{pi_label}</span>
                    <span class="problem-name">{pi_name}</span>
                    {f'<span class="problem-reason">{pi_reason}</span>' if pi_reason else ''}
                    <span class="problem-ta">目标: {pi_target} | 实测: {pi_actual}</span>
                </div>'''
            problem_items_html += '</div>'
        elif s.get('pass', 0) == s.get('total', 0) and s.get('total', 0) > 0:
            problem_items_html = '<div style="color:#10b981;font-size:14px;padding:6px 0;">✓ 全部通过</div>'

        sections_html += f'''
        <div class="section-block risk-{risk_cls}">
            <div class="section-header">
                <span class="risk-badge-pdf {risk_cls}">{s.get('risk_level', '')}</span>
                <span class="section-cat">{s.get('category', '')}</span>
                <span class="section-stats">{s_stats}</span>
            </div>
            <div class="section-summary">{s.get('summary', '')}</div>
            {problem_items_html}
        </div>'''

    if not sections_html:
        sections_html = '<div style="color:#999;padding:8px 0;font-size:15px;">无分类分析数据</div>'

    # ========== 测试项表格 ==========
    result_labels = {'pass': '通过', 'fail': '不通过', 'blocked': '阻塞', 'delayed': '已延期', 'n_a': '不适用', 'unknown': '未识别'}
    result_order = {'fail': 0, 'delayed': 1, 'blocked': 2, 'unknown': 3, 'n_a': 4, 'pass': 5}
    sev_order = {'blocker': 0, 'critical': 1, 'major': 2, 'minor': 3, 'trivial': 4}

    def _sort_key(item):
        r = result_order.get(item.get('result', ''), 3)
        return r

    sorted_items = sorted(test_items, key=_sort_key)

    rows_html = ''
    for idx, item in enumerate(sorted_items, 1):
        result_text = result_labels.get(item.get('result', ''), item.get('result_text', ''))
        result_cls = item.get('result', 'unknown')
        target = item.get('target', '') or '-'
        actual = item.get('actual', '') or '-'
        reason = item.get('reason', '') or '-'
        name = item.get('name', '')
        module = item.get('module', '') or '-'
        rows_html += f'''<tr>
            <td class="col-idx">{idx}</td>
            <td class="col-name">{name}</td>
            <td>{module}</td>
            <td><span class="pdf-badge {result_cls}">{result_text}</span></td>
            <td class="col-val">{target}</td>
            <td class="col-val">{actual}</td>
            <td class="col-reason">{reason}</td>
        </tr>'''

    # ========== AI 分析 ==========
    ai_html = ''
    if ai_analysis and ai_analysis.strip():
        # 将AI文本转换为HTML（保留段落和格式）
        ai_lines = ai_analysis.strip().split('\n')
        ai_formatted = ''
        for line in ai_lines:
            line = line.strip()
            if not line:
                continue
            # 标题行 (### 开头)
            if line.startswith('### '):
                title = line[4:].strip()
                ai_formatted += f'<div class="ai-sub-title">{title}</div>'
            elif line.startswith('## '):
                title = line[3:].strip()
                ai_formatted += f'<div class="ai-sub-title">{title}</div>'
            elif line.startswith('# '):
                title = line[2:].strip()
                ai_formatted += f'<div class="ai-sub-title">{title}</div>'
            # 列表项
            elif line.startswith('- ') or line.startswith('• '):
                ai_formatted += f'<div class="ai-list-item">{line[2:]}</div>'
            elif line.startswith('  - '):
                ai_formatted += f'<div class="ai-list-item sub">{line[4:]}</div>'
            else:
                ai_formatted += f'<div class="ai-paragraph">{line}</div>'
        ai_html = f'''
<div class="section">
    <div class="section-title ai-title">🤖 AI 深度分析</div>
    <div class="ai-content">{ai_formatted}</div>
</div>'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
@page {{ size: A4; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    color: #1e293b;
    font-size: 15px;
    line-height: 1.75;
    position: relative;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}
.watermark-layer {{
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    z-index: 0; pointer-events: none;
    overflow: hidden;
}}
.content {{ position: relative; z-index: 1; padding: 0; }}

/* ===== Cover Header ===== */
.report-header {{
    background: linear-gradient(135deg, #1e293b 0%, #334155 50%, #4f46e5 100%);
    color: white;
    padding: 36px 36px 28px;
    border-radius: 0 0 16px 16px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}}
.report-header::after {{
    content: '';
    position: absolute;
    right: -40px; top: -40px;
    width: 200px; height: 200px;
    background: rgba(255,255,255,0.05);
    border-radius: 50%;
}}
.report-header::before {{
    content: '';
    position: absolute;
    right: 40px; bottom: -60px;
    width: 120px; height: 120px;
    background: rgba(79, 70, 229, 0.15);
    border-radius: 50%;
}}
.report-header h1 {{
    font-size: 30px; font-weight: 800; margin-bottom: 8px;
    letter-spacing: 1px;
}}
.report-header .meta {{
    font-size: 15px; opacity: 0.85; display: flex; flex-wrap: wrap; gap: 16px;
}}
.report-header .meta span {{ display: inline-flex; align-items: center; gap: 4px; }}
.report-header .badge {{
    display: inline-block; background: rgba(255,255,255,0.15);
    padding: 5px 16px; border-radius: 20px; font-size: 14px;
    margin-top: 8px; backdrop-filter: blur(4px);
}}

/* ===== Section ===== */
.section {{
    margin-bottom: 22px;
    padding: 0 36px;
}}
.section-title {{
    font-size: 19px; font-weight: 700; margin-bottom: 12px;
    padding: 6px 0 6px 14px; border-left: 4px solid #4f46e5;
    color: #1e293b; letter-spacing: 0.5px;
    display: flex; align-items: center; gap: 6px;
}}

/* ===== Info Grid ===== */
.info-grid {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.info-row {{
    background: #f8fafc; border-radius: 8px; padding: 10px 16px;
    border-left: 3px solid #4f46e5; min-width: 180px; flex: 1;
}}
.info-label {{ font-size: 13px; color: #94a3b8; margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px; }}
.info-val {{ font-size: 16px; font-weight: 600; color: #1e293b; }}

/* ===== Stats Grid ===== */
.stats-grid {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.stat-card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 14px 18px; text-align: center; min-width: 88px; flex: 1;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}}
.stat-card.highlight {{
    border-color: #c7d2fe; background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%);
}}
.stat-card .num {{ font-size: 28px; font-weight: 800; line-height: 1.2; }}
.stat-card .lbl {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}

.severity-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
.sev-tag {{
    display: inline-block; padding: 5px 14px; border-radius: 6px;
    font-size: 14px; border: 1px solid; background: #fff;
}}

/* ===== Risk Banner ===== */
.risk-banner {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 20px; border-radius: 24px;
    font-size: 16px; font-weight: 700; margin-bottom: 12px;
    background: {risk_bg}; color: {risk_color}; border: 1px solid {risk_color}44;
}}

/* ===== Executive Summary ===== */
.exec-summary {{
    background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
    border-radius: 10px; padding: 16px 20px; line-height: 1.8;
    border: 1px solid #e2e8f0; font-size: 15px; color: #334155;
}}

/* ===== Findings ===== */
.finding-item {{
    padding: 8px 14px; line-height: 1.7; border-radius: 8px;
    margin-bottom: 6px; font-size: 15px;
    border-left: 3px solid #cbd5e1; background: #f8fafc;
}}
.finding-item.finding-high {{ border-left-color: #ef4444; background: #fef2f2; }}
.finding-item.finding-medium {{ border-left-color: #f59e0b; background: #fffbeb; }}
.finding-item.finding-success {{ border-left-color: #10b981; background: #ecfdf5; }}

/* ===== Recommendations ===== */
.rec-item {{
    display: flex; align-items: flex-start; gap: 10px;
    padding: 8px 0; line-height: 1.7; border-bottom: 1px solid #f1f5f9;
}}
.rec-item:last-child {{ border-bottom: none; }}
.rec-num {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 26px; border-radius: 50%;
    background: #4f46e5; color: white; font-size: 14px; font-weight: 700;
    flex-shrink: 0;
}}
.rec-text {{ font-size: 15px; color: #334155; flex: 1; }}

/* ===== Analysis Sections ===== */
.section-block {{
    border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px;
    margin-bottom: 10px; page-break-inside: auto;
}}
.section-block.risk-high {{ border-left: 4px solid #ef4444; }}
.section-block.risk-medium {{ border-left: 4px solid #f59e0b; }}
.section-block.risk-low {{ border-left: 4px solid #3b82f6; }}
.section-block.risk-none {{ border-left: 4px solid #10b981; }}
.section-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
.section-cat {{ font-weight: 700; font-size: 16px; color: #1e293b; }}
.section-stats {{ font-size: 14px; color: #94a3b8; margin-left: auto; }}
.section-summary {{ font-size: 14px; color: #64748b; line-height: 1.6; margin-bottom: 8px; }}
.risk-badge-pdf {{
    padding: 4px 14px; border-radius: 12px; font-size: 14px; font-weight: 700;
}}
.risk-badge-pdf.high {{ background: #fee2e2; color: #991b1b; }}
.risk-badge-pdf.medium {{ background: #fef3c7; color: #92400e; }}
.risk-badge-pdf.low {{ background: #dbeafe; color: #1e40af; }}
.risk-badge-pdf.none {{ background: #d1fae5; color: #065f46; }}

/* Problem items */
.problem-list {{ margin-top: 6px; }}
.problem-item {{
    display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap;
    padding: 5px 0; font-size: 14px; border-bottom: 1px dashed #f1f5f9;
}}
.problem-item:last-child {{ border-bottom: none; }}
.problem-name {{ font-weight: 600; color: #1e293b; }}
.problem-reason {{ color: #dc2626; font-size: 13px; }}
.problem-ta {{ color: #94a3b8; font-size: 13px; width: 100%; }}

/* ===== Table ===== */
.table-wrapper {{ overflow: hidden; border-radius: 10px; border: 1px solid #e2e8f0; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
thead th {{
    background: #1e293b; color: #fff; padding: 10px 8px; text-align: left;
    font-weight: 600; font-size: 13px; letter-spacing: 0.5px;
    text-transform: uppercase;
}}
tbody td {{
    padding: 8px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top;
    word-break: break-word;
}}
tbody tr:nth-child(even) {{ background: #f8fafc; }}
.col-idx {{ color: #94a3b8; font-size: 13px; width: 36px; text-align: center; }}
.col-name {{ font-weight: 600; min-width: 120px; }}
.col-val {{ font-size: 13px; color: #64748b; white-space: nowrap; }}
.col-reason {{ max-width: 280px; font-size: 13px; color: #64748b; }}
.pdf-badge {{
    display: inline-block; padding: 3px 12px; border-radius: 10px;
    font-size: 13px; font-weight: 600; white-space: nowrap;
}}
.pdf-badge.pass {{ background: #d1fae5; color: #065f46; }}
.pdf-badge.fail {{ background: #fee2e2; color: #991b1b; }}
.pdf-badge.blocked {{ background: #fef3c7; color: #92400e; }}
.pdf-badge.delayed {{ background: #ffedd5; color: #9a3412; }}
.pdf-badge.n_a {{ background: #f3f4f6; color: #6b7280; }}
.pdf-badge.unknown {{ background: #f3f4f6; color: #4b5563; }}

/* ===== AI Section ===== */
.ai-title {{ border-left-color: #7c3aed; color: #6d28d9; }}
.ai-content {{
    background: linear-gradient(135deg, #faf5ff 0%, #f5f3ff 100%);
    border-radius: 10px; padding: 18px 22px; border: 1px solid #e9d5ff;
}}
.ai-sub-title {{
    font-size: 16px; font-weight: 700; color: #6d28d9;
    margin-top: 12px; margin-bottom: 6px; padding-bottom: 4px;
    border-bottom: 1px solid #e9d5ff;
}}
.ai-sub-title:first-child {{ margin-top: 0; }}
.ai-paragraph {{ font-size: 15px; color: #334155; line-height: 1.8; margin-bottom: 4px; }}
.ai-list-item {{
    font-size: 15px; color: #334155; line-height: 1.7;
    padding-left: 18px; position: relative; margin-bottom: 2px;
}}
.ai-list-item::before {{
    content: '▸'; position: absolute; left: 0; color: #7c3aed; font-weight: 700;
}}
.ai-list-item.sub {{ padding-left: 36px; font-size: 14px; color: #64748b; }}
.ai-list-item.sub::before {{ content: '·'; color: #94a3b8; }}

/* ===== Footer ===== */
.report-footer {{
    margin-top: 24px; padding: 16px 36px;
    background: #1e293b; color: #94a3b8;
    text-align: center; font-size: 13px;
    border-radius: 16px 16px 0 0;
}}
.report-footer .conf {{
    color: #fbbf24; font-weight: 600; letter-spacing: 1px;
}}
</style>
</head>
<body>
<div class="watermark-layer">{watermark_html}</div>
<div class="content">

<div class="report-header">
    <h1>📋 测试报告分析</h1>
    <div class="meta">
        <span>📁 {file_name or '未命名'}</span>
        <span>📊 {sheet_name or '未指定'}</span>
        <span>📅 {now_time}</span>
    </div>
    <div class="badge">Motorola Confidential</div>
</div>

<div class="section">
    <div class="section-title">📌 项目信息</div>
    <div class="info-grid">{info_rows}</div>
</div>

<div class="section">
    <div class="section-title">📊 测试统计</div>
    <div class="stats-grid">{stat_cards}</div>
    {f'<div class="severity-row">{severity_cards}</div>' if severity_cards else ''}
</div>

<div class="section">
    <div class="section-title">📝 执行摘要</div>
    <div class="risk-banner">{risk_icon} 整体风险等级：{overall_risk}</div>
    <div class="exec-summary">{exec_summary}</div>
</div>

<div class="section">
    <div class="section-title">🔍 分类分析</div>
    {sections_html}
</div>

<div class="section">
    <div class="section-title">⚠️ 关键发现</div>
    {findings_html}
</div>

<div class="section">
    <div class="section-title">💡 改进建议</div>
    {recs_html}
</div>

{ai_html}

<div class="section">
    <div class="section-title">📋 逐项明细</div>
    <div class="table-wrapper">
    <table>
        <thead><tr>
            <th style="width:32px;">#</th><th>测试项</th><th>模块</th><th>结果</th><th>目标</th><th>实测</th><th>原因/备注</th>
        </tr></thead>
        <tbody>{rows_html if rows_html else '<tr><td colspan="7" style="text-align:center;color:#999;padding:20px;">无测试项数据</td></tr>'}</tbody>
    </table>
    </div>
</div>

<div class="report-footer">
    <div>本报告由 <b>测试报告分析工具</b> 自动生成</div>
    <div style="margin-top:4px;"><span class="conf">MOTOROLA CONFIDENTIAL</span> | {now_time}</div>
</div>

</div>
</body>
</html>'''

    return html


def _analyze_sheet_detail(file_path, sheet_name, return_debug=False, progress_cb=None):
    """分析单个Sheet的详细内容"""
    from app import ExcelReader  # 延迟导入避免循环引用
    import os as _os
    file_size = _os.path.getsize(file_path) if _os.path.exists(file_path) else 0
    use_fast = file_size > 10 * 1024 * 1024

    if use_fast:
        # 大文件用 pandas 快速读取（比 openpyxl 快5-10倍）
        import pandas as _pd
        if progress_cb:
            progress_cb(10, "正在读取Excel文件...")
        _df = _pd.read_excel(file_path, sheet_name=sheet_name, engine='openpyxl', dtype=str, na_filter=False, header=None)
        rows = _df.values.tolist()
        rows = [[str(c).strip() if c is not None else '' for c in row] for row in rows]
        del _df
        if progress_cb:
            progress_cb(25, f"读取完成，共 {len(rows)} 行，正在分析...")
    else:
        reader = ExcelReader(file_path)
        reader.open()
        rows = reader.get_sheet_data(sheet_name)
        reader.close()

    debug_info = {'sheet_name': sheet_name, 'total_rows': len(rows), 'first_10_rows': [], 'detected_headers': [], 'info_end_row': 0, 'data_rows_count': 0}

    if not rows:
        if return_debug:
            return {
                'file_basename': os.path.basename(file_path),
                'sheet_name': sheet_name,
                'project_info': {},
                'test_items': [],
                'stats': {'total': 0, 'pass': 0, 'fail': 0, 'pass_rate': '0%'},
                'analysis': {'executive_summary': '未找到测试项数据，请检查Excel文件格式是否正确。', 'overall_risk': '未知', 'key_findings': [], 'recommendations': [], 'sections': []},
                '_debug': debug_info
            }
        return {
            'file_basename': os.path.basename(file_path),
            'sheet_name': sheet_name,
            'project_info': {},
            'test_items': [],
            'stats': {'total': 0, 'pass': 0, 'fail': 0, 'pass_rate': '0%'}
        }

    # 记录前10行用于调试
    for r in rows[:10]:
        cells_preview = [str(c).strip() if c is not None else '' for c in r]
        non_empty_count = sum(1 for c in cells_preview if c)
        debug_info['first_10_rows'].append({'row': cells_preview[:8], 'non_empty': non_empty_count})

    # 1. 识别KV信息区
    project_info = {}
    info_end_row = 0
    result_keywords = ['pass', 'fail', '通过', '不通过', 'blocker', 'critical', 'major', 'minor', 'trivial']
    header_keywords = ['test item', 'test case', '测试项', '模块', 'module', 'component', 'commponent', 'severity', '结果', 'result', 'status', '状态', 'name', '名称', 'category', '分类', 'risk', '风险', 'cwv', 'target', '目标', 'key issue', 'comment', '备注', '指标', '测试内容']

    for row_idx, row in enumerate(rows):
        cells = [str(c).strip() if c is not None else '' for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            info_end_row = row_idx + 1
            continue

        # 检查是否是表头行（至少匹配2个不同的表头关键词，避免KV行被误判）
        row_text = ' '.join(cells).lower()
        matched_kws = set()
        for kw in header_keywords:
            if kw in row_text:
                matched_kws.add(kw)
        is_header_row = len(non_empty) >= 3 and len(matched_kws) >= 2
        
        if is_header_row:
            info_end_row = row_idx
            break

        is_kv_row = False
        kv_pairs = []

        for cell_idx, cell_val in enumerate(cells):
            if not cell_val:
                continue

            if ':' in cell_val or '：' in cell_val:
                parts = cell_val.replace('：', ':').split(':', 1)
                label = parts[0].strip()
                value = parts[1].strip()
                if label and value and not any(kw in value.lower() for kw in result_keywords):
                    kv_pairs.append({'label': label, 'value': value})
                    is_kv_row = True

            elif cell_idx + 1 < len(cells) and cells[cell_idx + 1]:
                right_val = cells[cell_idx + 1].strip()
                if (len(cell_val) <= 20 and
                    not any(kw in cell_val.lower() for kw in result_keywords) and
                    not any(kw in right_val.lower() for kw in result_keywords)):
                    kv_pairs.append({'label': cell_val, 'value': right_val})
                    is_kv_row = True
                    break

        if is_kv_row and kv_pairs:
            for pair in kv_pairs:
                project_info[pair['label']] = pair['value']
            info_end_row = row_idx + 1
        elif non_empty and not is_kv_row:
            if len(non_empty) >= 2:
                break
            info_end_row = row_idx + 1

    # 2. 识别表格区域
    test_items = []
    headers = []
    data_rows = []
    table_header_keywords = ['结果', 'result', 'pass', 'fail', '通过', '不通过', '测试项', '测试内容', '测试用例', 'test item', 'test case', 'module', '模块', '组件', 'severity', '严重程度', '严重性', '等级', 'status', '状态', 'name', '名称', '指标', 'remark', '备注', '说明', '原因', 'reason', '目标', 'target', '实测', 'actual', '问题', 'issue', 'category', '分类', '类型']

    for row_idx in range(info_end_row, len(rows)):
        row = rows[row_idx]
        cells = [str(c).strip() if c is not None else '' for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            if headers:
                break
            continue

        if not headers and len(non_empty) >= 2:
            row_text = ' '.join(cells).lower()
            matched_kws = set()
            for kw in table_header_keywords:
                if kw in row_text:
                    matched_kws.add(kw)
            # 宽松匹配：2个非空+1个关键词，或3个非空+2个关键词
            if (len(non_empty) >= 3 and len(matched_kws) >= 2) or (len(non_empty) >= 2 and len(matched_kws) >= 1):
                headers = cells
                continue

        if headers and len(non_empty) >= 1:
            data_rows.append({'cells': cells, 'row_idx': row_idx})

    # 回退：如果严格匹配没找到表头，尝试找第一个含"结果"或"result"的行
    if not headers:
        for row_idx in range(info_end_row, len(rows)):
            row = rows[row_idx]
            cells = [str(c).strip() if c is not None else '' for c in row]
            non_empty = [c for c in cells if c]
            if not non_empty:
                continue
            row_text = ' '.join(cells).lower()
            if '结果' in row_text or 'result' in row_text or 'pass' in row_text or 'pass/fail' in row_text or '状态' in row_text or 'status' in row_text:
                headers = cells
                # 收集后续数据行
                for dr_idx in range(row_idx + 1, len(rows)):
                    dr = rows[dr_idx]
                    dr_cells = [str(c).strip() if c is not None else '' for c in dr]
                    dr_non_empty = [c for c in dr_cells if c]
                    if not dr_non_empty:
                        break
                    data_rows.append({'cells': dr_cells, 'row_idx': dr_idx})
                break

    # 最终回退：如果仍没找到表头，把所有非空行当数据，用第一行做表头
    if not headers and len(rows) > info_end_row:
        for row_idx in range(info_end_row, len(rows)):
            row = rows[row_idx]
            cells = [str(c).strip() if c is not None else '' for c in row]
            non_empty = [c for c in cells if c]
            if len(non_empty) >= 2:
                headers = cells
                for dr_idx in range(row_idx + 1, len(rows)):
                    dr = rows[dr_idx]
                    dr_cells = [str(c).strip() if c is not None else '' for c in dr]
                    dr_non_empty = [c for c in dr_cells if c]
                    if dr_non_empty:
                        data_rows.append({'cells': dr_cells, 'row_idx': dr_idx})
                break

    # 3. 检测列索引
    col_indices = _detect_column_indices(headers)

    # 记录调试信息
    debug_info['detected_headers'] = headers
    debug_info['info_end_row'] = info_end_row
    debug_info['data_rows_count'] = len(data_rows)
    debug_info['col_indices'] = col_indices

    # 4. 解析测试项
    for data_row in data_rows:
        cells = data_row['cells']
        row_idx = data_row['row_idx']

        name = _get_cell_value(cells, col_indices.get('name', -1))
        module = _get_cell_value(cells, col_indices.get('module', -1))
        severity = _get_cell_value(cells, col_indices.get('severity', -1))
        result_raw = _get_cell_value(cells, col_indices.get('result', -1))
        reason = _get_cell_value(cells, col_indices.get('reason', -1))
        key_issue = _get_cell_value(cells, col_indices.get('key_issue', -1)) if 'key_issue' in col_indices else ''
        comment = _get_cell_value(cells, col_indices.get('comment', -1)) if 'comment' in col_indices else ''

        # 尝试提取目标值和实测值
        target_val = _get_cell_value(cells, col_indices.get('target', -1)) if 'target' in col_indices else ''
        actual_val = _get_cell_value(cells, col_indices.get('actual', -1)) if 'actual' in col_indices else ''

        # 跳过没有名称的行（空行、子标题行）
        if not name or not name.strip():
            continue

        # 跳过明显不是测试项的行（纯数字、纯符号、太短）
        name_stripped = name.strip()
        if len(name_stripped) < 2 or name_stripped in ['-', '/', 'N/A', 'NA']:
            continue

        # 智能判断结果状态
        # 优先级1: 直接从 result 列文本判断
        result_text = result_raw.strip() if result_raw else ''
        result_class = _classify_result(result_text)

        # 优先级2: 如果 result 列无法识别，尝试用 CWV/actual 和 target 比较
        if result_class == 'unknown' and actual_val and target_val:
            result_class, result_text = _compare_target_actual(target_val, actual_val)

        # 优先级3: 如果 result 列和 actual 列都无法识别，检查 actual_val 是否是 Pass/Fail 文本
        if result_class == 'unknown' and actual_val:
            actual_class = _classify_result(actual_val.strip())
            if actual_class != 'unknown':
                result_class = actual_class
                result_text = actual_val.strip()

        # 如果 actual_val 为空但 result_raw 有值，用 result_raw 作为 actual
        if not actual_val and result_raw:
            actual_val = result_raw

        # 合并 key_issue + comment + reason 为完整备注
        raw_notes_parts = []
        if key_issue and key_issue.strip():
            raw_notes_parts.append(key_issue.strip())
        if comment and comment.strip():
            raw_notes_parts.append(comment.strip())
        if reason and reason.strip():
            raw_notes_parts.append(reason.strip())
        raw_notes = '\n'.join(raw_notes_parts)

        # 从备注中提取待办事项
        action_items = _extract_action_items(raw_notes)
        # 只保留待办事项，不显示原始备注
        if action_items:
            notes_display = '\n'.join(action_items)
        else:
            notes_display = ''

        test_item = {
            'name': name or f'测试项{row_idx + 1}',
            'module': module,
            'severity': severity,
            'result': result_class,
            'result_text': result_text if result_text else result_class,
            'reason': notes_display,
            'action_items': action_items,
            'target': target_val,
            'actual': actual_val,
            'row_index': row_idx + 1
        }
        test_items.append(test_item)

    # 5. 统计
    total = len(test_items)
    pass_count = sum(1 for item in test_items if item['result'] == 'pass')
    fail_count = sum(1 for item in test_items if item['result'] == 'fail')
    blocked_count = sum(1 for item in test_items if item['result'] == 'blocked')
    delayed_count = sum(1 for item in test_items if item['result'] == 'delayed')
    na_count = sum(1 for item in test_items if item['result'] == 'n_a')
    unknown_count = sum(1 for item in test_items if item['result'] == 'unknown')

    # 已执行项 = 总数 - 延期 - 阻塞 - N/A - 未知
    executed_count = total - delayed_count - blocked_count - na_count - unknown_count
    pass_rate = f"{(pass_count / total * 100):.1f}%" if total > 0 else "0%"
    executed_pass_rate = f"{(pass_count / executed_count * 100):.1f}%" if executed_count > 0 else "0%"

    severity_stats = {}
    for item in test_items:
        sev = item.get('severity', '').strip()
        if sev:
            matched = _match_severity_level(sev)
            if matched:
                severity_stats[matched] = severity_stats.get(matched, 0) + 1

    # 6. 生成智能分析报告
    analysis = _generate_intelligent_analysis(test_items, project_info, {
        'total': total,
        'pass': pass_count,
        'fail': fail_count,
        'blocked': blocked_count,
        'delayed': delayed_count,
        'n_a': na_count,
        'unknown': unknown_count,
        'executed': executed_count,
        'pass_rate': pass_rate,
        'executed_pass_rate': executed_pass_rate
    })

    result = {
        'file_basename': os.path.splitext(os.path.basename(file_path))[0],
        'sheet_name': sheet_name,
        'project_info': project_info,
        'test_items': test_items,
        'stats': {
            'total': total,
            'pass': pass_count,
            'fail': fail_count,
            'blocked': blocked_count,
            'delayed': delayed_count,
            'n_a': na_count,
            'unknown': unknown_count,
            'executed': executed_count,
            'pass_rate': pass_rate,
            'executed_pass_rate': executed_pass_rate,
            'severity': severity_stats
        },
        'analysis': analysis
    }
    if return_debug:
        result['_debug'] = debug_info
    return result

