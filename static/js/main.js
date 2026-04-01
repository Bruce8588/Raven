/**
 * Raven 股票趋势追踪 - 前端交互
 */

// 全局状态
let allStocks = [];

// 趋势代码 → 点评文字
const TREND_DESC = {
    'up': '进行中的单向运动',
    'up_natural': '正常反弹',
    'up_rally': '可能突破',
    'up_secondary': '无意义的运动',
    'up_break': '趋势可能反转',
    'down': '进行中的单向运动',
    'down_natural': '正常反弹',
    'down_rally': '可能突破',
    'down_secondary': '无意义的运动',
    'down_break': '趋势可能反转',
};
let currentFilter = 'all';
let autoRefreshTimer = null;
let lastFetchTime = null;

// ==========================================
// 初始化
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    checkTokenStatus();
    loadTrends();        // 只加载已有数据，不刷新
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
// 刷新所有数据（刷新按钮调用：先刷新iFind数据，再获取展示）
// ==========================================
let isRefreshing = false;

async function refreshAll() {
    if (isRefreshing) return;
    isRefreshing = true;

    const btn = document.querySelector('.btn-refresh');
    if (btn) btn.textContent = '⏳';
    const lastUpdateEl = document.getElementById('lastUpdate');
    const prevText = lastUpdateEl ? lastUpdateEl.textContent : '';
    if (lastUpdateEl) lastUpdateEl.textContent = '正在刷新...';

    try {
        // 先触发后端重新分析所有股票（POST /api/refresh）
        const refreshResp = await fetch('/api/refresh', { method: 'POST' });
        if (!refreshResp.ok) throw new Error('刷新请求失败');
        const refreshData = await refreshResp.json();
        const updated = refreshData.updated || 0;
        const total = refreshData.total || 0;

        // 然后获取最新数据展示
        const resp = await fetch('/api/trends');
        if (!resp.ok) throw new Error('获取数据失败');
        allStocks = await resp.json();
        // 缓存股票数据供分组使用
        window._cachedStocks = {};
        allStocks.forEach(s => { window._cachedStocks[s.symbol] = s; });
        lastFetchTime = new Date();
        renderStocks();
        updateLastTime();
        updateDataSource();

        if (lastUpdateEl) lastUpdateEl.textContent = `已更新 ${updated}/${total} 只股票`;
        else if (total > 0) alert(`已更新 ${updated}/${total} 只股票`);

        // 每次刷新时顺便检查token状态
        checkTokenStatusQuiet();
    } catch (e) {
        console.error(e);
        showEmpty('加载失败，请检查服务器是否启动');
        if (lastUpdateEl) lastUpdateEl.textContent = prevText || '刷新失败';
    } finally {
        isRefreshing = false;
        const btn = document.querySelector('.btn-refresh');
        if (btn) btn.textContent = '🔄';
    }
}

// ==========================================
// 仅加载数据（页面加载时调用，不触发iFind刷新）
// ==========================================
async function loadTrends() {
    try {
        const resp = await fetch('/api/trends');
        if (!resp.ok) throw new Error('获取数据失败');
        allStocks = await resp.json();
        // 缓存股票数据供分组使用
        window._cachedStocks = {};
        allStocks.forEach(s => { window._cachedStocks[s.symbol] = s; });
        lastFetchTime = new Date();
        renderStocks();
        updateLastTime();
        updateDataSource();
    } catch (e) {
        console.error(e);
        showEmpty('加载失败，请检查服务器是否启动');
    }
}

