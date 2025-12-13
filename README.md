# AllSky Dew Heater Platform

Raspberry Pi-based controller that keeps an AllSky camera enclosure dry by continuously monitoring temperature/humidity, computing the dew point, and driving a resistive heater through a relay. A built-in Flask + Chart.js dashboard exposes live graphs, historical data, relay controls, and astronomy/ambient weather context so the system can run unattended and still be inspected remotely.

![Dashboard Screenshot](screenshots/Screenshot%202025-12-09%20201813.png)

## Repository Layout

| Component | Description |
| --- | --- |
| `Dew_Heater_Controller.py` | Flask entry point that wires together the modules below, exposes the API, and launches the sensor thread. |
| `dew_heater_controller/config.py` | Centralized configuration + environment overrides (DHT pin, relay pin, ambient API settings, chart defaults, etc.). |
| `dew_heater_controller/state.py` | Thread-safe controller state (auto/manual mode, relay status, forced-run timers). |
| `dew_heater_controller/live.py` | Lightweight pub/sub broker used by the SSE endpoint to stream live readings to the dashboard. |
| `dew_heater_controller/logs.py` | CSV logging and history loading utilities for `Temp_Humidity_Logs/`. |
| `dew_heater_controller/metrics.py` | Math helpers such as the Magnus dew-point approximation. |
| `dew_heater_controller/weather.py` | Ambient weather + astronomy clients (Open-Meteo, 7timer) plus moon/sun descriptions. |
| `templates/dashboard.html` | Flask/Jinja template that renders the Chart.js dashboard, control widgets, and astro imagery. |
| `static/icons/` | SVG icons used throughout the dashboard interface. |
| `Temp_Humidity_Logs/` | Daily CSV exports created by the controller (`dew_heater_readings_YYYY-MM-DD.csv` and `dew_heater_events_YYYY-MM-DD.csv`). |
| `archive/` | Historical scripts that were superseded by the refactored controller but kept for reference. |

## Hardware Assumptions

- Raspberry Pi with GPIO access.
- DHT11 temperature/humidity sensor wired to BCM pin 16 (physical 36) with 3.3 V and ground.
- Relay module connected to BCM pin 26 (physical 37) driving the dew heater (active HIGH).
- Dew heater sized appropriately for the enclosure.
- Network access for pulling weather (Open-Meteo, 7timer) and serving the dashboard.

You can adapt the pin numbers and other defaults by editing `dew_heater_controller/config.py` or exporting environment variables (preferred for deployments).

## Key Features (Modular Controller)

- **Sensor monitoring:** Samples every 10 s, filters impossible values, and computes dew point + delta vs enclosure temperature.
- **Automatic control:** Uses configurable hysteresis (`HYSTERESIS_C`) plus a "forced run" mode that can pre-heat if ambient forecasts predict dew risk. Includes optional daylight blocking, warm-up and cooldown timers, and manual override buttons exposed via the web UI and REST API.
- **Logging:** Every reading and relay transition is appended to a dated CSV for later analysis.
- **Dashboard:** Flask app streams live charts via server-sent events. Graphs can toggle °F/°C, change time ranges, and show ambient vs enclosure trends. Manual relay buttons, climate summaries, moon phase, sunrise/sunset, 7timer chart, and the latest AllSky image are all embedded.
- **External data:** Calls Open-Meteo for ambient temp/dew point, 7timer for astronomy forecasts, and pulls moon/sun information plus AllSky imagery.
- **JSON API:** Endpoints for latest readings, history windows, relay state, manual overrides, and proxied resources so other tools can interact programmatically.

## Web Dashboard UI

The dashboard provides a modern, dark-themed interface for monitoring and controlling the dew heater system. The UI is fully responsive and updates in real-time using Server-Sent Events (SSE).

### Status Bar

Located at the top of the page:
- **Connection Indicator:** Shows connection status (Connected/Disconnected) with visual indicator
- **Last Sync:** Displays the timestamp of the last successful data synchronization

### Time Range Controls

A dedicated card section for selecting the time range displayed in all charts:
- **Quick Range Buttons:** Five preset buttons for common time ranges:
  - `1 H` - Last 1 hour
  - `6 H` - Last 6 hours (default)
  - `12 H` - Last 12 hours
  - `24 H` - Last 24 hours
  - `3 D` - Last 3 days
- **Units Picker:** Dropdown menu to toggle between Celsius (°C) and Fahrenheit (°F)
  - Changes all temperature displays and chart labels dynamically
  - Persists selection across page refreshes

### Latest AllSky Image

Displays the most recent image captured by the AllSky camera:
- Auto-refreshes every 60 seconds
- Manual refresh button available
- Shows timestamp of last image update
- Falls back to placeholder if image unavailable

### Dew Heater Control Panel

Comprehensive control interface for the relay system:

