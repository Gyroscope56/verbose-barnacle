import os
import argparse
import psycopg

DB_HOST = os.environ.get(
    "PARKING_DB_HOST",
    "ep-spring-lake-d8d06cdv.database.us-east-2.cloud.databricks.com",
)
DB_USER = "app_user"
DB_NAME = "databricks_postgres"
DB_PASSWORD = os.environ.get("PARKING_DB_PASSWORD")  # set this in your shell

THRESHOLD = 5.0


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


def update_parking_space(floor_zone_number, distance):

    is_occupied = abs(distance) < THRESHOLD

    with psycopg.connect(get_database_url()) as conn:

        with conn.cursor() as cur:

            # Retrieve only the relevant parking-space row
            cur.execute("""
                SELECT is_occupied, last_occupied
                FROM parking_spots
                WHERE floor_zone_number = %s
                FOR UPDATE;
            """, (floor_zone_number,))

            row = cur.fetchone()

            if row is None:
                raise ValueError(
                    f"Parking space {floor_zone_number} not found."
                )

            previous_status, last_occupied = row

            # FREE -> OCCUPIED
            if is_occupied and not previous_status:

                cur.execute("""
                    UPDATE parking_spots
                    SET
                        is_occupied = TRUE,
                        last_occupied = NOW(),
                        time_occupied = INTERVAL '0 seconds'
                    WHERE floor_zone_number = %s;
                """, (floor_zone_number,))

                print(f"{floor_zone_number}: Now occupied.")

            # OCCUPIED -> OCCUPIED
            elif is_occupied and previous_status:

                cur.execute("""
                    UPDATE parking_spots
                    SET time_occupied = NOW() - last_occupied
                    WHERE floor_zone_number = %s;
                """, (floor_zone_number,))

                print(f"{floor_zone_number}: Occupancy time updated.")

            # OCCUPIED -> FREE
            elif not is_occupied and previous_status:

                cur.execute("""
                    UPDATE parking_spots
                    SET
                        is_occupied = FALSE,
                        time_occupied = NULL,
                        last_occupied = NOW()
                    WHERE floor_zone_number = %s;
                """, (floor_zone_number,))

                print(f"{floor_zone_number}: Now free.")

            # FREE -> FREE
            else:
                print(f"{floor_zone_number}: Already free. No changes.")

    print("Database transaction completed.")


def test_connection():

    try:
        with psycopg.connect(get_database_url()) as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT *
                    FROM parking_spots
                    LIMIT 1;
                """)

                row = cur.fetchone()

                if row is None:
                    print("Connection successful, but table is empty.")
                    return

                print("Connection successful!")
                print("First parking-space record:")
                print(row)

    except Exception as e:
        print(f"Connection failed: {e}")


def main():

    parser = argparse.ArgumentParser(
        description="Update parking-space occupancy in PostgreSQL."
    )

    parser.add_argument(
        "floor_zone_number",
        type=str,
        help="Parking space identifier (e.g. 1-A-01)"
    )

    parser.add_argument(
        "distance",
        type=float,
        help="Arduino distance reading in inches"
    )

    args = parser.parse_args()

    #test_connection()
    update_parking_space(args.floor_zone_number, args.distance)


if __name__ == "__main__":
    main()