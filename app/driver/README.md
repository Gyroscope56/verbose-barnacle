# ParkSight driver app

The driver-facing **Parking availability** view. A Streamlit app that reads
`parking_spots`, open garage sessions, and visit history from Lakebase every two
seconds and renders live availability by floor and zone. Distance-sensor updates
from the UNO Q appear here as soon as they reach Lakebase.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PARKING_DB_HOST=... PARKING_DB_NAME=databricks_postgres PARKING_DB_USER=app_user
export PARKING_DB_PASSWORD=...   # from your secret store, never committed
streamlit run app.py
```

`DATABASE_URL` may be set instead of the individual `PARKING_DB_*` variables.

## Deploy as a Databricks App

1. Store the Lakebase password as a secret:
   ```bash
   databricks secrets create-scope parksight
   databricks secrets put-secret parksight db-password --string-value "<password>"
   ```
2. In the app's settings, add that secret as a resource with the key `db-password`
   (and the Genie space as `genie-space`). `app.yaml` maps them into the environment.
3. Deploy with `app/driver` as the source code path.