- **Relay Status Indicator:**
  - Visual dot indicator (green = ON, red = OFF)
  - Current relay state display
  - Real-time updates via SSE

- **Current Temperature Display:**
  - Shows the most recent sensor reading
  - Updates automatically with unit conversion

- **Control Mode Selection:**
  - **Automatic Mode:** Dew-point driven control with configurable hysteresis
    - System automatically turns relay on/off based on temperature vs dew point delta
    - Includes forced-run logic for predictive heating
  - **Manual Mode:** Direct relay control
    - "Force Relay On" button - Manually activate the heater
    - "Force Relay Off" button - Manually deactivate the heater
    - Manual controls only visible when manual mode is active

### Chart Visualizations

Three interactive Chart.js graphs displaying historical data:

1. **Temperature Chart**
   - Shows enclosure temperature over time
   - Y-axis scale controls (Min/Max) with Apply/Auto buttons
   - Updates in real-time with new sensor readings

2. **Dew Point Chart**
   - Displays calculated dew point trajectory
   - Dashed line style for visual distinction
   - Independent Y-axis scaling

3. **Humidity Chart**
   - Relative humidity percentage over time
   - 0-100% scale by default
   - Customizable Y-axis range

**Chart Features:**
- All charts support custom Y-axis scaling
- "Apply" button to set custom min/max values
- "Auto" button to reset to automatic scaling
- Real-time data streaming via SSE
- Time-based X-axis with hover tooltips
- Responsive design adapts to screen size

### Local Weather & Astronomy

Comprehensive weather and astronomy information card:

- **Location & Summary:**
  - Current location name
  - Weather condition summary

- **Weather Statistics:**
  - Temperature (current, high, low)
  - Dew Point
  - Humidity percentage
  - Cloud Cover percentage
  - Moon Phase with illumination percentage

- **Astronomy Conditions:**
  - Seeing quality (Excellent/Good/Poor)
  - Transparency quality
  - Precipitation chance
  - Last update timestamp

### Three Day Astronomy Forecast

Embedded 7timer! (CMA) astronomy forecast chart:
- Three-day visual forecast
- Auto-refreshes hourly
- Shows seeing and transparency predictions
- Color-coded quality indicators

## API Endpoints

The controller exposes a RESTful JSON API for programmatic access:

### `GET /`
Main dashboard page (HTML).

### `GET /api/readings`
Retrieve historical sensor readings.

**Query Parameters:**
- `hours` (float): Number of hours of history to retrieve (e.g., `?hours=6`)
- `start` (ISO 8601): Start timestamp for custom range
- `end` (ISO 8601): End timestamp for custom range

**Response:**
```json
{
  "timestamps": ["2025-12-10T20:00:00", ...],
  "temperature_c": [22.5, ...],
  "humidity_pct": [65.0, ...],
  "dew_point_c": [15.8, ...],
  "relay_state": [true, ...],
  "start": "2025-12-10T14:00:00",
  "end": "2025-12-10T20:00:00"
}
```

### `GET /api/control`
Get current controller state.

**Response:**
```json
{
  "mode": "auto",
  "manual_on": false,
  "relay_on": false,
  "weather": { ... }
}
```

### `POST /api/control`
Update controller mode and relay state.

**Request Body:**
```json
{
  "mode": "manual",
  "manual_on": true
}
```

**Response:** Updated controller state snapshot.

### `GET /api/live`
Server-Sent Events (SSE) stream for real-time updates.

**Response:** Continuous stream of JSON objects:
```
data: {"timestamp": "...", "temp_c": 22.5, "humidity_pct": 65.0, ...}

data: {"timestamp": "...", "temp_c": 22.6, ...}
```

### `GET /api/latest-image`
Get metadata about the latest AllSky image.

**Response:**
```json
{
  "available": true,
  "url": "/latest-image?cacheBust=1234567890",
  "last_modified": "2025-12-10T20:00:00"
}
```

### `GET /latest-image`
Serve the latest AllSky image file (JPEG/PNG).

### `GET /api/astro-chart`
Get the 7timer astronomy forecast chart URL.

**Response:**
```json
{
  "url": "http://www.7timer.info/bin/astro.php?..."
}
```

## Configuration

Most behavior is controlled through environment variables surfaced in `dew_heater_controller/config.py`; each constant has a docstring explaining its purpose. The script falls back to sensible defaults so it can run on the Pi without a `.env` file. Common overrides include:

