import os
import json
import streamlit as st
import streamlit.components.v1 as components
import psycopg

from psycopg.rows import dict_row
from datetime import datetime, timezone



# -----------------------------------------------------

# ParkSense / ParkSight — Responsive Parking Dashboard

# Desktop: Management | Mobile: Customer parking map

# -----------------------------------------------------



st.set_page_config(

page_title="ParkSight | Parking Availability",

page_icon="🅿️",

layout="wide",

initial_sidebar_state="collapsed",

)



st.markdown("""

<style>

    #MainMenu, footer, header[data-testid="stHeader"] {

        visibility: hidden;

    }

    [data-testid="stAppViewContainer"] {

        background: #F4F3F0;

    }

    .block-container {

        max-width: 1480px;

        padding: 0.5rem 1rem 1rem;

    }

    [data-testid="stVerticalBlock"] {

        gap: 0;

    }

    iframe {

        border: none !important;

    }

</style>

""", unsafe_allow_html=True)





# -----------------------------------------------------

# Database connection

# -----------------------------------------------------



def get_connection():

    database_url = os.getenv("DATABASE_URL")



    if database_url:

        return psycopg.connect(

            database_url,

row_factory=dict_row,

connect_timeout=10,

        )



    host = os.getenv("PARKING_DB_HOST")

    user = os.getenv("PARKING_DB_USER")

    password = os.getenv("PARKING_DB_PASSWORD")



    if not all([host, user, password]):

        raise RuntimeError(

            "Database connection is not configured. "

            "Set DATABASE_URL or PARKING_DB_HOST, "

            "PARKING_DB_USER and PARKING_DB_PASSWORD."

        )



    return psycopg.connect(

host=host,

port=int(os.getenv("PARKING_DB_PORT", "5432")),

dbname=os.getenv(

            "PARKING_DB_NAME", "databricks_postgres"

        ),

user=user,

password=password,

sslmode="require",

connect_timeout=10,

row_factory=dict_row,

    )





def serialize_row(row):

    result = {}



    for key, value in row.items():

        if key == "license_plate":

            continue

        if isinstance(value, datetime):

            result[key] = value.isoformat()

        elif value is None:

            result[key] = None

        else:

            result[key] = str(value)



    return result





def load_dashboard():

    # A single read-only transaction gives the dashboard

    # a reasonably consistent snapshot of all three tables.

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(

                "SET TRANSACTION READ ONLY, "

                "ISOLATION LEVEL REPEATABLE READ"

            )



            cur.execute("""

                SELECT floor_zone_number, is_occupied

                FROM public.parking_spots

                ORDER BY floor_zone_number

            """)

            spots = cur.fetchall()



            cur.execute("""

                SELECT license_plate, time_in, time_out,

                       has_entrance_ticket

                FROM public.g_sessions

                WHERE time_out IS NULL AND has_entrance_ticket = FALSE

                ORDER BY time_in DESC NULLS LAST

            """)

            active = cur.fetchall()



            cur.execute("""

                SELECT license_plate, time_in, time_out

                FROM public.garage_visit_history

                WHERE time_out IS NOT NULL

                ORDER BY time_out DESC NULLS LAST

                LIMIT 15

            """)

            history = cur.fetchall()



    normalized_spots = []



    for spot in spots:

        code = str(spot["floor_zone_number"])

        parts = code.split("-")



        floor = parts[0] if len(parts) > 0 else "Other"

        zone = parts[1] if len(parts) > 1 else "A"



        try:

            number = int(parts[2])

        except (IndexError, ValueError):

            number = 0



        normalized_spots.append({

            "id": code,

            "floor": floor,

            "zone": zone,

            "number": number,

            "occupied": bool(spot["is_occupied"]),

        })



    total = len(normalized_spots)

    occupied = sum(

        spot["occupied"] for spot in normalized_spots

    )



    return {

        "spots": normalized_spots,

        "active": [serialize_row(r) for r in active],

        "history": [serialize_row(r) for r in history],

        "total": total,

        "occupied": occupied,

        "available": total - occupied,

        "occupancy": round(

            occupied / total * 100

        ) if total else 0,

        "updated_at": datetime.now(

            timezone.utc

        ).isoformat(),

    }





# -----------------------------------------------------

# Responsive interface

# -----------------------------------------------------



