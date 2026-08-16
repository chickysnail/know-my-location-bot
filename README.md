# Know My Location Bot

A Telegram bot with an HTTP ingest endpoint. A phone automation app (Tasker) posts
location points to the service; authorized Telegram users ask the bot for the latest
one and get a Google Maps link back.

- `POST /ingest` — stores a location point, authenticated by a shared secret header
- `GET /health` — liveness probe
- `/where` — Telegram command returning the latest point (authorized users only)

Location points are stored in SQLite. No personal data lives in this repository:
tokens, user IDs and the database path all come from environment variables.

## Setup

### Prerequisites

- Python 3.12+
- Telegram Bot Token ([BotFather](https://t.me/botfather))

### Installation

```bash
git clone https://github.com/chickysnail/know_my_location_bot.git
cd know_my_location_bot
pip install -e ".[dev]"
```

### Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `INGEST_TOKEN` | Shared secret sent by the ingest client in `X-Auth-Token` |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to query the location |
| `DATABASE_PATH` | SQLite file path (default `./locations.db`) |
| `PORT` | HTTP port (default `8080`; Railway sets this automatically) |
| `LOG_LEVEL` | Logging level (default `INFO`) |

### Run

```bash
python -m src.bot.main
```

### Tests, lint and type checking

```bash
pytest
ruff check src/ tests/
mypy src/
```

## Deployment (Railway)

1. Create a new Railway project and connect this repository. The `Dockerfile` is
   used to build the service.
2. Add a **Volume** mounted at `/data` so the SQLite database survives redeploys.
3. Under **Settings → Networking**, generate a public domain — that domain is the
   ingest endpoint (`https://<your-domain>/ingest`).
4. Set the service variables:

   ```
   TELEGRAM_BOT_TOKEN=<from BotFather>
   INGEST_TOKEN=<a long random string>
   ALLOWED_USER_IDS=<your Telegram user ID>
   DATABASE_PATH=/data/locations.db
   ```

   `PORT` is provided by Railway; the ingest server binds to it.

## Tasker setup

Create a task that reads the current location and sends it to the service:

1. **Get Location v2** (or `%gl_coordinates` from an existing location profile).
2. **Variable Set**: `%formatted` to `%DATE %TIME`, or use Tasker's formatted date/time.
3. **HTTP Request**:
   - Method: `POST`
   - URL: `https://<your-railway-domain>/ingest`
   - Headers:
     ```
     Content-Type:application/json
     X-Auth-Token:<INGEST_TOKEN>
     ```
   - Body:
     ```json
     {"coordinates": "%gl_coordinates", "time": "%formatted"}
     ```

`coordinates` is a `"lat,lon"` string; `time` is a free-form timestamp
(e.g. `yyyy/MM/dd HH:mm`) shown back in the bot's reply.

Trigger the task from a time profile (for example every 15 minutes) or any other
Tasker profile.

## Telegram commands

| Command | Description |
| --- | --- |
| `/start`, `/help` | Usage information |
| `/where` | Latest location as a Google Maps link plus its timestamp |

Requests from users outside `ALLOWED_USER_IDS` get a generic denial.
