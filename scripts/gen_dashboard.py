"""Append new panels to dashboard.html — fixed version."""

import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(BASE, "backend", "api_gateway", "dashboard.html")

with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

# ── 1. Insert nav tabs after refresh-bar ──
nav_html = """
  <!-- 导航标签 -->
  <div class="nav-tabs" id="mainNav">
    <div class="tab active" onclick="switchPage('overview',this)">总览</div>
    <div class="tab" onclick="switchPage('growth',this)">用户成长</div>
    <div class="tab" onclick="switchPage('knowledge',this)">知识库</div>
    <div class="tab" onclick="switchPage('projects',this)">项目</div>
    <div class="tab" onclick="switchPage('ops',this)">系统运维</div>
  </div>
  <div class="tab-page active" id="page-overview">
"""
old_refresh = "</button>\n  </div>\n\n  <!-- 核心指标 -->"
new_refresh = "</button>\n  </div>\n" + nav_html + "\n  <!-- 核心指标 -->"
html = html.replace(old_refresh, new_refresh)

# ── 2. Close page-overview div before review-dialog, insert new pages ──
new_pages = """  </div><!-- end page-overview -->

  <!-- ==================== 用户成长 ==================== -->
  <div class="tab-page" id="page-growth">
    <div class="grid-4">
      <div class="card"><div class="metric-value" id="ugTotalSkills">-</div><div class="metric-label">总技能数</div></div>
      <div class="card"><div class="metric-value" id="ugAvgMastery">-</div><div class="metric-label">平均掌握度</div><div class="progress-bar"><div class="fill green" id="ugMasteryBar" style="width:0%"></div></div></div>
      <div class="card"><div class="metric-value" id="ugStreakDays">-</div><div class="metric-label">连续学习天数</div></div>
      <div class="card"><div class="metric-value" id="ugWeekNew">-</div><div class="metric-label">本周新增技能</div></div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-header"><h2>技能雷达</h2><span class="badge" id="ugTopDomain">-</span></div>
        <div id="radarContent" class="empty">加载中...</div>
      </div>
      <div class="card">
        <div class="card-header"><h2>领域分布</h2></div>
        <div id="domainDistContent" class="empty">加载中...</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-header"><h2>学习效率</h2></div>
        <div class="metric-value" style="font-size:28px;" id="ugEfficiency">-</div>
        <div class="metric-label">近30天学习效率</div>
        <div class="progress-bar"><div class="fill accent" id="ugEffBar" style="width:0%"></div></div>
      </div>
      <div class="card">
        <div class="card-header"><h2>最近更新</h2></div>
        <div style="font-size:12px;color:var(--text-muted);" id="ugLastUpdate">-</div>
      </div>
    </div>
    <div class="card" style="margin-bottom:24px;">
      <div class="card-header"><h2>学习热力图 (近4周)</h2><span class="badge" id="heatActiveDays">-</span></div>
      <div class="heatmap-labels" id="heatLabels"></div>
      <div class="heatmap-grid" id="heatGrid"></div>
      <div style="margin-top:12px;font-size:11px;color:var(--text-muted);display:flex;gap:12px;align-items:center;">
        <span>峰值: <b id="heatPeak" style="color:var(--text);">-</b></span>
        <span>均值: <b id="heatAvg" style="color:var(--text);">-</b></span>
        <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:#1a1d27;"></span>低
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:rgba(99,102,241,0.4);"></span>
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:rgba(99,102,241,0.7);"></span>
          <span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:var(--accent);"></span>高
        </span>
      </div>
    </div>
    <div class="card" style="margin-bottom:24px;">
      <div class="card-header"><h2>学习时间线</h2><span class="badge" id="tlTotal">-</span></div>
      <div id="timelineContent" class="empty">加载中...</div>
    </div>
  </div>

  <!-- ==================== 知识库 ==================== -->
  <div class="tab-page" id="page-knowledge">
    <div class="card" style="margin-bottom:24px;">
      <div class="card-header"><h2>知识库搜索</h2><span class="badge" id="kbListTotal">-</span></div>
      <div class="search-box">
        <input type="text" id="kbSearchInput" placeholder="输入关键词搜索知识库..." onkeyup="if(event.key==='Enter')searchKnowledge()">
        <button class="btn primary" onclick="searchKnowledge()">搜索</button>
        <button class="btn" onclick="listKnowledge()">全部列表</button>
      </div>
      <div id="kbSearchResults" class="empty">点击"全部列表"加载知识库...</div>
    </div>
  </div>

  <!-- ==================== 项目 ==================== -->
  <div class="tab-page" id="page-projects">
    <div class="card" style="margin-bottom:24px;">
      <div class="card-header"><h2>项目列表</h2><span class="badge" id="projCount">-</span></div>
      <div id="projContent" class="empty">加载中...</div>
    </div>
    <div class="card" style="margin-bottom:24px;">
      <div class="card-header"><h2>项目知识搜索</h2></div>
      <div class="search-box">
        <input type="text" id="projQueryInput" placeholder="输入问题搜索项目知识...">
        <select id="projSelect" style="background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:8px 12px;font-size:13px;outline:none;"></select>
        <button class="btn primary" onclick="queryProject()">查询</button>
      </div>
      <div id="projQueryResult" class="empty">输入问题并选择项目后查询...</div>
    </div>
  </div>

  <!-- ==================== 系统运维 ==================== -->
  <div class="tab-page" id="page-ops">
    <div class="grid-2">
      <div class="card">
        <div class="card-header"><h2>系统健康</h2></div>
        <div id="sysHealthContent" class="empty">加载中...</div>
      </div>
      <div class="card">
        <div class="card-header"><h2>系统诊断</h2></div>
        <div id="sysDiagContent" class="empty">加载中...</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-header"><h2>数据完整性检查</h2></div>
        <div id="sysIntegrityContent" class="empty">加载中...</div>
        <div class="ops-action-row" style="margin-top:10px;">
          <button class="btn primary" onclick="checkIntegrity()">运行检查</button>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h2>LLM 状态</h2></div>
        <div id="llmStatusContent" class="empty">加载中...</div>
        <div class="ops-action-row" style="margin-top:10px;">
          <button class="btn primary" onclick="checkLlmStatus()">刷新状态</button>
        </div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-header"><h2>数据清理</h2></div>
        <div style="margin-bottom:10px;">
          <label style="font-size:12px;color:var(--text-muted);margin-right:10px;">范围:</label>
          <select id="cleanupScope" style="background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:6px 10px;font-size:12px;">
            <option value="all">全部</option>
            <option value="old_logs">旧日志</option>
            <option value="orphan_data">孤立数据</option>
          </select>
        </div>
        <div class="ops-action-row">
          <button class="btn" onclick="runCleanup(false)">执行清理</button>
          <button class="btn" onclick="runCleanup(true)" style="color:var(--yellow);border-color:var(--yellow);">预览 (dry-run)</button>
        </div>
        <div id="cleanupResult" class="ops-result" style="display:none;margin-top:10px;"></div>
      </div>
      <div class="card">
        <div class="card-header"><h2>数据归档</h2></div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">归档旧数据以释放空间</div>
        <div class="ops-action-row">
          <button class="btn primary" onclick="runArchive()">执行归档</button>
        </div>
        <div id="archiveResult" class="ops-result" style="display:none;margin-top:10px;"></div>
      </div>
    </div>
  </div>

"""
# Insert before review-dialog
html = html.replace(
    '\n  <!-- 审核对话框 -->\n  <div class="review-dialog"',
    new_pages + '\n  <!-- 审核对话框 -->\n  <div class="review-dialog"',
)