HTML = r"""

<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta name="viewport"

      content="width=device-width, initial-scale=1">



<style>

:root {

    \--bg: #F4F3F0;

    \--surface: #FFFFFF;

    \--ink: #20272B;

    \--muted: #737D82;

    \--line: #DFE3E3;

    \--brand: #8D2637;

    \--green: #278451;

    \--red: #C64151;

    \--green-pale: #E8F5EC;

    \--red-pale: #FAEAED;

    \--lane: #E8EBED;

    \--radius: 12px;

}



* {

    box-sizing: border-box;

}



html, body {

    margin: 0;

    padding: 0;

    background: var(--bg);

    color: var(--ink);

    font-family: -apple-system, BlinkMacSystemFont,

                 "Segoe UI", Arial, sans-serif;

}



.page {

    max-width: 1400px;

    margin: auto;

    padding: 14px;

}



.topbar {

    display: flex;

    align-items: center;

    justify-content: space-between;

    padding: 14px 20px;

    border-radius: var(--radius);

    background: #20272B;

    color: white;

    margin-bottom: 16px;

}



.logo {

    display: flex;

    align-items: center;

    gap: 10px;

    font-size: 20px;

    font-weight: 750;

    letter-spacing: -0.5px;

}



.logo-mark {

    width: 30px;

    height: 30px;

    border-radius: 7px;

    background: var(--brand);

    color: white;

    display: flex;

    align-items: center;

    justify-content: center;

    font-weight: 800;

}



.live {

    color: #81DCAB;

    font-size: 12px;

    font-weight: 600;

}



.live::before {

    content: "● ";

}



.subtitle {

    color: var(--muted);

    font-size: 13px;

    margin-bottom: 14px;

}



.section-title {

    font-size: 16px;

    font-weight: 700;

    margin: 0 0 12px;

}



.card {

    background: var(--surface);

    border: 1px solid var(--line);

    border-radius: var(--radius);

    padding: 18px;

}



.metrics {

    display: grid;

    grid-template-columns: repeat(4, 1fr);

    gap: 12px;

    margin-bottom: 16px;

}



.metric-label {

    color: var(--muted);

    font-size: 12px;

    margin-bottom: 8px;

}



.metric-number {

    font-size: 30px;

    font-weight: 750;

    letter-spacing: -1.2px;

}



.metric-note {

    font-size: 12px;

    color: var(--muted);

    margin-top: 5px;

}



.green-text { color: var(--green); }

.red-text { color: var(--red); }



.progress {

    width: 100%;

    height: 8px;

    border-radius: 8px;

    overflow: hidden;

    background: #E7E9E8;

    margin-top: 12px;

}



.progress-fill {

    height: 100%;

    background: var(--brand);

    border-radius: inherit;

    transition: width .3s ease;

}



.desktop-grid {

    display: grid;

    grid-template-columns: minmax(0, 1.5fr)

                           minmax(300px, 1fr);

    gap: 16px;

    align-items: start;

}



.floor-buttons {

    display: flex;

    gap: 8px;

    flex-wrap: wrap;

    margin-bottom: 14px;

}



.floor-button {

    border: 1px solid var(--line);

    background: #F3F4F3;

    color: var(--ink);

    border-radius: 8px;

    font-size: 13px;

    font-weight: 600;

    padding: 10px 16px;

    cursor: pointer;

}



.floor-button.selected {

    background: var(--brand);

    color: white;

    border-color: var(--brand);

}



.floor-meta {

    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 10px;

    margin-bottom: 12px;

}



.floor-summary {

    color: var(--muted);

    font-size: 12px;

}



.zone-title {

    font-size: 12px;

    font-weight: 750;

    letter-spacing: .08em;

    color: var(--muted);

    text-transform: uppercase;

    margin: 12px 0 10px;

}



.parking-map {

    background: #F7F8F7;

    border: 1px solid var(--line);

    border-radius: 10px;

    padding: 12px;

}



.parking-layout {

    display: grid;

    grid-template-columns: minmax(0, 1fr)

                           60px

                           minmax(0, 1fr);

    gap: 8px;

}



.spot-column {

    display: flex;

    flex-direction: column;

    gap: 7px;

}



.spot {

    min-height: 43px;

    display: flex;

    align-items: center;

    justify-content: center;

    border-radius: 6px;

    font-size: 12px;

    font-weight: 750;

    letter-spacing: .1px;

    color: white;

}



.spot.free {

    background: var(--green);

}



.spot.taken {

    background: var(--red);

}



.spot.empty {

    background: transparent;

}



.lane {

    background: var(--lane);

    border-radius: 6px;

    display: flex;

    flex-direction: column;

    justify-content: space-between;

    align-items: center;

    color: #8A959B;

    padding: 12px 3px;

    font-size: 22px;

}



.lane-label {

    font-size: 10px;

    text-transform: uppercase;

    font-weight: 800;

    color: #6E787D;

    text-align: center;

}



.legend {

    display: flex;

    justify-content: center;

    gap: 22px;

    flex-wrap: wrap;

    margin-top: 14px;

    font-size: 12px;

    color: var(--muted);

}



.legend-item {

    display: flex;

    align-items: center;

    gap: 6px;

}



.dot {

    width: 10px;

    height: 10px;

    border-radius: 3px;

    display: inline-block;

}



.dot.free { background: var(--green); }

.dot.taken { background: var(--red); }



.floor-row {

    margin-bottom: 17px;

}



.floor-row-top {

    display: flex;

    justify-content: space-between;

    font-size: 13px;

    margin-bottom: 6px;

}



.floor-row .progress {

    margin-top: 0;

    height: 7px;

}



.floor-row .progress-fill {

    background: #607781;

}



.activity-heading {

    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 10px;

}



.activity-row {

    display: grid;

    grid-template-columns: 1fr auto auto;

    gap: 12px;

    align-items: center;

    padding: 10px 0;

    border-bottom: 1px solid var(--line);

    font-size: 12px;

}



.activity-row:last-child {

    border-bottom: 0;

}



.plate {

    font-weight: 650;

}



.event-status {

    font-size: 10px;

    font-weight: 800;

    color: var(--muted);

}



.event-time {

    color: var(--muted);

    text-align: right;

}



.empty-message {

    color: var(--muted);

    font-size: 13px;

    padding: 16px 0;

}



.footer-note {

    text-align: center;

    margin: 12px 0;

    color: var(--muted);

    font-size: 11px;

}



.mobile-only {

    display: none;

}



/* Customer / mobile presentation */

@media (max-width: 768px) {

    .page {

        padding: 7px;

    }



    .topbar {

        padding: 14px 16px;

        border-radius: 9px;

        margin-bottom: 12px;

    }



    .logo {

        font-size: 19px;

    }



    .desktop-only {

        display: none !important;

    }



    .mobile-only {

        display: block;

    }



    .metrics {

        grid-template-columns: repeat(2, 1fr);

        gap: 9px;

        margin-bottom: 12px;

    }



    .metrics .metric-wide {

        grid-column: 1 / -1;

    }



    .card {

        padding: 13px;

    }



    .metric-number {

        font-size: 29px;

    }



    .desktop-grid {

        display: block;

    }



    .floor-buttons {

        display: grid;

        grid-template-columns: repeat(3, minmax(0, 1fr));

    }



    .floor-button {

        padding: 10px 5px;

    }



    .parking-layout {

        grid-template-columns: minmax(0, 1fr)

                               54px

                               minmax(0, 1fr);

        gap: 7px;

    }



    .parking-map {

        padding: 9px;

    }



    .spot {

        min-height: 43px;

        font-size: 12px;

    }



    .section-title {

        font-size: 15px;

    }

}

</style>

</head>



<body>

<div class="page">



    <header class="topbar">

        <div class="logo">

            <div class="logo-mark">P</div>

            <span>ParkSight</span>

        </div>

        <span class="live">Live data</span>

    </header>



    <div class="subtitle desktop-only">

        Garage operations · Overview

    </div>



    <div class="subtitle mobile-only">

        Find an available parking space

    </div>



    <div class="metrics" id="metrics"></div>



    <div class="desktop-grid">

        <main class="card">

            <div class="floor-meta">

                <div>

                    <h2 class="section-title">

                        Parking availability

                    </h2>

                    <div class="floor-summary"

                         id="floor-summary"></div>

                </div>

            </div>



            <div class="floor-buttons" id="floors"></div>



            <div id="maps"></div>



            <div class="legend">

                <div class="legend-item">

                    <span class="dot free"></span>

                    Available

                </div>

                <div class="legend-item">

                    <span class="dot taken"></span>

                    Occupied

                </div>

            </div>

        </main>



        <aside class="desktop-only">

            <section class="card" style="margin-bottom: 16px">

                <h2 class="section-title">

                    Capacity by floor

                </h2>

                <div id="floor-stats"></div>

            </section>



            <section class="card">

                <div class="activity-heading">

                    <h2 class="section-title"

                        style="margin:0">

                        Recent garage activity

                    </h2>

                </div>

                <div id="activity"></div>

            </section>

        </aside>

    </div>



    <div class="footer-note" id="updated"></div>

</div>



<script>

const DATA = __PARKING_DATA__;



const $ = (id) => document.getElementById(id);



function esc(value) {

    return String(value ?? "").replace(

        /[&<>"']/g,

        (c) => ({

            "&": "&amp;",

            "<": "&lt;",

            ">": "&gt;",

            '"': "&quot;",

            "'": "&#39;"

        })[c]

    );

}



const floors = [...new Set(

    DATA.spots.map(s => s.floor)

)].sort((a, b) =>

    String(a).localeCompare(String(b), undefined, {

        numeric: true

    })

);



let selectedFloor = floors[0] || "";



try {

    const saved = sessionStorage.getItem("parksight-floor");

    if (floors.includes(saved)) {

        selectedFloor = saved;

    }

} catch (e) {}



function percentage(occupied, total) {

    return total

        ? Math.round(100 * occupied / total)

        : 0;

}



function metric(label, number, note, color, wide=false) {

    return `

      <div class="card ${wide ? "metric-wide" : ""}">

        <div class="metric-label">${esc(label)}</div>

        <div class="metric-number ${color || ""}">

          ${esc(number)}

        </div>

        <div class="metric-note">${esc(note)}</div>

      </div>`;

}



function renderMetrics() {

    const t = DATA.total;

    const o = DATA.occupied;

    const a = DATA.available;



    $("metrics").innerHTML = `

      <div class="desktop-only"

           style="display:contents">

        ${metric("Total spaces", t, "Garage capacity")}

        ${metric("Available", a, "Open parking spaces",

                "green-text")}

        ${metric("Occupied", o, "Taken parking spaces",

                "red-text")}

        ${metric("Vehicles inside", DATA.active.length,

                "Active entry sessions")}

      </div>



      <div class="mobile-only metric-wide">

        <div class="card" style="margin-bottom:9px">

          <div class="metric-label">Garage capacity</div>

          <div class="metric-number">

            ${esc(o)} / ${esc(t)}

          </div>

          <div class="metric-note">

            ${percentage(o,t)}% occupied

          </div>

          <div class="progress">

            <div class="progress-fill"

                 style="width:${percentage(o,t)}%">

            </div>

          </div>

        </div>

        <div style="display:grid;

                    grid-template-columns:1fr 1fr;

                    gap:9px">

          ${metric("Available",a,"Open spaces","green-text")}

          ${metric("Occupied",o,"Taken spaces","red-text")}

        </div>

      </div>`;

}



function floorSpots(floor) {

    return DATA.spots.filter(s => s.floor === floor);

}



function makeSpot(spot) {

    if (!spot) {

        return '<div class="spot empty"></div>';

    }



    const status = spot.occupied ? "taken" : "free";



    return `<div class="spot ${status}"

                 title="${esc(spot.id)} — ${spot.occupied ?

                           "Occupied" : "Available"}">

              ${esc(spot.zone + "-" + String(spot.number).padStart(2, "0"))}

            </div>`;

}



function renderZone(zoneSpots) {

    // Odd-numbered spaces on the left;

    // even-numbered spaces on the right.

    const odd = zoneSpots

        .filter(s => s.number % 2 === 1)

        .sort((a,b) => a.number - b.number);



    const even = zoneSpots

        .filter(s => s.number % 2 === 0)

        .sort((a,b) => a.number - b.number);



    const rows = Math.max(odd.length, even.length);

    let left = "";

    let right = "";



    for (let i=0; i<rows; i++) {

        left += makeSpot(odd[i]);

        right += makeSpot(even[i]);

    }



    return `

      <div class="parking-map">

        <div class="parking-layout">

          <div class="spot-column">${left}</div>

          <div class="lane">

            <div>↑</div>

            <div style="display:flex;flex-direction:column;

                        gap:30px;align-items:center">

              <span>↑</span><span>↑</span>

            </div>

            <div class="lane-label">Entrance</div>

          </div>

          <div class="spot-column">${right}</div>

        </div>

      </div>`;

}



function renderFloors() {

    $("floors").innerHTML = floors.map(f => `

      <button

        class="floor-button ${f===selectedFloor ?

                             "selected" : ""}"

        data-floor="${esc(f)}">

        Floor ${esc(f)}

      </button>

    `).join("");



    $("floors").querySelectorAll("button")

      .forEach(btn => {

        btn.addEventListener("click", () => {

            selectedFloor = btn.dataset.floor;

            try {

                sessionStorage.setItem(

                    "parksight-floor", selectedFloor

                );

            } catch(e) {}

            renderFloors();

            renderMap();

        });

    });

}



function renderMap() {

    const spots = floorSpots(selectedFloor);

    const occupied = spots.filter(s=>s.occupied).length;

    const available = spots.length - occupied;



    $("floor-summary").textContent =

        `Floor ${selectedFloor} · ${available} open of ` +

        `${spots.length} spaces`;



    const zones = [...new Set(

        spots.map(s => s.zone)

    )].sort();



    if (!spots.length) {

        $("maps").innerHTML =

            '<p class="empty-message">No parking spaces found.</p>';

        return;

    }



    $("maps").innerHTML = zones.map(zone => {

        const zoneSpots = spots.filter(s=>s.zone===zone);

        return `

          <div class="zone-title">Zone ${esc(zone)}</div>

          ${renderZone(zoneSpots)}

        `;

    }).join("");

}



function renderFloorStats() {

    $("floor-stats").innerHTML = floors.map(floor => {

        const spots = floorSpots(floor);

        const occupied = spots.filter(s=>s.occupied).length;

        const available = spots.length - occupied;

        const pct = percentage(occupied,spots.length);



        return `

          <div class="floor-row">

            <div class="floor-row-top">

              <strong>Floor ${esc(floor)}</strong>

              <span>${available} available /

                    ${spots.length} total</span>

            </div>

            <div class="progress">

              <div class="progress-fill"

                   style="width:${pct}%"></div>

            </div>

          </div>

        `;

    }).join("");

}



function dateLabel(value) {

    if (!value) return "—";

    const d = new Date(value);

    return Number.isNaN(d.getTime())

        ? "—"

        : d.toLocaleString([], {

            month:"short", day:"numeric",

            hour:"numeric", minute:"2-digit"

        });

}



function renderActivity() {

    const events = [];



    DATA.active.forEach(s => {

        if (s.time_in) {

            events.push({

                plate:s.license_plate,

                type:"ENTERED",

                time:s.time_in

            });

        }

    });



    DATA.history.forEach(s => {

        if (s.time_out) {

            events.push({

                plate:s.license_plate,

                type:"EXITED",

                time:s.time_out

            });

        }

    });



    events.sort((a,b) =>

        new Date(b.time) - new Date(a.time)

    );



    $("activity").innerHTML = events.length

        ? events.slice(0,10).map(e => `

          <div class="activity-row">

            <span class="plate">Garage event</span>

            <span class="event-status">${esc(e.type)}</span>

            <span class="event-time">

              ${esc(dateLabel(e.time))}

            </span>

          </div>

        `).join("")

        : `<div class="empty-message">

             No recent garage activity.

           </div>`;

}



renderMetrics();

renderFloors();

renderMap();

renderFloorStats();

renderActivity();



$("updated").textContent =

    "Updated " + dateLabel(DATA.updated_at) +

    " · Automatic refresh every 10 seconds";

</script>

</body>

</html>

"""





@st.fragment(run_every="2s") #set Speed

def live_dashboard():

    try:

        dashboard = load_dashboard()

    except Exception:

        st.error(

            "Unable to retrieve live parking data. "

            "Check the Lakebase connection and app permissions."

        )

        st.info(

            "The dashboard will retry automatically. "

            "Database connection details are not displayed."

        )

        return



    # Escape HTML-sensitive characters within JSON.

    payload = json.dumps(dashboard).replace(

        "<", "\\\u003c"

    ).replace(">", "\\\u003e")



    page = HTML.replace("__PARKING_DATA__", payload)



    components.html(

        page,

height=1050,

scrolling=True,

    )

# -----------------------------------------------------
# Launch ParkSight Live Dashboard
# -----------------------------------------------------

live_dashboard()