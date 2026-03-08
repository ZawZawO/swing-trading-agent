/* ─── State ────────────────────────────────────────────────────────────── */
let scanResults = [];
let currentConfig = {};
let charts = { main: null, rsi: null, macd: null, backtest: null };
let activeGroup = 'All';
let autoRefreshTimer = null;
let countdownSeconds = 0;
let autoRefreshPaused = false;
let lastPrices = {};
let previousSignals = {};
let alertAudioCtx = null;
let currentDetailTicker = '';
let activePreset = null;
let tfAlignment = {};
let equityChart = null;
let earningsData = {};
let previousPresetMatches = {};
let presetAlertEnabled = {};
let simTradeToClose = null;
let marketOverviewData = null;
let _scannerPollTimer = null;

/* ─── Init ─────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-scan').addEventListener('click', () => { runScan(); resetCountdown(); });
    document.getElementById('btn-settings').addEventListener('click', openSettings);
    document.getElementById('btn-close-modal').addEventListener('click', closeSettings);
    document.getElementById('btn-cancel-settings').addEventListener('click', closeSettings);
    document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
    document.getElementById('btn-back').addEventListener('click', showSummary);
    document.getElementById('btn-add-ticker').addEventListener('click', addTicker);
    document.getElementById('add-ticker-input').addEventListener('keydown', e => { if (e.key === 'Enter') addTicker(); });
    // Auto-refresh
    document.getElementById('btn-pause').addEventListener('click', toggleAutoRefresh);
    // Journal
    document.getElementById('btn-journal').addEventListener('click', openJournal);
    document.getElementById('btn-close-journal').addEventListener('click', () => document.getElementById('journal-modal').classList.add('hidden'));
    document.getElementById('btn-add-journal').addEventListener('click', () => document.getElementById('journal-form').classList.toggle('hidden'));
    document.getElementById('btn-submit-journal').addEventListener('click', submitJournalEntry);
    document.getElementById('btn-cancel-journal').addEventListener('click', () => document.getElementById('journal-form').classList.add('hidden'));
    document.getElementById('btn-export-journal').addEventListener('click', exportJournalCSV);
    document.getElementById('btn-save-note').addEventListener('click', saveNote);
    document.getElementById('btn-add-group').addEventListener('click', addGroup);
    // Alerts
    document.getElementById('btn-add-alert').addEventListener('click', addAlert);
    document.getElementById('alert-type').addEventListener('change', () => {
        const t = document.getElementById('alert-type').value;
        document.getElementById('alert-value').style.display = t.startsWith('signal') ? 'none' : '';
    });
    // Backtest
    document.getElementById('btn-backtest-nav').addEventListener('click', () => showBacktest(''));
    document.getElementById('btn-backtest-detail').addEventListener('click', () => showBacktest(currentDetailTicker));
    document.getElementById('btn-back-bt').addEventListener('click', showSummary);
    document.getElementById('btn-run-backtest').addEventListener('click', runBacktest);
    // Portfolio
    document.getElementById('btn-portfolio').addEventListener('click', showPortfolio);
    document.getElementById('btn-back-portfolio').addEventListener('click', showSummary);
    // Heatmap
    document.getElementById('btn-heatmap').addEventListener('click', showHeatmap);
    document.getElementById('btn-back-heatmap').addEventListener('click', showSummary);
    // Screener filters
    document.getElementById('btn-apply-filters').addEventListener('click', applyFilters);
    document.getElementById('btn-clear-filters').addEventListener('click', clearFilters);
    document.getElementById('btn-save-preset').addEventListener('click', saveFilterPreset);
    // Trade Simulator
    document.getElementById('btn-simulator').addEventListener('click', showSimulator);
    document.getElementById('btn-back-simulator').addEventListener('click', showSummary);
    document.getElementById('btn-sim-open').addEventListener('click', openSimTrade);
    document.getElementById('btn-sim-autofill').addEventListener('click', autoFillSimForm);
    document.getElementById('sim-entry').addEventListener('input', updateSimRiskHint);
    document.getElementById('sim-stop').addEventListener('input', updateSimRiskHint);
    // Mobile filter toggle
    const filtersEl = document.getElementById('screener-filters');
    filtersEl.addEventListener('click', (e) => {
        if (window.innerWidth <= 600 && e.target.classList.contains('filter-toggle-mobile')) {
            filtersEl.classList.toggle('filters-expanded');
        }
    });
    // Audio init on first click
    document.addEventListener('click', () => {
        if (!alertAudioCtx) alertAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }, { once: true });

    // AI Weekly Intelligence
    document.getElementById('btn-ai-weekly').addEventListener('click', showAiWeekly);
    document.getElementById('btn-back-ai-weekly').addEventListener('click', showSummary);
    document.getElementById('btn-refresh-ai-weekly').addEventListener('click', () => loadAiWeekly(true));
    document.getElementById('btn-refresh-scanner').addEventListener('click', () => loadMarketScanner(true));

    loadSimQuickCard();
    runScan();
});

/* ─── Scan ─────────────────────────────────────────────────────────────── */
async function runScan() {
    showLoading('Scanning stocks...');
    try {
        const res = await fetch('/api/scan');
        const data = await res.json();
        scanResults = data.results;
        currentConfig = data.config;
        document.getElementById('scan-time').textContent = 'Last: ' + new Date(data.timestamp).toLocaleTimeString();
        renderSignalBar(scanResults);
        renderGroupTabs();
        filterTable();
        renderFilterPresets();
        checkAlerts(scanResults);
        checkPresetAlerts(scanResults);
        scanResults.forEach(r => { previousSignals[r.ticker] = r.signal; });
        if (!autoRefreshTimer) startAutoRefresh();
        // Deferred background fetches
        fetchMTFAlignment();
        fetchEarnings();
        fetchMarketOverview();
        fetchTopSetups();
        renderWatchlistPanel();
        fetchScannerTop10Dashboard();
    } catch (err) {
        console.error('Scan failed:', err);
    }
    hideLoading();
}

function renderSignalBar(results) {
    const buys = results.filter(r => r.signal.includes('BUY')).length;
    const holds = results.filter(r => r.signal === 'HOLD').length;
    const sells = results.filter(r => r.signal.includes('SELL')).length;
    document.getElementById('signal-bar').innerHTML = `
        <span class="signal-count buy">${buys} BUY</span>
        <span class="signal-count hold">${holds} HOLD</span>
        <span class="signal-count sell">${sells} SELL</span>
        <span style="color:var(--text2);font-size:12px;margin-left:auto">${results.length} stocks scanned</span>
    `;
}

function renderTable(results) {
    const tbody = document.getElementById('scan-body');
    tbody.innerHTML = '';
    results.forEach(r => {
        const tr = document.createElement('tr');
        tr.className = 'data-row';
        tr.onclick = () => showDetail(r.ticker);
        const signalClass = r.signal.toLowerCase().replace(' ', '-');
        const aiScore = r.swing_score != null ? r.swing_score : (r.score || 0);
        const scoreClass = aiScore >= 70 ? 'score-high' : aiScore >= 50 ? 'score-mid' : '';
        const changeClass = r.change_2m >= 0 ? 'positive' : 'negative';
        const changeSign = r.change_2m >= 0 ? '+' : '';
        const tfVal = tfAlignment[r.ticker];
        const tfText = tfVal === true ? '\u2713' : tfVal === false ? '\u2717' : '\u22EF';
        const tfClass = tfVal === true ? 'tf-aligned' : tfVal === false ? 'tf-misaligned' : 'tf-loading';
        const earnInfo = earningsData[r.ticker];
        let earnText = '-', earnClass = 'earn-cell', earnTitle = '';
        if (earnInfo && earnInfo.days_until <= 14) {
            earnText = '\u26A0 ' + earnInfo.days_until + 'd';
            earnClass = 'earn-cell earn-warning';
            earnTitle = 'Earnings on ' + earnInfo.next_date;
        } else if (earnInfo) {
            earnText = earnInfo.days_until + 'd';
            earnClass = 'earn-cell earn-safe';
            earnTitle = 'Earnings ' + earnInfo.next_date;
        }
        // LookForward columns
        const lf = r.lookforward || {};
        const lfCell = (key) => {
            const h = lf[key];
            if (!h) return '<td class="lf-cell">-</td>';
            const val = h.base_pct;
            const cls = val >= 0 ? 'positive' : 'negative';
            const sign = val >= 0 ? '+' : '';
            return `<td class="lf-cell ${cls}" title="Bull: ${sign}${h.bull_pct.toFixed(1)}% / Bear: ${h.bear_pct > 0 ? '+' : ''}${h.bear_pct.toFixed(1)}%">${sign}${val.toFixed(1)}%</td>`;
        };
        // Setup badge
        const setupType = r.setup_type || 'Neutral';
        const setupClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
        // Win rate
        const winRate = r.win_rate != null ? (r.win_rate * 100).toFixed(0) + '%' : '-';
        const winClass = r.win_rate != null ? (r.win_rate >= 0.55 ? 'positive' : r.win_rate < 0.45 ? 'negative' : '') : '';

        tr.innerHTML = `
            <td class="ticker-cell">${r.ticker}</td>
            <td>$${r.price.toFixed(2)}</td>
            <td><span class="setup-badge ${setupClass}">${setupType}</span></td>
            <td><span class="score-pill ${scoreClass}">${aiScore.toFixed(0)}</span></td>
            <td><span class="signal-cell ${signalClass}">${r.signal}</span></td>
            <td>${r.rsi.toFixed(1)}</td>
            <td>${r.volume_ratio.toFixed(1)}x</td>
            <td class="${winClass}">${winRate}</td>
            <td class="${changeClass}">${changeSign}${r.change_2m.toFixed(1)}%</td>
            <td>$${(r.entry || r.price).toFixed(2)}</td>
            <td>$${r.stop_loss.toFixed(2)}</td>
            <td>$${r.target.toFixed(2)}</td>
            <td>${r.rr_ratio.toFixed(1)}R</td>
            <td>${r.shares || '-'}</td>
            ${lfCell('1W')}
            ${lfCell('2W')}
            ${lfCell('1M')}
            ${lfCell('3M')}
            <td class="tf-cell ${tfClass}">${tfText}</td>
            <td class="${earnClass}" title="${earnTitle}">${earnText}</td>
        `;
        tbody.appendChild(tr);
    });
}

/* ─── Auto-Refresh & Live Prices ───────────────────────────────────────── */
function startAutoRefresh() {
    const mins = (currentConfig.auto_refresh_minutes || 5);
    countdownSeconds = mins * 60;
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    autoRefreshTimer = setInterval(() => {
        if (autoRefreshPaused) return;
        countdownSeconds--;
        updateCountdownDisplay();
        if (countdownSeconds <= 0) {
            runScan();
            fetchPrices();
            countdownSeconds = mins * 60;
        }
    }, 1000);
    updateCountdownDisplay();
    fetchPrices();
}

function resetCountdown() {
    countdownSeconds = (currentConfig.auto_refresh_minutes || 5) * 60;
    updateCountdownDisplay();
}

function toggleAutoRefresh() {
    autoRefreshPaused = !autoRefreshPaused;
    const btn = document.getElementById('btn-pause');
    btn.innerHTML = autoRefreshPaused ? '&#9654;' : '&#9646;&#9646;';
    btn.title = autoRefreshPaused ? 'Resume auto-refresh' : 'Pause auto-refresh';
}

function updateCountdownDisplay() {
    const m = Math.floor(countdownSeconds / 60);
    const s = countdownSeconds % 60;
    document.getElementById('countdown-timer').textContent = `${m}:${s.toString().padStart(2, '0')}`;
}

async function fetchPrices() {
    try {
        const res = await fetch('/api/prices');
        const data = await res.json();
        renderPriceTicker(data.prices);
    } catch (e) { /* silent */ }
}

function renderPriceTicker(prices) {
    const bar = document.getElementById('price-ticker');
    bar.innerHTML = '';
    for (const [ticker, info] of Object.entries(prices)) {
        if (!info.price) continue;
        const item = document.createElement('div');
        item.className = 'price-ticker-item';
        const prev = lastPrices[ticker];
        let flashClass = '';
        if (prev && Math.abs(info.price - prev) / prev > 0.01) {
            flashClass = info.price > prev ? 'price-flash-up' : 'price-flash-down';
        }
        if (flashClass) item.classList.add(flashClass);
        item.innerHTML = `<span class="price-ticker-name">${ticker}</span><span class="price-ticker-value">$${info.price.toFixed(2)}</span>`;
        item.style.cursor = 'pointer';
        item.onclick = () => showDetail(ticker);
        bar.appendChild(item);
        lastPrices[ticker] = info.price;
    }
}

/* ─── Smart Screener Filters ──────────────────────────────────────────── */
function getFilterValues() {
    return {
        rsi_min: parseFloat(document.getElementById('filter-rsi-min').value) || null,
        rsi_max: parseFloat(document.getElementById('filter-rsi-max').value) || null,
        score_min: parseFloat(document.getElementById('filter-score-min').value) || null,
        score_max: parseFloat(document.getElementById('filter-score-max').value) || null,
        volume_min: parseFloat(document.getElementById('filter-volume-min').value) || null,
        signal_type: document.getElementById('filter-signal-type').value || null,
        setup_type: document.getElementById('filter-setup-type').value || null,
        ema_trend: document.getElementById('filter-ema-trend').value || null,
        change_2m_min: parseFloat(document.getElementById('filter-change-min').value) || null,
        change_2m_max: parseFloat(document.getElementById('filter-change-max').value) || null,
    };
}

function setFilterValues(preset) {
    document.getElementById('filter-rsi-min').value = preset.rsi_min ?? '';
    document.getElementById('filter-rsi-max').value = preset.rsi_max ?? '';
    document.getElementById('filter-score-min').value = preset.score_min ?? '';
    document.getElementById('filter-score-max').value = preset.score_max ?? '';
    document.getElementById('filter-volume-min').value = preset.volume_min ?? '';
    document.getElementById('filter-signal-type').value = preset.signal_type ?? '';
    document.getElementById('filter-setup-type').value = preset.setup_type ?? '';
    document.getElementById('filter-ema-trend').value = preset.ema_trend ?? '';
    document.getElementById('filter-change-min').value = preset.change_2m_min ?? '';
    document.getElementById('filter-change-max').value = preset.change_2m_max ?? '';
}

