"""Tests for driving a centre-tracked ZPL printer (Zebra ZD410 and relatives).

Desktop label printers with spring-loaded media guides self-centre the roll under
a printhead much wider than a 20 mm label, so ZPL dot 0 is the left edge of the
*head*, not of the label. Without an offset the job is geometrically perfect and
prints entirely on bare liner — and neither the media guard nor the undersize
guard can detect that, because both only compare numbers the configuration gave
them.

Head widths from the ZD410 User Guide P1130712-01EN p.165: 56 mm at 203 dpi
(448 dots), 54 mm at 300 dpi (640 dots).
"""

import pytest
from PyQt6.QtGui import QImage

from app.services.printing import plan_label
from app.services.printing.backends.zpl_tcp import ZplOptions, ZplSocketBackend


def qr_image() -> QImage:
    img = QImage(410, 410, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    return img


def build(**opts) -> tuple[ZplSocketBackend, str]:
    backend = ZplSocketBackend({"host": "10.0.0.5", **opts})
    return backend, backend.build_zpl(qr_image(), plan_label(backend._metrics()))


def header(job: str) -> str:
    return job.split("^GFA")[0]


# --- Default behaviour is unchanged -----------------------------------------


def test_edge_justified_is_the_default():
    """An existing installation must not move when this option is added."""
    backend, job = build()
    assert ZplOptions().head_width_mm == 0.0
    assert backend.media_offset_dots() == 0
    assert "^FO0,0" in job
    assert "^PW160" in header(job)  # label width, as before


def test_head_width_zero_means_no_offset():
    backend, _job = build(head_width_mm=0.0)
    assert backend.head_width_dots() == 0
    assert backend.media_offset_dots() == 0


# --- Centre-tracked offset --------------------------------------------------


def test_zd410_203dpi_offset_matches_the_head_arithmetic():
    """56 mm head, 20 mm label at 203 dpi -> (448-160)/2 = 144 dots."""
    backend, job = build(head_width_mm=56.0)
    assert backend.head_width_dots() == 448
    assert backend.media_offset_dots() == 144
    assert "^FO144,0" in job


def test_zd410_300dpi_offset_matches_the_head_arithmetic():
    backend, job = build(head_width_mm=54.0, dpi=300)
    assert backend.head_width_dots() == 638
    assert backend.media_offset_dots() == 201
    assert "^FO201,0" in job


def test_offset_centres_the_qr_on_the_label():
    """The QR must land in the middle of where the label actually is."""
    backend, _job = build(head_width_mm=56.0)
    head = backend.head_width_dots()
    label = 160
    offset = backend.media_offset_dots()
    left_gap = offset
    right_gap = head - (offset + label)
    assert abs(left_gap - right_gap) <= 1, "label is not centred under the head"


def test_print_width_becomes_the_full_head_not_the_label():
    """^PW clips from the left edge of the head.

    Leaving ^PW at the label width would clip the entire offset image away —
    the QR would be positioned correctly and then thrown out.
    """
    _backend, job = build(head_width_mm=56.0)
    assert "^PW448" in header(job)
    assert "^PW160" not in header(job)


def test_a_wider_label_gets_a_smaller_offset():
    narrow, _ = build(head_width_mm=56.0, label_width_mm=20.0)
    wide, _ = build(head_width_mm=56.0, label_width_mm=50.0)
    assert wide.media_offset_dots() < narrow.media_offset_dots()


def test_label_as_wide_as_the_head_needs_no_offset():
    backend, _job = build(head_width_mm=56.0, label_width_mm=56.0)
    assert backend.media_offset_dots() == 0


def test_label_wider_than_the_head_never_goes_negative():
    """A nonsensical config must clamp, not emit a negative coordinate.

    The QR is still centred on the label by the shared plan — only the
    head-centring offset drops to zero, because there is nothing to offset by.
    """
    backend, job = build(head_width_mm=56.0, label_width_mm=60.0)
    assert backend.media_offset_dots() == 0
    plan_x = round(plan_label(backend._metrics()).qr_rect[0])
    assert f"^FO{plan_x},0" in job
    assert "^FO-" not in job


# --- Media sensing and runaway feed -----------------------------------------


def test_gap_sensing_is_forced_by_default():
    """A printer that last ran continuous stock would treat die-cut as a strip."""
    _backend, job = build()
    assert "^MNY" in header(job)


def test_gap_sensing_can_be_turned_off():
    _backend, job = build(gap_media=False)
    assert "^MNY" not in header(job)


def test_max_length_caps_a_runaway_feed():
    """The ZD410 default is 39 inches of stock before it gives up."""
    _backend, job = build(max_length_dots=406)
    assert "^ML406" in header(job)


def test_max_length_omitted_leaves_the_printer_default():
    _backend, job = build()
    assert "^ML" not in header(job)


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize("value", [10.0, 500.0, -5.0])
def test_implausible_head_width_is_rejected(value):
    with pytest.raises(ValueError):
        ZplOptions(head_width_mm=value)


def test_zero_head_width_is_allowed():
    assert ZplOptions(head_width_mm=0.0).head_width_mm == 0.0


@pytest.mark.parametrize("value", [50, 99999, -1])
def test_implausible_max_length_is_rejected(value):
    with pytest.raises(ValueError):
        ZplOptions(max_length_dots=value)


def test_invalid_stored_head_width_falls_back_instead_of_misprinting():
    backend = ZplSocketBackend({"host": "h", "head_width_mm": 999.0})
    assert backend.options()["head_width_mm"] == 0.0
    assert backend.media_offset_dots() == 0


# --- The guards still apply -------------------------------------------------


def test_offsetting_does_not_change_the_printed_size():
    """The offset moves the QR; it must not resize it."""
    plain, plain_job = build()
    offset, offset_job = build(head_width_mm=56.0)
    assert plain_job.split("^GFA,")[1][:20] == offset_job.split("^GFA,")[1][:20]
    assert plan_label(plain._metrics()).side == plan_label(offset._metrics()).side
