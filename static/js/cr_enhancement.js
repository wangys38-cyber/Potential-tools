// Task2: CR分析增强 - 研发效率排名 + 模块健康度
(function() {
    function injectTabs() {
        var tabsContainer = document.querySelector('.tabs');
        if (!tabsContainer || document.querySelector('[data-tab="efficiency"]')) return;
        var effBtn = document.createElement('button');
        effBtn.className = 'tab';
        effBtn.dataset.tab = 'efficiency';
        effBtn.onclick = function() { switchTab('efficiency'); };
        effBtn.innerHTML = '&#9889; 研发效率';
        tabsContainer.appendChild(effBtn);
        var healthBtn = document.createElement('button');
        healthBtn.className = 'tab';
        healthBtn.dataset.tab = 'health';
        healthBtn.onclick = function() { switchTab('health'); };
        healthBtn.innerHTML = '&#128154; 模块健康';
        tabsContainer.appendChild(healthBtn);
        var tabDaily = document.getElementById('tab-daily');
        if (tabDaily && tabDaily.parentNode) {
            var effDiv = document.createElement('div');
            effDiv.className = 'tab-content';
            effDiv.id = 'tab-efficiency';
            effDiv.innerHTML = '<div id="efficiencyRanking"></div>';
            var healthDiv = document.createElement('div');
            healthDiv.className = 'tab-content';
            healthDiv.id = 'tab-health';
            healthDiv.innerHTML = '<div id="moduleHealth"></div>';
            tabDaily.parentNode.insertBefore(effDiv, tabDaily.nextSibling);
            tabDaily.parentNode.insertBefore(healthDiv, effDiv.nextSibling);
        }
    }

    function _parseDate(s) {
        if (!s) return null;
        var d = new Date(s);
        if (!isNaN(d.getTime())) return d;
        var m = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
        if (m) return new Date(parseInt(m[1]), parseInt(m[2])-1, parseInt(m[3]));
        return null;
    }

    function _isResolved(status) {
        if (!status) return false;
        var s = status.toLowerCase();
        return s.indexOf('resolved') >= 0 || s.indexOf('closed') >= 0 || s.indexOf('done') >= 0 || s.indexOf('已解决') >= 0 || s.indexOf('已关闭') >= 0;
    }

    function _isReopen(resolution, status) {
        var r = (resolution || '').toLowerCase();
        var s = (status || '').toLowerCase();
        return r.indexOf('reopen') >= 0 || s.indexOf('reopen') >= 0 || r.indexOf('重新打开') >= 0;
    }

    function _isSevere(severity) {
        if (!severity) return false;
        var s = severity.toLowerCase();
        return s.indexOf('blocker') >= 0 || s.indexOf('critical') >= 0 || s.indexOf('fatal') >= 0 || s.indexOf('致命') >= 0 || s.indexOf('严重') >= 0 || s.indexOf('p0') >= 0 || s.indexOf('p1') >= 0;
    }

    function _esc(s) {
        return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    window.renderEfficiencyRanking = function() {
        var container = document.getElementById('efficiencyRanking');
        if (!container || !window.currentAnalysisData) return;
        var issues = window.currentAnalysisData.all_issues || [];
        if (!issues.length) { container.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无数据</div>'; return; }
        var devMap = {};
        for (var i = 0; i < issues.length; i++) {
            var issue = issues[i];
            var dev = (issue.developer || '未分配').trim() || '未分配';
            if (!devMap[dev]) devMap[dev] = { total:0, resolved:0, reopen:0, times:[] };
            var d = devMap[dev]; d.total++;
            if (_isResolved(issue.status)) {
                d.resolved++;
                var c = _parseDate(issue.create_date), r = _parseDate(issue.resolved_date);
                if (c && r) { var days = (r-c)/86400000; if (days>=0 && days<365) d.times.push(days); }
            }
            if (_isReopen(issue.resolution, issue.status)) d.reopen++;
        }
        var devList = [];
        for (var name in devMap) {
            if (!devMap.hasOwnProperty(name)) continue;
            var d = devMap[name];
            var avg = d.times.length ? d.times.reduce(function(a,b){return a+b;},0)/d.times.length : 0;
            var reopenRate = d.resolved ? d.reopen/d.resolved*100 : 0;
            var resolveRate = d.total ? d.resolved/d.total*100 : 0;
            var score = resolveRate*0.4 + Math.max(0,100-avg*2)*0.3 + Math.max(0,100-reopenRate*5)*0.3;
            var level='medium',label='中等',color='#f59e0b';
            if (score>=70){level='high';label='高效';color='#10b981';}
            else if(score<40){level='low';label='低效';color='#ef4444';}
            devList.push({name:name,total:d.total,resolved:d.resolved,reopen:d.reopen,avgTime:avg.toFixed(1),reopenRate:reopenRate.toFixed(1),resolveRate:resolveRate.toFixed(1),score:score.toFixed(1),level:level,label:label,color:color});
        }
        devList.sort(function(a,b){return parseFloat(b.score)-parseFloat(a.score);});
        window._effData = devList; window._effSort = {};
        var hi=0, lo=0;
        for (var j=0;j<devList.length;j++){ if(devList[j].level==='high')hi++; if(devList[j].level==='low')lo++; }
        var html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">';
        html += '<div style="background:var(--bg-card);border-radius:12px;padding:16px;text-align:center;border:1px solid var(--border);"><div style="font-size:24px;font-weight:700;color:#10b981;">'+hi+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">高效研发</div></div>';
        html += '<div style="background:var(--bg-card);border-radius:12px;padding:16px;text-align:center;border:1px solid var(--border);"><div style="font-size:24px;font-weight:700;color:#f59e0b;">'+(devList.length-hi-lo)+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">中等研发</div></div>';
        html += '<div style="background:var(--bg-card);border-radius:12px;padding:16px;text-align:center;border:1px solid var(--border);"><div style="font-size:24px;font-weight:700;color:#ef4444;">'+lo+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">低效研发</div></div></div>';
        html += '<div style="background:var(--bg-card);border-radius:12px;border:1px solid var(--border);overflow:hidden;"><div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;"><span style="font-weight:600;font-size:14px;">研发效率排名</span><span style="font-size:12px;color:var(--text-secondary);">点击表头排序</span></div><div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="background:var(--bg-secondary);">';
        html += '<th style="padding:10px 12px;text-align:left;cursor:pointer;" onclick="window._sortEff(\'name\')">研发人员</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'total\')">总数</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'resolved\')">已解决</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'reopen\')">Reopen</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'avgTime\')">平均(天)</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'reopenRate\')">Reopen率</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'resolveRate\')">解决率</th>';
        html += '<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortEff(\'score\')">效率分</th>';
        html += '<th style="padding:10px 12px;text-align:center;">等级</th></tr></thead><tbody id="effBody"></tbody></table></div></div>';
        container.innerHTML = html;
        _renderEffRows(devList);
    };

    function _renderEffRows(data) {
        var tb = document.getElementById('effBody'); if (!tb) return;
        var rows = [];
        for (var i=0;i<data.length;i++){
            var d=data[i];
            rows.push('<tr style="border-bottom:1px solid var(--border);"><td style="padding:10px 12px;font-weight:500;">'+_esc(d.name)+'</td><td style="padding:10px 12px;text-align:center;">'+d.total+'</td><td style="padding:10px 12px;text-align:center;color:#10b981;">'+d.resolved+'</td><td style="padding:10px 12px;text-align:center;color:#ef4444;">'+d.reopen+'</td><td style="padding:10px 12px;text-align:center;">'+d.avgTime+'</td><td style="padding:10px 12px;text-align:center;">'+d.reopenRate+'%</td><td style="padding:10px 12px;text-align:center;">'+d.resolveRate+'%</td><td style="padding:10px 12px;text-align:center;font-weight:600;">'+d.score+'</td><td style="padding:10px 12px;text-align:center;"><span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600;color:#fff;background:'+d.color+';">'+d.label+'</span></td></tr>');
        }
        tb.innerHTML = rows.join('');
    }

    window._sortEff = function(field) {
        if (!window._effData) return;
        var dir = window._effSort[field]==='asc'?'desc':'asc'; window._effSort[field]=dir;
        var sorted = window._effData.slice().sort(function(a,b){
            var va=a[field],vb=b[field];
            if(typeof va==='string'){va=va.replace('%','');vb=vb.replace('%','');}
            var na=parseFloat(va),nb=parseFloat(vb);
            if(!isNaN(na)&&!isNaN(nb))return dir==='asc'?na-nb:nb-na;
            return dir==='asc'?String(va).localeCompare(String(vb)):String(vb).localeCompare(String(va));
        });
        _renderEffRows(sorted);
    };

    window.renderModuleHealth = function() {
        var container = document.getElementById('moduleHealth');
        if (!container || !window.currentAnalysisData) return;
        var issues = window.currentAnalysisData.all_issues || [];
        if (!issues.length) { container.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无数据</div>'; return; }
        var modMap = {};
        for (var i=0;i<issues.length;i++){
            var issue=issues[i];
            var mod=(issue.module||'未分类').trim()||'未分类';
            if(!modMap[mod])modMap[mod]={total:0,unresolved:0,severe:0};
            var m=modMap[mod];m.total++;
            if(!_isResolved(issue.status))m.unresolved++;
            if(_isSevere(issue.severity))m.severe++;
        }
        var modCount=0;for(var k in modMap){if(modMap.hasOwnProperty(k))modCount++;}
        var avg=issues.length/Math.max(1,modCount);
        var modList=[];
        for(var name in modMap){
            if(!modMap.hasOwnProperty(name))continue;
            var m=modMap[name];
            var unresRate=m.total?m.unresolved/m.total*100:0;
            var density=(m.total/avg).toFixed(2);
            var score=Math.max(0,100-unresRate*0.5-(m.severe/m.total*100)*0.8-Math.max(0,(m.total/avg-1)*20));
            var level='healthy',label='健康',color='#10b981',bg='rgba(16,185,129,0.08)';
            if(score<40||(m.unresolved>5&&m.severe>2)){level='critical';label='重灾';color='#ef4444';bg='rgba(239,68,68,0.08)';}
            else if(score<70||m.unresolved>3||m.severe>0){level='warning';label='关注';color='#f59e0b';bg='rgba(245,158,11,0.08)';}
            modList.push({name:name,total:m.total,unresolved:m.unresolved,severe:m.severe,unresRate:unresRate.toFixed(1),density:density,score:score.toFixed(1),level:level,label:label,color:color,bg:bg});
        }
        modList.sort(function(a,b){return parseFloat(b.score)-parseFloat(a.score);});
        window._healthData=modList;window._healthSort={};
        var h=0,w=0,c=0;
        for(var j=0;j<modList.length;j++){if(modList[j].level==='healthy')h++;if(modList[j].level==='warning')w++;if(modList[j].level==='critical')c++;}
        var html='<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">';
        html+='<div style="background:rgba(16,185,129,0.08);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(16,185,129,0.2);"><div style="font-size:24px;font-weight:700;color:#10b981;">'+h+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">健康模块</div></div>';
        html+='<div style="background:rgba(245,158,11,0.08);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(245,158,11,0.2);"><div style="font-size:24px;font-weight:700;color:#f59e0b;">'+w+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">关注模块</div></div>';
        html+='<div style="background:rgba(239,68,68,0.08);border-radius:12px;padding:16px;text-align:center;border:1px solid rgba(239,68,68,0.2);"><div style="font-size:24px;font-weight:700;color:#ef4444;">'+c+'</div><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">重灾模块</div></div></div>';
        html+='<div style="background:var(--bg-card);border-radius:12px;border:1px solid var(--border);overflow:hidden;"><div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;"><span style="font-weight:600;font-size:14px;">模块健康度</span><span style="font-size:12px;color:var(--text-secondary);">点击表头排序</span></div><div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="background:var(--bg-secondary);">';
        html+='<th style="padding:10px 12px;text-align:left;cursor:pointer;" onclick="window._sortHealth(\'name\')">模块名称</th>';
        html+='<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortHealth(\'total\')">Bug总数</th>';
        html+='<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortHealth(\'unresolved\')">未关闭</th>';
        html+='<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortHealth(\'severe\')">严重Bug</th>';
        html+='<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortHealth(\'density\')">Bug密度</th>';
        html+='<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortHealth(\'unresRate\')">未关闭率</th>';
        html+='<th style="padding:10px 12px;text-align:center;cursor:pointer;" onclick="window._sortHealth(\'score\')">健康分</th>';
        html+='<th style="padding:10px 12px;text-align:center;">评级</th></tr></thead><tbody id="healthBody"></tbody></table></div></div>';
        container.innerHTML=html;
        _renderHealthRows(modList);
    };

    function _renderHealthRows(data) {
        var tb=document.getElementById('healthBody');if(!tb)return;
        var rows=[];
        for(var i=0;i<data.length;i++){
            var m=data[i];
            rows.push('<tr style="border-bottom:1px solid var(--border);background:'+m.bg+';"><td style="padding:10px 12px;font-weight:500;">'+_esc(m.name)+'</td><td style="padding:10px 12px;text-align:center;font-weight:600;">'+m.total+'</td><td style="padding:10px 12px;text-align:center;color:#ef4444;">'+m.unresolved+'</td><td style="padding:10px 12px;text-align:center;color:#dc2626;font-weight:600;">'+m.severe+'</td><td style="padding:10px 12px;text-align:center;">'+m.density+'x</td><td style="padding:10px 12px;text-align:center;">'+m.unresRate+'%</td><td style="padding:10px 12px;text-align:center;font-weight:600;">'+m.score+'</td><td style="padding:10px 12px;text-align:center;"><span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600;color:#fff;background:'+m.color+';">'+m.label+'</span></td></tr>');
        }
        tb.innerHTML=rows.join('');
    }

    window._sortHealth=function(field){
        if(!window._healthData)return;
        var dir=window._healthSort[field]==='asc'?'desc':'asc';window._healthSort[field]=dir;
        var sorted=window._healthData.slice().sort(function(a,b){
            var va=a[field],vb=b[field];
            if(typeof va==='string'){va=va.replace('%','').replace('x','');vb=vb.replace('%','').replace('x','');}
            var na=parseFloat(va),nb=parseFloat(vb);
            if(!isNaN(na)&&!isNaN(nb))return dir==='asc'?na-nb:nb-na;
            return dir==='asc'?String(va).localeCompare(String(vb)):String(vb).localeCompare(String(va));
        });
        _renderHealthRows(sorted);
    };

    function hookDisplayResults() {
        if (typeof window.displayResults !== 'function') return;
        var orig = window.displayResults;
        window.displayResults = function() {
            orig.apply(this, arguments);
            setTimeout(function() {
                if (window.renderEfficiencyRanking) window.renderEfficiencyRanking();
                if (window.renderModuleHealth) window.renderModuleHealth();
            }, 100);
        };
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { injectTabs(); hookDisplayResults(); });
    } else {
        injectTabs();
        hookDisplayResults();
    }
})();
