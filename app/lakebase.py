"""Connection settings shared by the garage tools and UNO Q deployment."""

import os
from dataclasses import dataclass

DEFAULT_HOST = "ep-spring-lake-d8d06cdv.database.us-east-2.cloud.databricks.com"


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    password: str
    user: str = "app_user"
    dbname: str = "databricks_postgres"
    port: int = 5432
    sslmode: str = "require"

    @classmethod
    def from_environment(cls):
        password = os.environ.get("PARKING_DB_PASSWORD")
        if not password:
            raise RuntimeError("PARKING_DB_PASSWORD is not set.")
        return cls(
            host=os.environ.get("PARKING_DB_HOST", DEFAULT_HOST),
            password=password,
            user=os.environ.get("PARKING_DB_USER", "app_user"),
            dbname=os.environ.get("PARKING_DB_NAME", "databricks_postgres"),
            port=int(os.environ.get("PARKING_DB_PORT", "5432")),
            sslmode=os.environ.get("PARKING_DB_SSLMODE", "require"),
        )

    def connect(self):
        import psycopg

        return psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            dbname=self.dbname,
            password=self.password,
            sslmode=self.sslmode,
            connect_timeout=4,
            options="-c statement_timeout=4000",
        )


def connect():
    return DatabaseSettings.from_environment().connect()
