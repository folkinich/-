# Деплой frontend с вашим Dockerfile

## Что теперь добавлено

- package.json и package-lock.json: полноценный npm-проект без внешних зависимостей.
- npm ci: воспроизводимая установка по lock-файлу.
- npm run build: создаёт dist/ только из публичных HTML/CSS/JS.
- npm run serve: запускает Node HTTP-сервер на 0.0.0.0:3000.
- /health и /healthz: проверка готовности.
- scripts/ и tests/: сборка, сервер и автоматические проверки.
- Dockerfile: предоставленный вами файл с исходным DEPS_IMAGE и командами сохранён.
- .dockerignore: исключает локальные зависимости, секреты и dist из контекста Docker.

Минимальная версия Node — 18.20; проверено на Node 22 в Docker и Node 24 локально.

## Загрузка в ваш GitLab

Создайте рабочую ветку от master в **frontend-project**. Сохраните текущую работу.
Перенесите содержимое этого архива в корень репозитория, рядом с Dockerfile:

```
frontend-project/
  package.json
  package-lock.json
  Dockerfile
  .dockerignore
  scripts/
    build.cjs
    serve.cjs
  tests/
    serve.test.cjs
  index.html
  login.html
  dashboard.html
  style.css
  config.js
  api.js
  data.js
  store.js
  login.js
  dashboard.js
```

Не переносите сюда папку-обёртку eventflow-frontend целиком.
Не удаляйте .gitlab-ci.yml и policy.yml: они относятся к вашей площадке.
Правила .gitignore объедините с существующими, сохранив нужные исключения.
node_modules и dist не загружайте: они создаются автоматически.
Сделайте Commit & Push, Merge Request и объедините после проверок.

В настройках приложения вашей площадки:

- Git repository: ваш frontend-project, branch master.
- Build: Dockerfile в корне, build context — корень репозитория.
- Internal/container port: **3000**, protocol HTTP.
- Health/readiness path: **/health**.
- Команды build и start уже заданы в Dockerfile — отдельная команда установки не нужна.
- FRONTEND работает в одном контейнере; отдельный Python HTTP-сервер не требуется.

После запуска откройте URL, который показывает сама площадка, и выберите демоверсию.
Успешный echo ok в GitLab CI сам по себе не запускает контейнер и не создаёт URL.
Если панель не собирает Docker автоматически, нужен запуск на ВМ или отдельное задание деплоя.
Без данных о вашей панели нельзя указать точное название её кнопки публикации.

## Если Docker запускаете вручную на ВМ

В терминале ВМ, из каталога с Dockerfile:

```bash
docker build -t sobralis-frontend .
docker run -d --name sobralis-frontend-v2 --restart unless-stopped -p 3000:3000 sobralis-frontend
```

Для первого build нужен доступ к registry.spirit.t-education.com и выданному образу.
Если доступ к нему отсутствует и правила хакатона разрешают официальный Node-образ:

```bash
docker build --build-arg DEPS_IMAGE=node:22-bookworm-slim -t sobralis-frontend .
```

Этот вариант с тем же Dockerfile проверен сборкой и запуском.
Приватный DEPS_IMAGE площадки из этой среды не проверялся.
Ключи registry не вставляйте в Dockerfile или чат; используйте выданный площадкой способ входа.

Проверка на ВМ:

```bash
curl -f http://localhost:3000/health
docker logs --tail 50 sobralis-frontend-v2
```

В браузере: http://PUBLIC_IP:3000, где PUBLIC_IP — публичный адрес ВМ.
Порт TCP 3000 должен быть разрешён в сетевых правилах площадки для посетителей.
Не отключайте firewall целиком. Перед настоящим входом по паролю настройте HTTPS
через обратный прокси/площадку; HTTP здесь подходит для показа демоверсии.
Если имя контейнера или порт уже заняты, сначала проверьте существующий сервис;
не удаляйте чужие контейнеры ради этой инструкции.

## Backend

По умолчанию config.js использует тот же origin, а не localhost компьютера посетителя.
Демоверсия работает сразу, даже если backend не подключён.
Реальные вход и записи требуют согласованного API, описанного в README.md.

Для проксирования /api задайте контейнеру runtime-переменную BACKEND_URL,
например http://backend:3001 **только если** этот адрес действительно доступен
в вашей Docker-сети. Само имя backend автоматически не создаётся.
При ручном запуске добавьте перед именем образа `-e BACKEND_URL=ВАШ_АДРЕС_BACKEND`.
Frontend будет передавать /api на этот сервер, включая cookie сессии.
Без BACKEND_URL запросы /api возвращают понятную ошибку 503.
Не указывайте в BACKEND_URL адрес с логином/паролем.

Альтернатива — публичный HTTPS backend прямо в frontend/config.js.
Тогда требуется корректный CORS и cookie-настройки backend.
API_BASE_URL при npm run build также меняет публичный адрес API в dist/config.js,
но ваш текущий Dockerfile не объявляет ARG API_BASE_URL: обычная runtime-переменная
не изменяет уже собранные JS-файлы. Для текущего Dockerfile проще использовать BACKEND_URL.
Ни логины, ни пароли, ни почтовые ключи не помещайте в config.js — это публичный файл.

## Локальная проверка без Docker

```bash
npm ci
npm run build
npm test
npm run serve
```

Откройте http://localhost:3000. HOST по умолчанию 0.0.0.0, PORT — 3000.
Сервер выдаёт только dist, остальные файлы репозитория извне недоступны.
