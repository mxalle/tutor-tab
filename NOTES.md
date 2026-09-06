# NOTES

Рабочие заметки по автономной сессии. Что сделано, какие решения принял сам,
что осталось.

## Что сделано

Шесть коммитов, каждый запушен в `origin/main` сразу после завершения шага:

| Коммит | Содержание |
|---|---|
| `chore: project skeleton…` | `app/config.py`, `app/database.py`, `app/main.py` + `/health`, `pytest.ini`, `CLAUDE.md`, `.env.example` |
| `feat: ORM models and initial Alembic migration` | `app/models.py`, `alembic/` + `0001_initial` |
| `feat: balance service` | `app/services/balance.py` |
| `feat: schemas and CRUD routers…` | `app/schemas.py`, `app/routers/{students,lessons,payments}.py` |
| `test: cover balance service and API endpoints` | `tests/` — 34 теста |
| `chore: docker-compose…` | `docker-compose.yml` (postgres 16, redis 7) |

Эндпоинты: CRUD по students / lessons / payments (все в рамках `tutor_id`),
`GET /students/{id}/balance`, `GET /tutors/{id}/summary`,
`PATCH /lessons/{id}/status`, `GET /health`.

### Проверено

- **34 теста проходят** (`.venv/bin/pytest`), SQLite in-memory, докер не нужен.
- **Миграция проверена на живом PostgreSQL 16**: `alembic upgrade head` применяется,
  `alembic check` не видит расхождений между моделями и миграцией,
  `downgrade base` → `upgrade head` отрабатывает без ошибок.
- **End-to-end прогон против настоящего Postgres** (поднял compose, применил
  миграцию, поднял uvicorn, погонял по HTTP): срез цены, баланс, summary,
  изоляция между репетиторами, каскадное удаление, кириллица в комментарии,
  `timestamptz` — всё сходится. Тестовый стек потом погашен, `docker compose down -v`.

## Решения, которые принял сам

### 1. Знак баланса (главное)

В задании противоречие: формула — «сумма занятий минус сумма оплат», но тут же
сказано «отрицательный баланс = долг». По формуле проведённое и неоплаченное
занятие даёт **плюс**, а не минус.

**Взял формулу буквально**, как более конкретную и повторённую дважды инструкцию:

```
balance = sum(price_snapshot по done) - sum(payments.amount)
```

То есть **положительный баланс = долг ученика**, отрицательный = переплата/аванс.
Это задокументировано в докстринге `app/services/balance.py`, в `CLAUDE.md` и
закреплено тестами.

Если нужна была вторая трактовка (аванс, отрицательный = долг) — меняется
**одна строка** в `_build()` в `app/services/balance.py` (поменять местами
`lessons - payments`) плюс знак фильтра в `total_debt` в `app/routers/students.py`.
Тесты покажут все места, где это важно.

### 2. Остальное

- **`GET /tutors/{id}/summary` лежит в `app/routers/students.py`** — в заданной
  структуре нет `routers/tutors.py`, а плодить файл ради одного эндпоинта не стал
  (правило 6). Роутер students объявлен без `prefix`, пути прописаны целиком.
- **Эндпоинтов для создания репетиторов нет** — их не было в списке. Сейчас
  `tutors` заполняется напрямую в БД; появится вместе с онбордингом бота.
  Из-за этого `POST /students` отдаёт 404 `Tutor not found`, если репетитора нет.
- **«Доход за месяц» считаю по оплатам** (`payments.paid_at` в текущем
  календарном месяце), а не по проведённым занятиям — это фактически полученные
  деньги. Границы месяца — UTC, полуинтервал `[начало, начало следующего)`.
- **`paid_at` необязателен** при создании оплаты, по умолчанию — «сейчас» (UTC).
- **`DELETE /students/{id}` — жёсткое удаление** с каскадом на занятия и оплаты.
  Мягкий вариант, сохраняющий историю, — `PATCH` с `is_active: false`.
- **`price_snapshot` нельзя изменить** через `PATCH /lessons/{id}` — это история.
  Смена цены ученика влияет только на занятия, созданные после неё (есть тест).
- **Хелпер проверки владельца продублирован** в трёх роутерах (по 6 строк)
  вместо общего `deps.py` — правило 6 про лишние слои. Роутеры самодостаточны.
- **Фильтры в списках**: `students?is_active=`, `lessons?student_id=&status=`,
  `payments?student_id=`. Без них поля `is_active` и `status` бесполезны на
  клиенте. Пагинации нет — не просили.
- **`Numeric` нормализую до 2 знаков** в `balance.py`: SQLite отдаёт `SUM` как
  float, Postgres — как `Decimal`. Приведение через `Decimal(str(v))` убирает
  расхождение. Pydantic v2 сериализует `Decimal` в JSON **строкой**
  (`"1500.00"`), не числом — это видно в тестах.
- **Статус занятия — нативный enum `lesson_status`** в Postgres, в SQLite
  разворачивается в `VARCHAR + CHECK`.

## Отклонения от условий задачи

- **В `.venv` стоит Python 3.13.1, а не 3.12.** Ничего не трогал, всё работает.
- **Доставил в окружение** `pytest`, `pytest-asyncio`, `aiosqlite`, `greenlet`
  (последний нужен SQLAlchemy для async) — их не было. `requirements.txt`
  перегенерирован через `pip freeze`.
- **Порты 5432 и 6379 на этой машине уже заняты** контейнерами соседнего проекта
  (`crypto-spread-db-1`, `crypto-spread-redis-1`). `docker compose up -d` в
  TutorTab **упадёт**, пока тот проект поднят. Поэтому порты в
  `docker-compose.yml` вынесены в переменные:

  ```bash
  POSTGRES_PORT=5433 REDIS_PORT=6380 docker compose up -d
  # и соответственно DATABASE_URL=...@localhost:5433/tutortab
  ```

  Значения по умолчанию оставил стандартными (5432/6379).

## Что осталось

- **Аутентификация.** Сейчас `tutor_id` приходит query-параметром и никак не
  проверяется — любой может подставить чужой id. `TODO` висит в каждом роутере.
  Заменить на валидацию Telegram WebApp `initData` (HMAC по токену бота) и
  резолвить репетитора из неё.
- **Регистрация репетитора** — эндпоинт или онбординг в боте.
- **Напоминания родителям** в `parent_chat_id` — ради них поле и заведено.
  `aiogram` уже в зависимостях, но бот не написан.
- **Redis поднимается в compose, но приложением не используется** — заведён на
  будущее (очередь напоминаний / кэш summary).
- Пагинация и сортировка в списках, если учеников станет много.
- CI, который гонял бы `pytest` и `alembic check` на пуше.
- `.env` не создавал — есть только `.env.example` (`.env` в `.gitignore`).
