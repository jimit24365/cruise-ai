// ═══════════════════════════════════════════════════════
// recommend.js — Fetch and render recommendation cards
// ═══════════════════════════════════════════════════════

(function () {
  'use strict';

  var allRecs = [];
  var activeCategory = 'all';

  var TRUST_ICONS = {
    validated: { icon: '✓✓', cls: 'trust-validated', label: 'Validated' },
    observed: { icon: '✓', cls: 'trust-observed', label: 'Observed' },
    heuristic: { icon: '~', cls: 'trust-heuristic', label: 'Heuristic' },
    experimental: { icon: '?', cls: 'trust-experimental', label: 'Experimental' }
  };

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function formatSavings(savings) {
    if (!savings || typeof savings !== 'object') return '';
    var parts = [];
    if (savings.tokens) parts.push(savings.tokens.toLocaleString() + ' tokens');
    if (savings.cost_usd) parts.push('$' + savings.cost_usd.toFixed(2));
    if (savings.time) parts.push(savings.time);
    return parts.join(' · ');
  }

  function renderCard(rec, idx) {
    var trust = TRUST_ICONS[rec.trust_level] || TRUST_ICONS.heuristic;
    var savingsStr = formatSavings(rec.savings_estimate);

    var html = '<div class="rec-card" data-category="' + esc(rec.category) + '" data-idx="' + idx + '">';
    html += '<div class="rc-head">';
    html += '<span class="rc-headline">' + esc(rec.headline) + '</span>';
    html += '<span class="rc-badges">';
    html += '<span class="rc-priority ' + esc(rec.priority) + '">' + esc(rec.priority) + '</span>';
    html += '<span class="rc-trust"><span class="rc-trust-icon ' + trust.cls + '">' + trust.icon + '</span>' + trust.label + '</span>';
    html += '</span></div>';

    html += '<div class="rc-detail">' + esc(rec.detail) + '</div>';
    html += '<div class="rc-category">' + esc(rec.category.replace(/_/g, ' ')) + '</div>';
    html += '<div class="rc-evidence">' + esc(rec.evidence) + '</div>';

    if (savingsStr) {
      html += '<div class="rc-savings">💰 ' + esc(savingsStr) + '</div>';
    }

    if (rec.teach_text) {
      html += '<div class="rc-teach">';
      html += '<button class="rc-teach-toggle" onclick="toggleTeach(this)">▸ Why this matters</button>';
      html += '<div class="rc-teach-body">' + esc(rec.teach_text) + '</div>';
      html += '</div>';
    }

    html += '<div class="rc-feedback">';
    html += '<button class="rc-fb-btn" onclick="sendFeedback(this,\'' + esc(rec.action_type) + '\',\'' + esc(rec.category) + '\',\'acted\',\'' + esc(rec.headline).replace(/'/g, '') + '\')">✓ Acted</button>';
    html += '<button class="rc-fb-btn" onclick="sendFeedback(this,\'' + esc(rec.action_type) + '\',\'' + esc(rec.category) + '\',\'dismissed\',\'' + esc(rec.headline).replace(/'/g, '') + '\')">✕ Dismissed</button>';
    html += '<button class="rc-fb-btn" onclick="sendFeedback(this,\'' + esc(rec.action_type) + '\',\'' + esc(rec.category) + '\',\'useful\',\'' + esc(rec.headline).replace(/'/g, '') + '\')">👍 Useful</button>';
    html += '<button class="rc-fb-btn" onclick="sendFeedback(this,\'' + esc(rec.action_type) + '\',\'' + esc(rec.category) + '\',\'not_useful\',\'' + esc(rec.headline).replace(/'/g, '') + '\')">👎 Not Useful</button>';
    html += '</div>';

    html += '</div>';
    return html;
  }

  function render() {
    var container = document.getElementById('recCards');
    var filtered = activeCategory === 'all'
      ? allRecs
      : allRecs.filter(function (r) { return r.category === activeCategory; });

    if (!filtered.length) {
      container.innerHTML = '<div class="empty">No recommendations available' +
        (activeCategory !== 'all' ? ' for this category' : '') +
        '. Run more AI coding sessions to generate coaching insights.</div>';
      return;
    }

    container.innerHTML = filtered.map(function (r, i) { return renderCard(r, i); }).join('');
  }

  function initFilters() {
    var btns = document.querySelectorAll('.filter-btn');
    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        btns.forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        activeCategory = btn.getAttribute('data-category');
        render();
      });
    });
  }

  function load() {
    fetch('/api/recommend')
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (data) {
        allRecs = data || [];
        render();
      })
      .catch(function () {
        document.getElementById('recCards').innerHTML =
          '<div class="empty">Failed to load recommendations. Is the server running?</div>';
      });
  }

  // Global functions for onclick handlers
  window.toggleTeach = function (btn) {
    var body = btn.nextElementSibling;
    var open = body.classList.toggle('open');
    btn.textContent = (open ? '▾' : '▸') + ' Why this matters';
  };

  window.sendFeedback = function (btn, actionType, category, response, headline) {
    if (btn.classList.contains('sent')) return;
    fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action_type: actionType,
        category: category,
        response: response,
        headline: headline,
        notes: ''
      })
    }).then(function (r) {
      if (r.ok) {
        btn.classList.add('sent');
        btn.textContent = '✓ Sent';
      }
    }).catch(function () {});
  };

  // Init
  initFilters();
  load();
})();
