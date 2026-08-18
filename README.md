# FGFE / TONFARM

Это репозиторий исходного Telegram Mini App TONFARM/FGFE.

Целевая структура:
- `web/` — интерфейс, HTML/CSS/JS, игры и медиа.
- `bac/` — Flask + Socket.IO backend, Telegram bot и API.
- `data/` — runtime-данные.
- `locales/` — переводы.

Страницы после миграции:
- `/` — Главная
- `/profile` — Профиль
- `/bonus` — Бонусы / стейкинг
- `/settings` — Настройки

Навигация между вкладками выполняет полноценный переход между страницами. Профильные блоки находятся в HTML сразу, а данные подгружаются после первого отображения.

Полный архив проекта импортируется через workflow `.github/workflows/import-tonfarm.yml`.