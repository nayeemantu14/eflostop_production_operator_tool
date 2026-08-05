"""Tests for the 20 mm QR label print geometry (QrPreview)."""

from app.ui.widgets.qr_preview import (
    QR_LABEL_SIZE_MM,
    QR_MIN_PRINT_MM,
    QrPreview,
)


def test_qr_label_size_is_20mm():
    # Manufacturing spec: every device's QR label is 20 mm x 20 mm.
    assert QR_LABEL_SIZE_MM == 20


def test_mm_to_px_rounds_to_nearest():
    # 20 mm at 203 dpi = 159.84 px -> rounds to 160 (20.02 mm), not 159 (19.90 mm).
    assert QrPreview._mm_to_px(20, 203) == 160
    # 20 mm at 300 dpi = 236.22 px -> 236.
    assert QrPreview._mm_to_px(20, 300) == 236


def test_mm_to_px_zero_is_zero():
    # A zero-length margin converts to zero pixels (invalid-margin edge case).
    assert QrPreview._mm_to_px(0, 203) == 0


def test_mm_to_px_is_dpi_proportional():
    # Doubling DPI doubles the pixel count for the same physical size.
    assert QrPreview._mm_to_px(20, 600) == 2 * QrPreview._mm_to_px(20, 300)


def test_px_to_mm_inverts_mm_to_px():
    # The undersize dialog reports mm via _px_to_mm — it must invert _mm_to_px.
    for mm in (11.8, 18, 20):
        px = QrPreview._mm_to_px(mm, 203)
        assert abs(QrPreview._px_to_mm(px, 203) - mm) < 0.05


def test_print_thresholds_at_203dpi():
    # The exact device-pixel thresholds the print guard compares against, at the
    # production label printer's 203 dpi. Locks them against silent drift.
    assert QrPreview._mm_to_px(QR_LABEL_SIZE_MM, 203) == 160  # 20 mm target
    assert QrPreview._mm_to_px(QR_MIN_PRINT_MM, 203) == 144   # 18 mm scannable floor


def test_undersize_floor_boundary():
    # Exercise the production predicate directly (not a copy), so flipping the
    # operator or moving the floor fails here: exactly the 18 mm floor prints
    # (no warning); a hair under it warns.
    dpi = 203
    floor = QrPreview._mm_to_px(QR_MIN_PRINT_MM, dpi)  # 144 px = 18 mm

    assert not QrPreview._is_undersized(floor, dpi)                        # 18.0 mm -> prints
    assert QrPreview._is_undersized(floor - 1, dpi)                        # just under -> warns
    assert not QrPreview._is_undersized(QrPreview._mm_to_px(20, dpi), dpi)  # 20 mm -> prints
    assert QrPreview._is_undersized(QrPreview._mm_to_px(11.8, dpi), dpi)    # Fuji 11.8 mm -> warns

