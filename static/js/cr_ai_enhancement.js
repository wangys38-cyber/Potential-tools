/**
 * v8.0 CR AI 增强功能
 * 趋势预测、智能归因、改进建议
 */
(function() {
    'use strict';

    // ==================== 工具函数 ====================
    function getAnalysisData() {
        // currentAnalysisData 是用 let 声明的全局变量，不在 window 上
        if (typeof currentAnalysisData !== 'undefined' && currentAnalysisData) return currentAnalysisData;
        if (window.currentAnalysisData) return window.currentAnalysisData;
        if (window.analysisData) return window.analysisData;
        if (window.crAnalysisData) return window.crAnalysisData;
        return null;
    }

    function getIssues() {
        const data = getAnalysisData();
        if (!data) return [];
        return data.all_issues || data.issues || data.allIssues || data.rows || data.bugs || [];
    }

    function getDailyData() {
        const data = getAnalysisData();
        if (!data) return [];
        return data.daily_trend || data.dailyTrend || data.daily_data || [];
    }

    function showLoading(elementId, text) {
        const el = document.getElementById(elementId);
        if (el) {
            el.innerHTML = '<div style="text-align:center;padding:40px;color:#86868b;"><div style="display:inline-block;width:24px;height:24px;border:3px solid #e5e5ea;border-top-color:#1d1d1f;border-radius:50%;animation:spin 0.8s linear infinite;"></div><div style="margin-top:12px;font-size:13px;">' + (text || '分析中...') + '</div></div>';
        }
    }

    function showError(elementId, message) {
        const el = document.getElementById(elementId);
        if (el) {
            el.innerHTML = '<div style="text-align:center;padding:30px;color:#ff3b30;font-size:13px;">❌ ' + message + '</div>';
        }
    }

    // ==================== 趋势预测 ====================
    window.loadBugPrediction = function() {
        const section = document.getElementById('bugPredictionSection');
        if (!section) return;

        const dailyData = getDailyData();
        if (!dailyData || dailyData.length < 3) {
            section.innerHTML = '<div style="text-align:center;padding:40px;color:#86868b;font-size:13px;">📊 趋势预测需要至少 3 天的历史数据<br><span style="font-size:12px;">请先上传包含日期字段的 CR 数据</span></div>';
            return;
        }

        showLoading('bugPredictionSection', 'AI 正在预测未来趋势...');

        fetch('/api/cr/ai/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ daily_data: dailyData, days_ahead: 7 })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                renderPrediction(data);
            } else {
                showError('bugPredictionSection', data.error || '预测失败');
            }
        })
        .catch(err => {
            showError('bugPredictionSection', '请求失败: ' + err.message);
        });
    };

    function renderPrediction(data) {
        const section = document.getElementById('bugPredictionSection');
        if (!section) return;

        const preds = data.predictions || [];
        const hist = data.historical || {};

        let html = '';

        // 概览卡片
        html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px;">';
        html += '<div style="background:var(--ds-bg-elevated);padding:16px;border-radius:12px;border:1px solid var(--ds-border-light);">';
        html += '<div style="font-size:12px;color:var(--ds-text-tertiary);margin-bottom:4px;">当前趋势</div>';
        html += '<div style="font-size:20px;font-weight:600;color:var(--ds-text);">' + (data.trend_icon || '') + ' ' + (data.trend || '-') + '</div>';
        html += '</div>';
        html += '<div style="background:var(--ds-bg-elevated);padding:16px;border-radius:12px;border:1px solid var(--ds-border-light);">';
        html += '<div style="font-size:12px;color:var(--ds-text-tertiary);margin-bottom:4px;">日均新增</div>';
        html += '<div style="font-size:20px;font-weight:600;color:var(--ds-text);">' + (data.avg_daily_new || 0) + '</div>';
        html += '</div>';
        html += '<div style="background:var(--ds-bg-elevated);padding:16px;border-radius:12px;border:1px solid var(--ds-border-light);">';
        html += '<div style="font-size:12px;color:var(--ds-text-tertiary);margin-bottom:4px;">未来7天预计新增</div>';
        html += '<div style="font-size:20px;font-weight:600;color:var(--ds-text);">' + (data.total_predicted_new || 0) + '</div>';
        html += '</div>';
        html += '<div style="background:var(--ds-bg-elevated);padding:16px;border-radius:12px;border:1px solid var(--ds-border-light);">';
        html += '<div style="font-size:12px;color:var(--ds-text-tertiary);margin-bottom:4px;">预测置信度</div>';
        html += '<div style="font-size:20px;font-weight:600;color:var(--ds-text);">' + (data.confidence || 0) + '%</div>';
        html += '</div>';
        html += '</div>';

        // 预测表格
        html += '<div style="background:var(--ds-bg-elevated);border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid var(--ds-border-light);">';
        html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 12px;color:var(--ds-text);">📅 未来 7 天预测明细</h4>';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:var(--ds-bg-secondary);">';
        html += '<th style="padding:8px 12px;text-align:left;color:var(--ds-text-secondary);font-weight:500;">日期</th>';
        html += '<th style="padding:8px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">预计新增</th>';
        html += '<th style="padding:8px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">预测区间</th>';
        html += '<th style="padding:8px 12px;text-align:center;color:var(--ds-text-secondary);font-weight:500;">预计累计</th>';
        html += '</tr></thead><tbody>';
        preds.forEach(p => {
            html += '<tr style="border-bottom:1px solid var(--ds-border-light);">';
            html += '<td style="padding:8px 12px;color:var(--ds-text);">' + p.date + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;color:var(--ds-text);font-weight:500;">' + p.predicted_new + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;color:var(--ds-text-tertiary);font-size:12px;">' + p.lower_bound + ' ~ ' + p.upper_bound + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;color:var(--ds-text);">' + p.predicted_cumulative + '</td>';
            html += '</tr>';
        });
        html += '</tbody></table>';
        html += '</div>';

        // AI 解释
        if (data.explanation) {
            html += '<div style="background:var(--ds-bg-elevated);border-radius:12px;padding:20px;border:1px solid var(--ds-border-light);">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 12px;color:var(--ds-text);">💡 AI 分析与建议</h4>';
            html += '<div style="font-size:13px;line-height:1.7;color:var(--ds-text-secondary);white-space:pre-wrap;">' + data.explanation + '</div>';
            html += '</div>';
        }

        section.innerHTML = html;
    }

    // ==================== 增强 AI 分析 ====================
    window.runEnhancedAIAnalysis = function() {
        const issues = getIssues();
        if (!issues || issues.length === 0) {
            alert('没有可分析的问题数据，请先完成 CR 分析');
            return;
        }

        const btn = document.getElementById('enhancedAIBtn');
        if (btn) { btn.disabled = true; btn.textContent = '分析中...'; }

        const content = document.getElementById('enhancedAIContent');
        if (content) showLoading('enhancedAIContent', 'AI 正在进行深度归因分析...');

        fetch('/api/cr/ai/enhanced-root-cause', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ issues: issues })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                renderEnhancedAnalysis(data);
            } else {
                showError('enhancedAIContent', data.error || '分析失败');
            }
        })
        .catch(err => {
            showError('enhancedAIContent', '请求失败: ' + err.message);
        })
        .finally(() => {
            if (btn) { btn.disabled = false; btn.textContent = '🔄 重新分析'; }
        });
    };

    function renderEnhancedAnalysis(data) {
        const content = document.getElementById('enhancedAIContent');
        if (!content) return;

        const ai = data.ai_analysis || {};
        const modules = data.module_stats || [];

        let html = '';

        // 概览
        html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">';
        html += '<div style="background:var(--ds-bg-secondary);padding:12px;border-radius:8px;text-align:center;">';
        html += '<div style="font-size:11px;color:var(--ds-text-tertiary);">总 Bug 数</div>';
        html += '<div style="font-size:18px;font-weight:600;color:var(--ds-text);">' + data.total_issues + '</div></div>';
        html += '<div style="background:var(--ds-bg-secondary);padding:12px;border-radius:8px;text-align:center;">';
        html += '<div style="font-size:11px;color:var(--ds-text-tertiary);">未解决</div>';
        html += '<div style="font-size:18px;font-weight:600;color:#ff9500;">' + data.unresolved_count + '</div></div>';
        html += '<div style="background:var(--ds-bg-secondary);padding:12px;border-radius:8px;text-align:center;">';
        html += '<div style="font-size:11px;color:var(--ds-text-tertiary);">高风险模块</div>';
        html += '<div style="font-size:18px;font-weight:600;color:#ff3b30;">' + Math.min(modules.length, 5) + '</div></div>';
        html += '</div>';

        // AI 根因
        if (ai.root_causes && ai.root_causes.length > 0) {
            html += '<div style="margin-bottom:20px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--ds-text);">🎯 主要根因（按优先级）</h4>';
            ai.root_causes.forEach((cause, idx) => {
                const severityColor = cause.severity === 'high' ? '#ff3b30' : cause.severity === 'medium' ? '#ff9500' : '#34c759';
                html += '<div style="background:var(--ds-bg-secondary);padding:12px 16px;border-radius:8px;margin-bottom:8px;border-left:3px solid ' + severityColor + ';">';
                html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">';
                html += '<span style="background:' + severityColor + ';color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">P' + (idx + 1) + '</span>';
                html += '<span style="font-weight:600;color:var(--ds-text);font-size:13px;">' + cause.cause + '</span>';
                html += '</div>';
                if (cause.affected_modules) html += '<div style="font-size:12px;color:var(--ds-text-tertiary);margin-bottom:4px;">影响模块: ' + cause.affected_modules.join(', ') + '</div>';
                if (cause.evidence) html += '<div style="font-size:12px;color:var(--ds-text-secondary);">📊 ' + cause.evidence + '</div>';
                html += '</div>';
            });
            html += '</div>';
        }

        // 关键发现
        if (ai.key_findings && ai.key_findings.length > 0) {
            html += '<div style="margin-bottom:20px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--ds-text);">🔍 关键发现</h4>';
            html += '<ul style="margin:0;padding-left:20px;font-size:13px;color:var(--ds-text-secondary);line-height:1.8;">';
            ai.key_findings.forEach(f => { html += '<li>' + f + '</li>'; });
            html += '</ul></div>';
        }

        // 高风险模块
        if (modules.length > 0) {
            html += '<div>';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--ds-text);">⚠️ 模块风险排名 TOP 5</h4>';
            html += '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
            html += '<thead><tr style="background:var(--ds-bg-secondary);">';
            html += '<th style="padding:6px 10px;text-align:left;color:var(--ds-text-secondary);">模块</th>';
            html += '<th style="padding:6px 10px;text-align:center;color:var(--ds-text-secondary);">总数</th>';
            html += '<th style="padding:6px 10px;text-align:center;color:var(--ds-text-secondary);">未解决</th>';
            html += '<th style="padding:6px 10px;text-align:center;color:var(--ds-text-secondary);">致命/严重</th>';
            html += '<th style="padding:6px 10px;text-align:center;color:var(--ds-text-secondary);">风险分</th>';
            html += '</tr></thead><tbody>';
            modules.slice(0, 5).forEach(m => {
                html += '<tr style="border-bottom:1px solid var(--ds-border-light);">';
                html += '<td style="padding:6px 10px;color:var(--ds-text);font-weight:500;">' + m.module + '</td>';
                html += '<td style="padding:6px 10px;text-align:center;color:var(--ds-text);">' + m.total + '</td>';
                html += '<td style="padding:6px 10px;text-align:center;color:#ff9500;">' + m.unresolved + '</td>';
                html += '<td style="padding:6px 10px;text-align:center;color:#ff3b30;">' + (m.critical + m.high) + '</td>';
                html += '<td style="padding:6px 10px;text-align:center;font-weight:600;color:var(--ds-text);">' + m.risk_score + '</td>';
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        }

        // 改进计划按钮
        html += '<div style="margin-top:16px;text-align:center;">';
        html += '<button class="btn btn-primary" onclick="generateImprovementPlan()" style="padding:10px 24px;font-size:13px;">📋 生成系统性改进计划</button>';
        html += '</div>';

        content.innerHTML = html;
    }

    // ==================== 改进计划 ====================
    window.generateImprovementPlan = function() {
        const issues = getIssues();
        if (!issues || issues.length === 0) {
            alert('没有可分析的问题数据');
            return;
        }

        const content = document.getElementById('enhancedAIContent');
        if (content) showLoading('enhancedAIContent', 'AI 正在制定改进计划...');

        fetch('/api/cr/ai/improvement-plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ issues: issues })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                renderImprovementPlan(data.plan);
            } else {
                showError('enhancedAIContent', data.error || '生成失败');
            }
        })
        .catch(err => {
            showError('enhancedAIContent', '请求失败: ' + err.message);
        });
    };

    function renderImprovementPlan(plan) {
        const content = document.getElementById('enhancedAIContent');
        if (!content) return;

        let html = '';

        // 优先改进模块
        if (plan.priority_modules && plan.priority_modules.length > 0) {
            html += '<div style="background:#fff3cd;padding:12px 16px;border-radius:8px;margin-bottom:16px;border:1px solid #ffeaa7;">';
            html += '<span style="font-size:13px;color:#856404;">🎯 优先改进模块: <strong>' + plan.priority_modules.join('、') + '</strong></span>';
            html += '</div>';
        }

        // 短期
        if (plan.short_term && plan.short_term.length > 0) {
            html += '<div style="margin-bottom:16px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--ds-text);">⚡ 短期行动（1周内）</h4>';
            plan.short_term.forEach((item, idx) => {
                html += '<div style="background:var(--ds-bg-secondary);padding:10px 14px;border-radius:8px;margin-bottom:6px;">';
                html += '<div style="font-weight:500;color:var(--ds-text);font-size:13px;margin-bottom:2px;">' + (idx + 1) + '. ' + item.action + '</div>';
                html += '<div style="font-size:12px;color:var(--ds-text-tertiary);">目标: ' + item.target + ' | 预期: ' + item.expected_impact + '</div>';
                html += '</div>';
            });
            html += '</div>';
        }

        // 中期
        if (plan.medium_term && plan.medium_term.length > 0) {
            html += '<div style="margin-bottom:16px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--ds-text);">🔧 中期改进（1个月内）</h4>';
            plan.medium_term.forEach((item, idx) => {
                html += '<div style="background:var(--ds-bg-secondary);padding:10px 14px;border-radius:8px;margin-bottom:6px;">';
                html += '<div style="font-weight:500;color:var(--ds-text);font-size:13px;margin-bottom:2px;">' + (idx + 1) + '. ' + item.action + '</div>';
                html += '<div style="font-size:12px;color:var(--ds-text-tertiary);">目标: ' + item.target + ' | 预期: ' + item.expected_impact + '</div>';
                html += '</div>';
            });
            html += '</div>';
        }

        // 长期
        if (plan.long_term && plan.long_term.length > 0) {
            html += '<div style="margin-bottom:16px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--ds-text);">🏗️ 长期建设（本季度）</h4>';
            plan.long_term.forEach((item, idx) => {
                html += '<div style="background:var(--ds-bg-secondary);padding:10px 14px;border-radius:8px;margin-bottom:6px;">';
                html += '<div style="font-weight:500;color:var(--ds-text);font-size:13px;margin-bottom:2px;">' + (idx + 1) + '. ' + item.action + '</div>';
                html += '<div style="font-size:12px;color:var(--ds-text-tertiary);">目标: ' + item.target + ' | 预期: ' + item.expected_impact + '</div>';
                html += '</div>';
            });
            html += '</div>';
        }

        // KPI 目标
        if (plan.kpi_targets) {
            html += '<div style="background:var(--ds-bg-elevated);padding:14px;border-radius:8px;border:1px solid var(--ds-border-light);">';
            html += '<h4 style="font-size:13px;font-weight:600;margin:0 0 8px;color:var(--ds-text);">📈 KPI 目标</h4>';
            html += '<div style="font-size:12px;color:var(--ds-text-secondary);line-height:1.8;">';
            if (plan.kpi_targets.bug_reduction_rate) html += '• Bug 降低率目标: <strong>' + plan.kpi_targets.bug_reduction_rate + '</strong><br>';
            if (plan.kpi_targets.mttr_improvement) html += '• 平均修复时间改善: <strong>' + plan.kpi_targets.mttr_improvement + '</strong>';
            html += '</div></div>';
        }

        content.innerHTML = html;
    }

    // ==================== 一键全量分析 ====================
    window.runFullAIAnalysis = function() {
        const issues = getIssues();
        const dailyData = getDailyData();

        if (!issues || issues.length === 0) {
            alert('没有可分析的问题数据，请先完成 CR 分析');
            return;
        }

        const content = document.getElementById('enhancedAIContent');
        if (content) showLoading('enhancedAIContent', 'AI 正在执行全量分析（归因+预测+建议），请稍候...');

        fetch('/api/cr/ai/full-analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ issues: issues, daily_data: dailyData })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                renderFullAnalysis(data);
            } else {
                showError('enhancedAIContent', data.error || '分析失败');
            }
        })
        .catch(err => {
            showError('enhancedAIContent', '请求失败: ' + err.message);
        });
    };

    function renderFullAnalysis(data) {
        const content = document.getElementById('enhancedAIContent');
        if (!content) return;

        let html = '<div style="margin-bottom:16px;padding:10px 14px;background:#e8f5e9;border-radius:8px;font-size:12px;color:#2e7d32;">✅ 全量分析完成，耗时 ' + (data.latency_ms / 1000).toFixed(1) + ' 秒</div>';

        // 归因分析摘要
        const rc = data.root_cause || {};
        if (rc.ai_analysis) {
            html += '<div style="margin-bottom:16px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 8px;color:var(--ds-text);">🎯 根因分析摘要</h4>';
            if (rc.ai_analysis.risk_assessment) html += '<div style="font-size:13px;color:var(--ds-text-secondary);margin-bottom:8px;padding:8px 12px;background:var(--ds-bg-secondary);border-radius:6px;">' + rc.ai_analysis.risk_assessment + '</div>';
            if (rc.ai_analysis.key_findings) {
                html += '<ul style="margin:0;padding-left:20px;font-size:12px;color:var(--ds-text-secondary);line-height:1.7;">';
                rc.ai_analysis.key_findings.slice(0, 3).forEach(f => { html += '<li>' + f + '</li>'; });
                html += '</ul>';
            }
            html += '</div>';
        }

        // 趋势预测摘要
        const pred = data.prediction || {};
        if (pred.status === 'success') {
            html += '<div style="margin-bottom:16px;">';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 8px;color:var(--ds-text);">📈 趋势预测摘要</h4>';
            html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">';
            html += '<div style="background:var(--ds-bg-secondary);padding:10px;border-radius:6px;text-align:center;">';
            html += '<div style="font-size:11px;color:var(--ds-text-tertiary);">趋势</div>';
            html += '<div style="font-size:16px;font-weight:600;color:var(--ds-text);">' + (pred.trend_icon || '') + ' ' + (pred.trend || '-') + '</div></div>';
            html += '<div style="background:var(--ds-bg-secondary);padding:10px;border-radius:6px;text-align:center;">';
            html += '<div style="font-size:11px;color:var(--ds-text-tertiary);">未来7天新增</div>';
            html += '<div style="font-size:16px;font-weight:600;color:var(--ds-text);">' + (pred.total_predicted_new || 0) + '</div></div>';
            html += '<div style="background:var(--ds-bg-secondary);padding:10px;border-radius:6px;text-align:center;">';
            html += '<div style="font-size:11px;color:var(--ds-text-tertiary);">置信度</div>';
            html += '<div style="font-size:16px;font-weight:600;color:var(--ds-text);">' + (pred.confidence || 0) + '%</div></div>';
            html += '</div></div>';
        }

        // 改进计划摘要
        const imp = data.improvement?.plan || {};
        if (imp.short_term) {
            html += '<div>';
            html += '<h4 style="font-size:14px;font-weight:600;margin:0 0 8px;color:var(--ds-text);">📋 改进计划摘要</h4>';
            html += '<ul style="margin:0;padding-left:20px;font-size:12px;color:var(--ds-text-secondary);line-height:1.7;">';
            imp.short_term.slice(0, 3).forEach(item => { html += '<li><strong>' + item.action + '</strong> - ' + item.expected_impact + '</li>'; });
            html += '</ul></div>';
        }

        // 查看详情按钮
        html += '<div style="margin-top:16px;display:flex;gap:10px;justify-content:center;">';
        html += '<button class="btn btn-secondary" onclick="runEnhancedAIAnalysis()" style="padding:8px 16px;font-size:12px;">查看详细归因</button>';
        html += '<button class="btn btn-secondary" onclick="loadBugPrediction();switchTab(\'prediction\')" style="padding:8px 16px;font-size:12px;">查看详细预测</button>';
        html += '</div>';

        content.innerHTML = html;
    }

    // ==================== 自动加载 ====================
    // 当切换到趋势预测标签时自动加载
    document.addEventListener('DOMContentLoaded', function() {
        // 监听标签切换
        const originalSwitchTab = window.switchTab;
        if (originalSwitchTab) {
            window.switchTab = function(tab) {
                originalSwitchTab(tab);
                if (tab === 'prediction') {
                    setTimeout(loadBugPrediction, 100);
                }
            };
        }
    });

})();
