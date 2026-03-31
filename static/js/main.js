/**
 * Raven 股票趋势追踪 - 前端交互
 */

// 全局状态
let allStocks = [];
let currentFilter = 'all';
let autoRefreshTimer = null;
let lastFetchTime = null;

// ==========================================
// 初始化
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    checkTokenStatus();
    refreshAll();
    setupAutoRefresh();
});

// ==========================================
// Token 状态检查
// ==========================================
async function checkTokenStatus() {
    try {
        const resp = await fetch('/api/check_token');
        const data = await resp.json();
        if (data.errorcode === -1301) {
            showTokenAlert(data.errmsg || 'iFinD Token已过期，请输入新Token');
        }
    } catch (e) {
        console.warn('Token状态检查失败:', e);
    }
}

function showTokenAlert(msg) {
    const alert = document.getElementById('tokenAlert');
    const msgEl = document.getElementById('tokenAlertMsg');
    const form = document.getElementById('tokenAlertForm');
    const progress = document.getElementById('tokenAlertProgress');

    if (msgEl) msgEl.textContent = msg;
    if (form) form.style.display = 'flex';
    if (progress) progress.style.display = 'none';
    if (alert) {
        alert.style.display = 'block';
        // 禁止自动刷新，避免在填写token时干扰
        const autoRefreshCheckbox = document.getElementById('autoRefresh');
        if (autoRefreshCheckbox) autoRefreshCheckbox.checked = false;
        stopAutoRefresh();
    }
}

function hideTokenAlert() {
    const alert = document.getElementById('tokenAlert');
    if (alert) alert.style.display = 'none';
    // 恢复自动刷新
    const autoRefreshCheckbox = document.getElementById('autoRefresh');
    if (autoRefreshCheckbox && autoRefreshCheckbox.checked) {
        const intervalSelect = document.getElementById('refreshInterval');
        startAutoRefresh(parseInt(intervalSelect.value) * 1000);
    }
}

async function submitNewToken() {
    const input = document.getElementById('newTokenInput');
    const form = document.getElementById('tokenAlertForm');
    const progress = document.getElementById('tokenAlertProgress');
    const msgEl = document.getElementById('tokenAlertMsg');

    if (!input || !input.value.trim()) {
        if (msgEl) msgEl.textContent = '请输入新的Token';
        return;
    }

    const token = input.value.trim();

    // 显示加载状态
    if (form) form.style.display = 'none';
    if (progress) {
        progress.style.display = 'flex';
        progress.querySelector('span').textContent = '正在验证Token...';
    }

    try {
        const resp = await fetch('/api/update_token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token })
        });
        const data = await resp.json();

        if (data.errorcode === 0) {
            if (msgEl) msgEl.textContent = `✅ Token保存成功，有效期至 ${data.expire_time || '未知'}`;
            // 2秒后隐藏提示并恢复刷新
            setTimeout(() => {
                hideTokenAlert();
                // 恢复自动刷新并刷新数据
                const autoRefreshCheckbox = document.getElementById('autoRefresh');
                if (autoRefreshCheckbox && autoRefreshCheckbox.checked) {
                    const intervalSelect = document.getElementById('refreshInterval');
                    startAutoRefresh(parseInt(intervalSelect.value) * 1000);
                }
                refreshAll();
            }, 2000);
        } else {
            // 验证失败，恢复表单
            if (msgEl) msgEl.textContent = data.errmsg || 'Token验证失败';
            if (form) form.style.display = 'flex';
            if (progress) progress.style.display = 'none';
        }
    } catch (e) {
        if (msgEl) msgEl.textContent = '验证请求失败: ' + e.message;
        if (form) form.style.display = 'flex';
        if (progress) progress.style.display = 'none';
    }
}

// ==========================================
// 刷新所有数据
// ==========================================
async function refreshAll() {
    showLoading();
    try {
        const resp = await fetch('/api/trends');
        if (!resp.ok) throw new Error('获取数据失败');
        allStocks = await resp.json();
        lastFetchTime = new Date();
        renderStocks();
        updateLastTime();
        updateDataSource();

        // 每次刷新时顺便检查token状态
        checkTokenStatusQuiet();
    } catch (e) {
        console.error(e);
        showEmpty('加载失败，请检查服务器是否启动');
    }
}

