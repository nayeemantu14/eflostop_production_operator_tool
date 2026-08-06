"""Shared 20 mm label geometry and print guards — pure Python, no Qt.

Every printer backend routes through this module, so the manufacturing spec and
the operator safety guards are defined exactly once. Keeping it Qt-free is
deliberate: constructing a ``QPrinter`` before a ``QApplication`` exists aborts
the interpreter outright (0xC0000409, not a catchable exception), so the guard
logic that matters most has to be testable without importing any Qt printing
type at all.

The Qt side lives in ``qt_geometry.py``; it feeds :class:`PrinterMetrics` in and
paints whatever :func:`plan_label` decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Protocol

# Fixed physical size of the printed QR label, in millimetres. Confirmed with
# the manufacturing partner: every device's QR label (hub, valve, leak sensor)
# is 20 mm x 20 mm. Too small for side text, so the printed label is QR-only.
QR_LABEL_SIZE_MM = 20

# Below this printed size the QR's modules get too small to scan reliably on a
# ~203 dpi thermal printer, so the operator is warned. A full-bleed 20 mm label
# printer prints the full 20 mm and never trips this; it catches a mis-selected
# printer whose hardware margin shrinks the QR (e.g. an office printer -> ~12 mm).
QR_MIN_PRINT_MM = 18

# How far the media may deviate from 20 mm before the operator is warned. A whole
# millimetre of slack absorbs driver rounding without letting an A4 page through.
MEDIA_TOLERANCE_MM = 1.0


# Where a backend's numbers came from. "measured" means the printer driver
# reported them, so the media/undersize warnings describe real hardware and use
# the wording the controlled work instruction (WI-VALVE-001 §6.6) quotes.
# "declared" means they were read out of config — a socket/raster backend has no
# driver to ask. Echoing config back as a hardware warning would be a lie, and a
# guard that cannot fire is worse than no guard, so declared metrics get their
# own honest checks instead. See run_guards().
Provenance = Literal["measured", "declared"]


class GuardOutcome(Enum):
    """What the guards decided about a print."""

    PROCEED = "proceed"
    ABORTED = "aborted"  # a hard stop, or the operator declined a warning


@dataclass(frozen=True)
class Margins:
    """Non-printable border, in millimetres."""

    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass(frozen=True)
class PrinterMetrics:
    """What a backend knows about the page it is about to print on.

    ``page_rect_px`` and ``media_size_mm`` are two INDEPENDENT readings and
    neither may be derived from the other. Qt sources the pixel rect from the
    driver's DEVMODE and the millimetre size from the page layout, and they
    disagree on purpose: a Fuji Xerox at 600 dpi reports a 475 px page for a
    20.0 mm media where ``mm_to_px(20, 600)`` is 472. Computing one from the
    other changes the printed size by ~0.13 mm and shifts the warning text the
    operator reads.
    """

    page_w_px: float
    page_h_px: float
    media_w_mm: float
    media_h_mm: float
    margins_mm: Margins
    dpi: int
    provenance: Provenance = "measured"


@dataclass(frozen=True)
class LabelPlan:
    """Where and how big the QR goes, plus what the guards found."""

    printable_x: float
    printable_y: float
    printable_w: float
    printable_h: float
    side: float
    media_ok: bool
    undersized: bool
    actual_mm: float
    metrics: PrinterMetrics

    @property
    def qr_rect(self) -> tuple[float, float, float, float]:
        """(x, y, w, h) of the QR, centred in the printable area."""
        return (
            self.printable_x + (self.printable_w - self.side) / 2,
            self.printable_y + (self.printable_h - self.side) / 2,
            self.side,
            self.side,
        )


class GuardUi(Protocol):
    """How the guards talk to the operator.

    Two methods, because two of the three guards are OK-only warnings that abort
    unconditionally and one is a Yes/No question. Collapsing them into a single
    yes/no callable would render "the printer reported no printable area" with a
    Yes button that does nothing.
    """

    def confirm(self, title: str, message: str) -> bool: ...

    def warn(self, title: str, message: str) -> None: ...


def mm_to_px(mm: float, dpi: int) -> int:
    """Convert millimeters to device pixels at the given DPI.

    Rounds (not truncates) so the physical size lands on the spec rather
    than systematically a hair under it (e.g. 20 mm -> 20.02 mm not 19.90 mm
    at 203 dpi).
    """
    return round(mm / 25.4 * dpi)


def px_to_mm(px: float, dpi: int) -> float:
    """Convert device pixels to millimetres (inverse of mm_to_px)."""
    return px * 25.4 / dpi


def is_undersized(side_px: float, dpi: int) -> bool:
    """True if the printed QR would fall below the scannable floor.

    Shared by the print guard and its tests so the boundary can't silently
    drift.
    """
    return side_px < mm_to_px(QR_MIN_PRINT_MM, dpi)


def plan_label(metrics: PrinterMetrics) -> LabelPlan:
    """Work out where the QR goes on a 20 mm x 20 mm label.

    The manufacturing spec fixes every device's QR label at ``QR_LABEL_SIZE_MM``
    square — too small for side text, so the label is QR-only. The page has
    already been forced to a 20 mm square full-bleed by the caller so the output
    matches the label stock regardless of the printer's saved page setup; the QR
    is then centred and scaled to fill the printable area. The QR image already
    carries a 4-module quiet zone, which becomes the required white border.
    Sizing is done in millimetres and converted to device pixels via the
    printer's DPI, so the physical size is identical on every printer regardless
    of resolution.
    """
    dpi = metrics.dpi
    m = metrics.margins_mm

    # In full-bleed mode the page rect is the whole 20 mm media (origin at the
    # media corner). It does NOT reflect the printer's hardware non-printable
    # border — that is exposed only via the driver's minimum margins — so those
    # are read separately and the draw area is shrunk to what the printer can
    # actually mark. On a true full-bleed label printer the margins are ~0 and
    # the QR fills the full 20 mm; a printer that cannot mark to the edge fits
    # the QR inside the printable area instead of clipping it — and if that
    # pushes the QR under 20 mm the operator is warned (see the size check
    # below).
    #
    # The rounding here is deliberately asymmetric and must stay that way: the
    # offsets round each margin on its own, while the extents round the SUM in
    # one call. Rounding the two edges separately and adding them can differ by
    # a pixel from rounding their sum, which would move the printed size off
    # what the current tool produces.
    printable_x = mm_to_px(m.left, dpi)
    printable_y = mm_to_px(m.top, dpi)
    printable_w = metrics.page_w_px - mm_to_px(m.left + m.right, dpi)
    printable_h = metrics.page_h_px - mm_to_px(m.top + m.bottom, dpi)

    # Fit the QR to the 20 mm target, never exceeding the printable area. Stays
    # a float when clamped — rounding it to an int would let a QR that is a hair
    # under the 18 mm floor round up to exactly the floor and stop warning.
    target_px = mm_to_px(QR_LABEL_SIZE_MM, dpi)
    side = min(target_px, printable_w, printable_h)

    # The media the driver actually accepted. Setting a 20 mm page size is a
    # request, not a guarantee: a driver may reject the custom size and fall back
    # to a larger default page (Letter/A4), which would print a correct-size QR
    # centred off the physical label. Catch that instead of silently wasting
    # label stock.
    media_ok = (
        abs(metrics.media_w_mm - QR_LABEL_SIZE_MM) <= MEDIA_TOLERANCE_MM
        and abs(metrics.media_h_mm - QR_LABEL_SIZE_MM) <= MEDIA_TOLERANCE_MM
    )

    # A printer that accepts 20 mm media but cannot mark to the edge shrinks the
    # QR. A true full-bleed label printer has ~0 margin so side == target and
    # this stays False; a mis-selected office printer (several mm of border)
    # shrinks the QR below the scannable floor and trips it.
    undersized = is_undersized(side, dpi)

    return LabelPlan(
        printable_x=printable_x,
        printable_y=printable_y,
        printable_w=printable_w,
        printable_h=printable_h,
        side=side,
        media_ok=media_ok,
        undersized=undersized,
        actual_mm=px_to_mm(side, dpi),
        metrics=metrics,
    )


# --- Guard messages ---------------------------------------------------------
# These strings are a compatibility surface, not cosmetics: WI-VALVE-001 §6.6
# reproduces the titles verbatim and trains operators on which one means what.
# Changing one silently invalidates a controlled work instruction.

NO_PRINTABLE_AREA_TITLE = "Print Error"
NO_PRINTABLE_AREA_BODY = (
    "The printer reported no printable area, so the 20 mm label "
    "could not be rendered. Select the 20 mm label media in Printer "
    "Setup and try again."
)

MEDIA_SIZE_TITLE = "Label size is not 20 mm"
UNDERSIZE_TITLE = "QR would print under 20 mm"

# The declared-metrics equivalents. Different wording because there is no driver
# behind these numbers — saying "this printer's non-printable border" about a
# value typed into a YAML file would misdirect the operator's troubleshooting.
DECLARED_MEDIA_TITLE = "Configured label size is not 20 mm"
DECLARED_UNDERSIZE_TITLE = "Configured QR size is under 20 mm"


def media_size_message(plan: LabelPlan) -> str:
    return (
        f"The selected printer's page is {plan.metrics.media_w_mm:.1f} x "
        f"{plan.metrics.media_h_mm:.1f} mm, not the required 20 x 20 mm, so the "
        f"QR may print off the label.\n\nSelect the 20 mm label media in "
        f"Printer Setup, or print anyway?"
    )


def undersize_message(plan: LabelPlan) -> str:
    return (
        f"This printer's non-printable border shrinks the QR to only "
        f"{plan.actual_mm:.1f} mm instead of 20 mm, so it may not scan "
        f"reliably.\n\nSelect a full-bleed 20 mm label printer in Printer "
        f"Setup, or print anyway?"
    )


def declared_media_message(plan: LabelPlan) -> str:
    return (
        f"This printer is configured for a {plan.metrics.media_w_mm:.1f} x "
        f"{plan.metrics.media_h_mm:.1f} mm label, not the required 20 x 20 mm, "
        f"so the QR may print off the label.\n\nCorrect the label size in "
        f"Printer Setup, or print anyway?"
    )


def declared_undersize_message(plan: LabelPlan) -> str:
    return (
        f"The configured margins shrink the QR to only {plan.actual_mm:.1f} mm "
        f"instead of 20 mm, so it may not scan reliably.\n\nCorrect the margins "
        f"in Printer Setup, or print anyway?"
    )


def run_guards(plan: LabelPlan, ui: GuardUi) -> GuardOutcome:
    """Apply the three print guards, showing AT MOST ONE dialog.

    Order and exclusivity are part of the contract: WI-VALVE-001 §6.6 tells the
    operator they will get "one of two warnings", so the media and undersize
    checks are mutually exclusive rather than stacking two prompts.

    Which wording is used depends on ``metrics.provenance`` — see the note on
    :data:`Provenance`.
    """
    if plan.side <= 0:
        ui.warn(NO_PRINTABLE_AREA_TITLE, NO_PRINTABLE_AREA_BODY)
        return GuardOutcome.ABORTED

    declared = plan.metrics.provenance == "declared"

    if not plan.media_ok:
        title = DECLARED_MEDIA_TITLE if declared else MEDIA_SIZE_TITLE
        body = declared_media_message(plan) if declared else media_size_message(plan)
        return GuardOutcome.PROCEED if ui.confirm(title, body) else GuardOutcome.ABORTED

    if plan.undersized:
        title = DECLARED_UNDERSIZE_TITLE if declared else UNDERSIZE_TITLE
        body = declared_undersize_message(plan) if declared else undersize_message(plan)
        return GuardOutcome.PROCEED if ui.confirm(title, body) else GuardOutcome.ABORTED

    return GuardOutcome.PROCEED
