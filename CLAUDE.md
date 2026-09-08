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
app/auth.py            Telegram initData check, get_current_tutor
app/config.py          Settings (pydantic-settings, .env)
app/database.py        async engine, session factory, get_session, Base
app/models.py          Tutor, Student, ScheduleSlot, Lesson, Payment, ParentInvite
app/schemas.py         pydantic request/response models
app/routers/           students.py, lessons.py, payments.py
app/services/balance.py balance calculation
app/services/invites.py parent invite issue / redeem
app/services/lessons.py local date ranges, ownership-checked status changes
app/services/schedule.py weekly slots -> lessons, without duplicates
app/services/tutors.py  tutor lookup / registration (shared by API and bot)
bot/main.py            bot entrypoint (long polling)
bot/handlers/          start.py (both roles), tutor.py, parent.py
bot/formatting.py      russian money / dates / plurals
bot/middlewares.py     one DB session per update
miniapp/index.html     Telegram Mini App: one file, no build step
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
   This holds for generated lessons too.
3. **Auth is Telegram `initData`.** Every endpoint depends on
   `get_current_tutor` (`app/auth.py`), which reads `Authorization: tma <initData>`,
   checks the HMAC signature against the bot token, refuses anything older than
   24 hours and resolves (or registers) the tutor. No endpoint takes a `tutor_id`.
   With `DEBUG=true` an `X-Debug-Tutor-Id` header stands in for it locally; it is
   ignored in production.
4. Endpoints: CRUD for students / lessons / payments (always scoped to the
   authenticated tutor), `GET /students/{id}/balance`, `GET /tutors/me/summary`,
   `PATCH /lessons/{id}/status`, `POST /lessons/generate`.
5. **The bot never calls the API.** It shares the database and goes through
   `app/services/*` with a session injected by `DbSessionMiddleware`. Keep the
   logic in services and the handlers thin, so tests can skip aiogram entirely.
6. Anything a tutor reaches by `callback_data` must be re-checked for ownership
   server-side — `lesson_id` and `student_id` come from the client.
7. Bot commands: tutor `/start`, `/students`, `/today`, `/invite`;
   parent `/start parent_<token>`, `/balance`. One account can be both roles.
   `/start` also carries a `web_app` button pointing at `MINIAPP_URL`; the
   button is skipped unless that URL is https, which is all Telegram accepts.
8. Tests must cover `balance.py`, the main endpoints, invites, lesson status
   changes, `initData` verification and schedule generation, and must all pass.
9. A student may have recurring `schedule_slots` (weekday 0-6 Monday-first,
   local wall-clock time in `BOT_TIMEZONE`). `POST /lessons/generate` turns them
   into planned lessons N days ahead and never creates a second lesson at a
   minute that already has one.
10. The Mini App is one file, `miniapp/index.html`: vanilla JS, no frameworks,
   no external CSS or fonts, every colour a `--tg-theme-*` variable. FastAPI
   serves it at `/app`, so it shares an origin with the API and needs no CORS.
11. Keep it small. No extra abstractions, layers or features beyond the list above.

## Commands

```bash
.venv/bin/uvicorn app.main:app --reload   # run the API (Mini App on /app)
.venv/bin/python -m bot.main              # run the Telegram bot (needs a token)
.venv/bin/pytest                          # run tests (SQLite)
.venv/bin/alembic upgrade head            # apply migrations (needs Postgres)
docker compose up -d                      # postgres + redis
```

See `README.md` for how to set the bot up.
