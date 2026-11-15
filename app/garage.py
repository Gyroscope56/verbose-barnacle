"""Transactional garage operations, shared by the CLI and the UNO Q."""

import argparse
from dataclasses import dataclass

if __package__:
    from .lakebase import connect
else:
    from lakebase import connect


@dataclass(frozen=True)
class GarageResult:
    status: str
    message: str


def fetch_open_session(cur, license_plate):
    cur.execute(
        """
        SELECT has_entrance_ticket, time_in
        FROM g_sessions
        WHERE license_plate = %s
        FOR UPDATE
        """,
        (license_plate,),
    )
    return cur.fetchone()


def check(license_plate, *, connection=connect):
    with connection() as conn, conn.cursor() as cur:
        row = fetch_open_session(cur, license_plate)
    if row is None:
        return GarageResult("unbooked", "No open booking. Entry requires a booking.")
    has_ticket, time_in = row
    if time_in is not None:
        return GarageResult("inside", f"Inside since {time_in}.")
    if has_ticket:
        return GarageResult("booked", "Booked and outside. May enter.")
    return GarageResult("denied", "No entry permission.")


def book(license_plate, *, connection=connect):
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO g_sessions (license_plate, has_entrance_ticket, time_in, time_out)
            VALUES (%s, TRUE, NULL, NULL)
            ON CONFLICT (license_plate) DO NOTHING
            RETURNING license_plate
            """,
            (license_plate,),
        )
        if cur.fetchone() is None:
            raise ValueError("Already has an open session.")
    return GarageResult("booked", "Booked. May enter.")


def enter(license_plate, *, connection=connect):
    with connection() as conn, conn.cursor() as cur:
        row = fetch_open_session(cur, license_plate)
        if row is None:
            raise ValueError("Entry requires an open booking.")
        has_ticket, time_in = row
        if time_in is not None:
            raise ValueError("Already inside.")
        if not has_ticket:
            raise ValueError("No entry permission.")
        cur.execute(
            """
            UPDATE g_sessions
            SET has_entrance_ticket = FALSE, time_in = NOW()
            WHERE license_plate = %s RETURNING time_in
            """,
            (license_plate,),
        )
        (time_in,) = cur.fetchone()
    return GarageResult("inside", f"Entered at {time_in}.")


def exit_garage(license_plate, *, connection=connect):
    with connection() as conn, conn.cursor() as cur:
        row = fetch_open_session(cur, license_plate)
        if row is None:
            raise ValueError("No open session.")
        if row[1] is None:
            raise ValueError("Vehicle never entered. Cancel the booking instead.")

        cur.execute(
            "UPDATE g_sessions SET time_out = NOW() WHERE license_plate = %s",
            (license_plate,),
        )
        cur.execute(
            """
            INSERT INTO garage_visit_history
                (license_plate, has_entrance_ticket, time_in, time_out)
            SELECT license_plate, has_entrance_ticket, time_in, time_out
            FROM g_sessions WHERE license_plate = %s
            """,
            (license_plate,),
        )
        cur.execute("DELETE FROM g_sessions WHERE license_plate = %s", (license_plate,))
    return GarageResult("exited", "Exited. Visit archived.")


def cancel(license_plate, *, connection=connect):
    with connection() as conn, conn.cursor() as cur:
        row = fetch_open_session(cur, license_plate)
        if row is None:
            raise ValueError("No open booking.")
        if row[1] is not None:
            raise ValueError("Vehicle is inside. Record an exit instead.")
        cur.execute("DELETE FROM g_sessions WHERE license_plate = %s", (license_plate,))
    return GarageResult("cancelled", "Booking cancelled.")


COMMANDS = {
    "book": book,
    "enter": enter,
    "exit": exit_garage,
    "cancel": cancel,
    "check": check,
}


def main():
    parser = argparse.ArgumentParser(description="Manage a garage session.")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("license_plate", help="Existing Lakebase plate key, e.g. WI-ABC-1234")
    args = parser.parse_args()
    try:
        result = COMMANDS[args.command](args.license_plate)
    except ValueError as error:
        parser.exit(1, f"Rejected: {error}\n")
    print(f"{args.license_plate}: {result.message}")


if __name__ == "__main__":
    main()
