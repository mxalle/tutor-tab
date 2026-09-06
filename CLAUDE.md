# TutorTab

Backend for a Telegram service that helps private tutors track lessons and payments.
A tutor registers students, marks lessons as done and records payments. A student may
have a parent attached (`parent_chat_id`) — the bot will send reminders there later.

## Stack

- FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, pydantic-settings
- aiogram 3 for the Telegram bot, a separate process on the same database
- PostgreSQL 16 + Redis 7 via `docker-compose.yml`
- pytest + pytest-asyncio + httpx; tests run on SQLite (aiosqlite), no Docker needed

## Layout

```
app/main.py            FastAPI app, lifespan, /health
app/config.py          Settings (pydantic-settings, .env)
app/database.py        async engine, session factory, get_session, Base
app/models.py          Tutor, Student, Lesson, Payment, ParentInvite
app/schemas.py         pydantic request/response models
app/routers/           students.py, lessons.py, payments.py
app/services/balance.py balance calculation
app/services/invites.py parent invite issue / redeem
app/services/lessons.py local date ranges, ownership-checked status changes
bot/main.py            bot entrypoint (long polling)
bot/handlers/          start.py (both roles), tutor.py, parent.py
bot/formatting.py      russian money / dates / plurals
bot/middlewares.py     one DB session per update
alembic/               migrations
tests/                 pytest suite
```

## Rules

1. **Balance is never stored.** It is computed in `app/services/balance.py` as
   `sum(price_snapshot of lessons with status=done) - sum(payments.amount)`.
   With this formula a **positive** balance means the student owes money (debt).
   See `NOTES.md` for why this sign convention was chosen.
   The bot flips the sign for humans in `bot/formatting.py:format_balance` —
   a debt reads as `−3 000 ₽`. Flip it in one place only, never in both.
2. When a lesson is created, the student's current `price` is copied into
   `lessons.price_snapshot`, so later price changes do not rewrite history.
3. **No auth yet.** Every endpoint takes `tutor_id` as a query parameter.
   Each router carries a `TODO` about validating Telegram `initData` instead.
4. Endpoints: CRUD for students / lessons / payments (always scoped by `tutor_id`),
   `GET /students/{id}/balance`, `GET /tutors/{id}/summary`, `PATCH /lessons/{id}/status`.
5. **The bot never calls the API.** It shares the database and goes through
   `app/services/*` with a session injected by `DbSessionMiddleware`. Keep the
   logic in services and the handlers thin, so tests can skip aiogram entirely.
6. Anything a tutor reaches by `callback_data` must be re-checked for ownership
   server-side — `lesson_id` and `student_id` come from the client.
7. Bot commands: tutor `/start`, `/students`, `/today`, `/invite`;
   parent `/start parent_<token>`, `/balance`. One account can be both roles.
8. Tests must cover `balance.py`, the main endpoints, invites and lesson status
   changes, and must all pass.
9. Keep it small. No extra abstractions, layers or features beyond the list above.

## Commands

```bash
.venv/bin/uvicorn app.main:app --reload   # run the API
.venv/bin/python -m bot.main              # run the Telegram bot (needs a token)
.venv/bin/pytest                          # run tests (SQLite)
.venv/bin/alembic upgrade head            # apply migrations (needs Postgres)
docker compose up -d                      # postgres + redis
```

See `README.md` for how to set the bot up.
