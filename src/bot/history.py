"""Formatting of location history into Telegram replies."""

from src.bot.storage.locations import Location

NO_DATA_TEXT = "No location points received yet."
MAX_ROUTE_POINTS = 10


def maps_route_url(points: list[Location]) -> str:
    """Google Maps directions URL drawing the track through every point."""
    trimmed = points[-MAX_ROUTE_POINTS:]
    legs = "/".join(f"{p.lat:.6f},{p.lon:.6f}" for p in trimmed)
    return f"https://www.google.com/maps/dir/{legs}"


def format_history(points: list[Location], hours: int) -> str:
    """Latest position first, then the older points and a route link."""
    if not points:
        return NO_DATA_TEXT

    latest = points[-1]
    lines = [
        f"\U0001f4cd Now ({latest.when}){_accuracy_suffix(latest)}",
        latest.maps_url,
    ]

    earlier = points[:-1]
    if earlier:
        lines.append("")
        lines.append(f"Earlier (last {hours}h):")
        for point in reversed(earlier):
            lines.append(f"\u2022 {point.when}{_accuracy_suffix(point)} — {point.maps_url}")
        lines.append("")
        lines.append(f"Full track on the map: {maps_route_url(points)}")

    return "\n".join(lines)


def _accuracy_suffix(point: Location) -> str:
    if point.accuracy_m is None:
        return ""
    return f" \u00b1{round(point.accuracy_m)} m"
