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


def apply_read(conn, zone, plate):
    """Apply a read and return (zone, outcome).

    zone "auto" (manual operator runs) closes the visit when the plate is inside
    and otherwise treats the read as an entry.
    """
    sessions = conn.execute(
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
    if zone == "auto":
        inside = len(sessions) == 1 and sessions[0][2] is not None
        zone = "exit" if inside else "entry"
    if len(sessions) > 1:
        return zone, "ambiguous"
    if not sessions:
        return zone, "unbooked" if zone == "entry" else "not_inside"

    key, has_ticket, time_in = sessions[0]
    connection = partial(nullcontext, conn)
    if zone == "entry":
        if time_in is not None:
            return zone, "already_inside"
        if not has_ticket:
            return zone, "denied"
        return zone, enter(key, connection=connection).status
    if time_in is None:
        return zone, "not_inside"
    return zone, exit_garage(key, connection=connection).status


def record_read(conn, camera_id, event_id, zone, plate):
    created = conn.execute(
        """INSERT INTO parksight_garage_events (camera_id, event_id, zone, plate, outcome)
           VALUES (%s, %s, %s, %s, 'pending')
           ON CONFLICT (camera_id, event_id) DO NOTHING
           RETURNING event_id""",
        # "auto" is resolved below, in the same transaction, before commit.
        (camera_id, event_id, "entry" if zone == "auto" else zone, plate),
    ).fetchone()
    if created is None:
        outcome, = conn.execute(
            """SELECT outcome FROM parksight_garage_events
               WHERE camera_id = %s AND event_id = %s""",
            (camera_id, event_id),
        ).fetchone()
        return {"outcome": outcome}

    zone, outcome = apply_read(conn, zone, plate)
    conn.execute(
        """UPDATE parksight_garage_events SET zone = %s, outcome = %s
           WHERE camera_id = %s AND event_id = %s""",
        (zone, outcome, camera_id, event_id),
    )
    return {"outcome": outcome}
