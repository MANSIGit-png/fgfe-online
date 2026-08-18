// ========== КАРУСЕЛЬ ==========

let slidesData = [];
let currentIndex = 0;
let autoTimer = null;
let isDraggingCarousel = false;
let startX = 0;
let startTranslate = 0;
let track;

const AUTO_INTERVAL = 5000;
const SWIPE_THRESHOLD = 40;
const CAROUSEL_GAP = 16;

const icons = {
    external: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M15 3h6v6"></path><path d="M10 14 21 3"></path><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path></svg>`
};

function getIcon(iconName) {
    if (!iconName || iconName === 'none') return '';
    return icons[iconName] || '';
}

function getCardWidth() {
    const card = document.querySelector('.content-card');
    return card ? card.offsetWidth : 300;
}

function getTranslateX(index) {
    const container = document.querySelector('.carousel-container');
    const containerWidth = container.clientWidth;
    const card = document.querySelector('.content-card');
    const cardWidth = card.offsetWidth;
    const gap = 16;
    const slideWidth = cardWidth + gap;
    const offset = (containerWidth - cardWidth) / 2 - 8;
    let transform = -(index * slideWidth) + offset;
    const maxTransform = offset;
    const minTransform = -((slidesData.length - 1) * slideWidth) + offset;
    return Math.min(maxTransform, Math.max(minTransform, transform));
}

function setTransform(translate, withTransition = true) {
    if (!track) return;
    if (withTransition) {
        track.style.transition = `transform 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94)`;
    } else {
        track.style.transition = 'none';
    }
    track.style.transform = `translateX(${translate}px)`;
}

function updateActiveSlideContent() {
    const slide = slidesData[currentIndex];
    if (!slide || !track) return;
    const card = track.children[currentIndex];
    if (!card) return;

    card.style.background = slide.cardBackground || 'linear-gradient(135deg, #c084fc 0%, #8b5cf6 100%)';

    const titleEl = card.querySelector('.content-title');
    const descEl = card.querySelector('.content-description');
    const buttonTextEl = card.querySelector('.button-text-span');
    const iconContainer = card.querySelector('.button-icon');

    if (titleEl) titleEl.innerHTML = slide.title || '—';
    if (descEl) descEl.innerHTML = slide.description || '';
    if (buttonTextEl) buttonTextEl.innerHTML = slide.buttonText || 'Подробнее';

    const iconHtml = getIcon(slide.buttonIcon);
    if (iconContainer) {
        if (iconHtml) {
            iconContainer.innerHTML = iconHtml;
            iconContainer.style.display = 'inline-flex';
        } else {
            iconContainer.innerHTML = '';
            iconContainer.style.display = 'none';
        }
    }

    const btn = card.querySelector('.content-button');
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.classList.add('content-button');
    newBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (slide.buttonAction === 'alert') alert(slide.buttonValue || '🚀');
        else if (slide.buttonAction === 'link') window.open(slide.buttonValue, '_blank');
    });

    const stickerContainer = card.querySelector('.content-right');
    if (stickerContainer) {
        const stickerSpeed = slide.stickerSpeed !== undefined ? slide.stickerSpeed : 1.0;
        const url = slide.stickerUrl || '';

        if (url.endsWith('.json')) {
            stickerContainer.innerHTML = '';
            const lottiePlayer = document.createElement('lottie-player');
            lottiePlayer.setAttribute('src', url);
            lottiePlayer.setAttribute('background', 'transparent');
            lottiePlayer.setAttribute('speed', stickerSpeed);
            lottiePlayer.setAttribute('loop', '');
            lottiePlayer.setAttribute('autoplay', '');
            lottiePlayer.setAttribute('style', 'width:100%;height:100%;');
            stickerContainer.appendChild(lottiePlayer);
        }
        else if (url.endsWith('.webm') || url.endsWith('.mp4')) {
            stickerContainer.innerHTML = `<video class="sticker-video" autoplay loop muted playsinline src="${url}" style="width:100%;height:100%;object-fit:contain; background:transparent;"></video>`;
        }
        else if (url.endsWith('.gif') || url.endsWith('.png') || url.endsWith('.apng') || url.endsWith('.webp')) {
            stickerContainer.innerHTML = `<img src="${url}" style="width:100%;height:100%;object-fit:contain; display:block;" alt="sticker">`;
        }
        else {
            stickerContainer.innerHTML = '<span class="sticker-emoji">💎</span>';
        }
    }
}

function renderSlides() {
    if (!track) return;
    track.innerHTML = '';
    slidesData.forEach((slide) => {
        const card = document.createElement('div');
        card.className = 'content-card';
        card.style.background = slide.cardBackground || 'linear-gradient(135deg, #c084fc 0%, #8b5cf6 100%)';
        card.innerHTML = `
            <div class="content-left">
                <div class="content-title">${slide.title || '—'}</div>
                <div class="content-description">${slide.description || ''}</div>
                <button class="content-button">
                    <span class="button-icon"></span>
                    <span class="button-text-span">${slide.buttonText || 'Подробнее'}</span>
                </button>
            </div>
            <div class="content-right">
                <span class="sticker-emoji">💎</span>
            </div>
        `;
        track.appendChild(card);
    });
    updateActiveSlideContent();
    setTransform(getTranslateX(currentIndex), false);
}