// 静默检查token，不干扰用户操作
async function checkTokenStatusQuiet() {
    try {
        const resp = await fetch('/api/check_token');
        const data = await resp.json();
        const alert = document.getElementById('tokenAlert');
        if (data.errorcode === -1301 && alert && alert.style.display === 'none') {
            showTokenAlert(data.errmsg || 'iFinD Token已过期，请输入新Token');
        }
    } catch (e) {
        // 静默失败
    }
}

// ==========================================
// 查询单只股票
// ==========================================
async function queryStock() {
    const name = document.getElementById('stockInput').value.trim();
    if (!name) {
        showToast('请输入股票名称', 'error');
        return;
    }

    try {
        const resp = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        const data = await resp.json();

        if (resp.status === 300) {
            // 多个匹配
            showToast(data.error, 'error');
            // 高亮匹配项
            const matches = data.matches || [];
            if (matches.length > 0) {
                filterStocksByNames(matches.map(m => m.name));
            }
            return;
        }

        if (resp.status === 404) {
            showToast(data.error, 'error');
            return;
        }

        if (data.error === 'no_data') {
            showToast(`❌ ${data.name}: 暂无趋势数据`, 'error');
            return;
        }

        // 显示查询结果
        showResult(data);

    } catch (e) {
        showToast('查询失败: ' + e.message, 'error');
    }
}