# ── 3. Add new CSS ──
new_css = """
  .nav-tabs{display:flex;gap:8px;margin-bottom:24px;border-bottom:1px solid var(--border);padding-bottom:0;flex-wrap:wrap;}
  .nav-tabs .tab{padding:8px 16px;border-radius:6px 6px 0 0;font-size:13px;cursor:pointer;color:var(--text-muted);border:1px solid transparent;border-bottom:none;transition:all 0.2s;white-space:nowrap;}
  .nav-tabs .tab:hover{color:var(--text);}
  .nav-tabs .tab.active{color:var(--accent);border-color:var(--border);background:var(--card-bg);}
  .tab-page{display:none;}.tab-page.active{display:block;}
  .skill-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
  .skill-row .s-name{width:80px;font-size:12px;color:var(--text-muted);flex-shrink:0;}
  .skill-row .s-bar{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;}
  .skill-row .s-bar .s-fill{height:100%;border-radius:3px;transition:width 0.5s ease;}
  .skill-row .s-val{font-size:12px;width:36px;text-align:right;flex-shrink:0;}
  .search-box{display:flex;gap:8px;margin-bottom:12px;}
  .search-box input{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:8px 12px;font-size:13px;outline:none;}
  .search-box input:focus,.search-box select:focus{border-color:var(--accent);}
  .search-box select{background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:8px 12px;font-size:13px;outline:none;}
  .heatmap-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;}
  .heatmap-cell{aspect-ratio:1;border-radius:3px;min-width:16px;}
  .heatmap-labels{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-bottom:4px;}
  .heatmap-labels span{font-size:10px;color:var(--text-muted);text-align:center;}
  .timeline-item{display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;align-items:flex-start;}
  .timeline-item .tl-icon{font-size:16px;flex-shrink:0;}
  .timeline-item .tl-time{font-size:11px;color:var(--text-muted);flex-shrink:0;width:80px;}
  .timeline-item .tl-content{flex:1;}
  .timeline-item .tl-delta{font-size:11px;color:var(--accent);flex-shrink:0;}
  .trend-bar-chart{display:flex;align-items:flex-end;gap:2px;height:120px;padding-top:8px;}
  .trend-bar{flex:1;min-width:12px;background:var(--accent);border-radius:2px 2px 0 0;transition:height 0.5s ease;position:relative;}
  .trend-bar:hover{background:var(--accent-hover);}
  .trend-bar-label{font-size:9px;color:var(--text-muted);text-align:center;margin-top:4px;}
  .ops-action-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;}
  .ops-result{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px;font-family:monospace;font-size:11px;max-height:300px;overflow-y:auto;white-space:pre-wrap;line-height:1.5;color:var(--text-muted);}
"""
old_css_end = "@media (max-width:768px)"
html = html.replace(old_css_end, new_css + "\n  " + old_css_end)

