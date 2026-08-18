const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const deviceType = document.body.dataset.device || 'desktop';
const isMobileDevice = deviceType === 'mobile' || deviceType === 'tablet';

if (isMobileDevice && tg) {
    document.body.classList.add('mobile-mode');
    try { tg.disableVerticalSwipes(); } catch(e) {}
    setTimeout(async () => {
        try {
            if (typeof tg.requestFullscreen === 'function') await tg.requestFullscreen();
            else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
        } catch(e) {}
    }, 300);
}

let userTimezone = null;
let userIP = null;
let userCountry = null;
let userCity = null;

async function getUserIPAndTimezone() {
    try {
        const ipResponse = await fetch('https://api.ipify.org?format=json');
        const ipData = await ipResponse.json();
        userIP = ipData.ip;
        const geoResponse = await fetch(`https://api.ipapi.co/${userIP}/json/`);
        const geoData = await geoResponse.json();
        userTimezone = geoData.timezone;
        userCountry = geoData.country_name;
        userCity = geoData.city;
        localStorage.setItem('user_timezone', userTimezone);
        localStorage.setItem('user_ip', userIP);
        localStorage.setItem('user_country', userCountry);
        localStorage.setItem('user_city', userCity);
        await sendUserDataToServer();
        return { ip: userIP, timezone: userTimezone, country: userCountry, city: userCity };
    } catch (error) {
        userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return { ip: null, timezone: userTimezone, source: 'browser' };
    }
}

async function sendUserDataToServer() {
    try {
        const tg = window.Telegram?.WebApp;
        const telegramUser = tg?.initDataUnsafe?.user;
        await fetch('/api/user/timezone', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: telegramUser?.id || null,
                username: telegramUser?.username || null,
                ip: userIP,
                timezone: userTimezone,
                country: userCountry,
                city: userCity,
                user_agent: navigator.userAgent
            })
        });
    } catch (error) {}
}

function formatLocalTime(date, mode = 'time') {
    if (!date) return '';
    const options = { timeZone: userTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone };
    switch(mode) {
        case 'time': return new Date(date).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', ...options });
        case 'datetime': return new Date(date).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', ...options });
        case 'date': return new Date(date).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', ...options });
        default: return new Date(date).toLocaleString('ru-RU', options);
    }
}

function updateTimezoneDisplay() {
    const tzElement = document.getElementById('timezoneInfo');
    if (tzElement && userTimezone) {
        const offset = -new Date().getTimezoneOffset();
        const hours = Math.floor(Math.abs(offset) / 60);
        const sign = offset >= 0 ? '+' : '-';
        tzElement.innerHTML = `🕐 Ваш часовой пояс: ${userTimezone} (UTC${sign}${hours})`;
    }
}

(async function init() {
    await getUserIPAndTimezone();
    updateTimezoneDisplay();
})();

const telegramUser = tg.initDataUnsafe?.user;
const urlParams = new URLSearchParams(window.location.search);
const userId = telegramUser?.id || urlParams.get('user_id');

function showToast(msg, isError) {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.textContent = msg;
        toast.className = 'toast' + (isError ? ' error' : '');
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 2000);
    }
}

function copyToClipboard(text) {
    const idMatch = text.match(/\d+/);
    if (idMatch) navigator.clipboard.writeText(idMatch[0]);
    showToast('✅ ID скопирован!');
}

setTimeout(() => {
    const buyBtnText = document.getElementById('buyBtnText');
    if (buyBtnText) buyBtnText.innerText = 'Купить';
}, 100);

async function loadUserData() {
    try {
        const res = await fetch(`/api/user?user_id=${userId}`);
        const data = await res.json();
        const name = `${telegramUser?.first_name || 'User'} ${telegramUser?.last_name || ''}`.trim();
        const elements = {
            profileName: name,
            profileUsername: `@${telegramUser?.username || 'username'}`,
            profileId: `ID: ${telegramUser?.id || userId}`,
            pointsBalance: data.balans || '0',
            tonBalance: data.ton_balance || '0',
            walletStatus: data.kosh || 'Не подключен'
        };
        for (const [id, value] of Object.entries(elements)) {
            const el = document.getElementById(id);
            if (el) el.innerHTML = value;
        }
        await setAvatar();
    } catch(e) {
        showToast('❌ Ошибка загрузки', true);
    }
}

async function setAvatar() {
    if (telegramUser?.photo_url) {
        const emojiSpan = document.getElementById('profileAvatarEmoji');
        const img = document.getElementById('profileAvatarImg');
        if (emojiSpan) emojiSpan.style.display = 'none';
        if (img) {
            img.style.display = 'block';
            img.src = telegramUser.photo_url;
        }
    } else {
        const emojiSpan = document.getElementById('profileAvatarEmoji');
        if (emojiSpan) emojiSpan.innerHTML = (telegramUser?.first_name?.charAt(0) || '👤').toUpperCase();
    }
}

async function connectWallet() {
    tg.showPopup({
        title: 'Подключение кошелька',
        message: 'Введите адрес TON кошелька:',
        buttons: [{ type: 'default', text: 'Подключить' }, { type: 'cancel', text: 'Отмена' }]
    }, async (btnId) => {
        if (btnId === 'default') {
            tg.showPrompt({ title: 'Адрес кошелька', message: 'Введите ваш TON кошелек:' }, async (wallet) => {
                if (wallet) {
                    await fetch(`/api/connect_wallet?user_id=${userId}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ wallet })
                    });
                    showToast('✅ Кошелек подключен!');
                    await loadUserData();
                }
            });
        }
    });
}

document.getElementById('connectWalletBtn')?.addEventListener('click', connectWallet);

// Основная навигация вынесена в реальные URL (/profile, /bonus, /settings).
createGrid();
if (telegramUser || userId) loadUserData();
else showToast('❌ Ошибка авторизации', true);
