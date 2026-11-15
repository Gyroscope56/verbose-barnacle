# 🚗 ParkSight — Quickstart & Local Development Guide

Welcome! This guide explains how to open the **ParkSight** project in VS Code, run the live UI locally on your computer to tweak the styling and features, and deploy your changes to Databricks.

---

## 📁 1. Project Files

- **`app.py`** — The Streamlit application (UI layout, colors, charts, live sensor polling).
- **`app.yaml`** — Databricks Apps configuration and environment variables.
- **`requirements.txt`** — Python packages required to run the app.

---

## 💻 2. How to Run & Visualize Locally in VS Code

You can run and test the dashboard on your own machine without deploying to Databricks first:

### Step 1: Open the Folder in VS Code
1. Open VS Code.
2. Go to **File** > **Open Folder...** and select the `parksight-app` (or `dashboard`) folder.
3. Open a terminal inside VS Code (`Ctrl + \`` or `Cmd + \``).

### Step 2: Set Up Python Virtual Environment
Run these commands in your VS Code terminal:

```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate it:
# On Mac/Linux:
source .venv/bin/activate
# On Windows (Command Prompt / PowerShell):
# .venv\Scripts\activate

# 3. Install the dependencies
pip install -r requirements.txt
```

### Step 3: Set Your Environment Variables
The app connects to our Databricks Lakebase database. Set the environment variables in your terminal:

**On Mac / Linux:**
```bash
export PARKING_DB_HOST="ep-spring-lake-d8d06cdv.database.us-east-2.cloud.databricks.com"
export PARKING_DB_NAME="databricks_postgres"
export PARKING_DB_USER="app_user"
export PARKING_DB_PASSWORD="npg_hw5GSrRMk1cz"
```

**On Windows (PowerShell):**
```powershell
$env:PARKING_DB_HOST="ep-spring-lake-d8d06cdv.database.us-east-2.cloud.databricks.com"
$env:PARKING_DB_NAME="databricks_postgres"
$env:PARKING_DB_USER="app_user"
$env:PARKING_DB_PASSWORD="npg_hw5GSrRMk1cz"
```

### Step 4: Run the App!
```bash
streamlit run app.py
```
VS Code will automatically pop up a browser tab at **`http://localhost:8501`** showing the live dashboard!

> 💡 **Live Reloading:** Whenever you edit `app.py` and hit **Save** (`Cmd+S` or `Ctrl+S`), Streamlit detects the change and automatically refreshes your browser!

---

## 🎨 3. Customizing the Design & Colors

Near the top of `app.py`, you'll find the color palette constants. You can customize them directly:

```python
# Palette: Campus Stone + Dark Red
CANVAS    = "#E9E7E3"   # Page background
CARD      = "#FAF9F7"   # Card & container background
ACCENT    = "#9B0000"   # Red accent / Occupied indicators
TEXT      = "#282728"   # Headings and body text
MUTED     = "#75716C"   # Secondary text and borders
SPOT_OCC  = "#9B0000"   # Occupied parking spot color
SPOT_FREE = "#4A7C59"   # Available parking spot color
```

### Testing Phone vs. Desktop View:
The app automatically adapts:
- **Desktop (>768px width):** Shows the business management view (Occupancy gauges, hourly trends, 7-day forecast, gate history log).
- **Mobile (≤768px width):** Switches into the Driver view with the parking aisle map (left and right spots separated by a driving lane).
- **How to test in your browser:** Press `F12` (or right-click > **Inspect**), then click the **Mobile Device Toggle** icon in Developer Tools or simply resize the browser window.

---

## 🚀 4. How to Deploy Your Changes to Databricks

When you're happy with your local changes and want them live on the Databricks URL:

```bash
# 1. Sync your changes to the workspace
databricks sync . /Workspace/Users/lalcalaroblero2@gmail.com/parksight

# 2. Deploy the app
databricks apps deploy parksight --source-code-path /Workspace/Users/lalcalaroblero2@gmail.com/parksight
```

Live Databricks App URL:
👉 **https://parksight-7474648110463211.aws.databricksapps.com**