# ── 4. Add JS for new panels ──
new_js = """
// ── Page switching ──
function switchPage(name, el) {
  document.querySelectorAll('#mainNav .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  if (name === 'growth') refreshGrowthPage();
  if (name === 'knowledge') listKnowledge();
  if (name === 'projects') refreshProjects();
  if (name === 'ops') refreshOpsPage();
}

// ── Trends chart ──
async function refreshTrends() {
  try {
    const d = await fetchJSON('/api/trends/system');
    const ts = d.timestamps || [];
    const ss = d.sessions || [];
    const maxVal = Math.max(...ss, 1);
    let html = '<div class="trend-bar-chart">';
    ts.forEach((t, i) => {
      const h = Math.max(4, Math.round((ss[i] / maxVal) * 100));
      html += `<div style="flex:1;text-align:center;"><div class="trend-bar" style="height:${h}px;" title="${t}: ${ss[i]} 个会话"></div><div class="trend-bar-label">${t}</div></div>`;
    });
    html += '</div>';
    document.getElementById('trendContent').innerHTML = html || '<div class="empty">无趋势数据</div>';
  } catch(e) { document.getElementById('trendContent').innerHTML = '<div class="empty">趋势数据获取失败</div>'; }
}

// ── Growth page ──
async function refreshGrowthPage() {
  await Promise.all([refreshUserOverview(), refreshSkillRadar(), refreshHeatmap(), refreshTimeline()]);
}
async function refreshUserOverview() {
  try {
    const d = await fetchJSON('/api/growth/user-overview');
    document.getElementById('ugTotalSkills').textContent = d.total_skills ?? '-';
    document.getElementById('ugAvgMastery').textContent = (d.avg_mastery ?? 0) + '%';
    document.getElementById('ugMasteryBar').style.width = (d.avg_mastery ?? 0) + '%';
    document.getElementById('ugStreakDays').textContent = d.streak_days ?? '-';
    document.getElementById('ugWeekNew').textContent = d.this_week_new ?? '-';
    document.getElementById('ugEfficiency').textContent = Math.round((d.learning_efficiency ?? 0) * 100) + '%';
    document.getElementById('ugEffBar').style.width = Math.round((d.learning_efficiency ?? 0) * 100) + '%';
    document.getElementById('ugTopDomain').textContent = d.top_domain || '-';
    document.getElementById('ugLastUpdate').textContent = '最后更新: ' + (d.last_updated || '-');
    const domains = d.skills_by_domain || [];
    if (domains.length > 0) {
      const maxCount = Math.max(...domains.map(dd => dd.count), 1);
      document.getElementById('domainDistContent').innerHTML = domains.map(dd => `
        <div class="skill-row">
          <span class="s-name">${escHtml(dd.domain)}</span>
          <div class="s-bar"><div class="s-fill" style="width:${Math.round((dd.count/maxCount)*100)}%;background:var(--accent);"></div></div>
          <span class="s-val">${dd.count}</span>
        </div>
      `).join('');
    }
  } catch(e) { /* silent */ }
}
async function refreshSkillRadar() {
  try {
    const d = await fetchJSON('/api/growth/skill-radar');
    const dims = d.dimensions || [];
    const curr = d.current_scores || [];
    const hist = d.historical_scores || d.thirty_days_ago_scores || [];
    if (dims.length > 0) {
      document.getElementById('radarContent').innerHTML = dims.map((dim, i) => {
        const c = curr[i] || 0;
        const h = hist[i] || 0;
        const diff = c - h;
        const cls = diff > 0 ? 'up' : (diff < 0 ? 'down' : '');
        return `<div class="skill-row">
          <span class="s-name">${escHtml(dim)}</span>
          <div class="s-bar"><div class="s-fill" style="width:${c}%;background:var(--accent);"></div></div>
          <span class="s-val">${c}</span>
          <span class="metric-change ${cls}" style="width:50px;text-align:right;">${diff > 0 ? '+' + diff : diff}</span>
        </div>`;
      }).join('');
    }
  } catch(e) { /* silent */ }
}
async function refreshHeatmap() {
  try {
    const d = await fetchJSON('/api/growth/activity-heatmap');
    document.getElementById('heatActiveDays').textContent = '活跃 ' + (d.active_days || 0) + ' 天';
    document.getElementById('heatPeak').textContent = (d.peak_intensity ?? 0).toFixed(1);
    document.getElementById('heatAvg').textContent = (d.avg_intensity ?? 0).toFixed(1);
    const labels = d.labels || ['一','二','三','四','五','六','日'];
    document.getElementById('heatLabels').innerHTML = labels.map(l => '<span>' + l + '</span>').join('');
    const daily = d.daily_data || [];
    if (daily.length > 0) {
      const maxV = Math.max(...daily.map(dd => dd.intensity || 0), 0.1);
      document.getElementById('heatGrid').innerHTML = daily.map(dd => {
        const v = dd.intensity || 0;
        const alpha = v / maxV;
        const color = alpha > 0.7 ? 'var(--accent)' : (alpha > 0.4 ? 'rgba(99,102,241,0.7)' : (alpha > 0.05 ? 'rgba(99,102,241,0.4)' : '#1a1d27'));
        return '<div class="heatmap-cell" style="background:' + color + ';" title="' + dd.date + ': ' + v.toFixed(1) + '"></div>';
      }).join('');
    }
  } catch(e) { /* silent */ }
}
async function refreshTimeline() {
  try {
    const d = await fetchJSON('/api/growth/timeline?limit=30');
    document.getElementById('tlTotal').textContent = d.total_events ?? 0;
    const events = d.events || [];
    if (events.length > 0) {
      document.getElementById('timelineContent').innerHTML = events.map(e => `
        <div class="timeline-item">
          <span class="tl-icon">${e.icon || '•'}</span>
          <span class="tl-time">${fmtTime(e.time)}</span>
          <span class="tl-content">${escHtml(e.content || '')}</span>
          <span class="tl-delta">${escHtml(e.delta || e.impact || '')}</span>
        </div>
      `).join('');
    }
  } catch(e) { /* silent */ }
}

// ── Knowledge page ──
async function listKnowledge() {
  try {
    const d = await fetchJSON('/api/knowledge/list?limit=100');
    const items = d.data?.items || d.data || [];
    document.getElementById('kbListTotal').textContent = items.length;
    if (items.length > 0) {
      document.getElementById('kbSearchResults').innerHTML = items.map(item => `
        <div class="growth-item">
          <div class="g-header">
            <span class="g-title">${escHtml(item.title || '')}</span>
            <span class="tag low">${escHtml(item.domain || '')}</span>
          </div>
          <div class="g-body">${escHtml((item.content || '').slice(0, 200))}</div>
          <div class="g-meta">${escHtml(item.category || '')} | ${formatDate(item.timestamp || item.created_at)}</div>
        </div>
      `).join('');
    } else {
      document.getElementById('kbSearchResults').innerHTML = '<div class="empty">知识库为空</div>';
    }
  } catch(e) { document.getElementById('kbSearchResults').innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>'; }
}
async function searchKnowledge() {
  const q = document.getElementById('kbSearchInput').value.trim();
  if (!q) { listKnowledge(); return; }
  try {
    const d = await fetchJSON('/api/knowledge/search?query=' + encodeURIComponent(q));
    const items = d.data || [];
    document.getElementById('kbListTotal').textContent = items.length;
    if (items.length > 0) {
      document.getElementById('kbSearchResults').innerHTML = items.map(item => `
        <div class="growth-item">
          <div class="g-header">
            <span class="g-title">${escHtml(item.title || '')}</span>
            <span class="tag low">${escHtml(item.domain || '')}</span>
          </div>
          <div class="g-body">${escHtml((item.content || '').slice(0, 200))}</div>
          <div class="g-meta">${escHtml(item.category || '')} | ${formatDate(item.timestamp || item.created_at)}</div>
        </div>
      `).join('');
    } else {
      document.getElementById('kbSearchResults').innerHTML = '<div class="empty">未找到匹配结果</div>';
    }
  } catch(e) { document.getElementById('kbSearchResults').innerHTML = '<div class="empty">搜索失败: ' + e.message + '</div>'; }
}

// ── Projects page ──
async function refreshProjects() {
  try {
    const d = await fetchJSON('/api/projects/list');
    const projects = d.projects || [];
    document.getElementById('projCount').textContent = projects.length;
    const sel = document.getElementById('projSelect');
    sel.innerHTML = '<option value="">-- 选择项目 --</option>' + projects.map(p => '<option value="' + escHtml(p) + '">' + escHtml(p) + '</option>').join('');
    if (projects.length > 0) {
      document.getElementById('projContent').innerHTML = projects.map(p => `
        <div class="growth-item" style="cursor:pointer;" onclick="document.getElementById('projSelect').value='${escHtml(p)}';queryProject();">
          <div class="g-title">${escHtml(p)}</div>
        </div>
      `).join('');
    } else {
      document.getElementById('projContent').innerHTML = '<div class="empty">暂无项目数据</div>';
    }
  } catch(e) { /* silent */ }
}
async function queryProject() {
  const project = document.getElementById('projSelect').value;
  const question = document.getElementById('projQueryInput').value.trim();
  if (!question && !project) return;
  try {
    const body = { question, project_name: project || undefined, limit: 10 };
    const res = await fetch('/api/projects/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await res.json();
    const items = d.results || d.data || [];
    if (items.length > 0) {
      document.getElementById('projQueryResult').innerHTML = items.map(item => `
        <div class="growth-item">
          <div class="g-header">
            <span class="g-title">${escHtml(item.title || '')}</span>
            <span class="tag low">${escHtml(item.domain || '')}</span>
          </div>
          <div class="g-body">${escHtml((item.content || '').slice(0, 200))}</div>
        </div>
      `).join('');
    } else {
      document.getElementById('projQueryResult').innerHTML = '<div class="empty">未找到结果</div>';
    }
  } catch(e) { document.getElementById('projQueryResult').innerHTML = '<div class="empty">查询失败: ' + e.message + '</div>'; }
}

// ── Ops page ──
async function refreshOpsPage() {
  await Promise.all([refreshSysHealth(), refreshSysDiagnose()]);
}
async function refreshSysHealth() {
  try {
    const d = await fetchJSON('/api/system/health');
    const items = Object.entries(d.services || d).filter(([k]) => k !== 'status' && k !== 'version');
    document.getElementById('sysHealthContent').innerHTML = items.map(([k, v]) => {
      const healthy = typeof v === 'object' ? (v.healthy !== false) : true;
      const dot = healthy ? '<span class="status-dot online"></span>' : '<span class="status-dot offline"></span>';
      const detail = typeof v === 'object' ? (v.detail || v.status || '') : String(v);
      return '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">' +
        '<span>' + dot + ' ' + escHtml(k) + '</span>' +
        '<span style="font-size:12px;color:var(--text-muted);">' + escHtml(detail) + '</span></div>';
    }).join('') || '<div class="empty">无服务数据</div>';
  } catch(e) { document.getElementById('sysHealthContent').innerHTML = '<div class="empty">获取失败</div>'; }
}
async function refreshSysDiagnose() {
  try {
    const d = await fetchJSON('/api/system/diagnose');
    document.getElementById('sysDiagContent').innerHTML = '<pre style="font-size:11px;line-height:1.5;white-space:pre-wrap;">' + escHtml(JSON.stringify(d, null, 2)) + '</pre>';
  } catch(e) { document.getElementById('sysDiagContent').innerHTML = '<div class="empty">诊断失败</div>'; }
}
async function checkIntegrity() {
  try {
    const d = await fetchJSON('/api/system/check-integrity');
    document.getElementById('sysIntegrityContent').innerHTML = '<pre style="font-size:11px;line-height:1.5;white-space:pre-wrap;">' + escHtml(JSON.stringify(d, null, 2)) + '</pre>';
  } catch(e) { document.getElementById('sysIntegrityContent').innerHTML = '<div class="empty">检查失败: ' + e.message + '</div>'; }
}
async function checkLlmStatus() {
  try {
    const d = await fetchJSON('/api/system/llm-status');
    document.getElementById('llmStatusContent').innerHTML = '<pre style="font-size:11px;line-height:1.5;white-space:pre-wrap;">' + escHtml(JSON.stringify(d, null, 2)) + '</pre>';
  } catch(e) { document.getElementById('llmStatusContent').innerHTML = '<div class="empty">获取失败: ' + e.message + '</div>'; }
}
async function runCleanup(dryRun) {
  const scope = document.getElementById('cleanupScope').value;
  try {
    const res = await fetch('/api/system/cleanup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope, dry_run: dryRun }) });
    const d = await res.json();
    const el = document.getElementById('cleanupResult');
    el.style.display = 'block';
    el.textContent = JSON.stringify(d, null, 2);
  } catch(e) {
    const el = document.getElementById('cleanupResult');
    el.style.display = 'block';
    el.textContent = '错误: ' + e.message;
  }
}
async function runArchive() {
  try {
    const res = await fetch('/api/archive/cleanup', { method: 'POST' });
    const d = await res.json();
    const el = document.getElementById('archiveResult');
    el.style.display = 'block';
    el.textContent = JSON.stringify(d, null, 2);
  } catch(e) {
    const el = document.getElementById('archiveResult');
    el.style.display = 'block';
    el.textContent = '错误: ' + e.message;
  }
}
"""

old_js_refreshAll = "async function refreshAll() {"
html = html.replace(old_js_refreshAll, new_js + "\n" + old_js_refreshAll)

# ── 5. Add new refresh calls to refreshAll ──
old_refresh_all_body = "    refreshGrowth(),\n  ]);"
new_refresh_all_body = "    refreshGrowth(),\n    refreshTrends(),\n  ]);"
html = html.replace(old_refresh_all_body, new_refresh_all_body)

# Write back
with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

open(os.path.join(BASE, "_gen_result.txt"), "w").write("OK " + str(len(html)))