// ==========================================
// 显示查询结果
// ==========================================
function showResult(data) {
    const section = document.getElementById('resultSection');
    const detail = document.getElementById('stockDetail');
    section.style.display = 'block';

    const isUp = data.trend_code.startsWith('up');
    const priceClass = isUp ? 'up' : 'down';

    // 根据趋势类型确定显示哪些关键点（根据趋势体系详解文档）
    const trendCode = data.trend_code;
    let keypoints = '';

    if (trendCode === 'up') {
        // 上升趋势：关键高点
        keypoints = `${renderKeypoint('key_high', data.key_high)}`;
    } else if (trendCode === 'up_natural') {
        // 自然回撤：自然回撤低点
        keypoints = `${renderKeypoint('n_low', data.n_low)}`;
    } else if (trendCode === 'up_rally') {
        // 回升：自然回撤低点、关键高点、回升高点
        keypoints = `
            ${renderKeypoint('n_low', data.n_low)}
            ${renderKeypoint('key_high', data.key_high)}
            ${renderKeypoint('rally_high', data.rally_high)}
        `;
    } else if (trendCode === 'up_secondary') {
        // 次级回撤：自然回撤低点、回升高点、次级回撤低点
        keypoints = `
            ${renderKeypoint('n_low', data.n_low)}
            ${renderKeypoint('rally_high', data.rally_high)}
            ${renderKeypoint('secondary_low', data.secondary_low)}
        `;
    } else if (trendCode === 'up_break') {
        // 上升破碎：自然回撤低点、破碎低点
        keypoints = `
            ${renderKeypoint('n_low', data.n_low)}
            ${renderKeypoint('break_low', data.break_low)}
        `;
    } else if (trendCode === 'down') {
        // 下跌趋势：关键低点
        keypoints = `${renderKeypoint('key_low', data.key_low)}`;
    } else if (trendCode === 'down_natural') {
        // 自然回升：自然回升高点
        keypoints = `${renderKeypoint('n_high', data.n_high)}`;
    } else if (trendCode === 'down_rally') {
        // 回撤：自然回升高点、关键低点、回撤低点
        keypoints = `
            ${renderKeypoint('n_high', data.n_high)}
            ${renderKeypoint('key_low', data.key_low)}
            ${renderKeypoint('rally_low', data.rally_low)}
        `;
    } else if (trendCode === 'down_secondary') {
        // 次级回升：自然回升高点、回撤低点、次级回升高点
        keypoints = `
            ${renderKeypoint('n_high', data.n_high)}
            ${renderKeypoint('rally_low', data.rally_low)}
            ${renderKeypoint('secondary_high', data.secondary_high)}
        `;
    } else if (trendCode === 'down_break') {
        // 下跌破碎：自然回升高点、破碎高点
        keypoints = `
            ${renderKeypoint('n_high', data.n_high)}
            ${renderKeypoint('break_high', data.break_high)}
        `;
    }

    detail.innerHTML = `
        <div class="detail-header">
            <div>
                <div class="detail-name">${data.name}</div>
                <div class="detail-code">${data.code || ''} ${data.market === 'SZ' ? '深圳' : data.market === 'SH' ? '上海' : ''}</div>
            </div>
            <div class="detail-signal" style="background:${data.signal_color}">
                ${data.signal_text}
            </div>
        </div>
        <div class="detail-main">
            <div>
                <div class="detail-price">¥${data.price > 0 ? data.price.toFixed(2) : '--'}</div>
                <div class="detail-trend">${data.trend_name || '未知趋势'}</div>
            </div>
        </div>
        <div class="detail-desc">${data.description || ''}</div>
        <div class="detail-keypoints">
            ${keypoints}
        </div>
        <div style="margin-top:12px;font-size:12px;color:#999;">
            ${data.changed ? '🔔 趋势刚发生变化' : ''} 更新时间: ${data.update_time || '--'}
        </div>
    `;

    // 滚动到结果区
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderKeypoint(label, value) {
    const labels = {
        key_high: '关键高点',
        key_low: '关键低点',
        n_low: 'N值低点',
        n_high: 'N值高点',
        rally_high: '回升高点',
        rally_low: '回撤低点',
        secondary_low: '次级低点',
        secondary_high: '次级高点',
        break_low: '破碎支撑',
        break_high: '破碎阻力'
    };
    const isValid = (v) => v !== null && v !== undefined && v !== '' && !isNaN(v);
    const val = isValid(value) ? parseFloat(value).toFixed(2) : '--';
    return `
        <div class="keypoint">
            <div class="keypoint-label">${labels[label] || label}</div>
            <div class="keypoint-value">${val}</div>
        </div>
    `;
}

function closeResult() {
    document.getElementById('resultSection').style.display = 'none';
}

// ==========================================
// 渲染股票列表
// ==========================================
function renderStocks() {
    const grid = document.getElementById('stocksGrid');
    let filtered = allStocks;

    if (currentFilter === 'up') {
        // 精确匹配：只有 up（上升趋势）
        filtered = allStocks.filter(s => s.trend_code === 'up');
    } else if (currentFilter === 'down') {
        // 精确匹配：只有 down（下跌趋势）
        filtered = allStocks.filter(s => s.trend_code === 'down');
    } else if (currentFilter === 'changed') {
        filtered = allStocks.filter(s => s.changed);
    } else if (currentFilter === 'up_system') {
        // 上升体系：所有以上升开头的趋势
        filtered = allStocks.filter(s => s.trend_code.startsWith('up'));
    } else if (currentFilter === 'down_system') {
        // 下跌体系：所有以下跌开头的趋势
        filtered = allStocks.filter(s => s.trend_code.startsWith('down'));
    } else if (currentFilter !== 'all') {
        // 精确匹配某种趋势类型
        filtered = allStocks.filter(s => s.trend_code === currentFilter);
    }

    document.getElementById('stockCount').textContent = `${filtered.length} / ${allStocks.length} 只`;

    if (filtered.length === 0) {
        grid.innerHTML = `<div class="empty-state">暂无数据</div>`;
        return;
    }

    grid.innerHTML = filtered.map(stock => {
        const isUp = stock.trend_code.startsWith('up');
        const priceClass = isUp ? 'up' : 'down';
        const cardClass = stock.changed ? 'changed' : (isUp ? 'up' : 'down');
        const updated = stock.update_time ? stock.update_time.replace('2026-', '').replace('03-', '03/') : '--';
        const borderColor = stock.signal_color || (isUp ? 'var(--up-color)' : 'var(--down-color)');

        return `
            <div class="stock-card ${cardClass}" style="border-left-color: ${borderColor}" onclick="showResultFromList('${stock.symbol}')">
                ${stock.changed ? '<span class="changed-badge">变化</span>' : ''}
                <div class="stock-card-header">
                    <div>
                        <div class="stock-name">${stock.name}</div>
                        <div class="stock-code">${stock.symbol}</div>
                    </div>
                </div>
                <div class="stock-price ${priceClass}">¥${stock.price > 0 ? stock.price.toFixed(2) : '--'}</div>
                <div class="stock-trend">
                    <span class="trend-name">${stock.trend_name || '未知'}</span>
                    <span class="trend-signal" style="background:${stock.signal_color}">${stock.signal_text}</span>
                </div>
                <div class="stock-updated">${updated}</div>
            </div>
        `;
    }).join('');
}

function showResultFromList(symbol) {
    const stock = allStocks.find(s => s.symbol === symbol);
    if (stock) {
        document.getElementById('stockInput').value = stock.name;
        showResult(stock);
    }
}

// ==========================================
// 过滤
// ==========================================
function filterStocks(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });
    renderStocks();
}