function goToSlide(index, withAnimation = true) {
    if (index < 0) index = 0;
    if (index >= slidesData.length) index = slidesData.length - 1;
    if (index === currentIndex) return;
    currentIndex = index;
    setTransform(getTranslateX(currentIndex), withAnimation);
    updateActiveSlideContent();
    updateIndicators();
    restartAutoSlide();
}

function nextSlide() { goToSlide((currentIndex + 1) % slidesData.length, true); }
function prevSlide() { goToSlide((currentIndex - 1 + slidesData.length) % slidesData.length, true); }

function updateIndicators() {
    const container = document.getElementById('promoBannerIndicator');
    if (!container) return;
    container.innerHTML = '';
    if (slidesData.length <= 1) { container.style.display = 'none'; return; }
    container.style.display = 'flex';
    for (let i = 0; i < slidesData.length; i++) {
        const indicator = document.createElement('div');
        indicator.className = 'promo-banner-indicator-item';
        if (i === currentIndex) indicator.classList.add('is-active');
        indicator.addEventListener('click', (e) => {
            e.stopPropagation();
            goToSlide(i, true);
            restartAutoSlide();
        });
        if (i === currentIndex) {
            const fill = document.createElement('span');
            fill.className = 'promo-banner-indicator-fill';
            indicator.appendChild(fill);
        }
        container.appendChild(indicator);
    }
}

function startAutoSlide() {
    if (autoTimer) clearInterval(autoTimer);
    if (slidesData.length > 1) autoTimer = setInterval(nextSlide, AUTO_INTERVAL);
}

function restartAutoSlide() { startAutoSlide(); }

function onDragStart(e) {
    if (slidesData.length <= 1) return;
    isDraggingCarousel = true;
    startX = e.type === 'mousedown' ? e.clientX : e.touches[0].clientX;
    startTranslate = getTranslateX(currentIndex);
    if (track) track.style.transition = 'none';
}

function onDragMove(e) {
    if (!isDraggingCarousel) return;
    e.preventDefault();
    const curX = e.type === 'mousemove' ? e.clientX : e.touches[0].clientX;
    const diff = curX - startX;
    let newX = startTranslate + diff;
    const maxTranslate = getTranslateX(0);
    const minTranslate = getTranslateX(slidesData.length - 1);
    newX = Math.min(maxTranslate, Math.max(minTranslate, newX));
    if (track) track.style.transform = `translateX(${newX}px)`;
}

function onDragEnd(e) {
    if (!isDraggingCarousel) return;
    isDraggingCarousel = false;
    const endX = e.type === 'mouseup' ? e.clientX : (e.changedTouches ? e.changedTouches[0].clientX : startX);
    const diff = endX - startX;
    let newIdx = currentIndex;
    if (Math.abs(diff) > SWIPE_THRESHOLD) {
        if (diff > 0) newIdx = currentIndex - 1;
        else newIdx = currentIndex + 1;
    }
    newIdx = Math.min(Math.max(0, newIdx), slidesData.length - 1);
    goToSlide(newIdx, true);
}

async function loadCarouselContent() {
    try {
        const response = await fetch('/webapp/content.json');
        if (!response.ok) throw new Error('JSON не загружен');
        const data = await response.json();
        slidesData = data.slides || [];
        if (slidesData.length === 0) throw new Error();
        track = document.getElementById('carouselTrack');
        renderSlides();
        updateIndicators();
        startAutoSlide();

        track.addEventListener('mousedown', onDragStart);
        window.addEventListener('mousemove', onDragMove);
        window.addEventListener('mouseup', onDragEnd);
        track.addEventListener('touchstart', onDragStart, { passive: false });
        window.addEventListener('touchmove', onDragMove, { passive: false });
        window.addEventListener('touchend', onDragEnd);

        document.querySelector('.carousel-wrapper').addEventListener('wheel', (e) => {
            if (slidesData.length <= 1) return;
            if (e.target.closest('.promo-banner-indicator')) return;
            if (e.deltaY > 0) nextSlide();
            else if (e.deltaY < 0) prevSlide();
            restartAutoSlide();
            e.preventDefault();
        });

        window.addEventListener('resize', () => { if (track) setTransform(getTranslateX(currentIndex), false); });
    } catch(e) {
        console.error('Ошибка загрузки карусели:', e);
        if (track) track.innerHTML = '<div class="content-card" style="justify-content:center;">📌 Нет контента</div>';
    }
}

// Запуск карусели
loadCarouselContent();
