"""Weekly schedule slots and the lessons generated from them."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, ScheduleSlot, Student, Tutor
from app.services.schedule import generate_lessons, slot_moments
from tests.initdata import auth

MSK = ZoneInfo("Europe/Moscow")
# a Monday, so weekday 0 is the first day of the window
MONDAY = date(2026, 9, 7)


async def add_slots(session: AsyncSession, student: Student, *slots: ScheduleSlot):
    student.schedule = list(slots)
    await session.commit()
    await session.refresh(student)
    return student


def slot(weekday: int, hour: int, minute: int = 0, is_active: bool = True):
    return ScheduleSlot(weekday=weekday, time=time(hour, minute), is_active=is_active)


# --- slot_moments -----------------------------------------------------------


def test_slots_repeat_every_week_within_the_window() -> None:
    moments = slot_moments([slot(0, 17)], MSK, MONDAY, days=14)

    assert [m.astimezone(MSK).date() for m in moments] == [
        MONDAY,
        MONDAY + timedelta(days=7),
    ]


def test_local_time_is_converted_to_utc() -> None:
    (moment,) = slot_moments([slot(0, 17, 30)], MSK, MONDAY, days=1)

    # Moscow is UTC+3 all year round
    assert moment == datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)


def test_inactive_slots_are_skipped() -> None:
    assert slot_moments([slot(0, 17, is_active=False)], MSK, MONDAY, days=7) == []


def test_a_slot_survives_a_dst_change_at_the_same_local_time() -> None:
    """Berlin leaves DST on 2026-10-25; 17:00 stays 17:00 for the student."""
    berlin = ZoneInfo("Europe/Berlin")
    moments = slot_moments([slot(6, 17)], berlin, date(2026, 10, 18), days=14)

    assert [m.astimezone(berlin).hour for m in moments] == [17, 17]
    # ...which is a different UTC hour on either side of the switch
    assert [m.hour for m in moments] == [15, 16]


# --- generate_lessons -------------------------------------------------------


async def test_generation_creates_lessons_for_two_weeks(
    session: AsyncSession, student: Student
) -> None:
    await add_slots(session, student, slot(0, 17), slot(3, 10, 30))

    generated = await generate_lessons(session, [student], MSK, days=14, today=MONDAY)

    assert len(generated.created) == 4
    assert generated.skipped == 0
    assert {lesson.status for lesson in generated.created} == {LessonStatus.planned}
    assert {lesson.price_snapshot for lesson in generated.created} == {
        Decimal("1500.00")
    }


async def test_generation_is_idempotent(
    session: AsyncSession, student: Student
) -> None:
    await add_slots(session, student, slot(0, 17))

    first = await generate_lessons(session, [student], MSK, days=14, today=MONDAY)
    second = await generate_lessons(session, [student], MSK, days=14, today=MONDAY)

    assert len(first.created) == 2
    assert second.created == []
    assert second.skipped == 2
    total = await session.scalar(
        select(func.count()).select_from(Lesson).where(Lesson.student_id == student.id)
    )
    assert total == 2


async def test_a_cancelled_lesson_is_not_recreated(
    session: AsyncSession, student: Student
) -> None:
    """The slot is taken by a lesson whatever its status — no ghost duplicates."""
    await add_slots(session, student, slot(0, 17))
    await generate_lessons(session, [student], MSK, days=7, today=MONDAY)

    lesson = (
        await session.execute(select(Lesson).where(Lesson.student_id == student.id))
    ).scalar_one()
    lesson.status = LessonStatus.cancelled
    await session.commit()

    again = await generate_lessons(session, [student], MSK, days=7, today=MONDAY)

    assert again.created == []
    assert again.skipped == 1


async def test_a_manual_lesson_at_the_same_minute_blocks_the_slot(
    session: AsyncSession, student: Student
) -> None:
    await add_slots(session, student, slot(0, 17))
    session.add(
        Lesson(
            student_id=student.id,
            starts_at=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
            price_snapshot=Decimal("1500.00"),
        )
    )
    await session.commit()

    generated = await generate_lessons(session, [student], MSK, days=7, today=MONDAY)

    assert generated.created == []
    assert generated.skipped == 1


async def test_a_lesson_at_another_time_does_not_block_the_slot(
    session: AsyncSession, student: Student
) -> None:
    await add_slots(session, student, slot(0, 17))
    session.add(
        Lesson(
            student_id=student.id,
            starts_at=datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc),
            price_snapshot=Decimal("1500.00"),
        )
    )
    await session.commit()

    generated = await generate_lessons(session, [student], MSK, days=7, today=MONDAY)

    assert len(generated.created) == 1


async def test_generation_freezes_the_current_price(
    session: AsyncSession, student: Student
) -> None:
    await add_slots(session, student, slot(0, 17))
    await generate_lessons(session, [student], MSK, days=7, today=MONDAY)

    student.price = Decimal("2000.00")
    await session.commit()
    later = await generate_lessons(
        session, [student], MSK, days=7, today=MONDAY + timedelta(days=7)
    )

    assert [lesson.price_snapshot for lesson in later.created] == [Decimal("2000.00")]


async def test_students_without_slots_generate_nothing(
    session: AsyncSession, student: Student
) -> None:
    generated = await generate_lessons(session, [student], MSK, days=14, today=MONDAY)

    assert generated == ([], 0)


# --- the API ----------------------------------------------------------------


async def test_student_is_created_with_a_schedule(
    client: AsyncClient, tutor: Tutor
) -> None:
    created = await client.post(
        "/students",
        headers=auth(tutor),
        json={
            "name": "Petya",
            "price": "1500.00",
            "schedule": [
                {"weekday": 3, "time": "10:30"},
                {"weekday": 0, "time": "17:00"},
            ],
        },
    )

    assert created.status_code == 201
    # slots come back ordered by weekday, whatever order they were sent in
    assert [(s["weekday"], s["time"]) for s in created.json()["schedule"]] == [
        (0, "17:00:00"),
        (3, "10:30:00"),
    ]

    fetched = await client.get(
        f"/students/{created.json()['id']}", headers=auth(tutor)
    )
    assert len(fetched.json()["schedule"]) == 2


async def test_weekday_must_be_within_the_week(
    client: AsyncClient, tutor: Tutor
) -> None:
    response = await client.post(
        "/students",
        headers=auth(tutor),
        json={
            "name": "Petya",
            "price": "1500.00",
            "schedule": [{"weekday": 7, "time": "17:00"}],
        },
    )

    assert response.status_code == 422


async def test_patch_replaces_the_whole_schedule(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    await client.patch(
        f"/students/{student.id}",
        headers=auth(tutor),
        json={"schedule": [{"weekday": 1, "time": "12:00"}]},
    )

    replaced = await client.patch(
        f"/students/{student.id}",
        headers=auth(tutor),
        json={"schedule": [{"weekday": 5, "time": "09:00"}]},
    )

    assert [(s["weekday"], s["time"]) for s in replaced.json()["schedule"]] == [
        (5, "09:00:00")
    ]


async def test_patch_without_schedule_keeps_it(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    await client.patch(
        f"/students/{student.id}",
        headers=auth(tutor),
        json={"schedule": [{"weekday": 1, "time": "12:00"}]},
    )

    patched = await client.patch(
        f"/students/{student.id}", headers=auth(tutor), json={"price": "1800.00"}
    )

    assert len(patched.json()["schedule"]) == 1


async def test_generate_endpoint_fills_the_calendar(
    client: AsyncClient, tutor: Tutor
) -> None:
    student = (
        await client.post(
            "/students",
            headers=auth(tutor),
            json={
                "name": "Petya",
                "price": "1500.00",
                "schedule": [{"weekday": d, "time": "17:00"} for d in range(7)],
            },
        )
    ).json()

    response = await client.post("/lessons/generate", headers=auth(tutor), json={})

    assert response.status_code == 201
    body = response.json()
    # one slot a day, the default window is 14 days
    assert body["created"] == 14
    assert body["skipped"] == 0
    assert len(body["lessons"]) == 14
    assert {lesson["student_id"] for lesson in body["lessons"]} == {student["id"]}

    again = await client.post("/lessons/generate", headers=auth(tutor), json={})
    assert again.json() == {"created": 0, "skipped": 14, "lessons": []}


async def test_generate_respects_the_days_argument(
    client: AsyncClient, tutor: Tutor
) -> None:
    await client.post(
        "/students",
        headers=auth(tutor),
        json={
            "name": "Petya",
            "price": "1500.00",
            "schedule": [{"weekday": d, "time": "17:00"} for d in range(7)],
        },
    )

    response = await client.post(
        "/lessons/generate", headers=auth(tutor), json={"days": 3}
    )

    assert response.json()["created"] == 3


async def test_generate_window_must_be_sane(client: AsyncClient, tutor: Tutor) -> None:
    assert (
        await client.post("/lessons/generate", headers=auth(tutor), json={"days": 0})
    ).status_code == 422
    assert (
        await client.post("/lessons/generate", headers=auth(tutor), json={"days": 400})
    ).status_code == 422


async def test_generate_skips_archived_students(
    client: AsyncClient, tutor: Tutor
) -> None:
    await client.post(
        "/students",
        headers=auth(tutor),
        json={
            "name": "Left",
            "price": "900.00",
            "is_active": False,
            "schedule": [{"weekday": d, "time": "17:00"} for d in range(7)],
        },
    )

    response = await client.post("/lessons/generate", headers=auth(tutor), json={})

    assert response.json()["created"] == 0


async def test_generate_for_one_student_only(
    client: AsyncClient, tutor: Tutor
) -> None:
    every_day = [{"weekday": d, "time": "17:00"} for d in range(7)]
    first = (
        await client.post(
            "/students",
            headers=auth(tutor),
            json={"name": "Petya", "price": "1500.00", "schedule": every_day},
        )
    ).json()
    await client.post(
        "/students",
        headers=auth(tutor),
        json={"name": "Masha", "price": "1000.00", "schedule": every_day},
    )

    response = await client.post(
        "/lessons/generate",
        headers=auth(tutor),
        json={"days": 7, "student_id": first["id"]},
    )

    assert response.json()["created"] == 7
    assert {lesson["student_id"] for lesson in response.json()["lessons"]} == {
        first["id"]
    }


async def test_cannot_generate_for_another_tutors_student(
    client: AsyncClient, student: Student, other_tutor: Tutor
) -> None:
    response = await client.post(
        "/lessons/generate",
        headers=auth(other_tutor),
        json={"student_id": student.id},
    )

    assert response.status_code == 404


async def test_deleting_a_student_removes_their_slots(
    client: AsyncClient, session: AsyncSession, tutor: Tutor
) -> None:
    student = (
        await client.post(
            "/students",
            headers=auth(tutor),
            json={
                "name": "Petya",
                "price": "1500.00",
                "schedule": [{"weekday": 0, "time": "17:00"}],
            },
        )
    ).json()

    await client.delete(f"/students/{student['id']}", headers=auth(tutor))

    left = (
        await session.execute(
            select(ScheduleSlot).where(ScheduleSlot.student_id == student["id"])
        )
    ).scalars().all()
    assert list(left) == []


# --- lesson list filtered by time -------------------------------------------


async def test_lessons_can_be_filtered_by_a_time_window(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    for hour in (9, 12, 20):
        await client.post(
            "/lessons",
            headers=auth(tutor),
            json={
                "student_id": student.id,
                "starts_at": f"2026-09-07T{hour:02d}:00:00+00:00",
            },
        )

    listed = await client.get(
        "/lessons",
        headers=auth(tutor),
        params={
            "starts_from": "2026-09-07T10:00:00+00:00",
            "starts_to": "2026-09-07T20:00:00+00:00",
        },
    )

    assert [lesson["starts_at"][11:16] for lesson in listed.json()] == ["12:00"]


async def test_a_window_given_in_another_offset_is_understood(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    await client.post(
        "/lessons",
        headers=auth(tutor),
        json={"student_id": student.id, "starts_at": "2026-09-07T21:00:00+00:00"},
    )

    # midnight to midnight in Moscow: the lesson falls on the 8th there
    listed = await client.get(
        "/lessons",
        headers=auth(tutor),
        params={
            "starts_from": "2026-09-08T00:00:00+03:00",
            "starts_to": "2026-09-09T00:00:00+03:00",
        },
    )

    assert len(listed.json()) == 1