// ==========================================
// 刷新单只股票（点击卡片时调用）
// ==========================================
async function refreshStock(symbol) {
    const stock = allStocks.find(s => s.symbol === symbol);
    if (!stock) return;

    // 显示加载状态
    const cards = document.querySelectorAll(`.stock-card[onclick*="refreshStock('${symbol}')"]`);
    cards.forEach(card => {
        card.style.opacity = '0.6';
        card.style.pointerEvents = 'none';
    });

    try {
        // 调用后端刷新单只股票
        const resp = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: stock.name || stock.code })
        });

        if (resp.ok) {
            // 重新加载所有数据
            await loadTrends();
            showToast(`✅ ${stock.name} 已刷新`, 'info');
            // 跳转到趋势详情页
            setTimeout(() => {
                goToDetail(symbol);
            }, 300);
        } else {
            throw new Error('刷新失败');
        }
    } catch (e) {
        console.error(e);
        showToast(`❌ ${stock.name} 刷新失败`, 'error');
    } finally {
        cards.forEach(card => {
            card.style.opacity = '';
            card.style.pointerEvents = '';
        });
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
    let keypoints = '';  // 搜索结果中不展示关键点小卡片区，留空

    detail.innerHTML = `
        <div class="detail-header" onclick="goToDetail('${data.symbol}')" style="cursor:pointer;" title="点击查看趋势详情">
            <div>
                <div class="detail-name">${data.name}</div>
                <div class="detail-code">${data.code || ''} ${data.market === 'SZ' ? '深圳' : data.market === 'SH' ? '上海' : ''}</div>
            </div>
            <div class="detail-signal" style="background:${data.signal_color}">
                ${TREND_DESC[data.trend_code] || data.signal_text}
            </div>
        </div>
        <div class="detail-main">
            <div>
                <div class="detail-price">¥${data.price > 0 ? data.price.toFixed(2) : '--'}</div>
                <div class="detail-trend">${data.trend_name || '未知趋势'}</div>
            </div>
            <div style="display:flex;gap:8px;margin-top:8px;">
                <button onclick="openGroupSelectModal('${data.symbol}', '${data.name}')"
                    style="padding:6px 14px;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:20px;font-size:13px;cursor:pointer;color:#374151;">
                    📁 加入分组
                </button>
            </div>
        </div>
        <div class="detail-desc">${data.description || ''}</div>
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

        const hasDetail = stock.has_trend_data !== false;

        return `
            <div class="stock-card ${cardClass}" style="border-left-color: ${borderColor}" onclick="refreshStock('${stock.symbol}')">
                ${stock.changed ? '<span class="changed-badge">变化</span>' : ''}
                <div class="stock-card-header">
                    <div>
                        <div class="stock-name" style="cursor:pointer;" onclick="event.stopPropagation(); goToDetail('${stock.symbol}')">${stock.name}</div>
                        <div class="stock-code">${stock.symbol}</div>
                    </div>
                    
                </div>
                <div class="stock-price ${priceClass}">¥${stock.price > 0 ? stock.price.toFixed(2) : '--'}</div>
                <div class="stock-trend">
                    <span class="trend-name">${stock.trend_name || '未知'}</span>
                    <span class="trend-signal" style="background:${stock.signal_color}">${TREND_DESC[stock.trend_code] || stock.signal_text}</span>
                </div>
                <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center;">
                    <button onclick="event.stopPropagation(); openGroupSelectModal('${stock.symbol}', '${stock.name}')"
                        style="padding:4px 10px;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;font-size:11px;cursor:pointer;color:#6b7280;">
                        📁 加入分组
                    </button>
                </div>
                <div class="stock-updated">${updated}</div>
            </div>
        `;
    }).join('');
}

function showResultFromList(symbol) {
    // 点击列表中的股票也刷新最新数据
    refreshStock(symbol);
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
        const hasDetail = stock.has_trend_data !== false;
        return `
            <div class="stock-card ${cardClass}" onclick="refreshStock('${stock.symbol}')">
                ${stock.changed ? '<span class="changed-badge">变化</span>' : ''}
                <div class="stock-card-header">
                    <div>
                        <div class="stock-name" style="cursor:pointer;" onclick="event.stopPropagation(); goToDetail('${stock.symbol}')">${stock.name}</div>
                        <div class="stock-code">${stock.symbol}</div>
                    </div>
                    
                </div>
                <div class="stock-price ${priceClass}">¥${stock.price > 0 ? stock.price.toFixed(2) : '--'}</div>
                <div class="stock-trend">
                    <span class="trend-name">${stock.trend_name || '未知'}</span>
                    <span class="trend-signal" style="background:${stock.signal_color}">${TREND_DESC[stock.trend_code] || stock.signal_text}</span>
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
        loadTrends();  // 只加载数据，不触发iFind刷新
    }, intervalMs);
}