function applyFilters() {
    const f = getFilterValues();
    let results = scanResults;
    // Group filter
    if (activeGroup !== 'All' && currentConfig.groups && currentConfig.groups[activeGroup]) {
        results = results.filter(r => currentConfig.groups[activeGroup].includes(r.ticker));
    }
    // AND filters
    results = results.filter(r => {
        if (f.rsi_min !== null && r.rsi < f.rsi_min) return false;
        if (f.rsi_max !== null && r.rsi > f.rsi_max) return false;
        if (f.score_min !== null && r.score < f.score_min) return false;
        if (f.score_max !== null && r.score > f.score_max) return false;
        if (f.volume_min !== null && r.volume_ratio < f.volume_min) return false;
        if (f.signal_type !== null && r.signal !== f.signal_type) return false;
        if (f.setup_type !== null && r.setup_type !== f.setup_type) return false;
        if (f.ema_trend === 'bullish' && r.ema_fast <= r.ema_slow) return false;
        if (f.ema_trend === 'bearish' && r.ema_fast >= r.ema_slow) return false;
        if (f.change_2m_min !== null && r.change_2m < f.change_2m_min) return false;
        if (f.change_2m_max !== null && r.change_2m > f.change_2m_max) return false;
        return true;
    });
    renderTable(results);
}

function clearFilters() {
    setFilterValues({});
    activePreset = null;
    filterTable();
    renderFilterPresets();
}

function saveFilterPreset() {
    const name = prompt('Preset name:');
    if (!name || !name.trim()) return;
    if (!currentConfig.screener_presets) currentConfig.screener_presets = {};
    currentConfig.screener_presets[name.trim()] = getFilterValues();
    saveConfigSilent();
    renderFilterPresets();
    showToast(`Preset "${name.trim()}" saved`, 'alert');
}

function loadFilterPreset(name) {
    const preset = (currentConfig.screener_presets || {})[name];
    if (!preset) return;
    setFilterValues(preset);
    activePreset = name;
    applyFilters();
    renderFilterPresets();
}

function deleteFilterPreset(name) {
    if (currentConfig.screener_presets && currentConfig.screener_presets[name]) {
        delete currentConfig.screener_presets[name];
        saveConfigSilent();
        if (activePreset === name) activePreset = null;
        renderFilterPresets();
    }
}

function renderFilterPresets() {
    const container = document.getElementById('filter-preset-buttons');
    const presets = currentConfig.screener_presets || {};
    container.innerHTML = '';
    Object.keys(presets).forEach(name => {
        const btn = document.createElement('span');
        btn.className = 'filter-preset-btn' + (activePreset === name ? ' active' : '');
        btn.innerHTML = `${name}<span class="filter-preset-delete">&times;</span>`;
        btn.addEventListener('click', (e) => {
            if (e.target.classList.contains('filter-preset-delete')) deleteFilterPreset(name);
            else loadFilterPreset(name);
        });
        container.appendChild(btn);
    });
}

/* ─── Groups & Filter ──────────────────────────────────────────────────── */
function renderGroupTabs() {
    const container = document.getElementById('group-tabs');
    const groups = currentConfig.groups || {};
    const groupNames = Object.keys(groups);
    if (groupNames.length === 0) { container.innerHTML = ''; return; }
    let html = `<div class="group-tab ${activeGroup === 'All' ? 'active' : ''}" data-group="All">All</div>`;
    groupNames.forEach(name => {
        html += `<div class="group-tab ${activeGroup === name ? 'active' : ''}" data-group="${name}">${name}</div>`;
    });
    container.innerHTML = html;
    container.querySelectorAll('.group-tab').forEach(tab => {
        tab.onclick = () => {
            activeGroup = tab.dataset.group;
            renderGroupTabs();
            filterTable();
        };
    });
}

function filterTable() {
    const f = getFilterValues();
    const hasFilter = Object.values(f).some(v => v !== null);
    if (hasFilter) {
        applyFilters();
    } else if (activeGroup === 'All' || !currentConfig.groups || !currentConfig.groups[activeGroup]) {
        renderTable(scanResults);
    } else {
        const tickers = currentConfig.groups[activeGroup];
        renderTable(scanResults.filter(r => tickers.includes(r.ticker)));
    }
}

/* ─── Detail View ──────────────────────────────────────────────────────── */
async function showDetail(ticker) {
    showLoading(`Loading ${ticker}...`);
    try {
        const res = await fetch(`/api/stock/${ticker}`);
        const data = await res.json();
        if (data.error) { alert(data.error); hideLoading(); return; }
        const a = data.analysis;
        currentDetailTicker = a.ticker;

        document.getElementById('detail-ticker').textContent = a.ticker;
        document.getElementById('detail-price').textContent = `$${a.price.toFixed(2)}`;
        const changeEl = document.getElementById('detail-change');
        changeEl.textContent = `${a.change_2m >= 0 ? '+' : ''}${a.change_2m.toFixed(1)}% (2M)`;
        changeEl.className = 'detail-change ' + (a.change_2m >= 0 ? 'positive' : 'negative');

        const badge = document.getElementById('detail-signal-badge');
        badge.textContent = `${a.signal}  ${a.score}/100`;
        badge.className = `signal-badge ${a.signal.toLowerCase().replace(' ', '-')}`;

        const entryPrice = a.entry || a.price;
        const riskAmt = a.risk_amount != null ? a.risk_amount : null;
        document.getElementById('trade-plan').innerHTML = `
            <div class="plan-row"><span class="plan-label">Entry</span><span class="plan-value">$${entryPrice.toFixed(2)}</span></div>
            <div class="plan-row"><span class="plan-label">Stop Loss</span><span class="plan-value negative">$${a.stop_loss.toFixed(2)}</span></div>
            <div class="plan-row"><span class="plan-label">Target</span><span class="plan-value positive">$${a.target.toFixed(2)}</span></div>
            <div class="plan-row"><span class="plan-label">Risk / Reward</span><span class="plan-value">1 : ${a.rr_ratio.toFixed(1)}</span></div>
            <div class="plan-row"><span class="plan-label">Position Size</span><span class="plan-value">${a.shares} shares${riskAmt != null ? ' (£' + riskAmt.toFixed(0) + ' risk)' : ''}</span></div>
            ${a.atr != null ? `<div class="plan-row"><span class="plan-label">ATR (14)</span><span class="plan-value">$${a.atr.toFixed(2)}</span></div>` : ''}
            <div class="plan-row"><span class="plan-label">Support</span><span class="plan-value">${a.support ? '$' + a.support.toFixed(2) : 'N/A'}</span></div>
            <div class="plan-row"><span class="plan-label">Resistance</span><span class="plan-value">${a.resistance ? '$' + a.resistance.toFixed(2) : 'N/A'}</span></div>
        `;

        const ul = document.getElementById('signal-reasons');
        ul.innerHTML = '';
        a.reasons.forEach(reason => { const li = document.createElement('li'); li.textContent = reason; ul.appendChild(li); });

        // LookForward Projections
        renderLookforwardPanel(a.lookforward, a.price);

        // Notes
        const notes = currentConfig.notes || {};
        document.getElementById('stock-note').value = notes[a.ticker] || '';

        // Alert rules
        renderAlertRules(a.ticker);

        // Earnings card
        renderEarningsCard(a.ticker);

        // AI Score Card
        const aiCard = document.getElementById('ai-score-card');
        if (aiCard) {
            const swingScore = a.swing_score != null ? a.swing_score : (a.score || 0);
            const winRate = a.win_rate != null ? (a.win_rate * 100).toFixed(0) : 'N/A';
            const comps = a.score_components || {};
            const setupType = a.setup_type || 'Neutral';
            const scoreColor = swingScore >= 65 ? 'var(--green)' : swingScore >= 45 ? 'var(--yellow)' : 'var(--red)';
            const setupBadgeClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
            document.getElementById('ai-score-value').textContent = swingScore.toFixed(0);
            document.getElementById('ai-score-value').style.color = scoreColor;
            document.getElementById('ai-setup-badge').innerHTML =
                `<span class="setup-badge ${setupBadgeClass}">${setupType}</span> <span style="color:var(--text2);font-size:12px">Win Rate: ${winRate}%</span>`;
            const compDefs = [
                { label: 'Trend Strength (30%)', key: 'trend_strength' },
                { label: 'Volume Confirm (20%)', key: 'volume_confirmation' },
                { label: 'Momentum (20%)', key: 'momentum_score' },
                { label: 'Win Rate (30%)', key: 'win_rate' },
            ];
            document.getElementById('ai-score-components').innerHTML = compDefs.map(c => {
                const val = comps[c.key] != null ? comps[c.key] : 0;
                const pct = (val * 100).toFixed(0);
                return `<div class="ai-component-row">
                    <span class="ai-component-label">${c.label}</span>
                    <div class="ai-component-bar-bg"><div class="ai-component-bar-fill" style="width:${pct}%"></div></div>
                    <span class="ai-component-value">${pct}%</span>
                </div>`;
            }).join('');
            aiCard.classList.remove('hidden');
        }

        // Switch view
        document.getElementById('view-summary').classList.add('hidden');
        document.getElementById('view-backtest').classList.add('hidden');
        document.getElementById('view-portfolio').classList.add('hidden');
        document.getElementById('view-heatmap').classList.add('hidden');
        document.getElementById('view-simulator').classList.add('hidden');
        document.getElementById('view-detail').classList.remove('hidden');

        destroyCharts();
        if (data.chart) renderCharts(data.chart);

        // Multi-timeframe panel
        document.getElementById('mtf-panel').classList.add('hidden');
        fetchMTF(a.ticker).then(mtfData => renderMTFPanel(mtfData));
    } catch (err) { alert('Failed to load stock: ' + err.message); }
    hideLoading();
}

function showSummary() {
    destroyCharts();
    if (equityChart) { equityChart.remove(); equityChart = null; }
    clearTimeout(_scannerPollTimer);
    document.getElementById('view-detail').classList.add('hidden');
    document.getElementById('view-backtest').classList.add('hidden');
    document.getElementById('view-portfolio').classList.add('hidden');
    document.getElementById('view-heatmap').classList.add('hidden');
    document.getElementById('view-simulator').classList.add('hidden');
    document.getElementById('view-ai-weekly').classList.add('hidden');
    document.getElementById('view-summary').classList.remove('hidden');
}

/* ─── Notes ────────────────────────────────────────────────────────────── */
async function saveNote() {
    const ticker = currentDetailTicker;
    const note = document.getElementById('stock-note').value;
    try {
        const res = await fetch('/api/notes', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker, note }),
        });
        const data = await res.json();
        currentConfig.notes = data.notes;
        showToast(`Note saved for ${ticker}`, 'alert');
    } catch (e) { alert('Failed to save note'); }
}

/* ─── Multi-Timeframe Analysis ─────────────────────────────────────────── */
async function fetchMTF(ticker) {
    try {
        const res = await fetch(`/api/mtf/${ticker}`);
        const data = await res.json();
        if (data.error) return null;
        return data;
    } catch (e) { return null; }
}

function renderMTFPanel(data) {
    const panel = document.getElementById('mtf-panel');
    if (!data) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');

    const tfs = { '1h': data.timeframes['1h'], '4h': data.timeframes['4h'], '1d': data.timeframes['1d'] };
    for (const [tf, result] of Object.entries(tfs)) {
        const signalEl = document.getElementById(`mtf-signal-${tf}`);
        const scoreEl = document.getElementById(`mtf-score-${tf}`);
        const trendEl = document.getElementById(`mtf-trend-${tf}`);
        const card = document.getElementById(`mtf-${tf}`);
        if (!result) {
            signalEl.textContent = 'N/A';
            scoreEl.textContent = '-';
            trendEl.textContent = 'No data';
            card.style.borderColor = 'var(--border)';
            continue;
        }
        signalEl.textContent = result.signal;
        signalEl.className = 'mtf-signal ' + (result.signal.includes('BUY') ? 'positive' : result.signal.includes('SELL') ? 'negative' : '');
        scoreEl.textContent = result.score;
        scoreEl.style.color = result.score >= 60 ? 'var(--green)' : result.score >= 40 ? 'var(--yellow)' : 'var(--red)';
        const trend = result.ema_fast > result.ema_slow ? 'Bullish (EMA 8>21)' : 'Bearish (EMA 8<21)';
        trendEl.textContent = trend;
        trendEl.className = 'mtf-trend ' + (result.ema_fast > result.ema_slow ? 'positive' : 'negative');
        card.style.borderColor = result.score >= 60 ? 'var(--green)' : result.score <= 40 ? 'var(--red)' : 'var(--border)';
    }

    const alignIcon = document.getElementById('mtf-alignment-icon');
    if (data.aligned === true) {
        alignIcon.textContent = '\u2713';
        alignIcon.className = 'mtf-alignment-icon mtf-aligned';
    } else if (data.aligned === false) {
        alignIcon.textContent = '\u2717';
        alignIcon.className = 'mtf-alignment-icon mtf-misaligned';
    } else {
        alignIcon.textContent = '?';
        alignIcon.className = 'mtf-alignment-icon mtf-unknown';
    }
}

async function fetchMTFAlignment() {
    try {
        const res = await fetch('/api/mtf-alignment');
        const data = await res.json();
        tfAlignment = data.alignment;
        updateAlignmentColumn();
    } catch (e) { /* silent */ }
}

function updateAlignmentColumn() {
    document.querySelectorAll('#scan-body tr.data-row').forEach(row => {
        const ticker = row.querySelector('.ticker-cell')?.textContent;
        const tfCell = row.querySelector('.tf-cell');
        if (!tfCell || !ticker) return;
        const aligned = tfAlignment[ticker];
        if (aligned === true) {
            tfCell.textContent = '\u2713';
            tfCell.className = 'tf-cell tf-aligned';
        } else if (aligned === false) {
            tfCell.textContent = '\u2717';
            tfCell.className = 'tf-cell tf-misaligned';
        } else {
            tfCell.textContent = '\u22EF';
            tfCell.className = 'tf-cell tf-loading';
        }
    });
}

