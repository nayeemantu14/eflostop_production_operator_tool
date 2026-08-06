"""Tests for the shared 20 mm label geometry and print guards.

Deliberately Qt-free: these exercise the code that decides whether a label is
safe to print, so they must run everywhere and never risk the interpreter abort
that constructing a QPrinter without a QApplication causes.
"""

from app.services.printing.geometry import (
    DECLARED_MEDIA_TITLE,
    DECLARED_UNDERSIZE_TITLE,
    MEDIA_SIZE_TITLE,
    NO_PRINTABLE_AREA_BODY,
    NO_PRINTABLE_AREA_TITLE,
    QR_LABEL_SIZE_MM,
    QR_MIN_PRINT_MM,
    UNDERSIZE_TITLE,
    GuardOutcome,
    Margins,
    PrinterMetrics,
    is_undersized,
    mm_to_px,
    plan_label,
    px_to_mm,
    run_guards,
)


class RecordingUi:
    """A GuardUi that records what it was asked and answers a fixed way."""

    def __init__(self, answer: bool = True):
        self.answer = answer
        self.confirms: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []

    def confirm(self, title: str, message: str) -> bool:
        self.confirms.append((title, message))
        return self.answer

    def warn(self, title: str, message: str) -> None:
        self.warnings.append((title, message))

    @property
    def dialog_count(self) -> int:
        return len(self.confirms) + len(self.warnings)


def metrics(
    *,
    dpi: int = 203,
    page_px: float | None = None,
    media_mm: float = 20.0,
    margin_mm: float = 0.0,
    provenance: str = "measured",
) -> PrinterMetrics:
    """A square page, defaulting to a perfect full-bleed 20 mm label."""
    px = page_px if page_px is not None else mm_to_px(media_mm, dpi)
    return PrinterMetrics(
        page_w_px=px,
        page_h_px=px,
        media_w_mm=media_mm,
        media_h_mm=media_mm,
        margins_mm=Margins(margin_mm, margin_mm, margin_mm, margin_mm),
        dpi=dpi,
        provenance=provenance,
    )


# --- Conversions ------------------------------------------------------------


def test_mm_to_px_rounds_to_nearest():
    # 20 mm at 203 dpi = 159.84 px -> rounds to 160 (20.02 mm), not 159 (19.90 mm).
    assert mm_to_px(20, 203) == 160
    assert mm_to_px(20, 300) == 236


def test_puqu_profile_thresholds_at_203dpi():
    # The AQ20's head is 203 dpi. These are the device-dot thresholds the guards
    # compare against on that printer.
    assert mm_to_px(QR_LABEL_SIZE_MM, 203) == 160  # 20 mm target
    assert mm_to_px(QR_MIN_PRINT_MM, 203) == 144  # 18 mm scannable floor


def test_px_to_mm_inverts_mm_to_px():
    for mm in (11.8, 18, 20):
        assert abs(px_to_mm(mm_to_px(mm, 203), 203) - mm) < 0.05


def test_undersize_uses_strict_less_than():
    # Exactly the floor prints; a hair under warns. A float just below the floor
    # must warn too — rounding `side` to an int here would let 143.6 px round up
    # to 144 and silently stop warning.
    floor = mm_to_px(QR_MIN_PRINT_MM, 203)  # 144
    assert not is_undersized(floor, 203)
    assert is_undersized(floor - 1, 203)
    assert is_undersized(143.6, 203)
    assert not is_undersized(mm_to_px(20, 203), 203)


# --- Planning ---------------------------------------------------------------


def test_full_bleed_printer_gets_the_whole_20mm():
    plan = plan_label(metrics())
    assert plan.side == 160
    assert plan.media_ok
    assert not plan.undersized
    assert abs(plan.actual_mm - 20) < 0.05


def test_hardware_margin_shrinks_the_qr_and_trips_the_guard():
    # A Fuji Xerox office MFP reports 4.11 mm minimum margins at 600 dpi. That
    # leaves ~11.9 mm of printable width — well under the scannable floor.
    plan = plan_label(metrics(dpi=600, page_px=475.0, margin_mm=4.11))
    assert plan.media_ok  # it does accept 20 mm media
    assert plan.undersized
    assert 11.5 < plan.actual_mm < 12.5


def test_page_px_is_not_derived_from_media_mm():
    # Qt reads the pixel rect from the driver's DEVMODE and the millimetre size
    # from the page layout, and they legitimately disagree: the Fuji reports
    # 475 px for a 20.0 mm page where mm_to_px(20, 600) is 472. Deriving one
    # from the other changes the printed size, so the plan must use the reading
    # it was given.
    assert mm_to_px(20, 600) == 472
    plan = plan_label(metrics(dpi=600, page_px=475.0))
    assert plan.printable_w == 475.0


def test_a4_fallback_is_caught_as_wrong_media():
    plan = plan_label(metrics(dpi=600, media_mm=210.0))
    assert not plan.media_ok


def test_media_tolerance_absorbs_driver_rounding():
    # 20.11 mm is a real page size a Windows driver returns for a 20 mm request.
    assert plan_label(metrics(media_mm=20.11)).media_ok
    assert not plan_label(metrics(media_mm=22.0)).media_ok


