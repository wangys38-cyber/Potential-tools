/**
 * Potential-tools v6.0 - 跨工具数据流转管道
 * 负责工具间的数据传递、同步和联动
 *
 * 数据流方向:
 * - CR分析 → 修复计划 → 计划生成器
 * - 日志分析 → Bug趋势看板
 * - 站会阻塞 → Dashboard风险卡片
 * - 会议纪要待办 → 计划节点
 * - 周报数据 ← 站会/CR/日志汇总
 */
(function() {
    'use strict';

    const PIPELINE_PREFIX = (window._USER_PREFIX || '') + 'pipeline_';
    const STORAGE_KEYS = {
        CR_TO_PLAN: 'cr_to_plan',
        LOG_TO_BUG: 'log_to_bug',
        STANDUP_TO_DASHBOARD: 'standup_to_dashboard',
        MEETING_TO_PLAN: 'meeting-minutes_to_plan',
        WEEKLY_SOURCES: 'weekly_sources'
    };

    /**
     * 存储流转数据
     */
    function setData(key, data) {
        try {
            const fullKey = PIPELINE_PREFIX + key;
            const payload = {
                data: data,
                timestamp: Date.now(),
                source: window.location.pathname
            };
            localStorage.setItem(fullKey, JSON.stringify(payload));
            // 触发自定义事件，通知其他页面
            window.dispatchEvent(new CustomEvent('pipeline-data-updated', {
                detail: { key: key, data: data }
            }));
            return true;
        } catch(e) {
            console.warn('Pipeline setData failed:', e);
            return false;
        }
    }

    /**
     * 获取流转数据（一次性消费）
     */
    function getData(key, consume) {
        try {
            const fullKey = PIPELINE_PREFIX + key;
            const raw = localStorage.getItem(fullKey);
            if (!raw) return null;
            const payload = JSON.parse(raw);
            if (consume !== false) {
                localStorage.removeItem(fullKey);
            }
            return payload;
        } catch(e) {
            console.warn('Pipeline getData failed:', e);
            return null;
        }
    }

    /**
     * 检查是否有待消费的流转数据
     */
    function hasData(key) {
        const fullKey = PIPELINE_PREFIX + key;
        return !!localStorage.getItem(fullKey);
    }

    /**
     * CR分析结果 → 修复计划
     * 将CR分析中的未解决问题转为修复计划节点
     */
    function crToFixPlan(analysisData) {
        if (!analysisData) return null;

        const summary = analysisData.summary || {};
        const moduleStats = analysisData.module_stats || {};
        const devStats = analysisData.dev_stats || {};

        // 按模块生成修复任务
        const tasks = [];
        let taskIndex = 1;

        // Blocker优先
        const blockerCount = summary.blocker_unresolved || 0;
        if (blockerCount > 0) {
            tasks.push({
                index: taskIndex++,
                name: ' Blocker问题修复 (' + blockerCount + '个)',
                duration: Math.max(1, Math.ceil(blockerCount / 3)),
                isMilestone: false,
                priority: 'blocker',
                description: '优先解决所有Blocker级别的未关闭问题'
            });
        }

        // 按未解决问题数排序模块
        const modulesByUnresolved = Object.entries(moduleStats)
            .map(([name, stats]) => ({
                name: name,
                total: stats.total || 0,
                unresolved: stats.unresolved || 0,
                resolved: stats.resolved || 0
            }))
            .filter(m => m.unresolved > 0)
            .sort((a, b) => b.unresolved - a.unresolved);

        modulesByUnresolved.slice(0, 8).forEach(mod => {
            tasks.push({
                index: taskIndex++,
                name: mod.name + ' 模块修复 (' + mod.unresolved + '个未解决)',
                duration: Math.max(1, Math.ceil(mod.unresolved / 5)),
                isMilestone: taskIndex % 3 === 0,
                priority: mod.unresolved > 10 ? 'high' : 'medium',
                description: '模块: ' + mod.name + ', 总计' + mod.total + '个, 未解决' + mod.unresolved + '个'
            });
        });

        // 回归验证里程碑
        if (tasks.length > 0) {
            tasks.push({
                index: taskIndex++,
                name: ' 回归测试验证',
                duration: 1,
                isMilestone: true,
                priority: 'normal',
                description: '所有修复完成后进行全量回归测试'
            });
        }

        return {
            source: 'cr-analysis',
            sourceFile: analysisData.file_name || 'CR分析报告',
            generatedAt: new Date().toISOString(),
            summary: {
                totalIssues: summary.total_issues || 0,
                unresolved: summary.total_unresolved || 0,
                blockers: blockerCount,
                resolutionRate: summary.resolution_rate || 0
            },
            tasks: tasks
        };
    }

    /**
     * 日志分析结果 → Bug趋势数据
     */
    function logToBugTrend(logData) {
        if (!logData) return null;

        const errors = logData.errors || [];
        const dailyStats = {};

        // 按日期统计错误数
        errors.forEach(err => {
            const date = err.date || new Date().toISOString().split('T')[0];
            if (!dailyStats[date]) dailyStats[date] = 0;
            dailyStats[date]++;
        });

        const sortedDates = Object.keys(dailyStats).sort();
        const recentDates = sortedDates.slice(-7);

        return {
            source: 'log-analyzer',
            generatedAt: new Date().toISOString(),
            days: recentDates.map(d => d.slice(5)), // MM-DD
            values: recentDates.map(d => dailyStats[d]),
            totalErrors: errors.length,
            errorCategories: logData.categories || {}
        };
    }

    /**
     * 站会阻塞项 → Dashboard风险数据
     */
    function standupToDashboard(standupData) {
        if (!standupData || !standupData.blocker) return null;

        const blockers = Array.isArray(standupData.blocker)
            ? standupData.blocker
            : (standupData.blocker || '').split('\n').filter(Boolean);

        return {
            source: 'daily-standup',
            generatedAt: new Date().toISOString(),
            date: standupData.date || new Date().toLocaleDateString('zh-CN'),
            blockers: blockers,
            blockerCount: blockers.length,
            yesterdayCompleted: (standupData.yesterday || []).length,
            todayPlanned: (standupData.today || []).length
        };
    }

    /**
     * 会议纪要待办 → 计划节点
     */
    function meetingToPlan(meetingData) {
        if (!meetingData) return null;

        const todos = meetingData.todoList || meetingData.todos || [];
        const todoItems = Array.isArray(todos)
            ? todos
            : (todos || '').split('\n').map(l => l.replace(/^[-*•\d.)\s]+/, '').trim()).filter(Boolean);

        const nodes = todoItems.map((todo, i) => ({
            index: i + 1,
            name: todo.text || todo,
            duration: 1,
            isMilestone: false,
            status: 'pending',
            source: 'meeting-minutes'
        }));

        return {
            source: 'meeting-minutes',
            meetingTitle: meetingData.title || '会议纪要',
            meetingDate: meetingData.date || new Date().toLocaleDateString('zh-CN'),
            generatedAt: new Date().toISOString(),
            nodes: nodes,
            todoCount: nodes.length
        };
    }

    /**
     * 汇总多源数据 → 周报
     */
    function aggregateWeeklyData() {
        const sources = {};

        // 从站会历史获取
        try {
            const standupHistory = JSON.parse(localStorage.getItem('standup_history') || '[]');
            const oneWeekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
            const recentStandups = standupHistory.filter(h => new Date(h.date).getTime() >= oneWeekAgo);
            sources.standups = recentStandups.map(h => ({
                date: h.date,
                yesterday: h.items?.yesterday || [],
                today: h.items?.today || [],
                blockers: h.items?.blocker || []
            }));
        } catch(e) { sources.standups = []; }

        // 从CR分析缓存获取
        try {
            const crResult = JSON.parse(localStorage.getItem('cr_analysis_result') || 'null');
            if (crResult) {
                sources.crAnalysis = {
                    summary: crResult.summary || {},
                    moduleStats: crResult.module_stats || {}
                };
            }
        } catch(e) { sources.crAnalysis = null; }

        // 从日志分析获取
        try {
            const logResult = JSON.parse(localStorage.getItem('log_analysis_result') || 'null');
            if (logResult) {
                sources.logAnalysis = {
                    totalErrors: logData.errors?.length || 0,
                    categories: logData.categories || {}
                };
            }
        } catch(e) { sources.logAnalysis = null; }

        return {
            generatedAt: new Date().toISOString(),
            weekRange: getWeekRange(),
            sources: sources
        };
    }

    /**
     * 获取本周日期范围
     */
    function getWeekRange() {
        const now = new Date();
        const dayOfWeek = now.getDay() || 7;
        const monday = new Date(now);
        monday.setDate(now.getDate() - dayOfWeek + 1);
        const sunday = new Date(monday);
        sunday.setDate(monday.getDate() + 6);
        return {
            start: monday.toISOString().split('T')[0],
            end: sunday.toISOString().split('T')[0]
        };
    }

    /**
     * 显示流转通知
     */
    function showNotification(message, type) {
        if (window.ToolboxToast) {
            window.ToolboxToast.show(message, type || 'info');
        } else {
            console.log('[Pipeline]', message);
        }
    }

    /**
     * 跳转到目标工具并传递数据
     */
    function navigateWithData(targetUrl, storageKey, data) {
        setData(storageKey, data);
        showNotification('数据已流转，正在跳转...', 'info');
        setTimeout(() => {
            window.location.href = targetUrl;
        }, 500);
    }

    // 暴露全局API
    window.Pipeline = {
        STORAGE_KEYS: STORAGE_KEYS,
        setData: setData,
        getData: getData,
        hasData: hasData,
        crToFixPlan: crToFixPlan,
        logToBugTrend: logToBugTrend,
        standupToDashboard: standupToDashboard,
        meetingToPlan: meetingToPlan,
        aggregateWeeklyData: aggregateWeeklyData,
        navigateWithData: navigateWithData,
        showNotification: showNotification
    };

    // 监听跨标签页数据更新
    window.addEventListener('storage', function(e) {
        if (e.key && e.key.indexOf(PIPELINE_PREFIX) === 0) {
            const key = e.key.replace(PIPELINE_PREFIX, '');
            window.dispatchEvent(new CustomEvent('pipeline-data-updated', {
                detail: { key: key, data: e.newValue ? JSON.parse(e.newValue) : null }
            }));
        }
    });

})();