/* ─── Earnings Shield ──────────────────────────────────────────────────── */
async function fetchEarnings() {
    try {
        const res = await fetch('/api/earnings');
        const data = await res.json();
        earningsData = data.earnings || {};
        updateEarningsColumn();
    } catch (e) { /* silent */ }
}

function updateEarningsColumn() {
    document.querySelectorAll('#scan-body tr.data-row').forEach(row => {
        const ticker = row.querySelector('.ticker-cell')?.textContent;
        const earnCell = row.querySelector('.earn-cell');
        if (!earnCell || !ticker) return;
        const info = earningsData[ticker];
        if (info && info.days_until <= 14) {
            earnCell.textContent = '\u26A0 ' + info.days_until + 'd';
            earnCell.className = 'earn-cell earn-warning';
            earnCell.title = 'Earnings on ' + info.next_date;
        } else if (info) {
            earnCell.textContent = info.days_until + 'd';
            earnCell.className = 'earn-cell earn-safe';
            earnCell.title = 'Earnings ' + info.next_date;
        } else {
            earnCell.textContent = '-';
            earnCell.className = 'earn-cell';
            earnCell.title = '';
        }
    });
}

function renderLookforwardPanel(lf, price) {
    const panel = document.getElementById('lookforward-panel');
    if (!panel) return;
    if (!lf || Object.keys(lf).length === 0) {
        panel.innerHTML = '<p style="color:var(--text2)">No projection data available</p>';
        return;
    }
    const horizons = ['1W', '2W', '3W', '1M', '2M', '3M'];
    let html = '<table class="lf-detail-table"><thead><tr>';
    html += '<th>Horizon</th><th>Days</th><th>Base</th><th>Base %</th><th>Bull (+1s)</th><th>Bull %</th><th>Bear (-1s)</th><th>Bear %</th>';
    html += '</tr></thead><tbody>';
    horizons.forEach(h => {
        const d = lf[h];
        if (!d) return;
        const baseClass = d.base_pct >= 0 ? 'positive' : 'negative';
        const bullClass = d.bull_pct >= 0 ? 'positive' : 'negative';
        const bearClass = d.bear_pct >= 0 ? 'positive' : 'negative';
        const sign = (v) => v >= 0 ? '+' : '';
        html += `<tr>
            <td class="lf-horizon">${h}</td>
            <td>${d.days}</td>
            <td>$${d.base.toFixed(2)}</td>
            <td class="${baseClass}">${sign(d.base_pct)}${d.base_pct.toFixed(1)}%</td>
            <td class="positive">$${d.bull.toFixed(2)}</td>
            <td class="${bullClass}">${sign(d.bull_pct)}${d.bull_pct.toFixed(1)}%</td>
            <td class="negative">$${d.bear.toFixed(2)}</td>
            <td class="${bearClass}">${sign(d.bear_pct)}${d.bear_pct.toFixed(1)}%</td>
        </tr>`;
    });
    html += '</tbody></table>';
    html += '<p class="lf-note">Bull = +1 sigma envelope | Bear = -1 sigma envelope | Momentum + Volatility model</p>';
    panel.innerHTML = html;
}

function renderEarningsCard(ticker) {
    const existing = document.getElementById('earnings-card');
    if (existing) existing.remove();

    const info = earningsData[ticker];
    if (!info) return;

    const card = document.createElement('div');
    card.id = 'earnings-card';
    card.className = 'card card-full-width';

    const isWarning = info.days_until <= 14;
    if (isWarning) card.style.borderColor = 'var(--yellow)';

    let content = `<h3>${isWarning ? '\u26A0 ' : ''}Earnings</h3>`;
    content += `<div class="trade-plan">`;
    content += `<div class="plan-row"><span class="plan-label">Next Earnings</span><span class="plan-value">${info.next_date}</span></div>`;
    content += `<div class="plan-row"><span class="plan-label">Days Until</span><span class="plan-value" style="color:${isWarning ? 'var(--yellow)' : 'var(--text)'}">${info.days_until} days</span></div>`;
    if (info.eps_estimate !== null) {
        content += `<div class="plan-row"><span class="plan-label">EPS Estimate</span><span class="plan-value">$${info.eps_estimate}</span></div>`;
    }
    if (isWarning) {
        content += `<div class="plan-row" style="border-bottom:none"><span class="plan-label" style="color:var(--yellow);font-weight:600">WARNING: Earnings within hold period. Consider avoiding new swing entry.</span></div>`;
    }
    content += `</div>`;
    card.innerHTML = content;

    const detailCards = document.querySelector('#view-detail .detail-cards');
    if (detailCards) detailCards.insertBefore(card, detailCards.firstChild);
}

/* ─── Auto-Alert on Presets ──────────────────────────────────────────── */
function matchesPreset(stock, preset) {
    if (preset.rsi_min !== null && stock.rsi < preset.rsi_min) return false;
    if (preset.rsi_max !== null && stock.rsi > preset.rsi_max) return false;
    if (preset.score_min !== null && stock.score < preset.score_min) return false;
    if (preset.score_max !== null && stock.score > preset.score_max) return false;
    if (preset.volume_min !== null && stock.volume_ratio < preset.volume_min) return false;
    if (preset.signal_type !== null && stock.signal !== preset.signal_type) return false;
    if (preset.ema_trend === 'bullish' && stock.ema_fast <= stock.ema_slow) return false;
    if (preset.ema_trend === 'bearish' && stock.ema_fast >= stock.ema_slow) return false;
    if (preset.change_2m_min !== null && stock.change_2m < preset.change_2m_min) return false;
    if (preset.change_2m_max !== null && stock.change_2m > preset.change_2m_max) return false;
    return true;
}

function checkPresetAlerts(results) {
    const presets = currentConfig.screener_presets || {};
    const isFirstCheck = Object.keys(previousPresetMatches).length === 0;

    Object.entries(presets).forEach(([name, preset]) => {
        if (presetAlertEnabled[name] === false) return;

        const currentMatches = new Set();
        results.forEach(r => {
            if (matchesPreset(r, preset)) currentMatches.add(r.ticker);
        });

        if (!isFirstCheck && previousPresetMatches[name]) {
            const prevSet = previousPresetMatches[name];
            currentMatches.forEach(ticker => {
                if (!prevSet.has(ticker)) {
                    triggerAlert(`${ticker} now matches "${name}" preset`, 'alert');
                }
            });
        }

        previousPresetMatches[name] = currentMatches;
    });
}

function renderPresetAlertToggles() {
    const container = document.getElementById('preset-alert-toggles');
    const presets = currentConfig.screener_presets || {};
    const names = Object.keys(presets);
    if (names.length === 0) {
        container.innerHTML = '<span style="color:var(--text2);font-size:12px">No presets defined</span>';
        return;
    }
    container.innerHTML = '';
    names.forEach(name => {
        const label = document.createElement('label');
        label.className = 'toggle-label';
        const checked = presetAlertEnabled[name] !== false ? 'checked' : '';
        label.innerHTML = `<input type="checkbox" class="preset-alert-toggle" data-preset="${name}" ${checked}> Alert on "${name}"`;
        label.querySelector('input').addEventListener('change', (e) => {
            presetAlertEnabled[e.target.dataset.preset] = e.target.checked;
        });
        container.appendChild(label);
    });
}

/* ─── Alerts & Notifications ──────────────────────────────────────────── */
function checkAlerts(results) {
    const alerts = currentConfig.alerts || {};
    const alertSettings = currentConfig.alert_settings || {};
    let firstScan = Object.keys(previousSignals).length === 0;

    results.forEach(r => {
        if (!firstScan) {
            const prev = previousSignals[r.ticker];
            if (prev && !prev.includes('BUY') && r.signal.includes('BUY')) {
                triggerAlert(`${r.ticker} turned BUY (Score: ${r.score})`, 'buy');
            }
            if (prev && !prev.includes('SELL') && r.signal.includes('SELL')) {
                triggerAlert(`${r.ticker} turned SELL (Score: ${r.score})`, 'sell');
            }
        }
        const tickerAlerts = alerts[r.ticker] || [];
        tickerAlerts.forEach(rule => {
            if (!rule.enabled) return;
            if (rule.type === 'price_above' && r.price >= rule.value) {
                triggerAlert(`${r.ticker} above $${rule.value} (now $${r.price.toFixed(2)})`, 'alert');
                rule.enabled = false;
            }
            if (rule.type === 'price_below' && r.price <= rule.value) {
                triggerAlert(`${r.ticker} below $${rule.value} (now $${r.price.toFixed(2)})`, 'alert');
                rule.enabled = false;
            }
            if (rule.type === 'signal_buy' && r.signal.includes('BUY') && !firstScan) {
                const prev = previousSignals[r.ticker];
                if (prev && !prev.includes('BUY')) triggerAlert(`${r.ticker} BUY signal triggered!`, 'buy');
            }
            if (rule.type === 'signal_sell' && r.signal.includes('SELL') && !firstScan) {
                const prev = previousSignals[r.ticker];
                if (prev && !prev.includes('SELL')) triggerAlert(`${r.ticker} SELL signal triggered!`, 'sell');
            }
        });
    });
}

function triggerAlert(message, type) {
    const settings = currentConfig.alert_settings || {};
    if (settings.toast_enabled !== false) showToast(message, type);
    if (settings.sound_enabled !== false) playBeep();
    if (settings.browser_notifications && Notification.permission === 'granted') {
        new Notification('Swing Trading Alert', { body: message });
    }
}

function playBeep() {
    if (!alertAudioCtx) return;
    try {
        const osc = alertAudioCtx.createOscillator();
        const gain = alertAudioCtx.createGain();
        osc.connect(gain); gain.connect(alertAudioCtx.destination);
        osc.frequency.value = 800; osc.type = 'sine'; gain.gain.value = 0.3;
        osc.start(); osc.stop(alertAudioCtx.currentTime + 0.2);
    } catch (e) { /* silent */ }
}

function showToast(message, type) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type || 'alert'}`;
    toast.textContent = message;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-show'));
    setTimeout(() => {
        toast.classList.remove('toast-show');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

function renderAlertRules(ticker) {
    const alerts = (currentConfig.alerts || {})[ticker] || [];
    const container = document.getElementById('alert-rules');
    if (alerts.length === 0) {
        container.innerHTML = '<div style="color:var(--text2);font-size:13px">No alerts set</div>';
        return;
    }
    container.innerHTML = '';
    alerts.forEach((rule, i) => {
        const div = document.createElement('div');
        div.className = 'alert-rule';
        let desc = '';
        if (rule.type === 'price_above') desc = `Price goes above $${rule.value}`;
        else if (rule.type === 'price_below') desc = `Price drops below $${rule.value}`;
        else if (rule.type === 'signal_buy') desc = 'Signal changes to BUY';
        else if (rule.type === 'signal_sell') desc = 'Signal changes to SELL';
        div.innerHTML = `
            <span>${desc} ${rule.enabled ? '' : '<span style="color:var(--text2)">(fired)</span>'}</span>
            <span class="tag-remove" style="cursor:pointer">&times;</span>
        `;
        div.querySelector('.tag-remove').onclick = () => removeAlert(ticker, i);
        container.appendChild(div);
    });
}

function addAlert() {
    const ticker = currentDetailTicker;
    if (!ticker) return;
    const type = document.getElementById('alert-type').value;
    const value = parseFloat(document.getElementById('alert-value').value);
    if (type.startsWith('price') && (!value || value <= 0)) { alert('Enter a valid price'); return; }
    if (!currentConfig.alerts) currentConfig.alerts = {};
    if (!currentConfig.alerts[ticker]) currentConfig.alerts[ticker] = [];
    const rule = { type, enabled: true };
    if (type.startsWith('price')) rule.value = value;
    currentConfig.alerts[ticker].push(rule);
    saveConfigSilent();
    renderAlertRules(ticker);
    document.getElementById('alert-value').value = '';
    showToast(`Alert added for ${ticker}`, 'alert');
}

function removeAlert(ticker, index) {
    if (currentConfig.alerts && currentConfig.alerts[ticker]) {
        currentConfig.alerts[ticker].splice(index, 1);
        saveConfigSilent();
        renderAlertRules(ticker);
    }
}

/* ─── Journal ──────────────────────────────────────────────────────────── */
async function openJournal() {
    try {
        const res = await fetch('/api/journal');
        const data = await res.json();
        renderJournalTable(data.entries);
        document.getElementById('journal-modal').classList.remove('hidden');
    } catch (e) { alert('Failed to load journal'); }
}

function renderJournalTable(entries) {
    const tbody = document.getElementById('journal-body');
    tbody.innerHTML = '';
    if (entries.length === 0) { tbody.innerHTML = '<tr><td colspan="14" style="color:var(--text2);text-align:center;padding:20px">No journal entries yet</td></tr>'; return; }
    entries.forEach(e => {
        const pnl = e.exit_price && e.entry_price ? ((e.exit_price - e.entry_price) * (e.shares || 1)).toFixed(2) : '-';
        const pnlClass = parseFloat(pnl) >= 0 ? 'positive' : 'negative';
        const shares = e.shares || 1;
        const isOpen = !e.exit_price;

        // Projection columns for open trades
        let w1 = '-', w2 = '-', w3 = '-', w4 = '-', status = '-';
        let w1c = '', w2c = '', w3c = '', w4c = '', statusClass = '';

        if (isOpen && e.ticker && e.entry_price) {
            const stock = scanResults.find(s => s.ticker === e.ticker.toUpperCase());
            if (stock) {
                const entry = e.entry_price;
                const target = stock.target;
                const current = stock.price;
                const stopLoss = stock.stop_loss;
                const targetMove = target - entry;
                const proj = [0.25, 0.50, 0.75, 1.0].map(pct => {
                    const projPrice = entry + targetMove * pct;
                    const projPnl = (projPrice - entry) * shares;
                    const projPct = ((projPrice - entry) / entry * 100);
                    return { pnl: projPnl, pct: projPct };
                });
                const fmtProj = (p) => {
                    const sign = p.pct >= 0 ? '+' : '';
                    return `${sign}${p.pct.toFixed(1)}%`;
                };
                const projClass = (p) => p.pct >= 0 ? 'positive' : 'negative';
                w1 = fmtProj(proj[0]); w1c = projClass(proj[0]);
                w2 = fmtProj(proj[1]); w2c = projClass(proj[1]);
                w3 = fmtProj(proj[2]); w3c = projClass(proj[2]);
                w4 = fmtProj(proj[3]); w4c = projClass(proj[3]);

                // Status: compare current price vs projected path
                const currentPnlPct = (current - entry) / entry * 100;
                const proj2wPct = proj[1].pct;
                const proj1wPct = proj[0].pct;
                if (current <= stopLoss) {
                    status = 'Cut Loss'; statusClass = 'journal-status-cut';
                } else if (currentPnlPct >= proj2wPct && proj2wPct > 0) {
                    status = 'Ahead'; statusClass = 'journal-status-ahead';
                } else if (currentPnlPct >= proj1wPct * 0.5) {
                    status = 'On Track'; statusClass = 'journal-status-track';
                } else {
                    status = 'Behind'; statusClass = 'journal-status-behind';
                }
            }
        } else if (!isOpen && e.entry_price && e.exit_price) {
            const returnPct = ((e.exit_price - e.entry_price) / e.entry_price * 100);
            const sign = returnPct >= 0 ? '+' : '';
            status = returnPct >= 0 ? `Won ${sign}${returnPct.toFixed(1)}%` : `Lost ${returnPct.toFixed(1)}%`;
            statusClass = returnPct >= 0 ? 'journal-status-ahead' : 'journal-status-cut';
        }

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${e.entry_date || '-'}</td>
            <td class="ticker-cell">${e.ticker || '-'}</td>
            <td>${e.type || '-'}</td>
            <td>$${(e.entry_price || 0).toFixed(2)}</td>
            <td>${e.exit_price ? '$' + e.exit_price.toFixed(2) : '-'}</td>
            <td>${e.shares || '-'}</td>
            <td class="${pnlClass}">${pnl !== '-' ? '$' + pnl : '-'}</td>
            <td class="journal-proj ${w1c}">${w1}</td>
            <td class="journal-proj ${w2c}">${w2}</td>
            <td class="journal-proj ${w3c}">${w3}</td>
            <td class="journal-proj ${w4c}">${w4}</td>
            <td><span class="journal-status ${statusClass}">${status}</span></td>
            <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis">${e.notes || ''}</td>
            <td><span class="tag-remove" style="cursor:pointer">&times;</span></td>
        `;
        tr.querySelector('.tag-remove').onclick = async () => {
            await fetch('/api/journal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'delete', id: e.id }) });
            openJournal();
        };
        tbody.appendChild(tr);
    });
}

