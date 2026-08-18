let fdvChart = null;
let currentMode = '5min';
let priceHistoryData = [];
let currentPrice = 0;

async function loadPriceHistory(mode) {
    try {
        const response = await fetch(`/api/price_history?mode=${mode}`);
        if (response.ok) {
            const data = await response.json();
            priceHistoryData = data.history || [];
            currentPrice = data.current_price || 0;
            updatePriceDisplay();
            updateChart();
            return true;
        }
    } catch(e) {
        console.error('Ошибка загрузки истории цен:', e);
        return false;
    }
}

function updatePriceDisplay() {
    const currentFDVElement = document.getElementById('currentFDV');
    const priceChangeElement = document.getElementById('priceChange');
    const tokenAgeDisplay = document.getElementById('tokenAgeDisplay');

    if (currentFDVElement) currentFDVElement.innerHTML = `$${formatNumber(currentPrice)}`;

    if (priceChangeElement && priceHistoryData.length >= 2) {
        const firstPrice = priceHistoryData[0].price;
        const lastPrice = priceHistoryData[priceHistoryData.length - 1].price;
        const change = ((lastPrice - firstPrice) / firstPrice) * 100;
        const changeClass = change >= 0 ? 'positive' : 'negative';
        priceChangeElement.innerHTML = `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
        priceChangeElement.className = `change-value ${changeClass}`;
    }

    if (tokenAgeDisplay) tokenAgeDisplay.innerHTML = 'Токен активен';
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(2) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(2) + 'K';
    return num.toFixed(2);
}

function updateChart() {
    const canvas = document.getElementById('fdvChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const labels = priceHistoryData.map(item => {
        const date = new Date(item.timestamp);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });
    const prices = priceHistoryData.map(item => item.price);

    if (fdvChart) {
        fdvChart.data.labels = labels;
        fdvChart.data.datasets[0].data = prices;
        fdvChart.update();
    } else {
        fdvChart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets: [{ label: 'FDV (USD)', data: prices, borderColor: '#c084fc', backgroundColor: 'rgba(192, 132, 252, 0.1)', borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, pointBackgroundColor: '#c084fc', tension: 0.3, fill: true }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, callbacks: { label: context => `$${context.raw.toFixed(2)}` } } },
                scales: { x: { grid: { display: false, color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888', maxRotation: 45, minRotation: 45 } }, y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888', callback: value => '$' + value.toFixed(0) } } },
                interaction: { mode: 'index', intersect: false }
            }
        });
    }
}

function setupChartModeSwitcher() {
    const dropdownBtn = document.getElementById('dropdownBtn');
    const dropdownMenu = document.getElementById('dropdownMenu');
    const currentModeText = document.getElementById('currentModeText');
    if (!dropdownBtn || !dropdownMenu) return;

    dropdownBtn.addEventListener('click', e => { e.stopPropagation(); dropdownMenu.classList.toggle('show'); });
    document.addEventListener('click', () => dropdownMenu.classList.remove('show'));
    document.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', async () => {
            const mode = item.dataset.mode;
            if (!mode) return;
            currentModeText.innerText = item.innerText;
            dropdownMenu.classList.remove('show');
            currentMode = mode;
            showChartLoading();
            await loadPriceHistory(mode);
            hideChartLoading();
        });
    });
}

function showChartLoading() {
    const chartContainer = document.getElementById('chartContainer');
    if (!chartContainer) return;
    let loadingOverlay = document.querySelector('.chart-loading-overlay');
    if (!loadingOverlay) {
        loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'chart-loading-overlay';
        loadingOverlay.innerHTML = '<div class="loading-spinner"></div><span>Загрузка...</span>';
        loadingOverlay.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(10,10,15,.7);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;gap:10px;border-radius:16px;z-index:10;';
        chartContainer.style.position = 'relative';
        chartContainer.appendChild(loadingOverlay);
    } else loadingOverlay.style.display = 'flex';
}

function hideChartLoading() {
    const loadingOverlay = document.querySelector('.chart-loading-overlay');
    if (loadingOverlay) loadingOverlay.style.display = 'none';
}

async function initChart() {
    setupChartModeSwitcher();
    await loadPriceHistory(currentMode);
    setInterval(async () => { await loadPriceHistory(currentMode); }, 30000);
}

if (document.getElementById('fdvChart')) initChart();
