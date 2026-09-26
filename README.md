# Telefoncaller App

Мінімальний self-service застосунок для реєстрації користувача та запуску вихідного дзвінка через n8n/Vapi.

## Що реалізовано

- реєстрація: ім’я, email, пароль, телефон;
- нормалізація й валідація телефону через `phonenumbers`, збереження у E.164;
- Argon2id-хешування паролів;
- серверні сесії в SQLite, `Secure`/`HttpOnly`/`SameSite=Lax` cookie;
- CSRF та Origin-перевірка всіх state-changing запитів;
- rate limit для реєстрації та входу;
- захищена сторінка з рівно однією основною кнопкою **Jetzt anrufen**;
- серверний POST у n8n — URL webhook не потрапляє у браузер;
- SQLite cooldown від повторного/подвійного запуску дзвінка;
- security headers, trusted hosts, ліміт request body;
- `CALLS_ENABLED=false` за замовчуванням: жоден тест не може випадково подзвонити;
- Dockerfile і Compose для Coolify, non-root container, read-only root filesystem, healthcheck.

UI — німецькою, операційна документація — українською.

## Контракт n8n

Застосунок надсилає лише:

```json
{
  "name": "Max Mustermann",
  "email": "max@example.com",
  "phone": "+4915112345678",
  "source": "app"
}
```

Пароль, cookie, IP та внутрішній user ID ніколи не надсилаються.

Підтримані відповіді workflow:

| HTTP | Значення |
|---:|---|
| 202 | дзвінок прийнято |
| 400 | n8n відхилив payload; app повертає безпечний 502 |
| 409 | Vapi-лінія зайнята |
| 422 | поза дозволеним часом дзвінків |
| 404/5xx | n8n/webhook недоступний; app повертає 503 |

## Локальна перевірка

Потрібні Python 3.12 та `uv`.

```bash
uv sync --dev
uv run pytest -q
cp .env.example .env
```

Для локального HTTP змініть у `.env`:

```dotenv
APP_ORIGIN=http://localhost:8000
COOKIE_SECURE=false
CALLS_ENABLED=false
SESSION_SECRET=<щонайменше 32 випадкові символи>
DATABASE_PATH=./data/caller.db
```

Запуск:

```bash
set -a; . ./.env; set +a
uv run uvicorn caller_app.server:app --host 127.0.0.1 --port 8000
```

Відкрити `http://localhost:8000/register`. У безпечному режимі реєстрація та вхід працюють, а кнопка показує, що дзвінки вимкнені.

## Розгортання в Coolify

### 1. Resource

1. Додайте Git repository як **Application → Dockerfile** або використайте `compose.yaml` як Docker Compose resource.
2. Build context: корінь `caller-app`.
3. Container port: `8000`.
4. Healthcheck: `GET /healthz`.
5. Replicas: **1** — SQLite не призначений для кількох одночасних replicas.

### 2. Persistent storage

Створіть volume:

```text
/data
```

Без цього користувачі та сесії зникнуть після recreate контейнера.

### 3. Environment variables

Скопіюйте `.env.example` у Coolify Environment Variables та встановіть:

- `APP_ORIGIN` — точний публічний HTTPS origin без trailing slash;
- `SESSION_SECRET` — випадковий секрет довжиною не менше 32 символів;
- `DATABASE_PATH=/data/caller.db`;
- `COOKIE_SECURE=true`;
- `CALLS_ENABLED=false` для першого deployment;
- `N8N_WEBHOOK_URL` — production Start Call URL;
- `DEFAULT_PHONE_REGION=DE`;
- `CALL_COOLDOWN_SECONDS=60`.

Згенерувати секрет локально:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Не комітьте значення секрету.

### 4. Безпечний staging smoke-test

Поки `CALLS_ENABLED=false`:

1. `GET /healthz` → `200 {"status":"ok"}`;
2. зареєструйте тестовий акаунт;
3. перевірте повторний login;
4. натисніть **Jetzt anrufen**;
5. очікуйте повідомлення `Testmodus: Anrufe sind sicher deaktiviert.`;
6. у n8n не має з’явитися execution, а у Vapi — call.

### 5. Увімкнення реальних дзвінків

Перед `CALLS_ENABLED=true` окремо перевірте production webhook. Останній збережений canary цього workspace повертав:

```text
404 — webhook .../start-call is not registered
```

Тому сам факт `active: true` у workflow ще не є достатнім. Потрібен свіжий canary з невалідним payload, який має завершитися `400` на вузлі `Start Validation Response` і не створити Vapi call. Лише після цього:

```dotenv
CALLS_ENABLED=true
```

Redeploy, зареєструйте окремий дозволений тестовий номер і виконайте один контрольований дзвінок у дозволений час.

## Backup SQLite

Перед оновленням використовуйте SQLite online backup, а не копію активного WAL-файлу навмання:

```bash
python3 - <<'PY'
import sqlite3
src = sqlite3.connect('/data/caller.db')
dst = sqlite3.connect('/data/caller-backup.db')
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
```

Зберігайте backup поза контейнером/volume і перевірте хоча б одне відновлення перед production.

## Команди перевірки

```bash
uv run pytest -q
uv run pytest --cov=caller_app --cov-report=term-missing
uv build
```

Docker/Compose:

```bash
docker build -t telefoncaller-app:local .
docker run --rm -p 8000:8000 \
  -e APP_ORIGIN=http://localhost:8000 \
  -e COOKIE_SECURE=false \
  -e CALLS_ENABLED=false \
  -e SESSION_SECRET='<32+ random characters>' \
  -v telefoncaller-data:/data \
  telefoncaller-app:local
```