function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}

// ==========================================
// 标签切换：自选股 / 历史搜索 / 分组
// ==========================================
let currentTab = 'watchlist';

function switchTab(tab) {
    currentTab = tab;
    document.getElementById('tabWatchlist').classList.toggle('active', tab === 'watchlist');
    document.getElementById('tabHistory').classList.toggle('active', tab === 'history');
    document.getElementById('tabGroups').classList.toggle('active', tab === 'groups');
    document.getElementById('stocksGrid').style.display = tab === 'watchlist' ? '' : 'none';
    document.getElementById('historyGrid').style.display = tab === 'history' ? '' : 'none';
    document.getElementById('groupsSection').style.display = tab === 'groups' ? '' : 'none';

    if (tab === 'history') {
        loadHistory();
    } else if (tab === 'groups') {
        loadGroups();
    }
}

async function loadHistory() {
    const grid = document.getElementById('historyGrid');
    grid.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <span>加载历史搜索...</span>
        </div>
    `;

    try {
        const resp = await fetch('/api/history');
        const data = await resp.json();

        if (!data.history || data.history.length === 0) {
            grid.innerHTML = `<div class="empty-state">暂无历史搜索记录<br><span style="font-size:12px;color:#9ca3af;">搜索过的股票将显示在这里</span></div>`;
            return;
        }

        renderHistory(data.history);
    } catch (e) {
        grid.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
    }
}

function renderHistory(history) {
    const grid = document.getElementById('historyGrid');

    grid.innerHTML = history.map(stock => {
        const isUp = stock.trend_code.startsWith('up');
        const priceClass = isUp ? 'up' : 'down';
        const borderColor = stock.signal_color || '#9ca3af';
        const hasDetail = stock.has_detail;

        return `
            <div class="stock-card ${isUp ? 'up' : 'down'}" style="border-left-color:${borderColor}" onclick="refreshStock('${stock.symbol}')">
                <div class="stock-card-header">
                    <div>
                        <div class="stock-name">${stock.name}</div>
                        <div class="stock-code">${stock.code || stock.symbol}</div>
                    </div>

                </div>
                <div class="stock-price ${priceClass}">¥${stock.price > 0 ? stock.price.toFixed(2) : '--'}</div>
                <div class="stock-trend">
                    <span class="trend-name">${stock.trend_name || '暂无数据'}</span>
                    <span class="trend-signal" style="background:${stock.signal_color}">${TREND_DESC[stock.trend_code] || stock.signal_text}</span>
                </div>
                <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center;">
                    <button onclick="event.stopPropagation(); openGroupSelectModal('${stock.symbol}', '${stock.name}')"
                        style="padding:4px 10px;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;font-size:11px;cursor:pointer;color:#6b7280;">
                        📁 加入分组
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function goToDetail(symbol) {
    window.location.href = `/trend_detail/${symbol}`;
}

// ==========================================
// 分组管理
// ==========================================
async function loadGroups() {
    const container = document.getElementById('groupsList');
    container.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <span>加载分组...</span>
        </div>
    `;
    try {
        const resp = await fetch('/api/groups');
        const data = await resp.json();
        renderGroups(data.groups || []);
    } catch (e) {
        container.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
    }
}

async function createGroup() {
    const input = document.getElementById('newGroupName');
    const name = input.value.trim();
    if (!name) {
        showToast('请输入分组名称', 'error');
        return;
    }
    try {
        const resp = await fetch('/api/groups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await resp.json();
        if (data.errorcode === 0) {
            input.value = '';
            showToast('分组已创建', 'info');
            loadGroups();
        } else {
            showToast(data.errmsg || '创建失败', 'error');
        }
    } catch (e) {
        showToast('创建失败: ' + e.message, 'error');
    }
}

async function deleteGroup(groupId) {
    if (!confirm('确定要删除该分组吗？')) return;
    try {
        const resp = await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
        const data = await resp.json();
        if (data.errorcode === 0) {
            showToast('分组已删除', 'info');
            loadGroups();
        } else {
            showToast(data.errmsg || '删除失败', 'error');
        }
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

function renderGroups(groups) {
    const container = document.getElementById('groupsList');
    if (groups.length === 0) {
        container.innerHTML = `<div class="empty-state">暂无分组<br><span style="font-size:12px;color:#9ca3af;">点击上方"新建分组"创建</span></div>`;
        return;
    }
    container.innerHTML = groups.map(group => `
        <div style="background:white;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
            <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" onclick="toggleGroupExpand('${group.id}', this)">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span id="groupArrow_${group.id}" style="font-size:14px;transition:transform 0.2s;">▶</span>
                    <span style="font-weight:600;font-size:15px;">📁 ${group.name}</span>
                    <span style="font-size:12px;color:#9ca3af;">${group.stocks ? group.stocks.length : 0} 只</span>
                </div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <button onclick="event.stopPropagation(); deleteGroup('${group.id}')" style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:13px;" title="删除分组">🗑️</button>
                </div>
            </div>
            <div id="groupStocks_${group.id}" style="display:none;margin-top:12px;" class="group-stocks-grid"></div>
        </div>
    `).join('');

    // 加载每个分组的股票数据到隐藏容器
    groups.forEach(group => {
        const stocks = group.stocks || [];
        const stockContainer = document.getElementById(`groupStocks_${group.id}`);
        if (!stockContainer) return;

        if (stocks.length === 0) {
            stockContainer.innerHTML = `<span style="font-size:12px;color:#d1d5db;">暂无股票</span>`;
            return;
        }

        const stockInfos = stocks.map(symbol => {
            const found = allStocks.find(s => s.symbol === symbol);
            if (found) return found;
            const cached = window._cachedStocks ? window._cachedStocks[symbol] : null;
            if (cached) return cached;
            return { symbol, name: symbol, code: '', price: 0, trend_code: '', trend_name: '', signal_color: '#9ca3af', has_trend_data: false };
        });

        stockInfos.forEach(stock => {
            const isUp = (stock.trend_code || '').startsWith('up');
            const priceClass = isUp ? 'up' : 'down';
            const borderColor = stock.signal_color || '#9ca3af';
            const trendText = TREND_DESC[stock.trend_code] || stock.signal_text || '未知';

            const el = document.createElement('div');
            el.className = `stock-card ${isUp ? 'up' : 'down'}`;
            el.style.cssText = `border-left-color:${borderColor};cursor:pointer;`;
            el.onclick = () => refreshStock(stock.symbol);
            el.innerHTML = `
                <div class="stock-card-header">
                    <div>
                        <div class="stock-name" style="cursor:pointer;" onclick="event.stopPropagation(); goToDetail('${stock.symbol}')">${stock.name || stock.symbol}</div>
                        <div class="stock-code">${stock.code || stock.symbol}</div>
                    </div>
                </div>
                <div class="stock-price ${priceClass}">¥${stock.price > 0 ? stock.price.toFixed(2) : '--'}</div>
                <div class="stock-trend">
                    <span class="trend-name">${stock.trend_name || '暂无数据'}</span>
                    <span class="trend-signal" style="background:${stock.signal_color}">${trendText}</span>
                </div>
                <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center;">
                    <button onclick="event.stopPropagation(); openGroupSelectModal('${stock.symbol}', '${stock.name}')"
                        style="padding:4px 10px;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;font-size:11px;cursor:pointer;color:#6b7280;">
                        📁 加入分组
                    </button>
                </div>
            `;
            stockContainer.appendChild(el);
        });
    });
}

function toggleGroupExpand(groupId, headerEl) {
    const stockContainer = document.getElementById(`groupStocks_${groupId}`);
    const arrow = document.getElementById(`groupArrow_${groupId}`);
    if (!stockContainer) return;

    const isHidden = stockContainer.style.display === 'none';
    if (isHidden) {
        stockContainer.style.display = '';
        arrow.textContent = '▼';
    } else {
        stockContainer.style.display = 'none';
        arrow.textContent = '▶';
    }
}

// ==========================================
// 分组选择弹窗
// ==========================================
let _pendingAddSymbol = null;

async function openGroupSelectModal(symbol, stockName) {
    _pendingAddSymbol = symbol;
    const modal = document.getElementById('groupSelectModal');
    const title = document.getElementById('groupModalTitle');
    const body = document.getElementById('groupModalBody');

    title.textContent = `加入分组 - ${stockName || symbol}`;
    body.innerHTML = `<div class="loading"><div class="spinner"></div><span>加载分组...</span></div>`;
    modal.classList.add('active');

    try {
        const resp = await fetch('/api/groups');
        const data = await resp.json();
        const groups = data.groups || [];

        if (groups.length === 0) {
            body.innerHTML = `
                <p style="text-align:center;color:#9ca3af;padding:20px 0;">暂无分组</p>
                <div style="text-align:center;">
                    <input type="text" id="quickGroupName" placeholder="新建分组名称..." style="padding:6px 12px;border:1px solid #e5e7eb;border-radius:20px;font-size:13px;outline:none;width:60%;" />
                    <button onclick="quickCreateAndAdd()" style="padding:6px 14px;background:#1a73e8;color:white;border:none;border-radius:20px;font-size:13px;cursor:pointer;margin-top:8px;">创建并添加</button>
                </div>
            `;
            return;
        }

        body.innerHTML = groups.map(g => {
            const inGroup = g.stocks && g.stocks.includes(symbol);
            return `
                <div class="modal-row" style="cursor:pointer;border-bottom:1px solid #f3f4f6;padding:10px 0;" onclick="addToGroup('${g.id}', '${symbol}', this)">
                    <span class="modal-label">📁 ${g.name}</span>
                    <span class="modal-value" style="color:${inGroup ? '#16a34a' : '#9ca3af'};">${inGroup ? '✓ 已添加' : '+ 添加'}</span>
                </div>
            `;
        }).join('');
    } catch (e) {
        body.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
    }
}

async function quickCreateAndAdd() {
    const name = document.getElementById('quickGroupName').value.trim();
    if (!name) return;
    try {
        const resp = await fetch('/api/groups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await resp.json();
        if (data.errorcode === 0 && _pendingAddSymbol) {
            await addToGroup(data.group.id, _pendingAddSymbol);
            closeGroupModal();
            showToast('已创建并添加', 'info');
            loadGroups();
        }
    } catch (e) {}
}

async function addToGroup(groupId, symbol, rowEl) {
    try {
        const resp = await fetch(`/api/groups/${groupId}/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol })
        });
        const data = await resp.json();
        if (data.errorcode === 0) {
            if (rowEl) {
                rowEl.querySelector('.modal-value').textContent = '✓ 已添加';
                rowEl.querySelector('.modal-value').style.color = '#16a34a';
            }
            showToast('已添加到分组', 'info');
            // 刷新分组数据
            if (currentTab === 'groups') loadGroups();
        } else {
            showToast(data.errmsg || '添加失败', 'error');
        }
    } catch (e) {
        showToast('添加失败', 'error');
    }
}

function closeGroupModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('groupSelectModal').classList.remove('active');
    _pendingAddSymbol = null;
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
