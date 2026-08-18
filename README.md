# FGFE — fgfe.online

Готовый статический сайт для домена `fgfe.online`.

## Файлы

- `index.html` — главная страница
- `styles.css` — адаптивный дизайн
- `script.js` — мобильное меню и анимации
- `404.html` — страница ошибки
- `favicon.svg` — иконка сайта
- `site.webmanifest` — manifest
- `robots.txt` и `sitemap.xml` — файлы для поисковых систем
- `CNAME` — домен `fgfe.online`

## Публикация через GitHub Pages

1. Откройте репозиторий `MANSIGit-png/fgfe-online`.
2. Перейдите в **Settings → Pages**.
3. В **Build and deployment → Source** выберите **Deploy from a branch**.
4. Выберите ветку **main** и папку **/(root)**, затем нажмите **Save**.
5. В поле **Custom domain** укажите `fgfe.online` и сохраните.
6. После корректной настройки DNS включите **Enforce HTTPS**, когда GitHub разрешит переключатель.

> Если аккаунт использует GitHub Free, для GitHub Pages репозиторий обычно должен быть публичным. Если Pages недоступен для private-репозитория, измените Visibility на Public или используйте тариф с поддержкой Pages для private-репозиториев.

## DNS для fgfe.online

Для корневого домена (`@`) добавьте четыре A-записи:

| Type | Name | Value |
|---|---|---|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |

Рекомендуется также добавить `www`:

| Type | Name | Value |
|---|---|---|
| CNAME | www | MANSIGit-png.github.io |

После этого `www.fgfe.online` сможет перенаправляться на основной домен, если `fgfe.online` указан как Custom domain в GitHub Pages.

DNS может обновляться не мгновенно. Не добавляйте wildcard-запись `*` для GitHub Pages.
