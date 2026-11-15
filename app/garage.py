import os
import argparse
import psycopg

DB_HOST = os.environ.get(
    "PARKING_DB_HOST",
    "ep-spring-lake-d8d06cdv.database.us-east-2.cloud.databricks.com",
)
DB_USER = "app_user"
DB_NAME = "databricks_postgres"
DB_PASSWORD = os.environ.get("PARKING_DB_PASSWORD")


def get_database_url():
    if not DB_PASSWORD:
        raise RuntimeError(
            "PARKING_DB_PASSWORD is not set. "
            "Get it from the Lakebase console's Reset password option for app_user."
        )
    return (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
        "?sslmode=require"
    )


def fetch_open_session(cur, license_plate):
    """Return (has_entrance_ticket, time_in, time_out) or None. Locks the row."""
    cur.execute("""
        SELECT has_entrance_ticket, time_in, time_out
        FROM g_sessions
        WHERE license_plate = %s
        FOR UPDATE;
    """, (license_plate,))
    return cur.fetchone()


def book(license_plate):
    """Plate is outside: create a session row granting entry permission."""
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            row = fetch_open_session(cur, license_plate)
            if row is not None:
                raise ValueError(
                    f"{license_plate} already has an open session row "
                    "(inside or already booked)."
                )
            cur.execute("""
                INSERT INTO g_sessions
                    (license_plate, has_entrance_ticket, time_in, time_out)
                VALUES (%s, TRUE, NULL, NULL);
            """, (license_plate,))
    print(f"{license_plate}: booked. May enter.")


def enter(license_plate):
    """Plate enters the garage: flip flag to false, stamp time_in."""
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            row = fetch_open_session(cur, license_plate)
            if row is None:
                raise ValueError(f"{license_plate} has no session row.")
            has_ticket, time_in, _ = row
            if time_in is not None:
                raise ValueError(f"{license_plate} is already inside.")
            if not has_ticket:
                raise ValueError(
                    f"{license_plate} has no entry permission (flag is false)."
                )
            cur.execute("""
                UPDATE g_sessions
                SET has_entrance_ticket = FALSE, time_in = NOW()
                WHERE license_plate = %s;
            """, (license_plate,))
    print(f"{license_plate}: entered at {time_in or 'now'}.")


def exit_garage(license_plate):
    """Plate leaves: stamp time_out, copy row (as-is, flag=false) to
    history, delete from sessions. All in one transaction."""
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            row = fetch_open_session(cur, license_plate)
            if row is None:
                raise ValueError(f"{license_plate} has no session row.")
            has_ticket, time_in, _ = row
            if time_in is None:
                raise ValueError(
                    f"{license_plate} never entered — use 'cancel' instead."
                )
            cur.execute("""
                UPDATE g_sessions
                SET time_out = NOW()
                WHERE license_plate = %s;
            """, (license_plate,))
            # Copy the finished visit verbatim (flag stays false)
            cur.execute("""
                INSERT INTO garage_visit_history
                    (license_plate, has_entrance_ticket, time_in, time_out)
                SELECT license_plate, has_entrance_ticket, time_in, time_out
                FROM g_sessions
                WHERE license_plate = %s;
            """, (license_plate,))
            cur.execute("""
                DELETE FROM g_sessions
                WHERE license_plate = %s;
            """, (license_plate,))
    print(f"{license_plate}: exited. Visit archived, session row removed.")


def cancel(license_plate):
    """Remove a booked-but-never-entered row (no history copy)."""
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            row = fetch_open_session(cur, license_plate)
            if row is None:
                raise ValueError(f"{license_plate} has no session row.")
            if row[1] is not None:
                raise ValueError(
                    f"{license_plate} is inside — must exit, not cancel."
                )
            cur.execute(
                "DELETE FROM g_sessions WHERE license_plate = %s;",
                (license_plate,),
            )
    print(f"{license_plate}: booking cancelled.")


def check(license_plate):
    """Report live enter-eligibility for a plate."""
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            row = fetch_open_session(cur, license_plate)
    if row is None:
        print(f"{license_plate}: no open row — may enter (needs a booking first).")
    else:
        has_ticket, time_in, time_out = row
        if time_in is not None:
            print(f"{license_plate}: INSIDE (entered {time_in}). Cannot re-enter.")
        elif has_ticket:
            print(f"{license_plate}: booked, outside. May enter.")
        else:
            print(f"{license_plate}: no entry permission.")


COMMANDS = {
    "book": book,
    "enter": enter,
    "exit": exit_garage,
    "cancel": cancel,
    "check": check,
}


def main():
    parser = argparse.ArgumentParser(
        description="Garage session lifecycle: book / enter / exit."
    )
    parser.add_argument("command", choices=COMMANDS.keys())
    parser.add_argument("license_plate", type=str, help="e.g. WI-ABC-1234")
    args = parser.parse_args()
    try:
        COMMANDS[args.command](args.license_plate)
    except ValueError as e:
        print(f"Rejected: {e}")


if __name__ == "__main__":
    main()