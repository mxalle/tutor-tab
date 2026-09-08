from datetime import datetime, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Student, Tutor
from tests.initdata import auth, make_init_data

STARTS_AT = "2026-09-06T12:00:00+00:00"


def money(value: str | float) -> Decimal:
    return Decimal(str(value))


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- students ---------------------------------------------------------------


async def test_student_crud(client: AsyncClient, tutor: Tutor) -> None:
    created = await client.post(
        "/students",
        headers=auth(tutor),
        json={"name": "Petya", "price": "1500.00", "parent_chat_id": 4242},
    )
    assert created.status_code == 201
    student = created.json()
    assert student["name"] == "Petya"
    assert money(student["price"]) == Decimal("1500.00")
    assert student["parent_chat_id"] == 4242
    assert student["is_active"] is True

    listed = await client.get("/students", headers=auth(tutor))
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()] == [student["id"]]

    fetched = await client.get(
        f"/students/{student['id']}", headers=auth(tutor)
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == student["id"]

    patched = await client.patch(
        f"/students/{student['id']}",
        headers=auth(tutor),
        json={"price": "2000.00", "is_active": False},
    )
    assert patched.status_code == 200
    assert money(patched.json()["price"]) == Decimal("2000.00")
    assert patched.json()["is_active"] is False
    assert patched.json()["name"] == "Petya"

    deleted = await client.delete(
        f"/students/{student['id']}", headers=auth(tutor)
    )
    assert deleted.status_code == 204

    gone = await client.get(
        f"/students/{student['id']}", headers=auth(tutor)
    )
    assert gone.status_code == 404


async def test_unknown_telegram_user_is_registered_on_first_call(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A tutor who opens the Mini App without ever running /start is created."""
    headers = {"Authorization": f"tma {make_init_data(31337, name='Nina Petrova')}"}

    response = await client.post(
        "/students", headers=headers, json={"name": "X", "price": "100.00"}
    )

    assert response.status_code == 201
    tutor = (
        await session.execute(select(Tutor).where(Tutor.tg_id == 31337))
    ).scalar_one()
    assert tutor.name == "Nina Petrova"
    assert response.json()["tutor_id"] == tutor.id


async def test_student_of_another_tutor_is_not_visible(
    client: AsyncClient, student: Student, other_tutor: Tutor
) -> None:
    fetched = await client.get(
        f"/students/{student.id}", headers=auth(other_tutor)
    )
    assert fetched.status_code == 404

    listed = await client.get("/students", headers=auth(other_tutor))
    assert listed.json() == []

    patched = await client.patch(
        f"/students/{student.id}",
        headers=auth(other_tutor),
        json={"name": "hacked"},
    )
    assert patched.status_code == 404


async def test_list_students_filtered_by_is_active(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    await client.post(
        "/students",
        headers=auth(tutor),
        json={"name": "Left", "price": "900.00", "is_active": False},
    )

    active = await client.get(
        "/students", params={"is_active": True}, headers=auth(tutor)
    )
    inactive = await client.get(
        "/students", params={"is_active": False}, headers=auth(tutor)
    )

    assert [s["name"] for s in active.json()] == [student.name]
    assert [s["name"] for s in inactive.json()] == ["Left"]


async def test_student_price_must_not_be_negative(
    client: AsyncClient, tutor: Tutor
) -> None:
    response = await client.post(
        "/students",
        headers=auth(tutor),
        json={"name": "Petya", "price": "-1.00"},
    )

    assert response.status_code == 422


# --- lessons ----------------------------------------------------------------


async def test_lesson_create_copies_current_student_price(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    created = await client.post(
        "/lessons",
        headers=auth(tutor),
        json={"student_id": student.id, "starts_at": STARTS_AT},
    )
    assert created.status_code == 201
    lesson = created.json()
    assert money(lesson["price_snapshot"]) == Decimal("1500.00")
    assert lesson["status"] == "planned"

    # raising the price must not touch lessons that already exist
    await client.patch(
        f"/students/{student.id}",
        headers=auth(tutor),
        json={"price": "2000.00"},
    )
    old = await client.get(f"/lessons/{lesson['id']}", headers=auth(tutor))
    assert money(old.json()["price_snapshot"]) == Decimal("1500.00")

    # a new lesson picks up the new price
    newer = await client.post(
        "/lessons",
        headers=auth(tutor),
        json={"student_id": student.id, "starts_at": STARTS_AT},
    )
    assert money(newer.json()["price_snapshot"]) == Decimal("2000.00")


async def test_lesson_crud_and_status_patch(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    lesson = (
        await client.post(
            "/lessons",
            headers=auth(tutor),
            json={"student_id": student.id, "starts_at": STARTS_AT},
        )
    ).json()

    listed = await client.get("/lessons", headers=auth(tutor))
    assert [item["id"] for item in listed.json()] == [lesson["id"]]

    status_patched = await client.patch(
        f"/lessons/{lesson['id']}/status",
        headers=auth(tutor),
        json={"status": "done"},
    )
    assert status_patched.status_code == 200
    assert status_patched.json()["status"] == "done"

    patched = await client.patch(
        f"/lessons/{lesson['id']}",
        headers=auth(tutor),
        json={"status": "cancelled"},
    )
    assert patched.json()["status"] == "cancelled"

    filtered = await client.get(
        "/lessons", params={"status": "done"}, headers=auth(tutor)
    )
    assert filtered.json() == []

    deleted = await client.delete(
        f"/lessons/{lesson['id']}", headers=auth(tutor)
    )
    assert deleted.status_code == 204
    assert (
        await client.get(f"/lessons/{lesson['id']}", headers=auth(tutor))
    ).status_code == 404


async def test_lesson_status_must_be_valid(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    lesson = (
        await client.post(
            "/lessons",
            headers=auth(tutor),
            json={"student_id": student.id, "starts_at": STARTS_AT},
        )
    ).json()

    response = await client.patch(
        f"/lessons/{lesson['id']}/status",
        headers=auth(tutor),
        json={"status": "finished"},
    )

    assert response.status_code == 422


async def test_cannot_add_lesson_to_another_tutors_student(
    client: AsyncClient, student: Student, other_tutor: Tutor
) -> None:
    response = await client.post(
        "/lessons",
        headers=auth(other_tutor),
        json={"student_id": student.id, "starts_at": STARTS_AT},
    )

    assert response.status_code == 404


# --- payments ---------------------------------------------------------------


async def test_payment_crud(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    created = await client.post(
        "/payments",
        headers=auth(tutor),
        json={
            "student_id": student.id,
            "amount": "1000.00",
            "paid_at": STARTS_AT,
            "comment": "cash",
        },
    )
    assert created.status_code == 201
    payment = created.json()
    assert money(payment["amount"]) == Decimal("1000.00")
    assert payment["comment"] == "cash"

    listed = await client.get(
        "/payments", params={"student_id": student.id}, headers=auth(tutor)
    )
    assert [p["id"] for p in listed.json()] == [payment["id"]]

    patched = await client.patch(
        f"/payments/{payment['id']}",
        headers=auth(tutor),
        json={"amount": "1200.00"},
    )
    assert money(patched.json()["amount"]) == Decimal("1200.00")
    assert patched.json()["comment"] == "cash"

    deleted = await client.delete(
        f"/payments/{payment['id']}", headers=auth(tutor)
    )
    assert deleted.status_code == 204
    assert (
        await client.get(f"/payments/{payment['id']}", headers=auth(tutor))
    ).status_code == 404


async def test_payment_paid_at_defaults_to_now(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    before = datetime.now(timezone.utc).replace(tzinfo=None)

    created = await client.post(
        "/payments",
        headers=auth(tutor),
        json={"student_id": student.id, "amount": "500.00"},
    )

    assert created.status_code == 201
    paid_at = datetime.fromisoformat(created.json()["paid_at"]).replace(tzinfo=None)
    assert paid_at >= before


async def test_payment_amount_must_be_positive(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    response = await client.post(
        "/payments",
        headers=auth(tutor),
        json={"student_id": student.id, "amount": "0"},
    )

    assert response.status_code == 422


async def test_payments_of_another_tutor_are_hidden(
    client: AsyncClient, tutor: Tutor, student: Student, other_tutor: Tutor
) -> None:
    payment = (
        await client.post(
            "/payments",
            headers=auth(tutor),
            json={"student_id": student.id, "amount": "100.00"},
        )
    ).json()

    assert (
        await client.get(
            f"/payments/{payment['id']}", headers=auth(other_tutor)
        )
    ).status_code == 404
    assert (await client.get("/payments", headers=auth(other_tutor))).json() == []


# --- balance and summary ----------------------------------------------------


async def test_student_balance_endpoint(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    zero = await client.get(
        f"/students/{student.id}/balance", headers=auth(tutor)
    )
    assert zero.status_code == 200
    assert money(zero.json()["balance"]) == Decimal("0.00")

    for _ in range(2):
        lesson = (
            await client.post(
                "/lessons",
                headers=auth(tutor),
                json={"student_id": student.id, "starts_at": STARTS_AT},
            )
        ).json()
        await client.patch(
            f"/lessons/{lesson['id']}/status",
            headers=auth(tutor),
            json={"status": "done"},
        )
    await client.post(
        "/payments",
        headers=auth(tutor),
        json={"student_id": student.id, "amount": "2000.00"},
    )

    balance = (
        await client.get(
            f"/students/{student.id}/balance", headers=auth(tutor)
        )
    ).json()

    assert money(balance["lessons_total"]) == Decimal("3000.00")
    assert money(balance["payments_total"]) == Decimal("2000.00")
    assert money(balance["balance"]) == Decimal("1000.00")


async def test_balance_of_another_tutors_student_is_404(
    client: AsyncClient, student: Student, other_tutor: Tutor
) -> None:
    response = await client.get(
        f"/students/{student.id}/balance", headers=auth(other_tutor)
    )

    assert response.status_code == 404


async def test_tutor_summary(
    client: AsyncClient, session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    payer = Student(tutor_id=tutor.id, name="Masha", price=Decimal("1000.00"))
    session.add(payer)
    await session.commit()
    await session.refresh(payer)

    # Petya: one lesson held, nothing paid -> owes 1500
    lesson = (
        await client.post(
            "/lessons",
            headers=auth(tutor),
            json={"student_id": student.id, "starts_at": STARTS_AT},
        )
    ).json()
    await client.patch(
        f"/lessons/{lesson['id']}/status",
        headers=auth(tutor),
        json={"status": "done"},
    )
    # Masha: paid 1000 in advance, no lessons held -> -1000, not a debt
    await client.post(
        "/payments",
        headers=auth(tutor),
        json={"student_id": payer.id, "amount": "1000.00"},
    )

    summary = (await client.get("/tutors/me/summary", headers=auth(tutor))).json()

    assert summary["tutor_id"] == tutor.id
    rows = {row["name"]: row for row in summary["students"]}
    assert set(rows) == {"Petya", "Masha"}
    assert money(rows["Petya"]["balance"]) == Decimal("1500.00")
    assert money(rows["Masha"]["balance"]) == Decimal("-1000.00")
    # only positive balances add up to the debt
    assert money(summary["total_debt"]) == Decimal("1500.00")
    # income counts payments received this month
    assert money(summary["month_income"]) == Decimal("1000.00")


async def test_summary_for_tutor_without_students(
    client: AsyncClient, other_tutor: Tutor
) -> None:
    summary = (
        await client.get("/tutors/me/summary", headers=auth(other_tutor))
    ).json()

    assert summary["students"] == []
    assert money(summary["total_debt"]) == Decimal("0.00")
    assert money(summary["month_income"]) == Decimal("0.00")


async def test_summary_requires_a_signed_request(client: AsyncClient) -> None:
    assert (await client.get("/tutors/me/summary")).status_code == 401


async def test_deleting_student_removes_lessons_and_payments(
    client: AsyncClient, tutor: Tutor, student: Student
) -> None:
    await client.post(
        "/lessons",
        headers=auth(tutor),
        json={"student_id": student.id, "starts_at": STARTS_AT},
    )
    await client.post(
        "/payments",
        headers=auth(tutor),
        json={"student_id": student.id, "amount": "100.00"},
    )

    assert (
        await client.delete(f"/students/{student.id}", headers=auth(tutor))
    ).status_code == 204

    assert (await client.get("/lessons", headers=auth(tutor))).json() == []
    assert (await client.get("/payments", headers=auth(tutor))).json() == []