async function submitJournalEntry() {
    const entry = {
        ticker: document.getElementById('j-ticker').value.toUpperCase(),
        type: document.getElementById('j-type').value,
        entry_price: parseFloat(document.getElementById('j-entry').value) || 0,
        entry_date: document.getElementById('j-entry-date').value,
        exit_price: parseFloat(document.getElementById('j-exit').value) || null,
        exit_date: document.getElementById('j-exit-date').value || null,
        shares: parseInt(document.getElementById('j-shares').value) || 1,
        notes: document.getElementById('j-notes').value,
    };
    if (!entry.ticker || !entry.entry_price) { alert('Ticker and entry price are required'); return; }
    try {
        await fetch('/api/journal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'add', entry }) });
        document.getElementById('journal-form').classList.add('hidden');
        openJournal();
        showToast('Journal entry added', 'alert');
    } catch (e) { alert('Failed to save journal entry'); }
}

async function exportJournalCSV() {
    try {
        const res = await fetch('/api/journal');
        const data = await res.json();
        const entries = data.entries;
        if (entries.length === 0) { showToast('No journal entries to export', 'alert'); return; }

        const headers = ['Ticker', 'Type', 'Entry Price', 'Entry Date', 'Exit Price', 'Exit Date', 'Shares', 'P&L', 'P&L %', 'Notes'];
        const rows = entries.map(e => {
            const pnl = (e.exit_price && e.entry_price) ? ((e.exit_price - e.entry_price) * (e.shares || 1)) : '';
            const pnlPct = (e.exit_price && e.entry_price && e.entry_price > 0) ? (((e.exit_price - e.entry_price) / e.entry_price) * 100) : '';
            return [
                e.ticker || '',
                e.type || '',
                e.entry_price || '',
                e.entry_date || '',
                e.exit_price || '',
                e.exit_date || '',
                e.shares || '',
                pnl !== '' ? pnl.toFixed(2) : '',
                pnlPct !== '' ? pnlPct.toFixed(2) : '',
                '"' + (e.notes || '').replace(/"/g, '""') + '"',
            ];
        });

        let csv = headers.join(',') + '\n';
        rows.forEach(row => { csv += row.join(',') + '\n'; });

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `trade_journal_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Journal exported to CSV', 'alert');
    } catch (e) { showToast('Failed to export journal', 'alert'); }
}

/* ─── Groups Management ──────────────────────────────────────────────── */
function addGroup() {
    const input = document.getElementById('add-group-input');
    const name = input.value.trim();
    if (!name) return;
    if (!currentConfig.groups) currentConfig.groups = {};
    if (!currentConfig.groups[name]) currentConfig.groups[name] = [];
    input.value = '';
    renderGroupsEditor();
}

function renderGroupsEditor() {
    const container = document.getElementById('groups-editor');
    const groups = currentConfig.groups || {};
    const names = Object.keys(groups);
    if (names.length === 0) { container.innerHTML = '<div style="color:var(--text2);font-size:12px">No groups created</div>'; return; }
    container.innerHTML = '';
    names.forEach(name => {
        const div = document.createElement('div');
        div.className = 'group-item';
        const tickers = groups[name] || [];
        div.innerHTML = `
            <div class="group-item-header">
                <span>${name}</span>
                <span class="tag-remove" style="cursor:pointer">&times;</span>
            </div>
            <div class="tag-container">${tickers.map(t => `<span class="tag">${t}<span class="tag-remove grm" data-g="${name}" data-t="${t}">&times;</span></span>`).join('')}</div>
            <div class="tag-input-row">
                <select class="group-ticker-select" style="flex:1">${(currentConfig.watchlist || []).map(t => `<option>${t}</option>`).join('')}</select>
                <button class="btn btn-small group-add-btn" data-g="${name}">+ Add</button>
            </div>
        `;
        div.querySelector('.group-item-header .tag-remove').onclick = () => { delete currentConfig.groups[name]; renderGroupsEditor(); };
        div.querySelectorAll('.grm').forEach(el => {
            el.onclick = () => {
                currentConfig.groups[el.dataset.g] = currentConfig.groups[el.dataset.g].filter(t => t !== el.dataset.t);
                renderGroupsEditor();
            };
        });
        div.querySelector('.group-add-btn').onclick = () => {
            const sel = div.querySelector('.group-ticker-select');
            const t = sel.value;
            if (t && !groups[name].includes(t)) { groups[name].push(t); renderGroupsEditor(); }
        };
        container.appendChild(div);
    });
}

/* ─── Backtest ─────────────────────────────────────────────────────────── */
function showBacktest(ticker) {
    destroyCharts();
    if (equityChart) { equityChart.remove(); equityChart = null; }
    document.getElementById('view-summary').classList.add('hidden');
    document.getElementById('view-detail').classList.add('hidden');
    document.getElementById('view-portfolio').classList.add('hidden');
    document.getElementById('view-heatmap').classList.add('hidden');
    document.getElementById('view-backtest').classList.remove('hidden');
    if (ticker) document.getElementById('bt-ticker').value = ticker;
    document.getElementById('bt-summary').classList.add('hidden');
    document.getElementById('bt-trades-section').classList.add('hidden');
    document.getElementById('backtest-chart').innerHTML = '';
    document.getElementById('bt-trades-body').innerHTML = '';
}

async function runBacktest() {
    const input = document.getElementById('bt-ticker');
    const ticker = (input.value.trim() || input.placeholder.trim()).toUpperCase();
    const days = parseInt(document.getElementById('bt-days').value);
    if (!ticker) { alert('Enter a ticker'); return; }
    showLoading(`Backtesting ${ticker}...`);
    try {
        const res = await fetch('/api/backtest', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker, days }),
        });
        const data = await res.json();
        if (data.error) { alert(data.error); hideLoading(); return; }
        renderBacktestResults(data);
        renderBacktestChart(data);
    } catch (e) { alert('Backtest failed: ' + e.message); }
    hideLoading();
}

function renderBacktestResults(data) {
    const s = data.summary;
    const container = document.getElementById('bt-summary');
    container.classList.remove('hidden');
    container.innerHTML = `
        <div class="bt-card"><div class="bt-card-label">Total Trades</div><div class="bt-card-value">${s.total_trades}</div></div>
        <div class="bt-card"><div class="bt-card-label">Win Rate</div><div class="bt-card-value ${s.win_rate >= 50 ? 'positive' : 'negative'}">${s.win_rate}%</div></div>
        <div class="bt-card"><div class="bt-card-label">Avg Return</div><div class="bt-card-value ${s.avg_return >= 0 ? 'positive' : 'negative'}">${s.avg_return >= 0 ? '+' : ''}${s.avg_return}%</div></div>
        <div class="bt-card"><div class="bt-card-label">Total Return</div><div class="bt-card-value ${s.total_return >= 0 ? 'positive' : 'negative'}">${s.total_return >= 0 ? '+' : ''}${s.total_return}%</div></div>
        <div class="bt-card"><div class="bt-card-label">Max Drawdown</div><div class="bt-card-value negative">-${s.max_drawdown}%</div></div>
    `;
    const tbody = document.getElementById('bt-trades-body');
    tbody.innerHTML = '';
    document.getElementById('bt-trades-section').classList.remove('hidden');
    data.trades.forEach((t, i) => {
        const cls = t.return_pct >= 0 ? 'positive' : 'negative';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${i + 1}</td>
            <td>${new Date(t.entry_time * 1000).toLocaleDateString()}</td>
            <td>$${t.entry_price.toFixed(2)}</td>
            <td>${t.open ? 'Open' : new Date(t.exit_time * 1000).toLocaleDateString()}</td>
            <td>$${t.exit_price.toFixed(2)}</td>
            <td class="${cls}">${t.return_pct >= 0 ? '+' : ''}${t.return_pct.toFixed(2)}%</td>
            <td class="${cls}">${t.return_pct >= 0 ? 'WIN' : 'LOSS'}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderBacktestChart(data) {
    const el = document.getElementById('backtest-chart');
    el.innerHTML = '';
    const chartOptions = {
        layout: { background: { color: '#1a1a2e' }, textColor: '#d1d5db' },
        grid: { vertLines: { color: '#2d2d44' }, horzLines: { color: '#2d2d44' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        timeScale: { timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#2d2d44' },
        width: el.clientWidth, height: 500,
    };
    charts.backtest = LightweightCharts.createChart(el, chartOptions);
    const candleSeries = charts.backtest.addCandlestickSeries({
        upColor: '#26a69a', downColor: '#ef5350',
        borderUpColor: '#26a69a', borderDownColor: '#ef5350',
        wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeries.setData(data.candles);
    if (data.markers && data.markers.length > 0) candleSeries.setMarkers(data.markers);
    const resizeHandler = () => { if (charts.backtest) charts.backtest.applyOptions({ width: el.clientWidth }); };
    window.addEventListener('resize', resizeHandler);
    charts._btResizeHandler = resizeHandler;
}

/* ─── Portfolio Tracker ──────────────────────────────────────────────── */
function showPortfolio() {
    destroyCharts();
    if (equityChart) { equityChart.remove(); equityChart = null; }
    document.getElementById('view-summary').classList.add('hidden');
    document.getElementById('view-detail').classList.add('hidden');
    document.getElementById('view-backtest').classList.add('hidden');
    document.getElementById('view-heatmap').classList.add('hidden');
    document.getElementById('view-portfolio').classList.remove('hidden');
    loadPortfolio();
}

async function loadPortfolio() {
    showLoading('Loading portfolio...');
    try {
        const res = await fetch('/api/portfolio');
        const data = await res.json();
        renderPortfolioSummary(data.summary, data.positions);
        renderPositionCards(data.positions);
        renderEquityCurve(data.equity_curve);
    } catch (e) { alert('Failed to load portfolio: ' + e.message); }
    hideLoading();
}

function renderPortfolioSummary(s, positions) {
    const isPos = s.total_unrealized_pnl >= 0;
    const sign = isPos ? '+' : '';
    const pnlColor = isPos ? 'var(--green)' : 'var(--red)';
    const heatClass = s.portfolio_heat < 5 ? 'pf-heat-low' : s.portfolio_heat < 10 ? 'pf-heat-medium' : 'pf-heat-high';
    const heatLabel = s.portfolio_heat < 5 ? 'LOW' : s.portfolio_heat < 10 ? 'MEDIUM' : 'HIGH';
    const arrow = isPos ? '▲' : '▼';
    const glowColor = isPos ? 'rgba(38,166,154,0.15)' : 'rgba(239,83,80,0.15)';

    // ── Banner ──
    const banner = document.getElementById('pf-banner');
    banner.innerHTML = `
        <div class="pf-banner-inner" style="background:linear-gradient(135deg, var(--surface2) 0%, ${glowColor} 100%)">
            <div class="pf-banner-left">
                <div class="pf-banner-label">Unrealized P&L</div>
                <div class="pf-banner-amount" style="color:${pnlColor}">
                    <span class="pf-banner-arrow">${arrow}</span>
                    ${sign}$${Math.abs(s.total_unrealized_pnl).toFixed(2)}
                </div>
                <div class="pf-banner-pct" style="color:${pnlColor}">${sign}${s.total_unrealized_pct.toFixed(2)}%</div>
            </div>
            <div class="pf-banner-stats">
                <div class="pf-chip">
                    <span class="pf-chip-label">Invested</span>
                    <span class="pf-chip-value">$${s.total_invested.toFixed(0)}</span>
                </div>
                <div class="pf-chip">
                    <span class="pf-chip-label">Value</span>
                    <span class="pf-chip-value">$${s.total_current_value.toFixed(0)}</span>
                </div>
                <div class="pf-chip">
                    <span class="pf-chip-label">Positions</span>
                    <span class="pf-chip-value">${s.total_positions}</span>
                </div>
                <div class="pf-chip">
                    <span class="pf-chip-label">Heat</span>
                    <span class="pf-chip-value ${heatClass}">${s.portfolio_heat.toFixed(1)}%</span>
                </div>
                <div class="pf-chip">
                    <span class="pf-chip-label">Account</span>
                    <span class="pf-chip-value">$${s.account_size}</span>
                </div>
            </div>
        </div>
    `;

    // ── Allocation Bar ──
    const allocSection = document.getElementById('pf-alloc-section');
    const colors = ['#2196F3', '#26a69a', '#ab47bc', '#FF9800', '#ef5350', '#ffd54f', '#4caf50', '#e91e63'];
    const validPositions = positions.filter(p => p.invested > 0);
    const totalInvested = validPositions.reduce((sum, p) => sum + p.invested, 0);

    if (validPositions.length === 0 || totalInvested === 0) {
        allocSection.innerHTML = `<div class="pf-alloc-empty">No allocation data</div>`;
    } else {
        const segments = validPositions.map((p, i) => {
            const pct = ((p.invested / totalInvested) * 100);
            const color = colors[i % colors.length];
            return `<div class="pf-alloc-seg" style="width:${pct}%;background:${color}" title="${p.ticker} ${pct.toFixed(1)}%"></div>`;
        }).join('');
        const labels = validPositions.map((p, i) => {
            const pct = ((p.invested / totalInvested) * 100).toFixed(0);
            return `<div class="pf-alloc-label"><span class="pf-alloc-dot" style="background:${colors[i % colors.length]}"></span><span>${p.ticker}</span><span class="pf-alloc-label-pct">${pct}%</span></div>`;
        }).join('');
        allocSection.innerHTML = `
            <div class="pf-alloc-title-row">
                <span class="pf-section-label">Allocation</span>
                <span class="pf-alloc-total">$${totalInvested.toFixed(0)} across ${validPositions.length} positions</span>
            </div>
            <div class="pf-alloc-bar">${segments}</div>
            <div class="pf-alloc-labels">${labels}</div>
        `;
    }

    // ── List Count ──
    document.getElementById('pf-list-count').textContent = positions.length + ' active';

    // ── Risk Panel ──
    const riskPanel = document.getElementById('pf-risk-panel');
    const cashAvail = s.account_size - s.total_invested;
    const cashPct = s.account_size > 0 ? ((cashAvail / s.account_size) * 100).toFixed(1) : '100.0';
    const heatPct = Math.min(s.portfolio_heat, 100);
    const heatDeg = (heatPct / 100) * 180;
    riskPanel.innerHTML = `
        <div class="pf-section-label">Risk Overview</div>
        <div class="pf-risk-gauge">
            <div class="pf-gauge-track">
                <div class="pf-gauge-fill" style="transform:rotate(${heatDeg}deg)"></div>
                <div class="pf-gauge-cover"></div>
                <div class="pf-gauge-needle" style="transform:rotate(${heatDeg}deg)"></div>
            </div>
            <div class="pf-gauge-label">
                <span class="pf-gauge-value ${heatClass}">${s.portfolio_heat.toFixed(1)}%</span>
                <span class="pf-gauge-text">Portfolio Heat</span>
            </div>
        </div>
        <div class="pf-risk-rows">
            <div class="pf-risk-row">
                <span>Cash Available</span>
                <span class="pf-risk-val">$${cashAvail.toFixed(0)} (${cashPct}%)</span>
            </div>
            <div class="pf-risk-row">
                <span>Max Exposure</span>
                <span class="pf-risk-val">$${s.total_invested.toFixed(0)}</span>
            </div>
            <div class="pf-risk-row">
                <span>Risk Level</span>
                <span class="pf-risk-val ${heatClass}">${heatLabel}</span>
            </div>
            <div class="pf-risk-row">
                <span>Open Positions</span>
                <span class="pf-risk-val">${s.total_positions}</span>
            </div>
        </div>
    `;
}

function renderPositionCards(positions) {
    const list = document.getElementById('pf-list');
    list.innerHTML = '';
    if (positions.length === 0) {
        list.innerHTML = '<div class="pf-list-empty"><div class="pf-list-empty-icon">📊</div><div>No open positions</div><div class="pf-list-empty-sub">Add entries in the Trade Journal with no exit price to track them here.</div></div>';
        return;
    }
    positions.forEach(p => {
        const row = document.createElement('div');
        const hasPrice = p.current_price !== null;
        const isProfit = hasPrice && p.unrealized_pnl >= 0;
        const accentColor = !hasPrice ? 'var(--text2)' : isProfit ? 'var(--green)' : 'var(--red)';
        const typeCls = p.type === 'BUY' ? 'pf-type-buy' : 'pf-type-sell';
        const daysText = p.days_held !== null ? p.days_held + 'd' : '-';

        // P&L pill
        let pnlPill = '';
        if (hasPrice) {
            const sign = p.unrealized_pnl >= 0 ? '+' : '';
            const cls = isProfit ? 'pf-pnl-pos' : 'pf-pnl-neg';
            pnlPill = `<div class="pf-row-pnl ${cls}"><span class="pf-row-pnl-dollar">${sign}$${Math.abs(p.unrealized_pnl).toFixed(2)}</span><span class="pf-row-pnl-pct">${sign}${p.pnl_pct.toFixed(2)}%</span></div>`;
        } else {
            pnlPill = `<div class="pf-row-pnl pf-pnl-na">N/A</div>`;
        }

        // Risk bar
        let riskBar = '';
        if (hasPrice) {
            const stock = scanResults.find(s => s.ticker === p.ticker);
            if (stock && stock.stop_loss && stock.target) {
                const stop = stock.stop_loss;
                const target = stock.target;
                const range = target - stop;
                if (range > 0) {
                    const entryPct = Math.max(0, Math.min(100, ((p.entry_price - stop) / range) * 100));
                    const curPct = Math.max(0, Math.min(100, ((p.current_price - stop) / range) * 100));
                    const barColor = isProfit ? 'var(--green)' : 'var(--red)';
                    riskBar = `
                        <div class="pf-row-risk">
                            <div class="pf-row-risk-bar">
                                <div class="pf-row-risk-fill" style="width:${curPct}%;background:${barColor}"></div>
                                <div class="pf-row-risk-entry" style="left:${entryPct}%"></div>
                                <div class="pf-row-risk-dot" style="left:${curPct}%;background:${barColor}"></div>
                            </div>
                            <div class="pf-row-risk-labels"><span>$${stop.toFixed(0)}</span><span>$${target.toFixed(0)}</span></div>
                        </div>
                    `;
                }
            }
        }

        row.className = 'pf-row';
        row.innerHTML = `
            <div class="pf-row-accent" style="background:${accentColor}"></div>
            <div class="pf-row-main">
                <div class="pf-row-left">
                    <div class="pf-row-ticker-group">
                        <span class="pf-row-ticker">${p.ticker}</span>
                        <span class="pf-row-badge ${typeCls}">${p.type}</span>
                    </div>
                    <div class="pf-row-meta">${p.shares} shares · $${p.invested.toFixed(0)} · ${daysText}</div>
                </div>
                <div class="pf-row-center">
                    <div class="pf-row-prices">
                        <span class="pf-row-price-label">Entry</span>
                        <span class="pf-row-price">$${p.entry_price.toFixed(2)}</span>
                    </div>
                    <span class="pf-row-arrow">→</span>
                    <div class="pf-row-prices">
                        <span class="pf-row-price-label">Current</span>
                        <span class="pf-row-price">${hasPrice ? '$' + p.current_price.toFixed(2) : 'N/A'}</span>
                    </div>
                </div>
                ${pnlPill}
                ${riskBar}
                <button class="pf-row-close" title="Close position">✕</button>
            </div>
        `;
        row.querySelector('.pf-row-close').addEventListener('click', () => openCloseDialog(p));
        list.appendChild(row);
    });
}

function openCloseDialog(position) {
    const exitPrice = prompt(`Close ${position.ticker} at what price? (Current: $${position.current_price})`);
    if (!exitPrice) return;
    const price = parseFloat(exitPrice);
    if (isNaN(price) || price <= 0) { alert('Invalid price'); return; }
    closePosition(position.id, price);
}

async function closePosition(id, exitPrice) {
    try {
        await fetch('/api/portfolio/close', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, exit_price: exitPrice }),
        });
        showToast('Position closed', 'alert');
        loadPortfolio();
    } catch (e) { alert('Failed to close position: ' + e.message); }
}

function renderEquityCurve(curve) {
    const el = document.getElementById('equity-chart');
    el.innerHTML = '';
    if (equityChart) { equityChart.remove(); equityChart = null; }
    if (!curve || curve.length < 2) {
        el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text2)">Not enough data for equity curve</div>';
        return;
    }
    const chartOptions = {
        layout: { background: { color: '#1a1a2e' }, textColor: '#d1d5db' },
        grid: { vertLines: { color: '#2d2d44' }, horzLines: { color: '#2d2d44' } },
        rightPriceScale: { borderColor: '#2d2d44' },
        timeScale: { timeVisible: false },
        width: el.clientWidth, height: 350,
    };
    equityChart = LightweightCharts.createChart(el, chartOptions);
    const baseDate = new Date('2020-01-01');
    const data = curve.map((point, i) => ({
        time: Math.floor(baseDate.getTime() / 1000) + (i * 86400),
        value: point.value,
    }));
    const lineSeries = equityChart.addLineSeries({ color: '#2196F3', lineWidth: 2, title: 'Equity' });
    lineSeries.setData(data);
    lineSeries.createPriceLine({ price: curve[0].value, color: '#555', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Start' });
    const handler = () => { if (equityChart) equityChart.applyOptions({ width: el.clientWidth }); };
    window.addEventListener('resize', handler);
    charts._eqResizeHandler = handler;
}

/* ─── Heatmap View ─────────────────────────────────────────────────── */
function showHeatmap() {
    destroyCharts();
    if (equityChart) { equityChart.remove(); equityChart = null; }
    document.getElementById('view-summary').classList.add('hidden');
    document.getElementById('view-detail').classList.add('hidden');
    document.getElementById('view-backtest').classList.add('hidden');
    document.getElementById('view-portfolio').classList.add('hidden');
    document.getElementById('view-heatmap').classList.remove('hidden');
    renderHeatmap();
}

function renderHeatmap() {
    const container = document.getElementById('heatmap-container');
    container.innerHTML = '';

    if (scanResults.length === 0) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:300px;color:var(--text2)">No scan data. Run a scan first.</div>';
        return;
    }

    const minVol = Math.min(...scanResults.map(r => r.volume_ratio));
    const maxVol = Math.max(...scanResults.map(r => r.volume_ratio));
    const volRange = maxVol - minVol || 1;
    const maxAbsChange = Math.max(...scanResults.map(r => Math.abs(r.change_2m)), 1);

    const sorted = [...scanResults].sort((a, b) => Math.abs(b.change_2m) - Math.abs(a.change_2m));

    sorted.forEach(r => {
        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';

        const normVol = (r.volume_ratio - minVol) / volRange;
        const size = Math.round(80 + normVol * 100);
        cell.style.width = size + 'px';
        cell.style.height = size + 'px';

        const intensity = Math.min(Math.abs(r.change_2m) / maxAbsChange, 1);
        const alpha = 0.3 + intensity * 0.7;
        if (r.change_2m >= 0) {
            cell.style.background = `rgba(38, 166, 154, ${alpha})`;
        } else {
            cell.style.background = `rgba(239, 83, 80, ${alpha})`;
        }

        const changeSign = r.change_2m >= 0 ? '+' : '';
        cell.innerHTML = `
            <span class="heatmap-ticker">${r.ticker}</span>
            <span class="heatmap-price">$${r.price.toFixed(2)}</span>
            <span class="heatmap-change">${changeSign}${r.change_2m.toFixed(1)}%</span>
        `;

        cell.addEventListener('click', () => showDetail(r.ticker));
        container.appendChild(cell);
    });
}

/* ─── Charts (detail view) ─────────────────────────────────────────────── */
function renderCharts(data) {
    const chartOptions = {
        layout: { background: { color: '#1a1a2e' }, textColor: '#d1d5db' },
        grid: { vertLines: { color: '#2d2d44' }, horzLines: { color: '#2d2d44' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        timeScale: { timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#2d2d44' },
    };

    const mainEl = document.getElementById('main-chart');
    mainEl.innerHTML = '';
    charts.main = LightweightCharts.createChart(mainEl, { ...chartOptions, width: mainEl.clientWidth, height: 400 });

    const candleSeries = charts.main.addCandlestickSeries({
        upColor: '#26a69a', downColor: '#ef5350',
        borderUpColor: '#26a69a', borderDownColor: '#ef5350',
        wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeries.setData(data.candles);

    const emaFastSeries = charts.main.addLineSeries({ color: '#2196F3', lineWidth: 2, title: 'EMA 20' });
    emaFastSeries.setData(data.ema_fast);
    const emaSlowSeries = charts.main.addLineSeries({ color: '#FF9800', lineWidth: 2, title: 'EMA 50' });
    emaSlowSeries.setData(data.ema_slow);

    const volumeSeries = charts.main.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'volume' });
    charts.main.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeries.setData(data.volumes);

    const rsiEl = document.getElementById('rsi-chart');
    rsiEl.innerHTML = '';
    charts.rsi = LightweightCharts.createChart(rsiEl, { ...chartOptions, width: rsiEl.clientWidth, height: 180 });
    const rsiSeries = charts.rsi.addLineSeries({ color: '#ab47bc', lineWidth: 2, title: 'RSI' });
    rsiSeries.setData(data.rsi);
    rsiSeries.createPriceLine({ price: 70, color: '#ef5350', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Overbought' });
    rsiSeries.createPriceLine({ price: 30, color: '#26a69a', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Oversold' });
    rsiSeries.createPriceLine({ price: 50, color: '#555', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });

    const macdEl = document.getElementById('macd-chart');
    macdEl.innerHTML = '';
    charts.macd = LightweightCharts.createChart(macdEl, { ...chartOptions, width: macdEl.clientWidth, height: 180 });
    const macdHistSeries = charts.macd.addHistogramSeries({ priceFormat: { type: 'price' }, priceScaleId: 'macd' });
    macdHistSeries.setData(data.macd_hist.map(d => ({ ...d, color: d.value >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)' })));
    const macdLineSeries = charts.macd.addLineSeries({ color: '#2196F3', lineWidth: 2, title: 'MACD', priceScaleId: 'macd' });
    macdLineSeries.setData(data.macd);
    const macdSignalSeries = charts.macd.addLineSeries({ color: '#FF9800', lineWidth: 2, title: 'Signal', priceScaleId: 'macd' });
    macdSignalSeries.setData(data.macd_signal);

    function syncRange(source, targets) {
        let syncing = false;
        source.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (syncing) return; syncing = true;
            targets.forEach(t => { if (t) t.timeScale().setVisibleLogicalRange(range); });
            syncing = false;
        });
    }
    syncRange(charts.main, [charts.rsi, charts.macd]);
    syncRange(charts.rsi, [charts.main, charts.macd]);
    syncRange(charts.macd, [charts.main, charts.rsi]);

    function syncCrosshair(source, targets, series) {
        source.subscribeCrosshairMove(param => {
            targets.forEach((t, i) => {
                if (!t) return;
                if (param.time) t.setCrosshairPosition(undefined, param.time, series[i]);
                else t.clearCrosshairPosition();
            });
        });
    }
    syncCrosshair(charts.main, [charts.rsi, charts.macd], [rsiSeries, macdLineSeries]);
    syncCrosshair(charts.rsi, [charts.main, charts.macd], [candleSeries, macdLineSeries]);
    syncCrosshair(charts.macd, [charts.main, charts.rsi], [candleSeries, rsiSeries]);

    charts._resizeHandler = () => {
        if (charts.main) charts.main.applyOptions({ width: mainEl.clientWidth });
        if (charts.rsi) charts.rsi.applyOptions({ width: rsiEl.clientWidth });
        if (charts.macd) charts.macd.applyOptions({ width: macdEl.clientWidth });
    };
    window.addEventListener('resize', charts._resizeHandler);
}

function destroyCharts() {
    if (charts._resizeHandler) { window.removeEventListener('resize', charts._resizeHandler); charts._resizeHandler = null; }
    if (charts._btResizeHandler) { window.removeEventListener('resize', charts._btResizeHandler); charts._btResizeHandler = null; }
    if (charts._eqResizeHandler) { window.removeEventListener('resize', charts._eqResizeHandler); charts._eqResizeHandler = null; }
    ['main', 'rsi', 'macd', 'backtest'].forEach(key => {
        if (charts[key]) { charts[key].remove(); charts[key] = null; }
    });
}

/* ─── Settings ─────────────────────────────────────────────────────────── */
async function openSettings() {
    try {
        const res = await fetch('/api/config');
        currentConfig = await res.json();
    } catch (err) { alert('Failed to load settings'); return; }

    renderWatchlistTags(currentConfig.watchlist);
    renderGroupsEditor();
    document.getElementById('cfg-ema-fast').value = currentConfig.ema_fast;
    document.getElementById('cfg-ema-slow').value = currentConfig.ema_slow;
    document.getElementById('cfg-rsi').value = currentConfig.rsi_period;
    document.getElementById('cfg-macd-fast').value = currentConfig.macd_fast;
    document.getElementById('cfg-macd-slow').value = currentConfig.macd_slow;
    document.getElementById('cfg-macd-signal').value = currentConfig.macd_signal;
    document.getElementById('cfg-account').value = currentConfig.account_size;
    document.getElementById('cfg-risk').value = currentConfig.risk_percent;
    document.getElementById('cfg-volume').value = currentConfig.volume_spike_multiplier;
    document.getElementById('cfg-min-score').value = currentConfig.min_score;
    document.getElementById('cfg-refresh').value = currentConfig.auto_refresh_minutes || 5;
    document.getElementById('cfg-polygon-key').value = currentConfig.polygon_key || '';
    document.getElementById('cfg-alpha-key').value = currentConfig.alpha_key || '';

    const as = currentConfig.alert_settings || {};
    document.getElementById('cfg-sound').checked = as.sound_enabled !== false;
    document.getElementById('cfg-browser-notif').checked = !!as.browser_notifications;
    document.getElementById('cfg-toast').checked = as.toast_enabled !== false;

    renderPresetAlertToggles();

    document.getElementById('settings-modal').classList.remove('hidden');
}

function closeSettings() { document.getElementById('settings-modal').classList.add('hidden'); }

function renderWatchlistTags(watchlist) {
    const container = document.getElementById('watchlist-tags');
    container.innerHTML = '';
    watchlist.forEach(ticker => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.innerHTML = `${ticker}<span class="tag-remove" data-ticker="${ticker}">&times;</span>`;
        tag.querySelector('.tag-remove').onclick = () => removeTicker(ticker);
        container.appendChild(tag);
    });
}

function addTicker() {
    const input = document.getElementById('add-ticker-input');
    const ticker = input.value.trim().toUpperCase();
    if (!ticker) return;
    if (!currentConfig.watchlist.includes(ticker)) {
        currentConfig.watchlist.push(ticker);
        renderWatchlistTags(currentConfig.watchlist);
    }
    input.value = '';
}

function removeTicker(ticker) {
    currentConfig.watchlist = currentConfig.watchlist.filter(t => t !== ticker);
    renderWatchlistTags(currentConfig.watchlist);
}

async function saveSettings() {
    const browserNotif = document.getElementById('cfg-browser-notif').checked;
    if (browserNotif && Notification.permission === 'default') {
        await Notification.requestPermission();
    }
    const cfg = {
        watchlist: currentConfig.watchlist,
        lookback_days: currentConfig.lookback_days || 60,
        interval: currentConfig.interval || '1h',
        ema_fast: parseInt(document.getElementById('cfg-ema-fast').value),
        ema_slow: parseInt(document.getElementById('cfg-ema-slow').value),
        rsi_period: parseInt(document.getElementById('cfg-rsi').value),
        macd_fast: parseInt(document.getElementById('cfg-macd-fast').value),
        macd_slow: parseInt(document.getElementById('cfg-macd-slow').value),
        macd_signal: parseInt(document.getElementById('cfg-macd-signal').value),
        account_size: parseFloat(document.getElementById('cfg-account').value),
        risk_percent: parseFloat(document.getElementById('cfg-risk').value),
        volume_spike_multiplier: parseFloat(document.getElementById('cfg-volume').value),
        min_score: parseInt(document.getElementById('cfg-min-score').value),
        auto_refresh_minutes: parseInt(document.getElementById('cfg-refresh').value) || 5,
        groups: currentConfig.groups || {},
        notes: currentConfig.notes || {},
        alerts: currentConfig.alerts || {},
        alert_settings: {
            sound_enabled: document.getElementById('cfg-sound').checked,
            browser_notifications: browserNotif,
            toast_enabled: document.getElementById('cfg-toast').checked,
        },
        screener_presets: currentConfig.screener_presets || {},
        polygon_key: document.getElementById('cfg-polygon-key').value.trim(),
        alpha_key: document.getElementById('cfg-alpha-key').value.trim(),
    };
    try {
        await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) });
        currentConfig = cfg;
        closeSettings();
        startAutoRefresh();
        runScan();
    } catch (err) { alert('Failed to save settings: ' + err.message); }
}

async function saveConfigSilent() {
    const cfg = { ...currentConfig };
    try {
        await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) });
    } catch (e) { /* silent */ }
}

/* ─── Helpers ──────────────────────────────────────────────────────────── */
function showLoading(text) {
    document.getElementById('loading-text').textContent = text || 'Loading...';
    document.getElementById('loading').classList.remove('hidden');
}

function hideLoading() { document.getElementById('loading').classList.add('hidden'); }

/* ─── Market Overview ──────────────────────────────────────────────────── */
async function fetchMarketOverview() {
    try {
        const res = await fetch('/api/market-overview');
        const data = await res.json();
        marketOverviewData = data;
        renderMarketOverview(data);
    } catch (e) { /* silent */ }
}

function renderMarketOverview(data) {
    const el = document.getElementById('market-overview');
    if (!el || !data || data.error) { if (el) el.classList.add('hidden'); return; }
    const sentClass = (data.sentiment_class || 'neutral');
    const sentEl = document.getElementById('market-sentiment-text');
    if (sentEl) {
        sentEl.textContent = data.sentiment || 'Unknown';
        sentEl.className = 'market-sentiment-value sentiment-' + sentClass;
    }
    const indicesEl = document.getElementById('market-indices');
    if (indicesEl && data.indices) {
        indicesEl.innerHTML = Object.entries(data.indices).map(([sym, info]) => {
            const aboveText = info.above_ema50 ? '▲ Above EMA50' : '▼ Below EMA50';
            const aboveColor = info.above_ema50 ? 'var(--green)' : 'var(--red)';
            return `<div class="market-index-item">
                <span class="market-index-name">${sym}</span>
                <span style="color:${aboveColor};font-weight:700;font-size:11px">${aboveText}</span>
                <span style="color:var(--text2);font-size:11px">EMA50: $${(info.ema50 || 0).toFixed(2)}</span>
            </div>`;
        }).join('');
    }
    // Update header nav pills with live SPY / QQQ sentiment
    if (data.indices) {
        const spyPill = document.getElementById('nav-spy-pill');
        const qqqPill = document.getElementById('nav-qqq-pill');
        const spy = data.indices['SPY'];
        const qqq = data.indices['QQQ'];
        if (spyPill && spy) {
            spyPill.textContent = `SPY ${spy.above_ema50 ? '▲' : '▼'}`;
            spyPill.className = 'nav-pill ' + (spy.above_ema50 ? 'pill-bull' : 'pill-bear');
        }
        if (qqqPill && qqq) {
            qqqPill.textContent = `QQQ ${qqq.above_ema50 ? '▲' : '▼'}`;
            qqqPill.className = 'nav-pill ' + (qqq.above_ema50 ? 'pill-bull' : 'pill-bear');
        }
    }
    el.classList.remove('hidden');
}

/* ─── Top Setups ───────────────────────────────────────────────────────── */
async function fetchTopSetups() {
    try {
        const res = await fetch('/api/top-setups');
        const data = await res.json();
        renderTopSetups(data.setups || []);
    } catch (e) { /* silent */ }
}

function renderTopSetups(setups) {
    const section  = document.getElementById('top-setups-section');
    const heroSec  = document.getElementById('hero-section');
    const grid     = document.getElementById('top-setups-grid');
    if (!section || !grid) return;

    // Filter: score >= 70 only, limit to top 3
    const qualified = (setups || [])
        .filter(r => (r.swing_score != null ? r.swing_score : (r.score || 0)) >= 70)
        .slice(0, 3);

    if (qualified.length === 0) {
        section.classList.add('hidden');
        if (heroSec) heroSec.classList.add('hidden');
        return;
    }

    // §1 Hero Card — best trade
    if (heroSec) {
        heroSec.classList.remove('hidden');
        renderHeroCard(qualified[0]);
    }

    // §2 Top 3 cards
    section.classList.remove('hidden');
    const rankEmoji = ['🥇','🥈','🥉'];
    grid.innerHTML = '';
    qualified.forEach((r, i) => {
        const card = document.createElement('div');
        card.className = 'setup-card';
        const setupType  = r.setup_type || 'Neutral';
        const setupClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
        const score      = r.swing_score != null ? r.swing_score : (r.score || 0);
        const scoreClass = score >= 80 ? 'score-high' : 'score-mid';
        const winPct     = r.win_rate != null ? (r.win_rate * 100).toFixed(0) + '%' : '-';
        const entry      = (r.entry || r.price || 0).toFixed(2);
        const tgt        = r.target ? `$${r.target.toFixed(2)}` : '-';
        const retPct     = r.target && r.entry ? ((r.target - r.entry) / r.entry * 100).toFixed(1) : null;
        card.innerHTML = `
            <div class="setup-card-header">
                <span style="font-size:16px">${rankEmoji[i]}</span>
                <span class="setup-card-ticker">${r.ticker}</span>
                <span class="score-pill ${scoreClass}" style="margin-left:auto">${score.toFixed(0)}</span>
            </div>
            <div class="setup-card-price">$${(r.price || 0).toFixed(2)}</div>
            <span class="setup-badge ${setupClass}">${setupType}</span>
            <div class="setup-card-meta">
                <span class="setup-card-win">Win: ${winPct}</span>
                <span class="setup-card-entry">Entry: $${entry}</span>
                ${retPct ? `<span class="positive" style="font-size:11px;font-weight:700">+${retPct}%</span>` : ''}
            </div>
        `;
        card.onclick = () => showDetail(r.ticker);
        grid.appendChild(card);
    });
}

/* ── §1 Hero Card ─────────────────────────────────────────────────────────── */
function renderHeroCard(r) {
    const el = document.getElementById('hero-card');
    if (!el || !r) return;
    const score      = r.swing_score != null ? r.swing_score : (r.score || 0);
    const setupType  = r.setup_type || 'Neutral';
    const setupClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
    const entry      = (r.entry  || r.price || 0);
    const stop       = (r.stop_loss || 0);
    const target     = (r.target || 0);
    const retPct     = entry > 0 && target > 0 ? ((target - entry) / entry * 100) : 0;
    const retSign    = retPct >= 0 ? '+' : '';
    const signalRaw  = (r.signal || 'HOLD').toLowerCase().replace(' ', '-');
    const conf       = score >= 80 ? 'High' : score >= 70 ? 'Medium' : 'Low';
    const confClass  = conf === 'High' ? '' : 'conf-medium';
    el.innerHTML = `
        <div class="hero-card-left">
            <div class="hero-ticker">${r.ticker}</div>
            <div class="hero-price">$${(r.price || 0).toFixed(2)}</div>
            <span class="setup-badge ${setupClass}" style="font-size:11px">${setupType}</span>
        </div>
        <div class="hero-card-center">
            <div class="hero-setup-row">
                <span class="hero-score-badge">${score.toFixed(0)}</span>
                <span class="hero-confidence ${confClass}">${conf} Conviction</span>
                <span class="hero-signal-badge ${signalRaw}">${r.signal || 'HOLD'}</span>
            </div>
            <div class="hero-levels">
                <div class="hero-level-item">
                    <div class="hero-level-label">Entry</div>
                    <div class="hero-level-value entry">$${entry.toFixed(2)}</div>
                </div>
                <div class="hero-level-item">
                    <div class="hero-level-label">Stop Loss</div>
                    <div class="hero-level-value stop">$${stop.toFixed(2)}</div>
                </div>
                <div class="hero-level-item">
                    <div class="hero-level-label">Target</div>
                    <div class="hero-level-value target">$${target.toFixed(2)}</div>
                </div>
                <div class="hero-level-item">
                    <div class="hero-level-label">Expected Return</div>
                    <div class="hero-level-value ret">${retSign}${retPct.toFixed(1)}%</div>
                </div>
            </div>
        </div>
        <div class="hero-card-right">
            <div class="hero-rr">R:R = ${r.rr_ratio ? r.rr_ratio.toFixed(1) : '-'}R</div>
            ${r.win_rate ? `<div class="hero-rr">Win ${(r.win_rate*100).toFixed(0)}%</div>` : ''}
        </div>
    `;
    el.onclick = () => showDetail(r.ticker);
    el.title = `Click to view ${r.ticker} detail`;
}

/* ─── Trade Simulator ──────────────────────────────────────────────────── */
function showSimulator() {
    destroyCharts();
    if (equityChart) { equityChart.remove(); equityChart = null; }
    document.getElementById('view-summary').classList.add('hidden');
    document.getElementById('view-detail').classList.add('hidden');
    document.getElementById('view-backtest').classList.add('hidden');
    document.getElementById('view-portfolio').classList.add('hidden');
    document.getElementById('view-heatmap').classList.add('hidden');
    document.getElementById('view-simulator').classList.remove('hidden');
    loadSimulator();
}

async function loadSimulator() {
    showLoading('Loading simulator...');
    try {
        const res = await fetch('/api/simulator');
        const data = await res.json();
        renderSimSummary(data.summary || {});
        renderSimOpenTrades(data.open_trades || []);
        renderSimClosedTrades(data.closed_trades || []);
    } catch (e) { alert('Failed to load simulator: ' + e.message); }
    hideLoading();
}

function renderSimSummary(s) {
    const container = document.getElementById('sim-summary-cards');
    if (!container) return;
    const netCap = s.net_capital != null ? s.net_capital : 300;
    const totalPnl = s.total_pnl || 0;
    const winRatePct = s.win_rate != null ? (s.win_rate * 100).toFixed(0) : '-';
    const winRateNum = s.win_rate != null ? s.win_rate * 100 : null;
    container.innerHTML = `
        <div class="sim-card">
            <div class="sim-card-label">Net Capital</div>
            <div class="sim-card-value ${netCap >= 300 ? 'positive' : 'negative'}">£${netCap.toFixed(0)}</div>
        </div>
        <div class="sim-card">
            <div class="sim-card-label">Total P&L</div>
            <div class="sim-card-value ${totalPnl >= 0 ? 'positive' : 'negative'}">${totalPnl >= 0 ? '+' : ''}£${totalPnl.toFixed(2)}</div>
        </div>
        <div class="sim-card">
            <div class="sim-card-label">Win Rate</div>
            <div class="sim-card-value ${winRateNum != null && winRateNum >= 50 ? 'positive' : 'negative'}">${winRatePct}%</div>
        </div>
        <div class="sim-card">
            <div class="sim-card-label">Total Trades</div>
            <div class="sim-card-value">${s.total_trades || 0}</div>
        </div>
        <div class="sim-card">
            <div class="sim-card-label">Wins / Losses</div>
            <div class="sim-card-value"><span class="positive">${s.wins || 0}</span> / <span class="negative">${s.losses || 0}</span></div>
        </div>
    `;
}

function renderSimOpenTrades(trades) {
    const tbody = document.getElementById('sim-open-body');
    const countEl = document.getElementById('sim-open-count');
    if (!tbody) return;
    if (countEl) countEl.textContent = trades.length;
    tbody.innerHTML = '';
    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="sim-empty">No open trades — use Auto-Fill or enter details above</td></tr>';
        return;
    }
    trades.forEach(t => {
        const livePrice = t.live_price;
        const pnl = t.live_pnl;
        const pnlClass = pnl != null ? (pnl >= 0 ? 'positive' : 'negative') : '';
        const pnlText = pnl != null ? `${pnl >= 0 ? '+' : ''}£${Math.abs(pnl).toFixed(2)}` : '-';
        const pnlPct = (livePrice != null && t.entry_price) ? ((livePrice - t.entry_price) / t.entry_price * 100) : null;
        const pnlPctText = pnlPct != null ? `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%` : '-';
        const setupType = t.setup_type || 'Manual';
        const setupClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
        const openDate = t.open_time ? new Date(t.open_time * 1000).toLocaleDateString() : '-';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="ticker-cell">${t.ticker}</td>
            <td><span class="setup-badge ${setupClass}">${setupType}</span></td>
            <td>$${(t.entry_price || 0).toFixed(2)}</td>
            <td>${livePrice != null ? '$' + livePrice.toFixed(2) : '-'}</td>
            <td class="negative">$${(t.stop_loss || 0).toFixed(2)}</td>
            <td class="positive">$${(t.target || 0).toFixed(2)}</td>
            <td>${t.shares || 0}</td>
            <td class="${pnlClass}">${pnlText}</td>
            <td class="${pnlClass}">${pnlPctText}</td>
            <td>${openDate}</td>
            <td>
                <button class="sim-close-btn" onclick="promptCloseSimTrade('${t.id}', '${t.ticker}', ${livePrice || t.entry_price})">Close</button>
                <button class="sim-delete-btn" onclick="deleteSimTrade('${t.id}')" title="Delete">×</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function renderSimClosedTrades(trades) {
    const tbody = document.getElementById('sim-closed-body');
    const countEl = document.getElementById('sim-closed-count');
    if (!tbody) return;
    if (countEl) countEl.textContent = trades.length;
    tbody.innerHTML = '';
    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="sim-empty">No closed trades yet</td></tr>';
        return;
    }
    trades.forEach(t => {
        const pnl = t.pnl || 0;
        const pnlPct = t.pnl_pct || 0;
        const pnlClass = pnl >= 0 ? 'positive' : 'negative';
        const setupType = t.setup_type || '-';
        const setupClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
        const openDate = t.open_time ? new Date(t.open_time * 1000).toLocaleDateString() : '-';
        const closeDate = t.close_time ? new Date(t.close_time * 1000).toLocaleDateString() : '-';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="ticker-cell">${t.ticker}</td>
            <td><span class="setup-badge ${setupClass}">${setupType}</span></td>
            <td>$${(t.entry_price || 0).toFixed(2)}</td>
            <td>$${(t.exit_price || 0).toFixed(2)}</td>
            <td>${t.shares || 0}</td>
            <td class="${pnlClass}">${pnl >= 0 ? '+' : ''}£${Math.abs(pnl).toFixed(2)}</td>
            <td class="${pnlClass}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</td>
            <td>${openDate}</td>
            <td>${closeDate}</td>
            <td><span class="signal-cell ${pnl >= 0 ? 'buy' : 'sell'}">${pnl >= 0 ? 'WIN' : 'LOSS'}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

async function openSimTrade() {
    const ticker = (document.getElementById('sim-ticker').value || '').toUpperCase().trim();
    const entry = parseFloat(document.getElementById('sim-entry').value);
    const shares = parseInt(document.getElementById('sim-shares').value);
    const stop = parseFloat(document.getElementById('sim-stop').value);
    const target = parseFloat(document.getElementById('sim-target').value);
    if (!ticker || !entry || !shares || !stop || !target) {
        showToast('Fill in all trade fields', 'alert'); return;
    }
    const setupType = document.getElementById('sim-setup')?.value || 'Manual';
    try {
        const res = await fetch('/api/simulator/open', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker, entry_price: entry, shares, stop_loss: stop, target, setup_type: setupType }),
        });
        const data = await res.json();
        if (data.error) { showToast(data.error, 'alert'); return; }
        showToast(`Opened ${ticker} trade`, 'buy');
        loadSimulator();
    } catch (e) { alert('Failed to open trade: ' + e.message); }
}

function promptCloseSimTrade(id, ticker, currentPrice) {
    const exitInput = prompt(`Close ${ticker} trade at what price?\n(Last known: $${currentPrice != null ? Number(currentPrice).toFixed(2) : 'N/A'})`);
    if (exitInput === null) return;
    const exitPrice = parseFloat(exitInput);
    if (isNaN(exitPrice) || exitPrice <= 0) { alert('Invalid price'); return; }
    closeSimTrade(id, exitPrice);
}

async function closeSimTrade(id, exitPrice) {
    try {
        const res = await fetch('/api/simulator/close', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trade_id: id, exit_price: exitPrice }),
        });
        const data = await res.json();
        if (data.error) { showToast(data.error, 'alert'); return; }
        const pnl = data.trade?.pnl || 0;
        showToast(`Trade closed: ${pnl >= 0 ? '+' : ''}£${pnl.toFixed(2)}`, pnl >= 0 ? 'buy' : 'sell');
        loadSimulator();
    } catch (e) { alert('Failed to close trade: ' + e.message); }
}

async function deleteSimTrade(id) {
    if (!confirm('Delete this trade entry?')) return;
    try {
        await fetch(`/api/simulator/${id}`, { method: 'DELETE' });
        showToast('Trade deleted', 'alert');
        loadSimulator();
    } catch (e) { alert('Failed to delete: ' + e.message); }
}

function autoFillSimForm() {
    if (!scanResults || scanResults.length === 0) { showToast('Run a scan first', 'alert'); return; }
    const candidates = [...scanResults]
        .filter(r => r.setup_type && r.setup_type !== 'Neutral')
        .sort((a, b) => (b.swing_score || b.score || 0) - (a.swing_score || a.score || 0));
    const top = candidates[0] || scanResults[0];
    if (!top) return;
    document.getElementById('sim-ticker').value = top.ticker;
    document.getElementById('sim-entry').value = (top.entry || top.price).toFixed(2);
    document.getElementById('sim-stop').value = top.stop_loss.toFixed(2);
    document.getElementById('sim-target').value = top.target.toFixed(2);
    if (top.shares) document.getElementById('sim-shares').value = top.shares;
    const setupSel = document.getElementById('sim-setup');
    if (setupSel && top.setup_type) setupSel.value = top.setup_type;
    updateSimRiskHint();
    showToast(`Auto-filled ${top.ticker}`, 'alert');
}

function updateSimRiskHint() {
    const entry = parseFloat(document.getElementById('sim-entry')?.value);
    const stop = parseFloat(document.getElementById('sim-stop')?.value);
    const hintEl = document.getElementById('sim-risk-hint');
    if (!hintEl) return;
    if (entry > 0 && stop > 0 && entry > stop) {
        const riskPerShare = entry - stop;
        const accountSize = currentConfig.account_size || 300;
        const riskPct = currentConfig.risk_percent || 3;
        const riskAmount = accountSize * riskPct / 100;
        const calcShares = Math.max(1, Math.floor(riskAmount / riskPerShare));
        hintEl.textContent = `Risk: £${riskAmount.toFixed(0)} → ${calcShares} shares @ £${riskPerShare.toFixed(2)}/share`;
        document.getElementById('sim-shares').value = calcShares;
    } else {
        hintEl.textContent = '';
    }
}

/* ─────────────────────────────────────────────────────────────────────────────
   AI WEEKLY INTELLIGENCE
   ───────────────────────────────────────────────────────────────────────────── */

const ALL_VIEWS = [
    'view-summary','view-detail','view-backtest','view-portfolio',
    'view-heatmap','view-simulator','view-ai-weekly',
];

function _hideAllViews() {
    ALL_VIEWS.forEach(id => document.getElementById(id).classList.add('hidden'));
}

function showAiWeekly() {
    destroyCharts();
    if (equityChart) { equityChart.remove(); equityChart = null; }
    _hideAllViews();
    document.getElementById('view-ai-weekly').classList.remove('hidden');
    loadAiWeekly(false);
    loadMarketScanner(false);
}

/* ── Weekly Top-3 + Professor Mode ──────────────────────────────────────── */
async function loadAiWeekly(forceRefresh = false) {
    const loading  = document.getElementById('ai-weekly-loading');
    const profPanel = document.getElementById('professor-panel');
    const lastScan  = document.getElementById('ai-weekly-last-scan');

    loading.classList.remove('hidden');
    document.getElementById('ai-weekly-loading-text').textContent = 'Running 5-step AI pipeline...';
    profPanel.classList.add('hidden');

    try {
        const url = forceRefresh ? '/api/ai-weekly?refresh=1' : '/api/ai-weekly';
        const res  = await fetch(url);
        const data = await res.json();

        if (data.error) throw new Error(data.error);

        renderAiWeeklyTop3(data.top3 || []);
        renderProfessorMode(data.professor || {});

        if (data.last_scan) {
            lastScan.textContent = `Last scan: ${data.last_scan}${data.cached ? ' (cached)' : ''}`;
        }
    } catch (e) {
        document.getElementById('ai-weekly-body').innerHTML =
            `<tr><td colspan="13" style="text-align:center;color:var(--red);padding:24px">
                Failed to load AI analysis: ${e.message}
            </td></tr>`;
    } finally {
        loading.classList.add('hidden');
        profPanel.classList.remove('hidden');
    }
}

function renderAiWeeklyTop3(rows) {
    const tbody = document.getElementById('ai-weekly-body');
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text3);padding:24px">No data available</td></tr>';
        return;
    }
    const rankEmoji = ['🥇','🥈','🥉'];
    tbody.innerHTML = rows.map((r, i) => {
        const score      = (r.swing_score || 0).toFixed(1);
        const scoreClass = r.swing_score >= 70 ? 'score-high' : r.swing_score >= 50 ? 'score-mid' : '';
        const setupClass = 'setup-' + (r.setup_type || 'Neutral').toLowerCase().replace(/\s+/g,'-');
        const confClass  = 'conf-' + (r.confidence || 'low').toLowerCase();
        const tgt        = r.target_pct != null ? (r.target_pct >= 0 ? '+' : '') + r.target_pct + '%' : '-';

        const pipeScore = (val) => {
            const v = Math.round(val || 0);
            const cls = v >= 65 ? 'high' : v >= 45 ? 'mid' : 'low';
            return `<span class="ai-pipe-score ${cls}">${v}</span>`;
        };

        return `<tr>
            <td class="ai-rank-cell ai-rank-${i+1}">${rankEmoji[i] || i+1}</td>
            <td class="ai-ticker-cell" onclick="showDetail('${r.ticker}')" title="View details">${r.ticker}</td>
            <td><span class="setup-badge ${setupClass}">${r.setup_type || 'Neutral'}</span></td>
            <td><span class="score-pill ${scoreClass}">${score}</span></td>
            <td style="font-variant-numeric:tabular-nums">$${(r.entry||0).toFixed(2)}</td>
            <td style="color:var(--red);font-variant-numeric:tabular-nums">$${(r.stop_loss||0).toFixed(2)}</td>
            <td style="color:var(--green);font-variant-numeric:tabular-nums">$${(r.target||0).toFixed(2)}</td>
            <td class="${(r.target_pct||0)>=0?'positive':'negative'}" style="font-weight:700">${tgt}</td>
            <td><span class="confidence-badge ${confClass}">${r.confidence||'Low'}</span></td>
            <td>${pipeScore(r.technical_score)}</td>
            <td>${pipeScore(r.news_sentiment)}</td>
            <td>${pipeScore(r.social_sentiment)}</td>
            <td>${pipeScore(r.market_risk_score)}</td>
        </tr>`;
    }).join('');
}

/* ── Professor Mode ───────────────────────────────────────────────────────── */
function renderProfessorMode(p) {
    if (!p || !p.market_condition) return;

    // Condition badge
    const badge = document.getElementById('professor-condition-badge');
    const cond  = (p.market_condition || '').toLowerCase();
    badge.textContent = p.market_condition;
    badge.className   = 'professor-condition-badge ' +
        (cond.includes('bull') ? 'cond-bull' :
         cond.includes('crisis') || cond.includes('high volt') ? 'cond-crisis' :
         cond.includes('bear') || cond.includes('cautious') ? 'cond-bear' : 'cond-neutral');

    document.getElementById('professor-timestamp').textContent  = p.timestamp || '';
    document.getElementById('professor-advice').textContent     = p.advice || '';
    document.getElementById('prof-market-condition').textContent = p.market_condition || '-';
    document.getElementById('prof-vix').textContent             = p.vix ? `${p.vix} (${p.vix < 20 ? 'Low' : p.vix < 28 ? 'Medium' : 'High'})` : '-';

    const riskEl = document.getElementById('prof-risk-level');
    riskEl.textContent = p.risk_level || '-';
    riskEl.style.color = (p.risk_level||'').toLowerCase().startsWith('low') ? 'var(--green)'
                       : (p.risk_level||'').toLowerCase().startsWith('high') || (p.risk_level||'').toLowerCase().startsWith('very') ? 'var(--red)' : 'var(--yellow)';

    document.getElementById('prof-best-sector').textContent = p.best_sector || '-';
    document.getElementById('prof-best-sector').style.color = 'var(--green)';
    document.getElementById('prof-strategy').textContent    = p.recommended_strategy || '';

    // Sector bars
    const barsEl = document.getElementById('sector-strength-bars');
    const sectors = p.sector_strength || {};
    const maxAbs  = Math.max(...Object.values(sectors).map(Math.abs), 0.01);
    barsEl.innerHTML = Object.entries(sectors).map(([name, pct]) => {
        const isPos = pct >= 0;
        const width = Math.min(Math.abs(pct) / maxAbs * 50, 50);
        return `<div class="sector-bar-row">
            <span class="sector-bar-label">${name}</span>
            <div class="sector-bar-track">
                <div class="sector-bar-fill ${isPos ? 'positive' : 'negative'}"
                     style="width:${width}%"></div>
            </div>
            <span class="sector-bar-value ${isPos ? 'positive' : 'negative'}">${isPos?'+':''}${pct.toFixed(1)}%</span>
        </div>`;
    }).join('');
}

/* ── Market Scanner Top-10 ────────────────────────────────────────────────── */
async function loadMarketScanner(forceRefresh = false) {
    clearTimeout(_scannerPollTimer);
    const statusBar  = document.getElementById('scanner-status-bar');
    const lastScanEl = document.getElementById('scanner-last-scan');

    try {
        const url = forceRefresh ? '/api/market-scanner?refresh=1' : '/api/market-scanner';
        const res  = await fetch(url);
        const data = await res.json();

        if (data.status === 'running' || data.status === 'started') {
            statusBar.className   = 'scanner-status-bar status-running';
            statusBar.innerHTML   = '<div class="scanner-status-dot"></div>Scanning 200+ stocks in the background... auto-refreshing in 15s';
            statusBar.classList.remove('hidden');
            // Poll every 15 seconds
            _scannerPollTimer = setTimeout(() => loadMarketScanner(false), 15000);
            return;
        }

        if (data.status === 'ready' && data.top10 && data.top10.length > 0) {
            statusBar.className  = 'scanner-status-bar status-ready';
            statusBar.innerHTML  = `<div class="scanner-status-dot"></div>Scan complete — ${data.total_scanned} stocks analysed`;
            statusBar.classList.remove('hidden');
            renderMarketScanner(data.top10);
            if (data.last_scan) {
                lastScanEl.textContent = `Last scan: ${data.last_scan}${data.cached ? ' (24h cache)' : ''}`;
            }
        } else if (data.error) {
            statusBar.className  = 'scanner-status-bar status-error';
            statusBar.innerHTML  = `<div class="scanner-status-dot"></div>Scanner error: ${data.error}`;
            statusBar.classList.remove('hidden');
        }
    } catch (e) {
        statusBar.className = 'scanner-status-bar status-error';
        statusBar.innerHTML = `<div class="scanner-status-dot"></div>Failed to reach scanner`;
        statusBar.classList.remove('hidden');
    }
}

function renderMarketScanner(rows) {
    const tbody = document.getElementById('scanner-body');
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:24px">No data yet — scanner running...</td></tr>';
        return;
    }
    tbody.innerHTML = rows.slice(0, 10).map((r, i) => {
        const score      = (r.swing_score || 0).toFixed(1);
        const scoreClass = r.swing_score >= 70 ? 'score-high' : r.swing_score >= 50 ? 'score-mid' : '';
        const setupClass = 'setup-' + (r.setup_type || 'Neutral').toLowerCase().replace(/\s+/g,'-');
        const tgt        = r.target_pct != null ? (r.target_pct >= 0 ? '+' : '') + r.target_pct + '%' : '-';
        const confClass  = 'conf-' + (r.confidence || 'low').toLowerCase();

        return `<tr style="--i:${i}">
            <td style="color:var(--text3);font-weight:700;text-align:center">#${i+1}</td>
            <td class="ai-ticker-cell" onclick="showDetail('${r.ticker}')" title="View details">${r.ticker}</td>
            <td><span class="setup-badge ${setupClass}">${r.setup_type || 'Neutral'}</span></td>
            <td><span class="score-pill ${scoreClass}">${score}</span></td>
            <td style="font-variant-numeric:tabular-nums">$${(r.entry||0).toFixed(2)}</td>
            <td style="color:var(--green);font-variant-numeric:tabular-nums">$${(r.target||0).toFixed(2)}</td>
            <td class="${(r.target_pct||0)>=0?'positive':'negative'}" style="font-weight:700">${tgt}</td>
            <td><span class="confidence-badge ${confClass}">${r.confidence||'Low'}</span></td>
        </tr>`;
    }).join('');
}

/* ═══════════════════════════════════ §3 TOP-10 DASHBOARD SECTION ═══ */
let _top10DashboardTimer = null;

async function fetchScannerTop10Dashboard() {
    clearTimeout(_top10DashboardTimer);
    const section   = document.getElementById('top10-section');
    const statusEl  = document.getElementById('top10-status');
    if (!section) return;

    try {
        const res  = await fetch('/api/market-scanner');
        const data = await res.json();

        if (data.status === 'running' || data.status === 'started') {
            section.classList.remove('hidden');
            if (statusEl) {
                statusEl.innerHTML = '<div class="scanner-status-dot" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--yellow);animation:pulse 1.2s infinite;margin-right:4px"></div>Scanning...';
            }
            _top10DashboardTimer = setTimeout(fetchScannerTop10Dashboard, 15000);
            return;
        }

        if (data.status === 'ready' && data.top10 && data.top10.length > 0) {
            // Filter to score >= 70
            const qualified = data.top10.filter(r => (r.swing_score || 0) >= 70);
            if (qualified.length === 0) {
                section.classList.add('hidden');
                return;
            }
            section.classList.remove('hidden');
            if (statusEl) {
                statusEl.innerHTML = `<div class="scanner-status-dot" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);margin-right:4px"></div>${data.total_scanned || '?'} stocks scanned`;
            }
            renderTop10Section(qualified.slice(0, 10));
        }
    } catch (e) { /* silent — section stays hidden */ }
}

