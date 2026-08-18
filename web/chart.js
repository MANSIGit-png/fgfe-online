// ========== ГРАФИК FDV ==========

let fdvChart = null;
let allData = [];
let currentMode = 'all';
let currentFilteredData = [];
let dataLoaded = false;
let updateInterval = null;
let isLoading = false;

const POINTS_COUNT = 30;
const UPDATE_INTERVAL_MS = 30000; // 30 секунд

function formatPrice(value) {
    if (value === 0) return '$0';
    if (value >= 1_000_000) {
        return '$' + (value / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
    }
    if (value >= 1_000) {
        return '$' + (value / 1_000).toFixed(0) + 'K';
    }
    return '$' + Math.round(value).toString();
}

function formatPriceDetailed(value) {
    if (value === 0) return '$0';
    if (value >= 1_000_000) {
        return '$' + (value / 1_000_000).toFixed(2) + 'M';
    }
    if (value >= 1_000) {
        return '$' + (value / 1_000).toFixed(2) + 'K';
    }
    return '$' + Math.round(value).toString();
}

function showChartLoading() {
    let loadingOverlay = document.querySelector('.chart-loading-overlay');
    if (!loadingOverlay && chartContainerEl) {
        loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'chart-loading-overlay';
        loadingOverlay.innerHTML = '<div class="loading-spinner"></div>';
        loadingOverlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(10, 10, 15, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 16px;
            z-index: 5;
        `;
        chartContainerEl.style.position = 'relative';
        chartContainerEl.appendChild(loadingOverlay);
    } else if (loadingOverlay) {
        loadingOverlay.style.display = 'flex';
    }
}

function hideChartLoading() {
    const loadingOverlay = document.querySelector('.chart-loading-overlay');
    if (loadingOverlay) {
        loadingOverlay.style.display = 'none';
    }
}

function createGradient(ctx, height) {
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, 'rgba(192, 132, 252, 0.4)');
    gradient.addColorStop(0.5, 'rgba(192, 132, 252, 0.15)');
    gradient.addColorStop(1, 'rgba(192, 132, 252, 0.02)');
    return gradient;
}

async function loadDataFromFile(silent = false) {
    if (isLoading) return false;

    isLoading = true;
    if (!silent) showChartLoading();

    try {
        const response = await fetch('/api/price_history');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (!data || !data.length) {
            throw new Error('Файл пуст');
        }

        let parsedData = data.map(item => ({
            time: new Date(item.timestamp),
            fdv: item.fdv
        })).sort((a, b) => a.time - b.time);

        const uniqueData = [];
        for (const p of parsedData) {
            if (uniqueData.length === 0 || uniqueData[uniqueData.length - 1].time.getTime() !== p.time.getTime()) {
                uniqueData.push(p);
            }
        }

        allData = uniqueData;
        dataLoaded = true;

        updateFDVAndAge();

        // Обновляем фильтрованные данные и график
        refreshCurrentMode();

        return true;
    } catch (e) {
        console.error('Ошибка загрузки:', e);
        if (!silent) {
            document.getElementById('currentFDV').innerHTML = '$0';
            document.getElementById('tokenAgeDisplay').innerHTML = 'ошибка';
        }
        return false;
    } finally {
        isLoading = false;
        if (!silent) hideChartLoading();
    }
}

function refreshCurrentMode() {
    if (!dataLoaded && allData.length === 0) return;

    let filtered = [];

    switch (currentMode) {
        case '5min':
            filtered = getDataFromEnd(5 / 60, POINTS_COUNT);
            break;
        case '1hour':
            filtered = getDataFromEnd(1, POINTS_COUNT);
            break;
        case '12hour':
            filtered = getDataFromEnd(12, POINTS_COUNT);
            break;
        case '1day':
            filtered = getDataFromEnd(24, POINTS_COUNT);
            break;
        case 'all':
            filtered = getAllDataSampled(POINTS_COUNT);
            break;
        default:
            filtered = getDataFromEnd(5 / 60, POINTS_COUNT);
    }

    if (filtered.length < 2) filtered = getAllDataSampled(POINTS_COUNT);

    currentFilteredData = filtered;
    renderChart();
}

function updateFDVAndAge() {
    if (!allData.length) return;
    const currentFdv = allData[allData.length - 1].fdv;
    document.getElementById('currentFDV').innerHTML = formatPrice(currentFdv);

    const firstTime = allData[0].time;
    const lastTime = allData[allData.length - 1].time;
    const diffMs = lastTime - firstTime;
    const hours = diffMs / (1000 * 60 * 60);

    if (hours < 24) {
        const hoursInt = Math.floor(hours);
        const minutesInt = Math.floor((hours % 1) * 60);
        if (hoursInt < 1) {
            document.getElementById('tokenAgeDisplay').innerHTML = `существует <span>${minutesInt}</span> мин`;
        } else {
            document.getElementById('tokenAgeDisplay').innerHTML = `существует <span>${hoursInt}</span> ${hoursInt === 1 ? 'час' : (hoursInt < 5 ? 'часа' : 'часов')}`;
        }
    } else {
        const days = Math.floor(hours / 24);
        document.getElementById('tokenAgeDisplay').innerHTML = `существует <span>${days}</span> ${days === 1 ? 'день' : (days < 5 ? 'дня' : 'дней')}`;
    }
}

function getDataFromEnd(intervalHours, pointsCount) {
    if (!allData.length) return [];

    const lastTime = allData[allData.length - 1].time.getTime();
    const firstTime = allData[0].time.getTime();
    const totalHours = (lastTime - firstTime) / (1000 * 60 * 60);

    if (intervalHours * pointsCount > totalHours) {
        return getAllDataSampled(pointsCount);
    }

    const result = [];
    const stepMs = intervalHours * 60 * 60 * 1000;
    const startTime = lastTime - (stepMs * (pointsCount - 1));

    for (let i = 0; i < pointsCount; i++) {
        const targetTime = startTime + (i * stepMs);
        let closest = allData[0];
        let minDiff = Infinity;
        for (const p of allData) {
            const diff = Math.abs(p.time.getTime() - targetTime);
            if (diff < minDiff) {
                minDiff = diff;
                closest = p;
            }
        }
        result.push({
            time: new Date(targetTime),
            fdv: closest.fdv
        });
    }
    return result;
}

function getAllDataSampled(maxPoints) {
    if (allData.length <= maxPoints) return [...allData];
    const result = [];
    const step = (allData.length - 1) / (maxPoints - 1);
    for (let i = 0; i < maxPoints; i++) {
        result.push({ ...allData[Math.round(i * step)] });
    }
    return result;
}

function calculateStats(data) {
    if (!data.length) return { min: 0, max: 0, priceChange: 0, priceChangePercent: 0 };

    const nonZeroValues = data.filter(d => d.fdv > 0).map(d => d.fdv);
    if (!nonZeroValues.length) return { min: 0, max: 0, priceChange: 0, priceChangePercent: 0 };

    const min = Math.min(...nonZeroValues);
    const max = Math.max(...nonZeroValues);

    const firstNonZero = nonZeroValues[0];
    const lastPrice = nonZeroValues[nonZeroValues.length - 1];
    const priceChange = lastPrice - firstNonZero;
    const priceChangePercent = (priceChange / firstNonZero) * 100;

    return { min, max, priceChange, priceChangePercent };
}

function updateChange(data) {
    const stats = calculateStats(data);
    const changePercent = stats.priceChangePercent;
    const changeAbs = stats.priceChange;

    const changeElem = document.getElementById('priceChange');
    const isPositive = changePercent >= 0;

    changeElem.innerHTML = `${isPositive ? '+' : ''}${changePercent.toFixed(1)}% <span class="dim">(${isPositive ? '+' : ''}${formatPriceDetailed(Math.abs(changeAbs))})</span>`;

    if (isPositive) {
        changeElem.classList.add('positive');
        changeElem.classList.remove('negative');
    } else {
        changeElem.classList.add('negative');
        changeElem.classList.remove('positive');
    }
}

function formatLabel(date, mode) {
    switch (mode) {
        case '5min':
        case '1hour':
            return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        case '12hour':
            return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        case '1day':
        case 'all':
            return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
        default:
            return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    }
}

function renderChart() {
    if (!currentFilteredData.length) return;

    const labels = currentFilteredData.map(p => formatLabel(p.time, currentMode));
    const values = currentFilteredData.map(p => p.fdv);

    const nonZeroValues = values.filter(v => v > 0);
    const maxVal = nonZeroValues.length ? Math.max(...nonZeroValues) : 100;
    const minVal = nonZeroValues.length ? Math.min(...nonZeroValues) : 0;
    const range = maxVal - minVal;
    const padding = range * 0.15;

    const labelMax = document.getElementById('chartLabelMax');
    const labelMin = document.getElementById('chartLabelMin');
    if (labelMax) labelMax.innerHTML = formatPrice(maxVal);
    if (labelMin) labelMin.innerHTML = formatPrice(minVal);

    const canvas = document.getElementById('fdvChart');
    const ctx = canvas.getContext('2d');
    const container = canvas.parentElement;
    const size = container.clientWidth;
    canvas.width = size;
    canvas.height = size;

    if (fdvChart) {
        fdvChart.destroy();
        fdvChart = null;
    }

    // Создаем градиент заново при каждом рендере
    const gradient = createGradient(ctx, size);

    fdvChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                borderColor: '#c084fc',
                borderWidth: 2.5,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointBackgroundColor: '#c084fc',
                tension: 0.3,
                fill: true,
                backgroundColor: gradient
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                tooltip: { enabled: false },
                legend: { display: false }
            },
            scales: {
                x: {
                    ticks: { color: '#fff', font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 5 },
                    grid: { color: 'rgba(255, 255, 255, 0.06)' }
                },
                y: {
                    min: minVal > 0 ? Math.max(0, minVal - padding) : 0,
                    max: maxVal + padding,
                    ticks: { color: '#fff', callback: (v) => formatPrice(v), font: { size: 10 } },
                    grid: { color: 'rgba(255, 255, 255, 0.06)' }
                }
            }
        }
    });

    updateChange(currentFilteredData);
}

const crosshairH = document.getElementById('crosshairH');
const crosshairV = document.getElementById('crosshairV');
const hoverDot = document.getElementById('hoverDot');
const hoverPrice = document.getElementById('hoverPrice');
const chartContainerEl = document.getElementById('chartContainer');

function updateCrosshairAndDot(clientX, clientY) {
    if (!fdvChart || !currentFilteredData.length) return;

    const canvas = document.getElementById('fdvChart');
    if (!canvas) return;

    const canvasRect = canvas.getBoundingClientRect();
    const containerRect = chartContainerEl ? chartContainerEl.getBoundingClientRect() : canvasRect;
    const chartArea = fdvChart.chartArea;

    const mouseX = clientX - canvasRect.left;
    const mouseY = clientY - canvasRect.top;

    if (mouseX < chartArea.left || mouseX > chartArea.right || mouseY < chartArea.top || mouseY > chartArea.bottom) {
        hideAll();
        return;
    }

    const xScale = fdvChart.scales.x;
    const yScale = fdvChart.scales.y;

    let closestIndex = -1;
    let minDist = Infinity;
    for (let i = 0; i < currentFilteredData.length; i++) {
        const xPixel = xScale.getPixelForValue(i);
        const dist = Math.abs(xPixel - mouseX);
        if (dist < minDist) {
            minDist = dist;
            closestIndex = i;
        }
    }

    if (closestIndex !== -1) {
        const point = currentFilteredData[closestIndex];
        const pointX = xScale.getPixelForValue(closestIndex);
        const pointY = yScale.getPixelForValue(point.fdv);

        if (crosshairV) {
            crosshairV.style.display = 'block';
            crosshairV.style.left = (canvasRect.left + pointX - containerRect.left) + 'px';
            crosshairV.style.top = '0';
            crosshairV.style.height = (chartContainerEl || canvas.parentElement).clientHeight + 'px';
        }

        if (crosshairH) {
            crosshairH.style.display = 'block';
            crosshairH.style.top = (canvasRect.top + pointY - containerRect.top) + 'px';
            crosshairH.style.left = '0';
            crosshairH.style.width = (chartContainerEl || canvas.parentElement).clientWidth + 'px';
        }

        if (hoverDot) {
            hoverDot.style.display = 'block';
            hoverDot.style.left = (canvasRect.left + pointX - containerRect.left) + 'px';
            hoverDot.style.top = (canvasRect.top + pointY - containerRect.top) + 'px';
        }

        let timeStr;
        if (currentMode === '5min' || currentMode === '1hour') {
            timeStr = point.time.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        } else {
            timeStr = point.time.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        }

        if (hoverPrice) {
            hoverPrice.style.display = 'block';
            hoverPrice.innerHTML = `<div class="price">${formatPriceDetailed(point.fdv)}</div><div class="time">${timeStr}</div>`;

            let priceLeft = (canvasRect.left + pointX - containerRect.left) + 20;
            let priceTop = (canvasRect.top + pointY - containerRect.top) - 20;

            const containerWidth = (chartContainerEl || canvas.parentElement).clientWidth;
            if (priceLeft + 100 > containerWidth) {
                priceLeft = (canvasRect.left + pointX - containerRect.left) - 120;
            }

            if (priceTop < 0) {
                priceTop = (canvasRect.top + pointY - containerRect.top) + 15;
            }

            hoverPrice.style.left = priceLeft + 'px';
            hoverPrice.style.top = priceTop + 'px';
        }
    }
}

function hideAll() {
    if (crosshairH) crosshairH.style.display = 'none';
    if (crosshairV) crosshairV.style.display = 'none';
    if (hoverDot) hoverDot.style.display = 'none';
    if (hoverPrice) hoverPrice.style.display = 'none';
}

function onMouseMove(e) {
    updateCrosshairAndDot(e.clientX, e.clientY);
}

function onMouseLeave() {
    hideAll();
}

function onTouchMove(e) {
    e.preventDefault();
    if (e.touches.length) {
        updateCrosshairAndDot(e.touches[0].clientX, e.touches[0].clientY);
    }
}

function onTouchEnd() {
    hideAll();
}

function applyMode(mode) {
    currentMode = mode;
    const modeNames = { '5min': '5м', '1hour': '1ч', '12hour': '12ч', '1day': '1д', 'all': 'Всё' };
    const modeTextElem = document.getElementById('currentModeText');
    if (modeTextElem) modeTextElem.innerText = modeNames[mode] || mode;

    refreshCurrentMode();
}

function startAutoUpdate() {
    if (updateInterval) clearInterval(updateInterval);

    updateInterval = setInterval(async () => {
        await loadDataFromFile(true);
    }, UPDATE_INTERVAL_MS);
}

function stopAutoUpdate() {
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
    }
}

const dropdownBtn = document.getElementById('dropdownBtn');
const dropdownMenu = document.getElementById('dropdownMenu');

dropdownBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdownMenu.classList.toggle('show');
});

document.querySelectorAll('.dropdown-item').forEach(item => {
    item.addEventListener('click', () => {
        applyMode(item.dataset.mode);
        dropdownMenu.classList.remove('show');
    });
});

document.addEventListener('click', () => {
    dropdownMenu?.classList.remove('show');
});

const canvasEl = document.getElementById('fdvChart');
if (canvasEl) {
    canvasEl.addEventListener('mousemove', onMouseMove);
    canvasEl.addEventListener('mouseleave', onMouseLeave);
    canvasEl.addEventListener('touchmove', onTouchMove, { passive: false });
    canvasEl.addEventListener('touchend', onTouchEnd);
}

async function initChart() {
    await loadDataFromFile(false);
    applyMode('all');
    startAutoUpdate();
}

document.addEventListener('visibilitychange', () => {
    if (!document.hidden && window.location.pathname === '/') {
        loadDataFromFile(false);
    }
});

initChart();

window.refreshChart = () => loadDataFromFile(false);
