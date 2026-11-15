"""Apply a device read once, in the same transaction as the garage update."""

from contextlib import nullcontext
from functools import partial

if __package__:
    from ...garage import enter, exit_garage
else:
    from garage import enter, exit_garage


STATE_PREFIXES = """
AK AL AR AZ CA CO CT DC DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN
MO MS MT NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI WV WY
""".split()


def find_sessions(conn, plate):
    """Lock and return at most two garage sessions matching a normalized plate."""
    return conn.execute(
        """SELECT license_plate, has_entrance_ticket, time_in
           FROM g_sessions
           WHERE regexp_replace(upper(license_plate), '[^A-Z0-9]', '', 'g') = %s
              OR (upper(left(license_plate, 2)) = ANY(%s)
                  AND substring(license_plate from 3 for 1) IN ('-', ' ')
                  AND regexp_replace(upper(substring(license_plate from 4)),
                                     '[^A-Z0-9]', '', 'g') = %s)
           ORDER BY license_plate LIMIT 2 FOR UPDATE""",
        (plate, STATE_PREFIXES, plate),
    ).fetchall()


def resolve_zone(sessions, zone):
    """Manual operator runs send "auto": exit when the plate is inside, else entry."""
    if zone != "auto":
        return zone
    return "exit" if len(sessions) == 1 and sessions[0][2] is not None else "entry"


def apply_read(conn, zone, plate, sessions):
    if len(sessions) > 1:
        return "ambiguous"
    if not sessions:
        return "unbooked" if zone == "entry" else "not_inside"

    key, has_ticket, time_in = sessions[0]
    connection = partial(nullcontext, conn)
    if zone == "entry":
        if time_in is not None:
            return "already_inside"
        if not has_ticket:
            return "denied"
        return enter(key, connection=connection).status
    if time_in is None:
        return "not_inside"
    return exit_garage(key, connection=connection).status


def record_read(conn, camera_id, event_id, zone, plate):
    # Lock the matching sessions first so "auto" is resolved before the event is
    # stored; the API role may update only the event's outcome afterwards.
    sessions = find_sessions(conn, plate)
    zone = resolve_zone(sessions, zone)
    created = conn.execute(
        """INSERT INTO parksight_garage_events (camera_id, event_id, zone, plate, outcome)
           VALUES (%s, %s, %s, %s, 'pending')
           ON CONFLICT (camera_id, event_id) DO NOTHING
           RETURNING event_id""",
        (camera_id, event_id, zone, plate),
    ).fetchone()
    if created is None:
        outcome, = conn.execute(
            """SELECT outcome FROM parksight_garage_events
               WHERE camera_id = %s AND event_id = %s""",
            (camera_id, event_id),
        ).fetchone()
        return {"outcome": outcome}

    outcome = apply_read(conn, zone, plate, sessions)
    conn.execute(
        """UPDATE parksight_garage_events SET outcome = %s
           WHERE camera_id = %s AND event_id = %s""",
        (outcome, camera_id, event_id),
    )
    return {"outcome": outcome}
