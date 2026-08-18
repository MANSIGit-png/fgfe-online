// ========== НАВИГАЦИЯ МЕЖДУ СТРАНИЦАМИ (БЕЗ ПЕРЕХОДА ПО ССЫЛКАМ) ==========

// Получаем userId из URL
const urlParamsNav = new URLSearchParams(window.location.search);
const userIdNav = urlParamsNav.get('user_id');

// Функция для переключения страниц (БЕЗ ПЕРЕЗАГРУЗКИ)
function navigateTo(pageName) {
    // Скрываем все страницы
    document.querySelectorAll('.page-view').forEach(page => {
        page.classList.remove('active-page');
    });

    // Показываем нужную страницу
    const targetPage = document.getElementById(`${pageName}Page`);
    if (targetPage) {
        targetPage.classList.add('active-page');
    }

    // Обновляем активную кнопку навигации
    updateActiveNavButton(pageName);

    // Обновляем заголовок страницы
    updatePageTitle(pageName);

    // Сохраняем текущую страницу в localStorage (опционально)
    localStorage.setItem('currentPage', pageName);
}

// Функция для обновления активного состояния кнопок навигации
function updateActiveNavButton(currentPage) {
    // Убираем активный класс у всех кнопок
    document.querySelectorAll('.silhouette').forEach(el => {
        el.classList.remove('active-silhouette');
    });

    // Добавляем активный класс для текущей страницы
    const activeNav = document.getElementById(`nav-${currentPage}`);
    if (activeNav) {
        activeNav.classList.add('active-silhouette');
    }
}

// Функция для обновления заголовка страницы
function updatePageTitle(currentPage) {
    const titles = {
        'home': 'Главная',
        'profile': 'Профиль',
        'settings': 'Настройки'
    };
    const titleElement = document.getElementById('pageTitle');
    if (titleElement) {
        titleElement.innerText = titles[currentPage] || 'FTFE';
    }
}

// Функция для получения сохранённой страницы
function getSavedPage() {
    const saved = localStorage.getItem('currentPage');
    if (saved && (saved === 'home' || saved === 'profile' || saved === 'settings')) {
        return saved;
    }
    return 'home';
}

// НАВЕШИВАЕМ ОБРАБОТЧИКИ (ВАЖНО: удаляем старые и добавляем новые)
document.querySelectorAll('.icon-block').forEach(block => {
    const page = block.dataset.page;
    if (page) {
        // Удаляем старые обработчики (чтобы не было дублирования)
        const newBlock = block.cloneNode(true);
        block.parentNode.replaceChild(newBlock, block);

        // Добавляем новый обработчик
        newBlock.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            navigateTo(page);
        });
    }
});

// Инициализация навигации при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    const startPage = getSavedPage();
    navigateTo(startPage);
});
