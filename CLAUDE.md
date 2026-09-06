# TutorTab

Backend for a Telegram service that helps private tutors track lessons and payments.
A tutor registers students, marks lessons as done and records payments. A student may
have a parent attached (`parent_chat_id`) — the bot will send reminders there later.

## Stack

- FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, pydantic-settings
- PostgreSQL 16 + Redis 7 via `docker-compose.yml`
- pytest + pytest-asyncio + httpx; tests run on SQLite (aiosqlite), no Docker needed

## Layout

```
app/main.py            FastAPI app, lifespan, /health
app/config.py          Settings (pydantic-settings, .env)
app/database.py        async engine, session factory, get_session, Base
app/models.py          Tutor, Student, Lesson, Payment
app/schemas.py         pydantic request/response models
app/routers/           students.py, lessons.py, payments.py
app/services/balance.py balance calculation
alembic/               migrations
tests/                 pytest suite
```

## Rules

1. **Balance is never stored.** It is computed in `app/services/balance.py` as
   `sum(price_snapshot of lessons with status=done) - sum(payments.amount)`.
   With this formula a **positive** balance means the student owes money (debt).
   See `NOTES.md` for why this sign convention was chosen.
2. When a lesson is created, the student's current `price` is copied into
   `lessons.price_snapshot`, so later price changes do not rewrite history.
3. **No auth yet.** Every endpoint takes `tutor_id` as a query parameter.
   Each router carries a `TODO` about validating Telegram `initData` instead.
4. Endpoints: CRUD for students / lessons / payments (always scoped by `tutor_id`),
   `GET /students/{id}/balance`, `GET /tutors/{id}/summary`, `PATCH /lessons/{id}/status`.
5. Tests must cover `balance.py` and the main endpoints, and must all pass.
6. Keep it small. No extra abstractions, layers or features beyond the list above.

## Commands

```bash
.venv/bin/uvicorn app.main:app --reload   # run the API
.venv/bin/pytest                          # run tests (SQLite)
.venv/bin/alembic upgrade head            # apply migrations (needs Postgres)
docker compose up -d                      # postgres + redis
```
