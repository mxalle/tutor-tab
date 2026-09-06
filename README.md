# TutorTab

Сервис для частных репетиторов: учёт учеников, занятий и оплат. Состоит из
двух процессов поверх одной базы — HTTP API на FastAPI и Telegram-бот на
aiogram 3. Бот ходит в базу напрямую через SQLAlchemy, а не через API.

## Стек

- FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, pydantic-settings
- aiogram 3 — Telegram-бот
- PostgreSQL 16 + Redis 7 через `docker-compose.yml`
- pytest + pytest-asyncio; тесты идут на SQLite, Docker для них не нужен

## Быстрый старт

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # и заполнить TELEGRAM_BOT_TOKEN
docker compose up -d          # postgres + redis
.venv/bin/alembic upgrade head
```

## Запуск API

```bash
.venv/bin/uvicorn app.main:app --reload
```

Документация — на `http://localhost:8000/docs`, проверка живости —
`GET /health`.

## Запуск Telegram-бота

Бот — **отдельный процесс**, API для него поднимать не нужно, но база и
применённые миграции нужны.

```bash
.venv/bin/python -m bot.main
```

Перед первым запуском:

1. Получите токен у [@BotFather](https://t.me/BotFather).
2. Положите его в `.env`:

   ```
   TELEGRAM_BOT_TOKEN=123456:AA...
   BOT_TIMEZONE=Europe/Moscow
   ```

   `BOT_TIMEZONE` — часовой пояс, в котором бот понимает «сегодня» и рисует
   даты. Сами занятия всегда хранятся в UTC. По умолчанию `Europe/Moscow`.
3. Примените миграции: `.venv/bin/alembic upgrade head`.

Без токена процесс не стартует и говорит об этом в лог. Работает на long
polling, вебхук не нужен — то есть публичный адрес не требуется.

### Команды репетитора

| Команда | Что делает |
|---|---|
| `/start` | Регистрирует по `tg_id` (имя берётся из профиля Telegram) и здоровается |
| `/students` | Список активных учеников с балансом и суммарным долгом |
| `/today` | Занятия на сегодня, у каждого кнопки «Провёл» и «Отменил» |
| `/invite` | Список учеников; по выбору выдаёт ссылку для родителя |

Нажатие «Провёл» / «Отменил» меняет статус занятия и тут же перерисовывает
сообщение. Обе кнопки остаются на месте, так что ошибочный тап можно
исправить обратно.

### Команды родителя

| Команда | Что делает |
|---|---|
| `/start parent_<token>` | Привязывает чат к ученику по одноразовой ссылке |
| `/balance` | Баланс ребёнка и число проведённых занятий за текущий месяц |

Ссылку выдаёт репетитор командой `/invite`, выглядит она так:

```
https://t.me/<имя_бота>?start=parent_<token>
```

Ссылка одноразовая и живёт 7 дней. Когда родитель её открывает, его `chat_id`
записывается в `students.parent_chat_id`, а приглашение гасится.

Один и тот же аккаунт Telegram может быть и репетитором, и родителем — роль
определяется командой, а не пользователем.

## Тесты

```bash
.venv/bin/pytest
```

72 теста на in-memory SQLite, ни Postgres, ни токен бота не нужны.

## Миграции

```bash
.venv/bin/alembic upgrade head      # применить
.venv/bin/alembic downgrade -1      # откатить последнюю
.venv/bin/alembic check             # сверить модели с базой
```

## Структура

```
app/main.py             FastAPI, lifespan, /health
app/config.py           настройки (pydantic-settings, .env)
app/database.py         async engine, session_factory, Base
app/models.py           Tutor, Student, Lesson, Payment, ParentInvite
app/routers/            students.py, lessons.py, payments.py
app/services/balance.py расчёт баланса
app/services/invites.py выдача и погашение родительских приглашений
app/services/lessons.py диапазоны дат и смена статуса занятия
bot/main.py             точка входа бота, polling
bot/handlers/           start.py, tutor.py, parent.py
bot/formatting.py       деньги, даты и склонения по-русски
bot/middlewares.py      сессия БД на каждый апдейт
alembic/                миграции
tests/                  pytest
```

Подробности принятых решений и известные ограничения — в [NOTES.md](NOTES.md),
правила работы с кодом — в [CLAUDE.md](CLAUDE.md).
