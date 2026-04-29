/**
 * performance.js — Dashboard Affidabilità Predittiva Trading AI
 *
 * Gestisce:
 * 1. Caricamento statistiche aggregate (/api/performance/stats)
 * 2. Rendering KPI cards, grafici donut, tabelle
 * 3. Lista storico analisi con paginazione e filtri
 * 4. Azioni: ricarica, esporta CSV, ri-verifica outcome
 */

'use strict';

const Performance = (() => {
  // ── Stato ────────────────────────────────────────────────────────────
  let _state = {
    page:       1,
    perPage:    20,
    filterMarket:  '',
    filterOutcome: '',
    filterSymbol:  '',
    totalItems:    0,
    _filterTimer:  null,
  };

  // ── Label / Colori ────────────────────────────────────────────────────
  const MARKET_LABELS = {
    commodity: 'Materie Prime',
    stock:     'Azioni',
    forex:     'Forex',
    crypto:    'Crypto',
    index:     'Indici',
    etf:       'ETF',
    other:     'Altro',
    unknown:   'Sconosciuto',
  };

  const OUTCOME_CONFIG = {
    win_tp2:   { label: '✅ Win TP2',    cls: 'badge-win',  color: '#03F5A9' },
    win_tp1:   { label: '✅ Win TP1',    cls: 'badge-win',  color: '#4ade80' },
    loss_sl:   { label: '❌ Loss SL',    cls: 'badge-loss', color: '#CF6679' },
    no_entry:  { label: '⏳ No Entry',   cls: 'badge-none', color: '#94a3b8' },
    open:      { label: '🔵 Aperto',     cls: 'badge-open', color: '#fbbf24' },
    no_trade:  { label: '⚪ No Trade',   cls: 'badge-none', color: '#64748b' },
    no_data:   { label: '🔘 No Data',    cls: 'badge-none', color: '#475569' },
  };

  const DIRECTION_CONFIG = {
    bullish: { label: '📈 Bullish', cls: 'badge-bull' },
    bearish: { label: '📉 Bearish', cls: 'badge-bear' },
    neutral: { label: '↔️ Neutrale', cls: 'badge-neutral' },
    unknown: { label: '❓ Unknown', cls: 'badge-none' },
  };

  // ── Helpers ───────────────────────────────────────────────────────────

  function _fmt(v, suffix = '', fallback = '—') {
    if (v === null || v === undefined) return fallback;
    return `${v}${suffix}`;
  }

  function _fmtPct(v, fallback = '—') {
    if (v === null || v === undefined) return fallback;
    const cls = v >= 0 ? 'green' : 'red';
    return `<span style="color:var(--${cls},${v >= 0 ? '#03F5A9' : '#CF6679'})">${v >= 0 ? '+' : ''}${v}%</span>`;
  }

  function _fmtPrice(v) {
    if (v === null || v === undefined) return '—';
    return Number(v).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }

  function _fmtDate(iso) {
    if (!iso) return '—';
    return iso.slice(0, 10);
  }

  function _outcomeBadge(outcome) {
    const cfg = OUTCOME_CONFIG[outcome] || { label: outcome || '—', cls: 'badge-none' };
    return `<span class="badge ${cfg.cls}">${cfg.label}</span>`;
  }

  function _dirBadge(dir) {
    const cfg = DIRECTION_CONFIG[dir] || { label: dir || '—', cls: 'badge-none' };
    return `<span class="badge ${cfg.cls}">${cfg.label}</span>`;
  }

  function _winRateColor(wr) {
    if (wr === null || wr === undefined) return '#64748b';
    if (wr >= 60) return '#03F5A9';
    if (wr >= 45) return '#fbbf24';
    return '#CF6679';
  }

  function _showToast(msg, type = 'info') {
    const cont = document.getElementById('toastContainer');
    if (!cont) return;
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    cont.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3000);
  }

  // ── SVG Donut ─────────────────────────────────────────────────────────

  function _buildDonut(segments, size = 120, thickness = 22) {
    // segments: [{value, color, label}]
    const total = segments.reduce((s, x) => s + (x.value || 0), 0);
    if (total === 0) {
      return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size/2}" cy="${size/2}" r="${(size-thickness)/2}"
          fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="${thickness}"/>
      </svg>`;
    }

    const r  = (size - thickness) / 2;
    const cx = size / 2, cy = size / 2;
    const circ = 2 * Math.PI * r;
    let offset = 0;
    let paths  = '';

    for (const seg of segments) {
      if (!seg.value) continue;
      const pct  = seg.value / total;
      const dash = pct * circ;
      const gap  = circ - dash;
      paths += `<circle
        cx="${cx}" cy="${cy}" r="${r}"
        fill="none"
        stroke="${seg.color}"
        stroke-width="${thickness}"
        stroke-dasharray="${dash.toFixed(2)} ${gap.toFixed(2)}"
        stroke-dashoffset="${(-offset * circ + circ / 4).toFixed(2)}"
        transform="rotate(-90 ${cx} ${cy})"
        opacity="0.9"
      />`;
      offset += pct;
    }

    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${paths}</svg>`;
  }

  function _renderDonutCard(title, centerVal, centerLbl, segments) {
    const svg = _buildDonut(segments);
    const legend = segments.map(s =>
      `<div class="donut-legend-item">
        <span class="donut-legend-dot" style="background:${s.color}"></span>
        <span>${s.label}</span>
        <span class="donut-legend-val">${s.value}</span>
      </div>`
    ).join('');

    return `
      <div class="chart-card">
        <div class="chart-card-title">${title}</div>
        <div class="donut-wrap">
          ${svg}
          <div class="donut-center">
            <div class="donut-center-val">${centerVal}</div>
            <div class="donut-center-lbl">${centerLbl}</div>
          </div>
        </div>
        <div class="donut-legend">${legend}</div>
      </div>`;
  }

  // ── KPI Grid ──────────────────────────────────────────────────────────

  function _renderKPIs(stats) {
    const kpis = [
      {
        label: 'Analisi Totali',
        value: stats.total_analyses ?? 0,
        cls: 'blue',
        sub: `di cui ${stats.total_verified ?? 0} verificate`,
      },
      {
        label: 'Win Rate',
        value: stats.win_rate !== null ? `${stats.win_rate}%` : '—',
        cls: stats.win_rate >= 50 ? 'green' : (stats.win_rate !== null ? 'red' : ''),
        sub: `${stats.wins ?? 0} win · ${stats.losses ?? 0} loss`,
      },
      {
        label: 'P&L Medio',
        value: stats.avg_pnl !== null ? `${stats.avg_pnl >= 0 ? '+' : ''}${stats.avg_pnl}%` : '—',
        cls: (stats.avg_pnl ?? 0) >= 0 ? 'green' : 'red',
        sub: `Max: ${stats.max_pnl ?? '—'}% · Min: ${stats.min_pnl ?? '—'}%`,
      },
      {
        label: 'Err. Previsione AI',
        value: stats.avg_forecast_err !== null ? `${stats.avg_forecast_err}%` : '—',
        cls: (stats.avg_forecast_err ?? 999) <= 5 ? 'green' : ((stats.avg_forecast_err ?? 999) <= 15 ? '' : 'red'),
        sub: 'scostamento medio dal prezzo reale',
      },
      {
        label: 'Dir. Corretta %',
        value: stats.dir_accuracy !== null ? `${stats.dir_accuracy}%` : '—',
        cls: (stats.dir_accuracy ?? 0) >= 60 ? 'green' : ((stats.dir_accuracy ?? 0) >= 45 ? '' : 'red'),
        sub: 'direzione predetta vs movimento reale',
      },
      {
        label: 'Giorni a Entry',
        value: stats.avg_days_to_entry !== null ? `${stats.avg_days_to_entry}gg` : '—',
        cls: 'purple',
        sub: 'tempo medio prima del trigger',
      },
      {
        label: 'Giorni a Exit',
        value: stats.avg_days_to_exit !== null ? `${stats.avg_days_to_exit}gg` : '—',
        cls: 'purple',
        sub: 'durata media del trade (entry→exit)',
      },
      {
        label: 'No Entry %',
        value: stats.outcome_dist
          ? _fmt(
              Math.round((stats.outcome_dist.no_entry || 0) / Math.max(stats.total_verified, 1) * 100),
              '%'
            )
          : '—',
        cls: '',
        sub: 'analisi senza trigger entry',
      },
    ];

    return kpis.map(k => `
      <div class="kpi-card">
        <div class="kpi-label">${k.label}</div>
        <div class="kpi-value ${k.cls}">${k.value}</div>
        ${k.sub ? `<div class="kpi-sub">${k.sub}</div>` : ''}
      </div>
    `).join('');
  }

  // ── Grafici distribuzione ─────────────────────────────────────────────

  function _renderCharts(stats) {
    const od = stats.outcome_dist || {};
    const totalVer = stats.total_verified || 0;

    // Donut 1: Esiti trade
    const outcomeSegs = [
      { value: (od.win_tp2 || 0) + (od.win_tp1 || 0), color: '#03F5A9', label: 'Win' },
      { value: od.loss_sl || 0,   color: '#CF6679', label: 'Loss SL' },
      { value: od.no_entry || 0,  color: '#94a3b8', label: 'No Entry' },
      { value: od.open || 0,      color: '#fbbf24', label: 'Aperto' },
      { value: (od.no_trade || 0) + (od.no_data || 0), color: '#475569', label: 'No Trade/Data' },
    ].filter(s => s.value > 0);
    const wr = stats.win_rate !== null ? `${stats.win_rate}%` : '—';
    const donut1 = _renderDonutCard('Distribuzione Esiti', wr, 'Win Rate', outcomeSegs);

    // Donut 2: Direzione
    const bydDir = stats.by_direction || [];
    const dirSegs = [
      { value: bydDir.find(d => d.direction === 'bullish')?.total || 0, color: '#03F5A9', label: '📈 Bullish' },
      { value: bydDir.find(d => d.direction === 'bearish')?.total || 0, color: '#CF6679', label: '📉 Bearish' },
      { value: bydDir.find(d => d.direction === 'neutral')?.total || 0, color: '#94a3b8', label: '↔️ Neutrale' },
    ].filter(s => s.value > 0);
    const totalDir = dirSegs.reduce((s, x) => s + x.value, 0);
    const donut2 = _renderDonutCard('Direzione Predetta', totalDir, 'analisi', dirSegs);

    // Donut 3: Tipo mercato
    const byMkt = stats.by_market || [];
    const mktColors = { commodity: '#f59e0b', stock: '#3fbef5', forex: '#BB86FC', crypto: '#f97316', index: '#06b6d4', etf: '#84cc16', other: '#64748b' };
    const mktSegs = byMkt.map(m => ({
      value: m.total,
      color: mktColors[m.market_type] || '#64748b',
      label: m.label,
    })).filter(s => s.value > 0);
    const donut3 = _renderDonutCard('Mercati Analizzati', stats.total_analyses || 0, 'totale', mktSegs);

    return donut1 + donut2 + donut3;
  }

  // ── Tabella Mercati ───────────────────────────────────────────────────

  function _renderMarketTable(stats) {
    const rows = stats.by_market || [];
    if (!rows.length) return '<div class="empty-state"><div style="color:#475569;padding:20px;">Nessun dato disponibile</div></div>';

    const thead = `<thead><tr>
      <th>Mercato</th>
      <th data-tooltip="Analisi totali effettuate">Totale</th>
      <th data-tooltip="Analisi con esito verificato">Verificate</th>
      <th>Win</th>
      <th>Loss</th>
      <th data-tooltip="Entry mai toccata">No Entry</th>
      <th data-tooltip="Trade ancora aperto nella finestra">Aperti</th>
      <th data-tooltip="Win / (Win+Loss) × 100">Win Rate</th>
      <th data-tooltip="P&L medio sui trade chiusi">P&L Medio</th>
      <th data-tooltip="Giorni medi prima del trigger entry">⏱️ Entry</th>
      <th data-tooltip="Giorni medi da entry all'exit">⏱️ Exit</th>
      <th data-tooltip="Scostamento medio previsione AI dal prezzo reale">Err. Fcst</th>
      <th data-tooltip="% volte che la direzione predetta corrisponde al movimento reale">Dir. OK%</th>
    </tr></thead>`;

    const tbody = rows.map(r => {
      const wr = r.win_rate !== null ? r.win_rate : null;
      const wrStyle = `color:${_winRateColor(wr)};font-weight:700;`;
      return `<tr>
        <td><strong>${r.label}</strong></td>
        <td>${r.total}</td>
        <td>${r.verified}</td>
        <td style="color:#03F5A9;">${r.wins}</td>
        <td style="color:#CF6679;">${r.losses}</td>
        <td style="color:#94a3b8;">${r.no_entry}</td>
        <td style="color:#fbbf24;">${r.open_trades}</td>
        <td>
          <div class="mini-bar-wrap">
            <div class="mini-bar">
              <div class="mini-bar-fill" style="width:${wr || 0}%;background:${_winRateColor(wr)};"></div>
            </div>
            <span class="mini-bar-val" style="${wrStyle}">${wr !== null ? wr + '%' : '—'}</span>
          </div>
        </td>
        <td>${r.avg_pnl !== null ? `<span style="color:${(r.avg_pnl||0)>=0?'#03F5A9':'#CF6679'}">${(r.avg_pnl||0)>=0?'+':''}${r.avg_pnl}%</span>` : '—'}</td>
        <td>${r.avg_days_entry !== null ? r.avg_days_entry + 'gg' : '—'}</td>
        <td>${r.avg_days_exit !== null ? r.avg_days_exit + 'gg' : '—'}</td>
        <td>${r.avg_forecast_err !== null ? r.avg_forecast_err + '%' : '—'}</td>
        <td>${r.dir_accuracy !== null ? r.dir_accuracy + '%' : '—'}</td>
      </tr>`;
    }).join('');

    return `<table class="perf-table">${thead}<tbody>${tbody}</tbody></table>`;
  }

  // ── Tabella Direzione ─────────────────────────────────────────────────

  function _renderDirectionTable(stats) {
    const rows = stats.by_direction || [];
    if (!rows.length) return '<div style="color:#475569;padding:20px;">Nessun dato</div>';

    const thead = `<thead><tr>
      <th>Direzione</th>
      <th>Totale</th>
      <th>Win</th>
      <th>Loss</th>
      <th>Win Rate</th>
      <th>P&L Medio</th>
      <th>Giorni Exit</th>
      <th>Err. Forecast</th>
    </tr></thead>`;

    const tbody = rows.map(r => {
      const cfg = DIRECTION_CONFIG[r.direction] || { label: r.direction, cls: 'badge-none' };
      const wr  = r.win_rate;
      return `<tr>
        <td><span class="badge ${cfg.cls}">${cfg.label}</span></td>
        <td>${r.total}</td>
        <td style="color:#03F5A9;">${r.wins}</td>
        <td style="color:#CF6679;">${r.losses}</td>
        <td style="color:${_winRateColor(wr)};font-weight:700;">${wr !== null ? wr + '%' : '—'}</td>
        <td>${r.avg_pnl !== null ? `<span style="color:${(r.avg_pnl||0)>=0?'#03F5A9':'#CF6679'}">${(r.avg_pnl||0)>=0?'+':''}${r.avg_pnl}%</span>` : '—'}</td>
        <td>${r.avg_days_exit !== null ? r.avg_days_exit + 'gg' : '—'}</td>
        <td>${r.avg_forecast_err !== null ? r.avg_forecast_err + '%' : '—'}</td>
      </tr>`;
    }).join('');

    return `<table class="perf-table">${thead}<tbody>${tbody}</tbody></table>`;
  }

  // ── Tabella Provider ──────────────────────────────────────────────────

  function _renderProviderTable(stats) {
    const rows = stats.by_provider || [];
    if (!rows.length) return '<div style="color:#475569;padding:20px;">Nessun dato</div>';

    const thead = `<thead><tr>
      <th>LLM Provider</th>
      <th>Totale</th>
      <th>Win</th>
      <th>Loss</th>
      <th>Win Rate</th>
      <th>Err. Forecast</th>
      <th>Direzione OK%</th>
    </tr></thead>`;

    const tbody = rows.map(r => {
      const wr = r.win_rate;
      return `<tr>
        <td><strong style="color:#BB86FC;">${r.provider}</strong></td>
        <td>${r.total}</td>
        <td style="color:#03F5A9;">${r.wins}</td>
        <td style="color:#CF6679;">${r.losses}</td>
        <td style="color:${_winRateColor(wr)};font-weight:700;">${wr !== null ? wr + '%' : '—'}</td>
        <td>${r.avg_forecast_err !== null ? r.avg_forecast_err + '%' : '—'}</td>
        <td>${r.dir_accuracy !== null ? r.dir_accuracy + '%' : '—'}</td>
      </tr>`;
    }).join('');

    return `<table class="perf-table">${thead}<tbody>${tbody}</tbody></table>`;
  }

  // ── Distribuzione tempi ───────────────────────────────────────────────

  function _renderEntryTimeDist(stats) {
    const dist = stats.entry_time_dist || [];
    if (!dist.length) return '<div style="color:#475569;padding:20px;text-align:center;">Nessun dato</div>';

    const max = Math.max(...dist.map(d => d.count), 1);
    const bars = dist.map(d => {
      const pct = Math.round(d.count / max * 100);
      return `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
          <span style="width:60px;font-size:12px;color:#94a3b8;text-align:right;">${d.bucket}</span>
          <div class="mini-bar" style="flex:1;height:14px;">
            <div class="mini-bar-fill" style="width:${pct}%;background:#BB86FC;height:100%;"></div>
          </div>
          <span style="width:30px;font-size:12px;color:#e2e8f0;font-weight:600;">${d.count}</span>
        </div>`;
    }).join('');

    return `
      <div class="chart-card-title">Giorni trascorsi da end_date al primo contatto con Entry</div>
      ${bars}
    `;
  }

  // ── Tabella Storico Analisi ───────────────────────────────────────────

  function _renderAnalysisRow(item) {
    const outcome      = item.outcome || null;
    const outcomeBadge = outcome ? _outcomeBadge(outcome) : '<span style="color:#475569;font-size:11px;">Non verificato</span>';
    const dirBadge     = _dirBadge(item.direction);
    const pnlHtml      = item.pnl_percent !== null
      ? `<span style="color:${item.pnl_percent>=0?'#03F5A9':'#CF6679'};font-weight:600;">${item.pnl_percent>=0?'+':''}${item.pnl_percent}%</span>`
      : '—';
    const fcstErrHtml  = item.forecast_error_pct !== null
      ? `<span style="color:${item.forecast_error_pct<=5?'#03F5A9':(item.forecast_error_pct<=15?'#fbbf24':'#CF6679')}">${item.forecast_error_pct}%</span>`
      : '—';
    const dirOkHtml    = item.direction_correct !== null
      ? (item.direction_correct ? '✅' : '❌')
      : '—';

    const marketLabel = MARKET_LABELS[item.market_type] || item.market_type || '—';
    const period = (item.start_date && item.end_date)
      ? `${item.start_date} → ${item.end_date}`
      : '—';

    const dateStr = _fmtDate(item.analysis_date);
    const timeStr = item.analysis_time ? item.analysis_time.slice(0, 5) : '—';

    return `<tr>
      <td style="text-align:center;padding:7px 8px;">
        <input type="checkbox" class="analysis-checkbox" data-id="${item.id}"
               style="cursor:pointer;" onchange="Performance.onCheckboxChange()">
      </td>
      <td style="color:#64748b;">${dateStr}</td>
      <td style="color:#94a3b8;font-size:11px;">${timeStr}</td>
      <td><strong style="color:#3fbef5;">${item.symbol}</strong></td>
      <td>${marketLabel}</td>
      <td style="font-size:11px;color:#64748b;">${period}</td>
      <td>${dirBadge}</td>
      <td>${_fmtPrice(item.entry)}</td>
      <td>${_fmtPrice(item.stop_loss)}</td>
      <td>${_fmtPrice(item.take_profit_1)}</td>
      <td>${_fmtPrice(item.ai_forecast_price)}</td>
      <td>${outcomeBadge}</td>
      <td>${pnlHtml}</td>
      <td>${item.days_to_entry !== null ? item.days_to_entry + 'gg' : '—'}</td>
      <td>${item.days_to_exit !== null ? item.days_to_exit + 'gg' : '—'}</td>
      <td>${fcstErrHtml}</td>
      <td style="text-align:center;">${dirOkHtml}</td>
      <td style="color:#BB86FC;font-size:11px;">${item.llm_provider || '—'}</td>
      <td>
        ${!outcome ? `<button class="btn btn-secondary" style="font-size:10px;padding:3px 7px;" onclick="Performance.verifyNow('${item.id}')">▶ Verifica</button>` : ''}
      </td>
    </tr>`;
  }

  // ── Paginazione ───────────────────────────────────────────────────────

  function _renderPagination(total, page, perPage) {
    const totalPages = Math.ceil(total / perPage);
    if (totalPages <= 1) {
      document.getElementById('pagination').innerHTML = '';
      return;
    }
    let html = `<span class="page-info">${((page-1)*perPage)+1}–${Math.min(page*perPage,total)} di ${total}</span>`;
    html += `<button class="btn-page" ${page<=1?'disabled':''} onclick="Performance.goPage(${page-1})">◀</button>`;
    // pagine vicine
    const from = Math.max(1, page-2);
    const to   = Math.min(totalPages, page+2);
    for (let p = from; p <= to; p++) {
      html += `<button class="btn-page" ${p===page?'style="background:rgba(59,130,246,0.2);color:#3fbef5;border-color:rgba(59,130,246,0.4);"':''} onclick="Performance.goPage(${p})">${p}</button>`;
    }
    html += `<button class="btn-page" ${page>=totalPages?'disabled':''} onclick="Performance.goPage(${page+1})">▶</button>`;
    document.getElementById('pagination').innerHTML = html;
  }

  // ── Fetch Statistiche ─────────────────────────────────────────────────

  async function _loadStats() {
    try {
      const res = await fetch('/api/performance/stats');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error('[PERF] Errore caricamento stats:', e);
      return null;
    }
  }

  async function _loadList() {
    const params = new URLSearchParams({
      page:     _state.page,
      per_page: _state.perPage,
    });
    if (_state.filterMarket)  params.set('market_type', _state.filterMarket);
    if (_state.filterOutcome) params.set('outcome', _state.filterOutcome);
    if (_state.filterSymbol)  params.set('symbol', _state.filterSymbol);

    try {
      const res = await fetch(`/api/performance/list?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error('[PERF] Errore caricamento lista:', e);
      return null;
    }
  }

  // ── Render completo ───────────────────────────────────────────────────

  async function _renderAll() {
    document.getElementById('perfLoader').style.display = 'block';
    document.getElementById('perfContent').style.display = 'none';

    const [stats, list] = await Promise.all([_loadStats(), _loadList()]);

    document.getElementById('perfLoader').style.display = 'none';
    document.getElementById('perfContent').style.display = 'block';

    if (!stats) {
      document.getElementById('kpiGrid').innerHTML =
        '<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-title">Impossibile caricare le statistiche</div></div>';
      return;
    }

    // Se non ci sono analisi, mostra empty state
    if (!stats.total_analyses) {
      document.getElementById('kpiGrid').innerHTML = `
        <div class="empty-state" style="grid-column:1/-1;">
          <div class="empty-state-icon">📊</div>
          <div class="empty-state-title">Nessuna analisi registrata</div>
          <div class="empty-state-sub">Completa un backtesting per vedere le statistiche di performance</div>
        </div>`;
      document.getElementById('chartsRow').innerHTML = '';
      document.getElementById('marketTable').innerHTML = '';
      document.getElementById('directionTable').innerHTML = '';
      document.getElementById('providerTable').innerHTML = '';
      document.getElementById('entryTimeDist').innerHTML = '';
    } else {
      document.getElementById('kpiGrid').innerHTML       = _renderKPIs(stats);
      document.getElementById('chartsRow').innerHTML     = _renderCharts(stats);
      document.getElementById('marketTable').innerHTML   = _renderMarketTable(stats);
      document.getElementById('directionTable').innerHTML= _renderDirectionTable(stats);
      document.getElementById('providerTable').innerHTML = _renderProviderTable(stats);
      document.getElementById('entryTimeDist').innerHTML = _renderEntryTimeDist(stats);
    }

    // Lista analisi
    if (list) {
      _state.totalItems = list.total;
      document.getElementById('listCount').textContent = `${list.total} analisi totali`;
      const tbody = document.getElementById('analysesBody');
      if (!list.items || list.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="17" style="text-align:center;padding:40px;color:#475569;">
          <div class="empty-state-icon">🔍</div>
          <div>Nessuna analisi trovata con questi filtri</div>
        </td></tr>`;
      } else {
        tbody.innerHTML = list.items.map(_renderAnalysisRow).join('');
      }
      _renderPagination(list.total, _state.page, _state.perPage);
    }
  }

  // ── Gestione Selezione ────────────────────────────────────────────────

  function toggleSelectAll(checked) {
    const checkboxes = document.querySelectorAll('.analysis-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = checked;
    });
    onCheckboxChange();
  }

  async function onCheckboxChange() {
    const selected = Array.from(document.querySelectorAll('.analysis-checkbox:checked'))
      .map(cb => cb.dataset.id);

    if (selected.length === 0) {
      // Nascondi il panel filtrato se niente è selezionato
      const panel = document.getElementById('filteredStatsPanel');
      if (panel) panel.style.display = 'none';
      const selectAllCb = document.getElementById('selectAllCheckbox');
      if (selectAllCb) selectAllCb.checked = false;
      return;
    }

    // Carica le statistiche filtrate
    try {
      const res = await fetch('/api/performance/stats/filtered', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_ids: selected })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const stats = await res.json();
      _renderFilteredStats(selected, stats);
    } catch (e) {
      console.error('[PERF FILTERED] Errore:', e);
    }
  }

  function _renderFilteredStats(selectedIds, stats) {
    let html = `<div style="margin-top:28px;padding:20px;background:rgba(187,134,252,0.08);border:1px solid rgba(187,134,252,0.2);border-radius:10px;">
      <div style="font-size:13px;font-weight:700;color:#BB86FC;margin-bottom:14px;">
        📊 Statistiche Filtrate (${selectedIds.length} analisi selezionate)
      </div>
      <div class="kpi-grid" style="margin-bottom:14px;">`;

    const kpis = [
      { label: 'Totale', value: stats.total_analyses || 0 },
      { label: 'Verificate', value: stats.total_verified || 0 },
      { label: 'Win Rate', value: stats.win_rate !== null ? stats.win_rate + '%' : '—' },
      { label: 'Vittorie', value: stats.wins || 0 },
      { label: 'Sconfitte', value: stats.losses || 0 },
      { label: 'P&L Medio', value: stats.avg_pnl !== null ? stats.avg_pnl + '%' : '—' },
      { label: 'P&L Max', value: stats.max_pnl !== null ? stats.max_pnl + '%' : '—' },
      { label: 'P&L Min', value: stats.min_pnl !== null ? stats.min_pnl + '%' : '—' },
      { label: 'Err. Forecast', value: stats.avg_forecast_err !== null ? stats.avg_forecast_err + '%' : '—' },
      { label: 'Dir. Accuracy', value: stats.dir_accuracy !== null ? stats.dir_accuracy + '%' : '—' },
    ];

    for (const kpi of kpis) {
      html += `<div class="kpi-card" style="min-width:140px;">
        <div class="kpi-label">${kpi.label}</div>
        <div class="kpi-value">${kpi.value}</div>
      </div>`;
    }

    html += `</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
        <button class="btn btn-secondary" onclick="Performance.deleteSelected()"
                style="font-size:12px;padding:6px 14px;background:#CF6679;color:#fff;border:none;">
          🗑️ Elimina Selezionate
        </button>
        <button class="btn btn-secondary" onclick="Performance.clearSelection()"
                style="font-size:12px;padding:6px 14px;">
          ✕ Deseleziona Tutto
        </button>
      </div>
    </div>`;

    let panel = document.getElementById('filteredStatsPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'filteredStatsPanel';
      const analysesList = document.getElementById('analysesList');
      analysesList.parentElement.insertAdjacentElement('afterend', panel);
    }
    panel.innerHTML = html;
    panel.style.display = 'block';
  }

  async function deleteSelected() {
    const selected = Array.from(document.querySelectorAll('.analysis-checkbox:checked'))
      .map(cb => cb.dataset.id);

    if (!selected.length) {
      _showToast('Nessuna analisi selezionata', 'warning');
      return;
    }

    if (!confirm(`Sei sicuro di voler eliminare ${selected.length} analisi? Questa azione è irreversibile.`)) {
      return;
    }

    try {
      const res = await fetch('/api/performance/delete-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_ids: selected })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      _showToast(`✅ ${data.deleted_count} analisi eliminate`, 'success');
      clearSelection();
      refresh();
    } catch (e) {
      _showToast(`Errore eliminazione: ${e.message}`, 'error');
    }
  }

  function clearSelection() {
    document.querySelectorAll('.analysis-checkbox').forEach(cb => cb.checked = false);
    const selectAllCb = document.getElementById('selectAllCheckbox');
    if (selectAllCb) selectAllCb.checked = false;
    const panel = document.getElementById('filteredStatsPanel');
    if (panel) panel.style.display = 'none';
  }

  // ── API Pubblica ──────────────────────────────────────────────────────

  async function refresh() {
    _state.page = 1;
    await _renderAll();
  }

  async function goPage(p) {
    _state.page = p;
    const list = await _loadList();
    if (!list) return;
    _state.totalItems = list.total;
    const tbody = document.getElementById('analysesBody');
    tbody.innerHTML = list.items.map(_renderAnalysisRow).join('');
    _renderPagination(list.total, _state.page, _state.perPage);
  }

  function applyFilters() {
    _state.filterMarket  = document.getElementById('filterMarket')?.value  || '';
    _state.filterOutcome = document.getElementById('filterOutcome')?.value || '';
    _state.filterSymbol  = document.getElementById('filterSymbol')?.value  || '';
    _state.page = 1;
    goPage(1);
  }

  function debouncedFilter() {
    clearTimeout(_state._filterTimer);
    _state._filterTimer = setTimeout(applyFilters, 400);
  }

  async function verifyNow(analysisId) {
    _showToast('Avvio verifica outcome...', 'info');
    try {
      const res = await fetch(`/api/performance/verify/${analysisId}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      _showToast(`Verifica completata: ${data.outcome || 'N/D'}`, 'success');
      await goPage(_state.page);
    } catch (e) {
      _showToast(`Errore verifica: ${e.message}`, 'error');
    }
  }

  function exportCSV() {
    // Scarica tutti gli item come CSV
    const params = new URLSearchParams({ page: 1, per_page: 1000 });
    if (_state.filterMarket)  params.set('market_type', _state.filterMarket);
    if (_state.filterOutcome) params.set('outcome', _state.filterOutcome);
    if (_state.filterSymbol)  params.set('symbol', _state.filterSymbol);

    fetch(`/api/performance/list?${params}`)
      .then(r => r.json())
      .then(data => {
        if (!data.items?.length) { _showToast('Nessun dato da esportare', 'warning'); return; }
        const cols = ['analysis_date','symbol','market_type','start_date','end_date',
          'direction','entry','stop_loss','take_profit_1','take_profit_2',
          'ai_forecast_price','ai_forecast_bias','llm_provider','outcome',
          'pnl_percent','days_to_entry','days_to_exit','forecast_error_pct','direction_correct'];
        const header = cols.join(',');
        const rows = data.items.map(r =>
          cols.map(c => JSON.stringify(r[c] ?? '')).join(',')
        );
        const csv = [header, ...rows].join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href = url;
        a.download = `performance_${new Date().toISOString().slice(0,10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        _showToast(`Esportato ${data.items.length} righe`, 'success');
      })
      .catch(e => _showToast(`Errore export: ${e.message}`, 'error'));
  }

  // ── Init ──────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    _renderAll();
  });

  return {
    refresh,
    goPage,
    applyFilters,
    debouncedFilter,
    verifyNow,
    exportCSV,
    toggleSelectAll,
    onCheckboxChange,
    deleteSelected,
    clearSelection,
  };
})();