function renderTop10Section(rows) {
    const list = document.getElementById('top10-list');
    if (!list || !rows || rows.length === 0) return;
    const rankLabel = (i) => {
        if (i === 0) return '<span class="top10-rank r1">🥇</span>';
        if (i === 1) return '<span class="top10-rank r2">🥈</span>';
        if (i === 2) return '<span class="top10-rank r3">🥉</span>';
        return `<span class="top10-rank">#${i+1}</span>`;
    };
    list.innerHTML = rows.map((r, i) => {
        const score      = (r.swing_score || 0).toFixed(1);
        const scoreClass = r.swing_score >= 80 ? 'score-high' : 'score-mid';
        const setupType  = r.setup_type || 'Neutral';
        const setupClass = 'setup-' + setupType.toLowerCase().replace(/\s+/g, '-');
        const tgt        = r.target_pct != null ? (r.target_pct >= 0 ? '+' : '') + r.target_pct + '%' : null;
        const retClass   = (r.target_pct || 0) >= 0 ? '' : 'negative';
        const confClass  = 'conf-' + (r.confidence || 'low').toLowerCase();
        return `
        <div class="top10-item" onclick="showDetail('${r.ticker}')" title="View ${r.ticker}">
            ${rankLabel(i)}
            <div class="top10-body">
                <div class="top10-ticker-row">
                    <span class="top10-ticker">${r.ticker}</span>
                    <span class="score-pill ${scoreClass}" style="font-size:10px;padding:2px 7px">${score}</span>
                </div>
                <div class="top10-meta">
                    <span class="setup-badge ${setupClass}" style="font-size:10px;padding:1px 6px">${setupType}</span>
                    <span class="confidence-badge ${confClass}" style="font-size:9px;padding:1px 5px">${r.confidence||'Low'}</span>
                    ${r.entry ? `<span>$${r.entry.toFixed(2)}</span>` : ''}
                </div>
            </div>
            <div class="top10-right">
                ${tgt ? `<span class="top10-ret ${retClass}">${tgt}</span>` : ''}
                ${r.target ? `<span style="font-size:10px;color:var(--text3)">→ $${r.target.toFixed(2)}</span>` : ''}
            </div>
        </div>`;
    }).join('');
}

