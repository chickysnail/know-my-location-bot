import logging

from aiohttp import web

from src.bot.storage.locations import LocationStore

logger = logging.getLogger(__name__)

AUTH_HEADER = "X-Auth-Token"


class CoordinateError(ValueError):
    """Raised when the ingest payload does not contain usable coordinates."""


def parse_coordinates(raw: object) -> tuple[float, float]:
    """Parse Tasker's `%gl_coordinates` value ("lat,lon") into floats."""
    if not isinstance(raw, str):
        raise CoordinateError("coordinates must be a string")
    if "," not in raw:
        raise CoordinateError("coordinates must be 'lat,lon'")
    lat_raw, lon_raw = raw.split(",", 1)
    try:
        return float(lat_raw.strip()), float(lon_raw.strip())
    except ValueError as exc:
        raise CoordinateError("coordinates must be numeric") from exc


def parse_accuracy(raw: object) -> float | None:
    """Parse Tasker's `%gl_coordinates_accuracy` (metres); None when absent."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        accuracy = float(str(raw).strip())
    except ValueError:
        logger.warning("Ignoring unparsable accuracy value")
        return None
    return accuracy if accuracy >= 0 else None


def create_app(
    store: LocationStore,
    ingest_token: str,
    max_accuracy_m: float = 500.0,
) -> web.Application:
    async def health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def ingest(request: web.Request) -> web.Response:
        if request.headers.get(AUTH_HEADER) != ingest_token:
            logger.warning("Rejected ingest request with invalid token")
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid json"}, status=400)

        try:
            lat, lon = parse_coordinates(payload.get("coordinates"))
        except CoordinateError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        accuracy = parse_accuracy(payload.get("accuracy"))
        if accuracy is not None and accuracy > max_accuracy_m:
            # A fix this vague would drag the track across town.
            logger.info("Discarded point with accuracy %.0f m", accuracy)
            return web.json_response({"status": "discarded", "reason": "inaccurate"})

        recorded_at = payload.get("time")
        await store.insert(
            lat,
            lon,
            str(recorded_at) if recorded_at is not None else None,
            accuracy,
        )
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/ingest", ingest)
    return app


async def run_server(
    store: LocationStore,
    ingest_token: str,
    port: int,
    max_accuracy_m: float = 500.0,
) -> web.AppRunner:
    """Start the ingest HTTP server and return its runner for cleanup."""
    runner = web.AppRunner(create_app(store, ingest_token, max_accuracy_m))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Ingest server running on port %d", port)
    return runner
