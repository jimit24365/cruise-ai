// ═══════════════════════════════════════════════════════
// dashboard.js — Fetch and render dashboard data
// ═══════════════════════════════════════════════════════

(function () {
  'use strict';

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function fmtNum(n) {
    return (n || 0).toLocaleString();
  }

  function renderStats(usage) {
    var el = document.getElementById('statCards');
    if (!usage) { el.innerHTML = '<div class="empty">No usage data available.</div>'; return; }

    var activeDays = 0;
    if (window._dashData && window._dashData.daily) {
      activeDays = Object.keys(window._dashData.daily).length;
    }

    el.innerHTML = [
      { value: fmtNum(usage.total_sessions), label: 'Total Sessions' },
      { value: fmtNum(usage.total_tokens_estimated), label: 'Total Tokens (est.)' },
      { value: fmtNum(activeDays), label: 'Active Days' },
      { value: fmtNum(usage.total_prompts), label: 'Total Prompts' },
      { value: fmtNum(usage.total_responses), label: 'Total Responses' },
      { value: fmtNum(usage.avg_prompt_words), label: 'Avg Prompt Words' }
    ].map(function (s) {
      return '<div class="stat-card"><div class="sc-value">' + s.value + '</div><div class="sc-label">' + s.label + '</div></div>';
    }).join('');
  }

  function renderCost(cost) {
    var el = document.getElementById('costBody');
    if (!cost || !cost.total_estimated_cost_usd) {
      el.innerHTML = '<div class="empty">No cost data available.</div>';
      return;
    }

    var html = '<div class="cost-total">$' + cost.total_estimated_cost_usd.toFixed(2) + ' estimated</div>';
    if (cost.tokens_total) {
      html += '<div class="cost-detail">' + fmtNum(cost.tokens_total) + ' tokens total</div>';
    }

    if (cost.by_model && Object.keys(cost.by_model).length) {
      html += '<div class="bar-chart">';
      var models = Object.entries(cost.by_model).sort(function (a, b) { return b[1] - a[1]; });
      var maxCost = models[0] ? models[0][1] : 1;
      models.forEach(function (entry) {
        var pct = Math.max(2, (entry[1] / maxCost) * 100);
        html += '<div class="bar-row">';
        html += '<span class="bar-label">' + esc(entry[0]) + '</span>';
        html += '<span class="bar-track"><span class="bar-fill" style="width:' + pct + '%"></span></span>';
        html += '<span class="bar-value">$' + entry[1].toFixed(2) + '</span>';
        html += '</div>';
      });
      html += '</div>';
    }

    el.innerHTML = html;
  }

  function renderModels(models) {
    var el = document.getElementById('modelsBody');
    if (!models || !Object.keys(models).length) {
      el.innerHTML = '<div class="empty">No model data available.</div>';
      return;
    }

    var entries = Object.entries(models).sort(function (a, b) { return b[1] - a[1]; });
    var max = entries[0] ? entries[0][1] : 1;

    var html = '<div class="bar-chart">';
    entries.forEach(function (entry) {
      var pct = Math.max(2, (entry[1] / max) * 100);
      html += '<div class="bar-row">';
      html += '<span class="bar-label">' + esc(entry[0]) + '</span>';
      html += '<span class="bar-track"><span class="bar-fill" style="width:' + pct + '%;background:var(--blue)"></span></span>';
      html += '<span class="bar-value">' + fmtNum(entry[1]) + '</span>';
      html += '</div>';
    });
    html += '</div>';
    el.innerHTML = html;
  }

  function renderProjects(projects) {
    var el = document.getElementById('projectsBody');
    if (!projects || !Object.keys(projects).length) {
      el.innerHTML = '<div class="empty">No project data available.</div>';
      return;
    }

    var entries = Object.entries(projects).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 20);
    var html = '<table class="proj-table"><thead><tr><th>Project</th><th>Sessions</th></tr></thead><tbody>';
    entries.forEach(function (entry) {
      html += '<tr><td>' + esc(entry[0]) + '</td><td>' + fmtNum(entry[1]) + '</td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  }

  function renderTimeline(daily) {
    var el = document.getElementById('timelineBody');
    if (!daily || !Object.keys(daily).length) {
      el.innerHTML = '<div class="empty">No activity data available.</div>';
      return;
    }

    var days = Object.entries(daily).sort(function (a, b) { return a[0].localeCompare(b[0]); });
    var maxSessions = Math.max.apply(null, days.map(function (d) { return d[1].sessions || 0; }).concat([1]));

    var html = '<div class="timeline-chart">';
    days.forEach(function (entry) {
      var sessions = entry[1].sessions || 0;
      var height = Math.max(2, (sessions / maxSessions) * 100);
      html += '<div class="tl-bar" style="height:' + height + '%" title="' + esc(entry[0]) + ': ' + sessions + ' sessions"></div>';
    });
    html += '</div>';

    if (days.length > 1) {
      html += '<div class="tl-dates"><span>' + esc(days[0][0]) + '</span><span>' + esc(days[days.length - 1][0]) + '</span></div>';
    }

    el.innerHTML = html;
  }

  function renderLongitudinal(data) {
    var el = document.getElementById('longitudinalBody');
    if (!data || data.status === 'insufficient_data') {
      el.innerHTML = '<div class="empty">Not enough snapshots yet. Run recommendations multiple times to see trends.</div>';
      return;
    }

    var trends = data.trends || {};
    var keys = Object.keys(trends);
    if (!keys.length) {
      el.innerHTML = '<div class="empty">No trend data available yet.</div>';
      return;
    }

    var html = '<div class="trend-grid">';
    keys.forEach(function (key) {
      var t = trends[key];
      var changeClass = t.improved === true ? 'improved' : t.improved === false ? 'regressed' : 'neutral';
      var changeSign = t.change > 0 ? '+' : '';
      html += '<div class="trend-card">';
      html += '<div class="trend-metric">' + esc(key.replace(/([A-Z])/g, ' $1').trim()) + '</div>';
      html += '<div class="trend-values">';
      html += '<span class="trend-current">' + (typeof t.after === 'number' ? t.after.toLocaleString() : esc(String(t.after))) + '</span>';
      html += '<span class="trend-change ' + changeClass + '">' + changeSign + t.pct_change + '%</span>';
      html += '</div>';
      html += '</div>';
    });
    html += '</div>';

    if (data.first_date && data.latest_date) {
      html += '<div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:10px">'
        + esc(data.first_date) + ' → ' + esc(data.latest_date)
        + ' (' + data.snapshots_count + ' snapshots)</div>';
    }

    el.innerHTML = html;
  }

  function load() {
    // Load dashboard data
    fetch('/api/dashboard')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) {
          document.getElementById('statCards').innerHTML = '<div class="empty">Failed to load dashboard data.</div>';
          return;
        }
        window._dashData = data;
        renderStats(data.usage);
        renderCost(data.cost);
        renderModels(data.models);
        renderProjects(data.projects);
        renderTimeline(data.daily);
      })
      .catch(function () {
        document.getElementById('statCards').innerHTML = '<div class="empty">Failed to load dashboard data.</div>';
      });

    // Load longitudinal data
    fetch('/api/longitudinal')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        renderLongitudinal(data);
      })
      .catch(function () {
        document.getElementById('longitudinalBody').innerHTML = '<div class="empty">Failed to load trend data.</div>';
      });
  }

  load();
})();