/* ═══════════════════════════════════════ §5 WATCHLIST PANEL ═══ */
function renderWatchlistPanel() {
    const panel  = document.getElementById('watchlist-panel');
    const chips  = document.getElementById('watchlist-chips');
    if (!panel || !chips) return;

    const tickers = (currentConfig && currentConfig.tickers) ? currentConfig.tickers : [];
    if (tickers.length === 0) { panel.classList.add('hidden'); return; }

    // Build lookup from scan results
    const resultMap = {};
    (scanResults || []).forEach(r => { resultMap[r.ticker] = r; });

    chips.innerHTML = tickers.map(t => {
        const r      = resultMap[t];
        const signal = r ? r.signal : '';
        const score  = r ? (r.swing_score != null ? r.swing_score : (r.score || 0)) : 0;
        const cls    = !signal ? '' :
                       signal === 'STRONG BUY'  ? 'chip-strong-buy' :
                       signal === 'BUY'         ? 'chip-buy' :
                       signal === 'HOLD'        ? 'chip-hold' :
                       signal === 'SELL'        ? 'chip-sell' :
                       signal === 'STRONG SELL' ? 'chip-strong-sell' : '';
        const scoreTxt = score > 0 ? `<span class="chip-score">${score.toFixed(0)}</span>` : '';
        return `<span class="watchlist-chip ${cls}" onclick="showDetail('${t}')" title="${signal || 'No signal yet'}">${t}${scoreTxt}</span>`;
    }).join('');

    panel.classList.remove('hidden');
}

