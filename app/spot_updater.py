"""Parking-spot updates shared by the distance CLI and the UNO Q."""

import argparse
from math import isfinite

if __package__:
    from .lakebase import connect
else:
    from lakebase import connect


THRESHOLD = 5.0


def update_occupancy(floor_zone_number, occupied, *, connection=connect):
    """Write a known state while preserving an existing occupancy start time."""
    if type(occupied) is not bool:
        raise ValueError("Occupancy must be a known boolean state.")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_occupied FROM parking_spots WHERE floor_zone_number = %s FOR UPDATE",
            (floor_zone_number,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Parking space {floor_zone_number} not found.")
        if not occupied and not row[0]:
            return False
        cur.execute(
            """
            UPDATE parking_spots
            SET is_occupied = %(occupied)s,
                last_occupied = CASE
                    WHEN NOT %(occupied)s THEN NULL
                    WHEN is_occupied THEN COALESCE(last_occupied, NOW())
                    ELSE NOW()
                END,
                time_occupied = CASE
                    WHEN NOT %(occupied)s THEN NULL
                    WHEN is_occupied THEN NOW() - COALESCE(last_occupied, NOW())
                    ELSE INTERVAL '0 seconds'
                END
            WHERE floor_zone_number = %(spot)s
            """,
            {"occupied": occupied, "spot": floor_zone_number},
        )
    return occupied


def update_parking_space(floor_zone_number, distance):
    if not isfinite(distance):
        raise ValueError("Distance must be finite.")
    occupied = update_occupancy(floor_zone_number, abs(distance) < THRESHOLD)
    print(f"{floor_zone_number}: {'occupied' if occupied else 'free'}.")


def main():
    parser = argparse.ArgumentParser(description="Update parking occupancy from distance.")
    parser.add_argument("floor_zone_number", help="Parking spot key, e.g. 1-A-01")
    parser.add_argument("distance", type=float, help="Distance in inches")
    args = parser.parse_args()
    try:
        update_parking_space(args.floor_zone_number, args.distance)
    except ValueError as error:
        parser.exit(1, f"Rejected: {error}\n")


if __name__ == "__main__":
    main()