| Variable | Purpose (default) |
| --- | --- |
| `DEW_DHT_PIN` | BCM pin for DHT11 sensor (16) |
| `DEW_RELAY_PIN` | BCM pin for relay control (26) |
| `DEW_HYSTERESIS_C` | Temperature delta for relay control (5.0°C) |
| `DEW_POLL_INTERVAL` | Seconds between sensor readings (10) |
| `DEW_DEFAULT_RANGE_HOURS` | Default chart time range (6) |
| `DEW_WEB_HOST` / `DEW_WEB_PORT` | Flask binding, defaults to `0.0.0.0:8080`. |
| `AMBIENT_LAT` / `AMBIENT_LON` | Coordinates for Open-Meteo & 7timer requests (`43.339344`, `-71.038694`). |
| `AMBIENT_CACHE_SECONDS` | How long to cache ambient results (600 s). |
| `AMBIENT_TEMP_OFFSET_C` | Offset added to ambient temp when comparing dew risk (5.0°C). |
| `AMBIENT_LOCATION_NAME` | Display name for weather location (`Farmington, NH`) |
| `IMAGES_ROOT` | Path to AllSky image directory (`/home/allsky/allsky/images`). |
| `ALLSKY_PUBLIC_URL` | Base URL used for the "Latest Image" link (`http://192.168.40.210/public.php`). |
| `FORCE_RUN_TEMP_DIFF_C` | Temperature difference threshold for forced run (6.0°C) |
| `FORCE_RUN_DURATION_MIN` | Duration of forced run in minutes (30) |
| `FORCE_RUN_COOLDOWN_MIN` | Cooldown period between forced runs in minutes (60) |
| `SEVENTIMER_URL` | 7timer API endpoint |
| `SEVENTIMER_GRAPH_URL` | 7timer graph URL template |

Review `dew_heater_controller/config.py` for the complete list of configuration options.

## Installation

Run these commands on a fresh Raspberry Pi OS system:

```sh
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/alexlagle/Allsky-Dew-Heater-Platform.git
cd Allsky-Dew-Heater-Platform
sudo INSTALL_USER=pi ./install.sh    # replace pi with your non-root user if needed
```

The installer:
- Installs Python, build essentials, and pip tooling.
- Creates/updates a `.venv` inside the cloned repository and installs `requirements.txt`.
- Creates `/etc/dew-heater/dew-heater.env` for your overrides (GPIO pins, host/port, etc.).
- Registers and starts the `dew-heater.service` systemd unit that launches `Dew_Heater_Controller.py`.

Edit `/etc/dew-heater/dew-heater.env` after installation to customize settings, then restart with `sudo systemctl restart dew-heater`.

## Running the Controller

1. **Create a virtual environment (recommended):**
   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -U pip
   pip install flask requests RPi.GPIO dht11
   ```

2. **Export any needed environment variables** (coordinates, host/port, API overrides, etc.).

3. **Launch the service:**
   ```sh
   # Using the virtual environment Python directly
   /home/allsky/.venv/bin/python Dew_Heater_Controller.py
   
   # Or activate the venv first
   source .venv/bin/activate
   python Dew_Heater_Controller.py
   
   # Or make it executable and run directly (uses shebang)
   chmod +x Dew_Heater_Controller.py
   ./Dew_Heater_Controller.py
   ```

4. **Access the dashboard:**
   Open the dashboard in a browser at `http://<pi-address>:8080/` (or your chosen host/port). 
   
   The interface provides:
   - Real-time sensor data visualization
   - Interactive charts with customizable time ranges
   - Manual relay control options
   - Weather and astronomy context
   - Latest AllSky camera image

### Data Files

- `Temp_Humidity_Logs/dew_heater_readings_YYYY-MM-DD.csv` – timestamped sensor values, dew point, relay state, moon phase, etc.
- `Temp_Humidity_Logs/dew_heater_events_YYYY-MM-DD.csv` – entries for each relay transition or forced-run status change.

These are plain CSV files so you can ingest them into spreadsheets or dashboards.

## Automation Tips

- Use `systemd` or `tmux` to keep `Dew_Heater_Controller.py` running as a service on boot.
- Regularly archive the CSV logs or sync them off-device for long-term analysis.
- Keep your virtual environment (`.venv/`) and dependencies updated, especially Flask and requests, for security patches.
- The API endpoints can be integrated with home automation systems (Home Assistant, Node-RED, etc.) for advanced control and monitoring.

## Technology Stack

- **Backend:** Python 3, Flask (web framework)
- **Frontend:** HTML5, CSS3, JavaScript (ES6+)
- **Charts:** Chart.js 4.4.0 with date-fns adapter
- **Real-time Updates:** Server-Sent Events (SSE)
- **Hardware Interface:** RPi.GPIO, dht11 library
- **External APIs:** Open-Meteo (weather), 7timer! (astronomy)

## Recent Updates

- **UI Redesign:** Removed custom date range inputs in favor of quick-select time range buttons for improved usability
- **Real-time Streaming:** Live data updates via Server-Sent Events for instant chart updates
- **Responsive Design:** Modern dark theme with mobile-friendly layout

With the Pi, DHT11, and relay wired as specified, this repository provides an end-to-end dew mitigation solution complete with visualization and alerting hooks.
