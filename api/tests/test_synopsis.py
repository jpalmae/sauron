import io

from PIL import Image

from sauron_api.synopsis import build_contact_sheet, fmt_label


def _jpeg(color=(200, 100, 50)):
    img = Image.new("RGB", (640, 360), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def test_contact_sheet_grid():
    items = [(_jpeg(), f"label-{i}") for i in range(7)]
    sheet = build_contact_sheet(items, cols=4)
    img = Image.open(io.BytesIO(sheet))
    # 7 items, 4 cols -> 2 rows
    assert img.width == 4 * (320 + 6) + 6
    assert img.height == 2 * (200 + 18 + 6) + 6


def test_contact_sheet_empty():
    sheet = build_contact_sheet([])
    img = Image.open(io.BytesIO(sheet))
    assert img.width == 320


def test_contact_sheet_handles_bad_jpeg():
    items = [(b"not-a-jpeg", "broken"), (_jpeg(), "ok")]
    sheet = build_contact_sheet(items, cols=2)
    assert len(sheet) > 1000


def test_fmt_label():
    from datetime import UTC, datetime

    assert fmt_label(datetime(2026, 8, 8, 14, 30, tzinfo=UTC), "ALPR") == "08-08 14:30 ALPR"