/* ═══════════════════════════════════ §6 SIM QUICK CARD ═══ */
async function loadSimQuickCard() {
    const card = document.getElementById('sim-quick-card');
    if (!card) return;
    try {
        const res  = await fetch('/api/simulator');
        const data = await res.json();
        const s    = data.summary || {};
        const open = (data.open_trades || []).length;

        // Unrealised P&L from open trades
        const unrealised = (data.open_trades || []).reduce((acc, t) => acc + (t.live_pnl || 0), 0);
        const closed     = (data.closed_trades || []).length;
        const totalPnl   = s.total_pnl || 0;
        const winRate    = s.win_rate != null ? (s.win_rate * 100).toFixed(0) + '%' : '—';

        const fmt = (v) => (v >= 0 ? '+' : '') + '£' + Math.abs(v).toFixed(2);
        const cls = (v) => v >= 0 ? 'positive' : 'negative';

        document.getElementById('sq-open').textContent      = open;
        document.getElementById('sq-unrealised').textContent = unrealised !== 0 ? fmt(unrealised) : '£0.00';
        document.getElementById('sq-unrealised').className   = 'sq-value ' + (unrealised !== 0 ? cls(unrealised) : '');
        document.getElementById('sq-closed').textContent    = closed;
        document.getElementById('sq-total').textContent     = totalPnl !== 0 ? fmt(totalPnl) : '£0.00';
        document.getElementById('sq-total').className       = 'sq-value ' + (totalPnl !== 0 ? cls(totalPnl) : '');
        document.getElementById('sq-winrate').textContent   = winRate;

        card.classList.remove('hidden');
    } catch (e) {
        card.classList.add('hidden');
    }
}
