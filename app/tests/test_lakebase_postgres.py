"""Exercise the garage SQL against a disposable schema in a test PostgreSQL database."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from uuid import uuid4

from app import garage, spot_updater


TEST_DSN = os.environ.get("PARKSIGHT_TEST_POSTGRES")


@unittest.skipUnless(TEST_DSN, "Set PARKSIGHT_TEST_POSTGRES to a disposable database")
class PostgresTest(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.schema = "parksight_test_" + uuid4().hex
        with psycopg.connect(TEST_DSN) as conn:
            conn.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE g_sessions (
                    license_plate text PRIMARY KEY, has_entrance_ticket boolean NOT NULL,
                    time_in timestamptz, time_out timestamptz
                );
                CREATE TABLE garage_visit_history (
                    license_plate text NOT NULL, has_entrance_ticket boolean NOT NULL,
                    time_in timestamptz NOT NULL, time_out timestamptz NOT NULL,
                    CHECK (license_plate <> 'FAIL123')
                );
                CREATE TABLE parking_spots (
                    floor_zone_number text PRIMARY KEY, is_occupied boolean NOT NULL,
                    last_occupied timestamptz, time_occupied interval
                );
                INSERT INTO parking_spots VALUES ('1-A-01', FALSE, NULL, NULL);
            """)

    def connect(self):
        return self.psycopg.connect(TEST_DSN, options=f"-c search_path={self.schema}")

    def drop_schema(self):
        with self.psycopg.connect(TEST_DSN) as conn:
            conn.execute(self.psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(
                self.psycopg.sql.Identifier(self.schema)
            ))

    def test_session_lifecycle(self):
        plate = "WI-ABC-1234"
        self.assertEqual(garage.check(plate, connection=self.connect).status, "unbooked")
        with self.assertRaises(ValueError):
            garage.enter(plate, connection=self.connect)
        self.assertEqual(garage.book(plate, connection=self.connect).status, "booked")
        with self.assertRaises(ValueError):
            garage.exit_garage(plate, connection=self.connect)
        self.assertEqual(garage.cancel(plate, connection=self.connect).status, "cancelled")
        garage.book(plate, connection=self.connect)
        garage.enter(plate, connection=self.connect)
        with self.assertRaises(ValueError):
            garage.cancel(plate, connection=self.connect)
        self.assertEqual(garage.exit_garage(plate, connection=self.connect).status, "exited")
        with self.connect() as conn:
            archived = conn.execute(
                "SELECT license_plate, has_entrance_ticket, time_out >= time_in FROM garage_visit_history"
            ).fetchall()
        self.assertEqual(archived, [(plate, False, True)])
        self.assertEqual(garage.check(plate, connection=self.connect).status, "unbooked")

    def test_archive_failure_preserves_the_open_session(self):
        plate = "FAIL123"
        garage.book(plate, connection=self.connect)
        garage.enter(plate, connection=self.connect)
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            garage.exit_garage(plate, connection=self.connect)
        self.assertEqual(garage.check(plate, connection=self.connect).status, "inside")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT time_out FROM g_sessions").fetchone(), (None,))
            self.assertEqual(conn.execute("SELECT count(*) FROM garage_visit_history").fetchone(), (0,))

    def test_concurrent_booking_and_entry_allow_one_success_each(self):
        plate = "RACE123"
        for action in (garage.book, garage.enter):
            barrier = Barrier(2)

            def worker():
                barrier.wait(timeout=5)
                try:
                    return action(plate, connection=self.connect).status
                except ValueError:
                    return "rejected"

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
            self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(garage.check(plate, connection=self.connect).status, "inside")

    def test_occupancy_repeats_preserve_start_and_clear_resets(self):
        spot = "1-A-01"
        spot_updater.update_occupancy(spot, True, connection=self.connect)
        with self.connect() as conn:
            first = conn.execute("SELECT last_occupied FROM parking_spots").fetchone()[0]
        spot_updater.update_occupancy(spot, True, connection=self.connect)
        with self.connect() as conn:
            occupied, start, seconds = conn.execute(
                "SELECT is_occupied, last_occupied, EXTRACT(EPOCH FROM time_occupied) FROM parking_spots"
            ).fetchone()
        self.assertTrue(occupied)
        self.assertEqual(start, first)
        self.assertGreaterEqual(seconds, 0)
        with self.assertRaises(ValueError):
            spot_updater.update_occupancy("MISSING", False, connection=self.connect)
        with self.assertRaises(ValueError):
            spot_updater.update_occupancy(spot, None, connection=self.connect)
        spot_updater.update_occupancy(spot, False, connection=self.connect)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT * FROM parking_spots").fetchone(),
                             (spot, False, None, None))
