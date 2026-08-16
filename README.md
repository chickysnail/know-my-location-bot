# Know My Location Bot

A Telegram bot with an HTTP ingest endpoint. A phone automation app (Tasker) posts
location points to the service; anyone who knows the access password can ask the bot
where you are and gets your recent track as Google Maps links.

- `POST /ingest` — stores a location point, authenticated by a shared secret header
- `GET /health` — liveness probe
- `/where` — recent locations: the current position plus the earlier points and a
  Google Maps route link through the whole track

Points are stored in SQLite and deleted automatically after `RETENTION_DAYS`
(7 by default), so a leaked password can never expose more than the last week.

No personal data lives in this repository: tokens, the password, admin IDs and the
database path all come from environment variables.

## Access model

| Who | How |
| --- | --- |
| Anyone | sends `/start <password>` (or just the password as a message); access is remembered |
| Admins | listed in `ADMIN_USER_IDS`, never need the password |

Every location request — and every wrong password attempt — is reported to the admins
by DM, including the requester's username, user id and time.

Admin commands:

| Command | Description |
| --- | --- |
| `/users` | who has access, request counts, last request |
| `/block <user_id\|@username>` | revoke access; blocked users are ignored silently |
| `/unblock <user_id\|@username>` | restore access |

Usernames only work for people who already unlocked the bot (Telegram does not let
bots look up arbitrary usernames); otherwise use the numeric user id shown by
`/users` or in the admin notification.

## Accuracy handling

Tasker reports GPS accuracy in metres (`%gl_coordinates_accuracy`). The service:

- rejects points worse than `MAX_ACCURACY_M` (default 500 m) so a bad fix cannot
  teleport the track across town;
- shows `±25 m` next to each point so readers know how precise it is.

## Setup

### Prerequisites

- Python 3.12+
- Telegram Bot Token ([BotFather](https://t.me/botfather))

### Installation

```bash
git clone https://github.com/chickysnail/know-my-location-bot.git
cd know-my-location-bot
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
| `INGEST_TOKEN` | Shared secret sent by Tasker in the `X-Auth-Token` header. Invent one, e.g. `openssl rand -hex 24` |
| `ACCESS_PASSWORD` | Password that grants a Telegram user access to `/where` |
| `ADMIN_USER_IDS` | Comma-separated admin user IDs (notifications, `/block`, `/users`) |
| `ALLOWED_USER_IDS` | Optional pre-approved user IDs that skip the password |
| `DATABASE_PATH` | SQLite file path (default `./locations.db`) |
| `RETENTION_DAYS` | How long points are kept (default `7`) |
| `MAX_ACCURACY_M` | Reject points with worse accuracy (default `500`) |
| `HISTORY_HOURS` / `HISTORY_POINTS` | Size of the track `/where` returns (default `6` h / `10` points) |
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
3. Under **Settings → Networking**, click **Generate Domain**. The domain Railway
   shows there is your ingest endpoint: `https://<your-domain>/ingest`.
4. Set the service variables:

   ```
   TELEGRAM_BOT_TOKEN=<from BotFather>
   INGEST_TOKEN=<a long random string>
   ACCESS_PASSWORD=<the password you share with friends>
   ADMIN_USER_IDS=<your Telegram user ID>
   DATABASE_PATH=/data/locations.db
   ```

   `PORT` is provided by Railway; the ingest server binds to it.

5. Still under **Settings → Networking**, make sure the generated domain's target
   port is the one the server listens on (`8080`, or whatever `PORT` is). Railway
   sometimes guesses a random port, which makes every request return `502`.

Check the deployment with `curl https://<your-domain>/health` → `ok`.

## Tasker setup

Create a task that reads the current location and posts it:

1. **Get Location v2** — fills `%gl_coordinates` ("lat,lon") and
   `%gl_coordinates_accuracy` (metres).
2. **HTTP Request**:
   - Method: `POST`
   - URL: `https://<your-railway-domain>/ingest`
   - Headers:
     ```
     Content-Type:application/json
     X-Auth-Token:<INGEST_TOKEN>
     ```
   - Body:
     ```json
     {"coordinates": "%gl_coordinates", "accuracy": "%gl_coordinates_accuracy", "time": "%formatted"}
     ```

`coordinates` is required; `accuracy` and `time` are optional (`time` is any
timestamp string, e.g. `yyyy/MM/dd HH:mm`, and is echoed back in the bot's reply).

Trigger the task from a time profile (for example every 15 minutes).

On failure the response body says why, and the reason is logged by the service:

| Response | Cause |
| --- | --- |
| `401 unauthorized` | `X-Auth-Token` does not match `INGEST_TOKEN` |
| `400 Tasker variable %gl_coordinates was not set` | **Get Location v2** did not run before the HTTP Request, or timed out |
| `400 coordinates must be numeric` | the body reached the server with a non-coordinate value |
| `{"status": "discarded"}` | the fix was worse than `MAX_ACCURACY_M` |

## Telegram commands

| Command | Description |
| --- | --- |
| `/start <password>` | Unlock the bot |
| `/where` | Recent locations plus a route link |
| `/help` | Usage information |
| `/users`, `/block`, `/unblock` | Admin only |