def test_zero_printable_area_yields_no_side():
    # Margins wider than the label itself.
    plan = plan_label(metrics(margin_mm=12.0))
    assert plan.side <= 0


def test_qr_is_centred_in_the_printable_area():
    plan = plan_label(metrics(dpi=600, page_px=475.0, margin_mm=4.11))
    x, y, w, h = plan.qr_rect
    assert w == h == plan.side
    # Equal gap left and right of the QR within the printable box.
    left_gap = x - plan.printable_x
    right_gap = (plan.printable_x + plan.printable_w) - (x + w)
    assert abs(left_gap - right_gap) < 1e-9


def test_qr_never_upscaled_beyond_20mm():
    # A printer with a huge printable area still prints exactly 20 mm.
    plan = plan_label(metrics(dpi=203, page_px=2000.0, media_mm=20.0))
    assert plan.side == mm_to_px(20, 203)


# --- Guards -----------------------------------------------------------------


def test_healthy_printer_shows_no_dialog():
    ui = RecordingUi()
    assert run_guards(plan_label(metrics()), ui) is GuardOutcome.PROCEED
    assert ui.dialog_count == 0


def test_no_printable_area_warns_and_aborts():
    ui = RecordingUi(answer=True)  # even a Yes-happy operator cannot proceed
    outcome = run_guards(plan_label(metrics(margin_mm=12.0)), ui)
    assert outcome is GuardOutcome.ABORTED
    assert ui.warnings == [(NO_PRINTABLE_AREA_TITLE, NO_PRINTABLE_AREA_BODY)]
    assert not ui.confirms


def test_wrong_media_and_undersize_never_both_fire():
    # 10 mm label stock loaded on a full-bleed printer is BOTH the wrong media
    # AND too small to scan. WI-VALVE-001 §6.6 tells the operator they get "one
    # of two warnings" — stacking both would make the controlled work
    # instruction wrong, so media size wins and undersize stays quiet.
    ui = RecordingUi(answer=True)
    plan = plan_label(metrics(media_mm=10.0))
    assert not plan.media_ok  # both conditions genuinely hold
    assert plan.undersized
    assert run_guards(plan, ui) is GuardOutcome.PROCEED
    assert ui.dialog_count == 1
    assert ui.confirms[0][0] == MEDIA_SIZE_TITLE


def test_an_a4_fallback_warns_about_media_not_size():
    # A printer that ignored the 20 mm request and used A4 has a huge printable
    # area, so only the media guard is relevant.
    ui = RecordingUi(answer=True)
    plan = plan_label(metrics(dpi=600, media_mm=210.0, margin_mm=5.0))
    assert not plan.media_ok
    assert not plan.undersized  # the QR itself would still be a full 20 mm
    run_guards(plan, ui)
    assert ui.dialog_count == 1
    assert ui.confirms[0][0] == MEDIA_SIZE_TITLE


def test_declining_a_guard_aborts_the_print():
    ui = RecordingUi(answer=False)
    plan = plan_label(metrics(dpi=600, page_px=475.0, margin_mm=4.11))
    assert run_guards(plan, ui) is GuardOutcome.ABORTED
    assert ui.confirms[0][0] == UNDERSIZE_TITLE


def test_guard_titles_are_frozen():
    # WI-VALVE-001 §6.6 reproduces these verbatim and trains operators on which
    # is which. Changing one invalidates a controlled document.
    assert NO_PRINTABLE_AREA_TITLE == "Print Error"
    assert MEDIA_SIZE_TITLE == "Label size is not 20 mm"
    assert UNDERSIZE_TITLE == "QR would print under 20 mm"
    assert NO_PRINTABLE_AREA_BODY == (
        "The printer reported no printable area, so the 20 mm label "
        "could not be rendered. Select the 20 mm label media in Printer "
        "Setup and try again."
    )


def test_undersize_message_reports_the_actual_millimetres():
    ui = RecordingUi(answer=True)
    run_guards(plan_label(metrics(dpi=600, page_px=475.0, margin_mm=4.11)), ui)
    assert "11.9 mm" in ui.confirms[0][1]


def test_declared_metrics_get_honest_wording():
    # A socket backend has no driver to ask, so blaming "this printer's
    # non-printable border" for a configured value would misdirect the operator.
    ui = RecordingUi(answer=True)
    plan = plan_label(metrics(media_mm=50.0, provenance="declared"))
    run_guards(plan, ui)
    assert ui.confirms[0][0] == DECLARED_MEDIA_TITLE
    assert "configured" in ui.confirms[0][1].lower()

    ui2 = RecordingUi(answer=True)
    run_guards(plan_label(metrics(margin_mm=2.0, provenance="declared")), ui2)
    assert ui2.confirms[0][0] == DECLARED_UNDERSIZE_TITLE


def test_declared_metrics_still_abort_on_no_printable_area():
    # The hard stop is provenance-independent.
    ui = RecordingUi(answer=True)
    plan = plan_label(metrics(margin_mm=12.0, provenance="declared"))
    assert run_guards(plan, ui) is GuardOutcome.ABORTED