function filterStocksByNames(names) {
    const filtered = allStocks.filter(s => names.includes(s.name));
    document.getElementById('stockCount').textContent = `${filtered.length} / ${allStocks.length} 只`;
    const grid = document.getElementById('stocksGrid');
    if (filtered.length === 0) {
        grid.innerHTML = `<div class="empty-state">未找到匹配的股票</div>`;
        return;
    }
    grid.innerHTML = filtered.map(stock => {
        const isUp = stock.trend_code.startsWith('up');
        const priceClass = isUp ? 'up' : 'down';
        const cardClass = stock.changed ? 'changed' : (isUp ? 'up' : 'down');
        return `
            <div class="stock-card ${cardClass}" onclick="showResultFromList('${stock.symbol}')">
                ${stock.changed ? '<span class="changed-badge">变化</span>' : ''}
                <div class="stock-card-header">
                    <div>
                        <div class="stock-name">${stock.name}</div>
                        <div class="stock-code">${stock.symbol}</div>
                    </div>
                </div>
                <div class="stock-price ${priceClass}">¥${stock.price > 0 ? stock.price.toFixed(2) : '--'}</div>
                <div class="stock-trend">
                    <span class="trend-name">${stock.trend_name || '未知'}</span>
                    <span class="trend-signal" style="background:${stock.signal_color}">${stock.signal_text}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ==========================================
// 自动刷新
// ==========================================
function setupAutoRefresh() {
    const checkbox = document.getElementById('autoRefresh');
    const intervalSelect = document.getElementById('refreshInterval');

    checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
            startAutoRefresh(parseInt(intervalSelect.value) * 1000);
        } else {
            stopAutoRefresh();
        }
    });

    intervalSelect.addEventListener('change', () => {
        if (checkbox.checked) {
            startAutoRefresh(parseInt(intervalSelect.value) * 1000);
        }
    });

    // 初始启动
    startAutoRefresh(parseInt(intervalSelect.value) * 1000);
}

function startAutoRefresh(intervalMs) {
    stopAutoRefresh();
    autoRefreshTimer = setInterval(() => {
        refreshAll();
    }, intervalMs);
}

function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}

// ==========================================
// 辅助函数
// ==========================================
function showLoading() {
    const grid = document.getElementById('stocksGrid');
    grid.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <span>加载中...</span>
        </div>
    `;
}

function showEmpty(msg) {
    const grid = document.getElementById('stocksGrid');
    grid.innerHTML = `<div class="empty-state">${msg}</div>`;
}

function showToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = `toast ${type}`;
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 3000);
}

function updateLastTime() {
    const el = document.getElementById('lastUpdate');
    if (lastFetchTime) {
        el.textContent = `最后更新: ${lastFetchTime.toLocaleTimeString('zh-CN')}`;
    }
}

function updateDataSource() {
    const hasMock = allStocks.some(s => s.mock);
    document.getElementById('dataSource').textContent = hasMock ? '数据来源: 部分模拟数据' : '数据来源: iFinD API';
}
