"""Qt side of the shared label geometry — QPrinter in, pixels out.

Separate module from ``geometry.py`` so the pure guard logic never pulls a
``QPrinter`` into its import path. Everything Qt-specific about putting a 20 mm
label on a page lives here, and every driver-based backend uses it, so a new
printer inherits the sizing and the safety guards instead of reimplementing them.
"""

from __future__ import annotations

from PyQt6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QImage, QPageLayout, QPageSize, QPainter
from PyQt6.QtPrintSupport import QPrinter

from .base import PrintResult, PrintStatus
from .geometry import (
    NO_PRINTABLE_AREA_BODY,
    NO_PRINTABLE_AREA_TITLE,
    QR_LABEL_SIZE_MM,
    LabelPlan,
    Margins,
    PrinterMetrics,
)

# Qt's page-size name for our custom media. Naming it makes the 20 mm square
# identifiable in driver dialogs instead of showing up as an anonymous "Custom".
PAGE_SIZE_NAME = "eFloStop 20mm"

COULD_NOT_START_TITLE = "Print Error"
COULD_NOT_START_BODY = (
    "Could not start printing. Check that the printer is available."
)


def prepare(printer: QPrinter) -> PrinterMetrics:
    """Force the 20 mm full-bleed page, then read back what the driver gave us.

    One entry point rather than separate configure/read calls, because the two
    have a hidden ordering dependency that is easy to get wrong and silent when
    you do: ``minimumMargins()`` reports in the page layout's *current* units,
    and it is the ``setPageMargins(..., Millimeter)`` call below that switches
    those units to millimetres. Read the margins first and a Fuji Xerox reports
    11.64 (points) instead of 4.11 (mm), the printable area computes negative,
    and a perfectly good printer is rejected with "no printable area".

    Resolution is read back rather than assumed for the same reason: a backend
    that trusts a configured DPI while the driver is running at another would
    lay 160 logical units onto a 600 dpi surface and print a 6.8 mm QR with
    every guard green.
    """
    printer.setFullPage(True)
    printer.setPageSize(
        QPageSize(
            QSizeF(QR_LABEL_SIZE_MM, QR_LABEL_SIZE_MM),
            QPageSize.Unit.Millimeter,
            PAGE_SIZE_NAME,
            # ExactMatch keeps Qt from quietly snapping to a nearby standard
            # size. FuzzyOrientationMatch additionally transposes width/height,
            # which for a square is harmless but is a trap worth not inheriting.
            QPageSize.SizeMatchPolicy.ExactMatch,
        )
    )
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)

    layout = printer.pageLayout()
    dpi = printer.resolution()
    page = printer.pageRect(QPrinter.Unit.DevicePixel)
    margins = layout.minimumMargins()  # millimetres, thanks to the call above
    media = layout.pageSize().size(QPageSize.Unit.Millimeter)

    return PrinterMetrics(
        # The pixel rect and the millimetre size are read independently and must
        # stay that way — Qt takes the former from the driver's DEVMODE and the
        # latter from the layout, and they legitimately disagree.
        page_w_px=page.width(),
        page_h_px=page.height(),
        media_w_mm=media.width(),
        media_h_mm=media.height(),
        margins_mm=Margins(
            left=margins.left(),
            top=margins.top(),
            right=margins.right(),
            bottom=margins.bottom(),
        ),
        dpi=dpi,
        provenance="measured",
    )


def rasterize(image: QImage, side: float) -> QImage:
    """Scale the QR to `side` device pixels as pure black and white.

    For backends that pack their own bits (a raster/ZPL printer) rather than
    handing a rect to QPainter. Using this keeps "shared geometry" from meaning
    only a shared rectangle: two backends given the same LabelPlan produce the
    same pixels, which is the part that actually decides whether the label
    scans.

    Smooth scaling is off deliberately. On a 1-bit thermal head, anti-aliased
    grey edges get dithered into speckle and can cost a scan — and
    nearest-neighbour is what QPainter already does by default, so the two paths
    agree.
    """
    target = max(1, int(round(side)))
    return image.convertToFormat(QImage.Format.Format_Mono).scaled(
        target,
        target,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def draw(printer: QPrinter, image: QImage, plan: LabelPlan) -> PrintResult:
    """Paint the QR onto the prepared page, centred in the printable area.

    Failures are reported through the returned :class:`PrintResult` only — the
    caller raises exactly one dialog for it. Warning here as well would show the
    operator two identical modals for one failed print, where the tool has
    always shown one.
    """
    if plan.side <= 0:
        # run_guards already rules this out, but a backend could call draw()
        # directly; refusing beats painting a zero-size rect.
        return PrintResult(
            PrintStatus.ERROR, NO_PRINTABLE_AREA_TITLE, NO_PRINTABLE_AREA_BODY
        )

    painter = QPainter(printer)
    if not painter.isActive():
        # The printer went away between the availability check and here (powered
        # off, unplugged, spooler refused the job).
        return PrintResult(
            PrintStatus.ERROR, COULD_NOT_START_TITLE, COULD_NOT_START_BODY
        )

    try:
        x, y, w, h = plan.qr_rect
        painter.drawImage(QRectF(x, y, w, h), image)
    finally:
        # end() even if drawImage throws, or the QPrinter keeps an active
        # painter and every later print silently fails to start.
        painter.end()

    return PrintResult(PrintStatus.OK)
