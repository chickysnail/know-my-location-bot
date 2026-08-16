from src.bot.history import NO_DATA_TEXT, format_history, maps_route_url
from src.bot.storage.locations import Location


def point(lat: float, lon: float, when: str, accuracy: float | None = None) -> Location:
    return Location(
        lat=lat,
        lon=lon,
        recorded_at=when,
        received_at="2026-01-02 03:05:00 UTC",
        accuracy_m=accuracy,
    )


def test_format_history_empty() -> None:
    assert format_history([], 6) == NO_DATA_TEXT


def test_format_history_single_point_has_no_route() -> None:
    text = format_history([point(1.0, 2.0, "2026/01/02 03:04", 20.0)], 6)
    assert "https://maps.google.com/?q=1.0,2.0" in text
    assert "\u00b120 m" in text
    assert "maps/dir" not in text


def test_format_history_marks_latest_and_appends_route() -> None:
    points = [
        point(1.0, 1.0, "2026/01/02 01:00"),
        point(2.0, 2.0, "2026/01/02 02:00"),
        point(3.0, 3.0, "2026/01/02 03:00"),
    ]
    text = format_history(points, 6)
    lines = text.splitlines()

    assert lines[0].startswith("\U0001f4cd Now (2026/01/02 03:00)")
    assert lines[1] == "https://maps.google.com/?q=3.0,3.0"
    # Older points are listed newest first, latest excluded.
    assert "2026/01/02 02:00" in lines[4]
    assert "2026/01/02 01:00" in lines[5]
    assert text.endswith(maps_route_url(points))


def test_maps_route_url_orders_points_and_caps_length() -> None:
    points = [point(float(i), float(i), f"t{i}") for i in range(15)]
    url = maps_route_url(points)
    legs = url.removeprefix("https://www.google.com/maps/dir/").split("/")
    assert len(legs) == 10
    assert legs[0] == "5.000000,5.000000"
    assert legs[-1] == "14.000000,14.000000"
