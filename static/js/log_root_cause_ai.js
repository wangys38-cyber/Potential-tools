/**
 * 日志智能根因分析增强模块
 * 功能：异常模式识别、错误链分析、AI深度根因推理、相似历史问题匹配
 */

const LogRootCauseAI = (function() {
    'use strict';

    // 历史问题库（可扩展）
    const HISTORICAL_ISSUES = [
        {
            id: 'HIS-001',
            keywords: ['malloc', 'memory', 'alloc', 'heap', 'OOM'],
            title: '内存分配失败/内存泄漏',
            rootCause: '内存泄漏或堆内存不足，导致malloc失败',
            solution: '1. 检查malloc/free配对，使用内存检测工具定位泄漏点\n2. 增加内存池管理，减少频繁分配释放\n3. 优化大内存块使用，及时释放不需要的内存',
            severity: 'high'
        },
        {
            id: 'HIS-002',
            keywords: ['watchdog', 'wdog', 'reset', 'reboot', 'wdt'],
            title: '看门狗超时复位',
            rootCause: '任务阻塞或死循环导致看门狗超时',
            solution: '1. 检查复位前最后日志，定位阻塞任务\n2. 优化耗时操作，增加看门狗喂狗\n3. 检查是否有死锁或资源竞争',
            severity: 'high'
        },
        {
            id: 'HIS-003',
            keywords: ['crash', 'panic', 'fault', 'exception', 'abort'],
            title: '系统崩溃/异常',
            rootCause: '空指针、数组越界、非法指令等导致系统异常',
            solution: '1. 抓取crash dump，分析出错地址和调用栈\n2. 检查出错位置的指针和数组访问\n3. 增加边界检查和空指针防护',
            severity: 'high'
        },
        {
            id: 'HIS-004',
            keywords: ['gps', 'gnss', 'position', 'location', 'satellite'],
            title: 'GPS定位异常/丢星',
            rootCause: 'GPS信号弱、天线问题或固件配置错误',
            solution: '1. 检查GPS天线连接和信号强度\n2. 确认AGNSS辅助定位是否正常\n3. 检查GPS固件版本和配置参数',
            severity: 'medium'
        },
        {
            id: 'HIS-005',
            keywords: ['ble', 'bluetooth', 'bt_', 'disconnect', 'timeout'],
            title: '蓝牙连接异常/断连',
            rootCause: '蓝牙协议栈问题、信号干扰或连接参数不合理',
            solution: '1. 检查蓝牙连接参数（间隔、延迟、超时）\n2. 确认是否有2.4G信号干扰\n3. 检查蓝牙协议栈版本和已知问题',
            severity: 'medium'
        },
        {
            id: 'HIS-006',
            keywords: ['battery', 'power', 'current', 'sleep', 'wakeup'],
            title: '功耗异常/电量过快',
            rootCause: '休眠电流偏高、异常唤醒或外设未正确关闭',
            solution: '1. 使用功耗仪测量休眠和工作电流\n2. 检查唤醒源配置，排除异常唤醒\n3. 确认外设电源域管理（GPS/蓝牙/屏幕/传感器）',
            severity: 'medium'
        },
        {
            id: 'HIS-007',
            keywords: ['i2c', 'spi', 'uart', 'bus', 'sensor'],
            title: '传感器总线通信失败',
            rootCause: '总线时序问题、硬件连接异常或传感器故障',
            solution: '1. 用逻辑分析仪检查总线时序\n2. 确认传感器硬件连接和供电\n3. 检查传感器驱动初始化和复位流程',
            severity: 'medium'
        },
        {
            id: 'HIS-008',
            keywords: ['display', 'lcd', 'screen', 'flash', 'flicker'],
            title: '屏幕显示异常/闪烁',
            rootCause: '显示驱动问题、刷新率配置或硬件连接异常',
            solution: '1. 检查显示驱动初始化和刷新率配置\n2. 确认屏幕硬件连接和供电\n3. 检查是否有内存带宽不足导致的闪烁',
            severity: 'low'
        }
    ];

    // 异常模式定义
    const ANOMALY_PATTERNS = [
        {
            id: 'PAT-001',
            name: '连续错误爆发',
            description: '短时间内出现大量相同类型错误',
            detect: function(logs) {
                const errorLogs = logs.filter(l => l.type === 'error' || l.type === 'crash');
                if (errorLogs.length < 5) return null;
                // 检查是否有时间窗口内的错误爆发
                for (let i = 0; i < errorLogs.length - 4; i++) {
                    const timeDiff = Math.abs(new Date(errorLogs[i + 4].timestamp) - new Date(errorLogs[i].timestamp));
                    if (timeDiff < 60000) { // 1分钟内5个以上错误
                        return {
                            pattern: '连续错误爆发',
                            severity: 'high',
                            detail: `在 ${errorLogs[i].timestamp} 前后1分钟内出现 ${i + 5 - i} 个错误，可能是系统异常或级联失败`,
                            startTime: errorLogs[i].timestamp,
                            count: 5
                        };
                    }
                }
                return null;
            }
        },
        {
            id: 'PAT-002',
            name: '周期性异常',
            description: '错误按固定周期重复出现',
            detect: function(logs) {
                const errorLogs = logs.filter(l => l.type === 'error' || l.type === 'warning');
                if (errorLogs.length < 6) return null;
                // 简单检测：检查错误间隔是否相似
                const intervals = [];
                for (let i = 1; i < Math.min(errorLogs.length, 10); i++) {
                    intervals.push(Math.abs(new Date(errorLogs[i].timestamp) - new Date(errorLogs[i-1].timestamp)));
                }
                if (intervals.length < 4) return null;
                const avg = intervals.reduce((a,b) => a+b, 0) / intervals.length;
                const variance = intervals.reduce((a,b) => a + Math.pow(b - avg, 2), 0) / intervals.length;
                const stdDev = Math.sqrt(variance);
                if (stdDev < avg * 0.3 && avg > 5000) { // 标准差小于平均值30%，且平均间隔大于5秒
                    return {
                        pattern: '周期性异常',
                        severity: 'medium',
                        detail: `错误按约 ${Math.round(avg/1000)} 秒周期重复出现，可能是定时任务、轮询或定时器相关问题`,
                        interval: Math.round(avg/1000) + '秒',
                        count: errorLogs.length
                    };
                }
                return null;
            }
        },
        {
            id: 'PAT-003',
            name: '错误级联',
            description: '一个错误引发后续多个相关错误',
            detect: function(logs) {
                const crashLogs = logs.filter(l => l.type === 'crash');
                if (crashLogs.length === 0) return null;
                // 检查崩溃后是否有重启、错误等级联现象
                const crashIndex = logs.findIndex(l => l.type === 'crash');
                if (crashIndex === -1 || crashIndex >= logs.length - 3) return null;
                const afterCrash = logs.slice(crashIndex + 1, crashIndex + 6);
                const hasReboot = afterCrash.some(l => l.type === 'reboot');
                const hasError = afterCrash.some(l => l.type === 'error');
                if (hasReboot || hasError) {
                    return {
                        pattern: '错误级联',
                        severity: 'high',
                        detail: `崩溃后出现 ${hasReboot ? '重启' : ''}${hasReboot && hasError ? '和' : ''}${hasError ? '后续错误' : ''}，可能是崩溃导致的级联失败`,
                        trigger: '系统崩溃',
                        cascadeCount: afterCrash.length
                    };
                }
                return null;
            }
        }
    ];

    /**
     * 分析异常模式
     */
    function analyzeAnomalyPatterns(logs) {
        const patterns = [];
        ANOMALY_PATTERNS.forEach(pattern => {
            const result = pattern.detect(logs);
            if (result) patterns.push(result);
        });
        return patterns;
    }

    /**
     * 构建错误链
     */
    function buildErrorChain(logs) {
        const errorLogs = logs.filter(l => ['crash', 'error', 'warning', 'reboot', 'memory', 'power'].includes(l.type));
        if (errorLogs.length === 0) return [];

        const chain = [];
        let currentChain = [errorLogs[0]];

        for (let i = 1; i < errorLogs.length; i++) {
            const timeDiff = Math.abs(new Date(errorLogs[i].timestamp) - new Date(errorLogs[i-1].timestamp));
            if (timeDiff < 30000) { // 30秒内的错误视为同一错误链
                currentChain.push(errorLogs[i]);
            } else {
                if (currentChain.length >= 2) chain.push(currentChain);
                currentChain = [errorLogs[i]];
            }
        }
        if (currentChain.length >= 2) chain.push(currentChain);

        return chain.map((c, idx) => ({
            id: `CHAIN-${idx + 1}`,
            startTime: c[0].timestamp,
            endTime: c[c.length - 1].timestamp,
            events: c,
            rootEvent: c[0],
            severity: c.some(e => e.type === 'crash') ? 'high' : c.some(e => e.type === 'error') ? 'medium' : 'low'
        }));
    }

    /**
     * 匹配相似历史问题
     */
    function matchHistoricalIssues(logs, detailedIssues) {
        const matches = [];
        const logText = logs.map(l => l.content).join(' ').toLowerCase();
        const issueText = detailedIssues.map(i => i.label + ' ' + (i.subIssues || []).map(s => s.label).join(' ')).join(' ').toLowerCase();
        const fullText = logText + ' ' + issueText;

        HISTORICAL_ISSUES.forEach(issue => {
            const matchedKeywords = issue.keywords.filter(kw => fullText.includes(kw.toLowerCase()));
            if (matchedKeywords.length > 0) {
                matches.push({
                    ...issue,
                    matchScore: matchedKeywords.length,
                    matchedKeywords: matchedKeywords
                });
            }
        });

        return matches.sort((a, b) => b.matchScore - a.matchScore).slice(0, 5);
    }

    /**
     * AI 深度根因分析（调用后端API）
     */
    async function aiDeepAnalysis(logs, stats, patterns, errorChains, historicalMatches) {
        try {
            // 准备分析摘要
            const summary = {
                stats: stats,
                topIssues: (logs.filter(l => l.type !== 'normal').slice(0, 20)).map(l => ({
                    type: l.type,
                    content: l.content.substring(0, 200),
                    timestamp: l.timestamp
                })),
                patterns: patterns,
                errorChains: errorChains.map(c => ({
                    id: c.id,
                    startTime: c.startTime,
                    events: c.events.map(e => ({ type: e.type, content: e.content.substring(0, 100) }))
                })),
                historicalMatches: historicalMatches.map(m => ({
                    id: m.id,
                    title: m.title,
                    matchedKeywords: m.matchedKeywords
                }))
            };

            const resp = await fetch('/api/log-ai-root-cause', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(summary)
            });

            if (!resp.ok) {
                throw new Error('API请求失败: ' + resp.status);
            }

            const data = await resp.json();
            return data;
        } catch (e) {
            console.error('AI深度分析失败:', e);
            // 降级：返回基于规则的分析
            return generateRuleBasedAnalysis(stats, patterns, errorChains, historicalMatches);
        }
    }

    /**
     * 基于规则的降级分析
     */
    function generateRuleBasedAnalysis(stats, patterns, errorChains, historicalMatches) {
        const rootCauses = [];
        const recommendations = [];

        if (stats.crash > 0) {
            rootCauses.push('存在系统崩溃，需优先分析crash dump和复位原因');
            recommendations.push('抓取崩溃现场的寄存器和调用栈信息');
        }
        if (stats.memory > 0) {
            rootCauses.push('内存异常，可能存在内存泄漏或分配失败');
            recommendations.push('使用内存检测工具定位泄漏点');
        }
        if (patterns.length > 0) {
            patterns.forEach(p => {
                rootCauses.push(`检测到「${p.pattern}」模式：${p.detail}`);
            });
        }
        if (errorChains.length > 0) {
            rootCauses.push(`发现 ${errorChains.length} 条错误链，需分析因果关系`);
        }
        if (historicalMatches.length > 0) {
            recommendations.push(`参考历史相似问题：${historicalMatches.map(m => m.title).join('、')}`);
        }

        return {
            rootCauses: rootCauses,
            recommendations: recommendations,
            confidence: 'medium',
            note: '基于规则分析（AI服务不可用时的降级方案）'
        };
    }

    /**
     * 渲染智能分析结果
     */
    function renderAnalysis(container, data) {
        if (!container) return;

        const severityColors = {
            high: '#ff3b30',
            medium: '#ff9500',
            low: '#34c759'
        };

        let html = '';

        // AI 根因分析
        if (data.aiAnalysis) {
            html += `
                <div class="util-mb-16" style="padding:16px;background:var(--ds-bg-secondary);border-radius:12px;">
                    <div style="font-weight:600;font-size:15px;margin-bottom:10px;display:flex;align-items:center;gap:8px;">
                        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#6366f1;"></span>
                        AI 深度根因分析
                        <span style="font-size:11px;color:var(--ds-text-secondary);font-weight:normal;">置信度: ${data.aiAnalysis.confidence || 'medium'}</span>
                    </div>
                    ${data.aiAnalysis.rootCauses && data.aiAnalysis.rootCauses.length > 0 ? `
                        <div style="margin-bottom:12px;">
                            <div style="font-size:13px;font-weight:500;margin-bottom:6px;color:var(--ds-text);">根因分析：</div>
                            <ul style="margin:0;padding-left:20px;line-height:1.8;font-size:13px;color:var(--ds-text);">
                                ${data.aiAnalysis.rootCauses.map(r => `<li>${r}</li>`).join('')}
                            </ul>
                        </div>
                    ` : ''}
                    ${data.aiAnalysis.recommendations && data.aiAnalysis.recommendations.length > 0 ? `
                        <div>
                            <div style="font-size:13px;font-weight:500;margin-bottom:6px;color:var(--ds-text);">改进建议：</div>
                            <ol style="margin:0;padding-left:20px;line-height:1.8;font-size:13px;color:var(--ds-text);">
                                ${data.aiAnalysis.recommendations.map(r => `<li>${r}</li>`).join('')}
                            </ol>
                        </div>
                    ` : ''}
                    ${data.aiAnalysis.note ? `<div style="margin-top:8px;font-size:11px;color:var(--ds-text-secondary);">${data.aiAnalysis.note}</div>` : ''}
                </div>
            `;
        }

        // 异常模式
        if (data.patterns && data.patterns.length > 0) {
            html += `
                <div class="util-mb-16">
                    <div style="font-weight:600;font-size:15px;margin-bottom:10px;">异常模式识别：</div>
                    <div style="display:flex;flex-direction:column;gap:8px;">
                        ${data.patterns.map(p => `
                            <div style="padding:12px 16px;border-radius:10px;border-left:3px solid ${severityColors[p.severity] || '#ff9500'};background:var(--ds-bg-secondary);">
                                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                                    <span style="font-weight:600;font-size:13px;color:var(--ds-text);">${p.pattern}</span>
                                    <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${severityColors[p.severity] || '#ff9500'};color:#fff;">${p.severity === 'high' ? '高风险' : p.severity === 'medium' ? '中风险' : '低风险'}</span>
                                </div>
                                <div style="font-size:12px;color:var(--ds-text-secondary);line-height:1.5;">${p.detail}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        // 错误链
        if (data.errorChains && data.errorChains.length > 0) {
            html += `
                <div class="util-mb-16">
                    <div style="font-weight:600;font-size:15px;margin-bottom:10px;">错误链分析（${data.errorChains.length}条）：</div>
                    <div style="display:flex;flex-direction:column;gap:10px;">
                        ${data.errorChains.map(chain => `
                            <div style="padding:12px 16px;border-radius:10px;border:1px solid var(--ds-border-light);background:var(--ds-bg-elevated);">
                                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                                    <span style="font-weight:600;font-size:13px;color:var(--ds-text);">${chain.id}</span>
                                    <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${severityColors[chain.severity] || '#ff9500'};color:#fff;">${chain.severity === 'high' ? '高风险' : chain.severity === 'medium' ? '中风险' : '低风险'}</span>
                                </div>
                                <div style="font-size:11px;color:var(--ds-text-secondary);margin-bottom:6px;">${chain.startTime} → ${chain.endTime}（${chain.events.length}个事件）</div>
                                <div style="display:flex;flex-wrap:wrap;gap:4px;">
                                    ${chain.events.map((e, i) => `
                                        <span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:2px 8px;border-radius:6px;background:var(--ds-bg-secondary);color:var(--ds-text);">
                                            ${i > 0 ? '<span style="color:var(--ds-text-secondary);">→</span>' : ''}
                                            <span style="font-weight:600;">[${e.type}]</span>
                                            <span style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${e.content.substring(0, 30)}</span>
                                        </span>
                                    `).join('')}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        // 相似历史问题
        if (data.historicalMatches && data.historicalMatches.length > 0) {
            html += `
                <div>
                    <div style="font-weight:600;font-size:15px;margin-bottom:10px;">相似历史问题匹配：</div>
                    <div style="display:flex;flex-direction:column;gap:8px;">
                        ${data.historicalMatches.map(m => `
                            <div style="padding:12px 16px;border-radius:10px;border:1px solid var(--ds-border-light);background:var(--ds-bg-elevated);">
                                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                                    <span style="font-weight:600;font-size:13px;color:var(--ds-text);">${m.id} - ${m.title}</span>
                                    <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${severityColors[m.severity] || '#ff9500'};color:#fff;">匹配度: ${m.matchScore}</span>
                                </div>
                                <div style="font-size:12px;color:var(--ds-text-secondary);margin-bottom:6px;"><strong>根因：</strong>${m.rootCause}</div>
                                <div style="font-size:12px;color:var(--ds-text);line-height:1.6;white-space:pre-wrap;"><strong>解决方案：</strong>${m.solution}</div>
                                <div style="margin-top:6px;font-size:10px;color:var(--ds-text-secondary);">匹配关键词: ${m.matchedKeywords.join(', ')}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    return {
        analyzeAnomalyPatterns: analyzeAnomalyPatterns,
        buildErrorChain: buildErrorChain,
        matchHistoricalIssues: matchHistoricalIssues,
        aiDeepAnalysis: aiDeepAnalysis,
        renderAnalysis: renderAnalysis,
        HISTORICAL_ISSUES: HISTORICAL_ISSUES
    };
})();

window.LogRootCauseAI = LogRootCauseAI;
