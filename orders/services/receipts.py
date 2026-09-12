"""Composition of the receipt content (ESC/POS).

Only the **kitchen** ticket is produced here: no prices, just the comanda it
belongs to, where to deliver it and the items to prepare — each with the
waiter's note for that line, when it has one. The customer/bill receipt is a
separate concern that the close-flow will own.

The text is normalized to ASCII because thermal printers typically use DOS code
pages (CP437/CP850), where accented characters come out wrong.

Ported from the Okinawa POS project (``app/services/receipts.py``), which has
been printing on Elgin i9 / Bematech hardware in production.
"""
import textwrap
import unicodedata

from django.conf import settings
from django.utils import timezone

# --- ESC/POS commands -----------------------------------------------------
ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"  # resets the printer
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
SIZE_NORMAL = GS + b"!\x00"
SIZE_DOUBLE = GS + b"!\x11"  # double width and height
SIZE_TALL = GS + b"!\x01"  # double height
CUT = GS + b"VB\x00"  # full cut, with paper feed

SUBSTITUTIONS = {
    "ç": "c", "Ç": "C", "ñ": "n", "Ñ": "N",
    "°": "o", "º": "o", "ª": "a", "²": "2", "³": "3", "¹": "1",
    "–": "-", "—": "-", "…": "...",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "€": "EUR", "£": "GBP",
}


def normalize_text(text: str | None) -> str:
    """Strip accents and symbols the thermal printer does not reproduce well."""
    if not text:
        return ""
    for old, new in SUBSTITUTIONS.items():
        text = text.replace(old, new)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Anything left outside printable ASCII becomes '?' rather than binary junk.
    return text.encode("ascii", errors="replace").decode("ascii")


class ReceiptBuilder:
    """Assembles the receipt lines within the paper width."""

    def __init__(self, width: int | None = None, margin: int | None = None):
        paper = width or settings.KARAOKE_RECEIPT_WIDTH
        left = settings.KARAOKE_RECEIPT_LEFT_MARGIN if margin is None else margin

        # The margin must never swallow the whole paper.
        self.margin = max(0, min(left, paper - 8))

        # `width` is the usable content width: added to the margin, it gives the
        # paper width. That way right alignment (lr) and the dashed rules still
        # end on the same column as before.
        self.width = paper - self.margin
        self.parts: list[bytes] = [INIT]

    # -- primitives ------------------------------------------------------
    def raw(self, command: bytes) -> "ReceiptBuilder":
        self.parts.append(command)
        return self

    def text(self, text: str = "", margin: bool = True) -> "ReceiptBuilder":
        """Emit one line, with the left margin by default.

        ``margin=False`` is used on centred lines: it is the printer itself that
        centres them, over the full paper width, so leading spaces would only
        throw the centring off.
        """
        prefix = " " * self.margin if margin else ""
        content = prefix + normalize_text(text)
        self.parts.append(content.encode("ascii", errors="replace") + b"\n")
        return self

    def blank(self, how_many: int = 1) -> "ReceiptBuilder":
        self.parts.append(b"\n" * how_many)
        return self

    def rule(self, char: str = "-") -> "ReceiptBuilder":
        return self.text(char * self.width)

    def center(self, text: str) -> "ReceiptBuilder":
        return self.raw(ALIGN_CENTER).text(text, margin=False).raw(ALIGN_LEFT)

    def title(self, text: str) -> "ReceiptBuilder":
        return (
            self.raw(ALIGN_CENTER + SIZE_DOUBLE + BOLD_ON)
            .text(text, margin=False)
            .raw(SIZE_NORMAL + BOLD_OFF + ALIGN_LEFT)
        )

    def bold(self, text: str) -> "ReceiptBuilder":
        return self.raw(BOLD_ON).text(text).raw(BOLD_OFF)

    def wrapped(self, text: str, indent: str = "") -> "ReceiptBuilder":
        """Wrap long text over several lines without breaking words in half."""
        width = max(8, self.width - len(indent))
        for line in textwrap.wrap(normalize_text(text), width) or [""]:
            self.text(indent + line)
        return self

    def lr(self, left: str, right: str, bold: bool = False) -> "ReceiptBuilder":
        """One line with text on the left and a value aligned to the right."""
        left, right = normalize_text(left), normalize_text(right)
        space = self.width - len(left) - len(right)
        if space < 1:
            left = left[: max(0, self.width - len(right) - 1)]
            space = max(1, self.width - len(left) - len(right))
        line = left + " " * space + right
        return self.bold(line) if bold else self.text(line)

    def cut(self) -> "ReceiptBuilder":
        # Feed before cutting so the paper clears the guillotine.
        return self.blank(4).raw(CUT)

    # -- output ----------------------------------------------------------
    def to_bytes(self) -> bytes:
        return b"".join(self.parts)

    def to_text(self) -> str:
        """Readable version for the screen, simulating the printer alignment.

        Centred lines come out centred here too: without that the preview would
        show the header flush left, which is not what comes out on paper.
        """
        width = self.width + self.margin
        out: list[str] = []
        centered = False

        for part in self.parts:
            if part[:1] in (ESC, GS):
                if ALIGN_CENTER in part:
                    centered = True
                elif ALIGN_LEFT in part:
                    centered = False
                continue

            raw = part.decode("ascii", errors="replace")
            for line in raw.split("\n")[:-1]:
                if centered and line.strip():
                    line = line.strip().center(width).rstrip()
                out.append(line)

        return "\n".join(out).rstrip("\n")


def _header(b: ReceiptBuilder, order) -> None:
    """Who the ticket belongs to, where it goes and when it was placed.

    The comanda is the headline — it is what the kitchen calls out and what the
    waiter matches the plate against. The table rides underneath and only when
    the order actually has one: since #224 it is optional delivery context, not
    what the order hangs off.
    """
    b.title(order.tab.name)
    b.center("** COZINHA **")
    b.rule("=")

    # Just the order number, in double size: it is the one thing that has to be
    # readable from the pass at arm's length.
    b.raw(ALIGN_CENTER + SIZE_DOUBLE + BOLD_ON)
    b.text(f"PEDIDO #{order.pk}", margin=False)  # centred by the printer
    b.raw(SIZE_NORMAL + BOLD_OFF + ALIGN_LEFT)
    b.rule("=")

    if order.table:
        b.text(f"Mesa: {order.table.name}")

    # `created_at` is stored in UTC (USE_TZ); the kitchen reads wall-clock time.
    placed = timezone.localtime(order.created_at) if order.created_at else None
    b.text(f"Hora: {placed.strftime('%d/%m/%Y %H:%M')}" if placed else "Hora: -")


def build_kitchen_receipt(order) -> ReceiptBuilder:
    """Kitchen ticket for an :class:`orders.models.Order`: items, no prices.

    Prices are deliberately absent — the kitchen prepares food, the bill is the
    comanda's business — so ``OrderItem.unit_price`` never reaches the paper.
    Each line's note (#229) prints under its item, and only when there is one.

    Since #237 each kitchen line is annotated when done: a prepared line
    (``line.is_prepared`` True, the flag #236 adds to :class:`OrderItem`) is
    prefixed ``[FEITO] `` on the ticket so the kitchen can see at a glance
    which lines are already crossed off. The note still rides under the item
    unchanged. Done lines stay on the ticket, marked — the line list, totals
    and layout are otherwise untouched. If the ``is_prepared`` flag is absent
    on a line (an older row or a plain object), every line is treated as not
    prepared.
    """
    b = ReceiptBuilder()
    _header(b, order)

    b.rule()
    b.bold("PREPARAR")
    b.rule()

    lines = list(order.items.all())
    for line in lines:
        # The per-line "done" marker (#237): prefix the wrapped line with
        # "[FEITO] " when the line is prepared. ``getattr`` with a default of
        # False keeps this safe for callers that hand in a plain object or a
        # row from before the flag existed.
        is_prepared = getattr(line, "is_prepared", False)
        prefix = "[FEITO] " if is_prepared else ""
        b.raw(SIZE_TALL + BOLD_ON)
        b.wrapped(f"{prefix}{line.quantity}x {line.item.name}")
        b.raw(SIZE_NORMAL + BOLD_OFF)
        # The waiter's note for this line (#229), in normal size and indented
        # under the item so it reads as belonging to it and never competes
        # with the item name for the cook's eye. `wrapped` does the work: it
        # normalizes the accents ("com gelo e limao") and folds a long request
        # over as many lines as the paper needs instead of truncating it.
        if line.notes:
            b.wrapped(f"- {line.notes}", indent="   ")
        b.blank()

    b.rule()
    b.lr("Total de itens:", str(len(lines)))
    b.lr("Total de unidades:", str(sum(line.quantity for line in lines)))
    b.cut()
    return b


def strip_escpos(payload: bytes) -> str:
    """Strip the ESC/POS commands from a byte stream, leaving only the text.

    Used to produce the readable copy of the receipt in printerless mode.
    """
    # How many bytes each command takes up, prefix included.
    sizes = {
        (0x1B, 0x40): 2,  # ESC @  — initialize
        (0x1B, 0x61): 3,  # ESC a n — alignment
        (0x1B, 0x45): 3,  # ESC E n — bold
        (0x1B, 0x64): 3,  # ESC d n — feed lines
        (0x1D, 0x21): 3,  # GS ! n  — font size
        (0x1D, 0x56): 4,  # GS V m n — cut
    }

    out = bytearray()
    i = 0
    while i < len(payload):
        byte = payload[i]
        if byte in (0x1B, 0x1D) and i + 1 < len(payload):
            size = sizes.get((byte, payload[i + 1]))
            if size:
                i += size
                continue
            i += 2  # unknown command: drop the prefix and carry on
            continue
        out.append(byte)
        i += 1

    return out.decode("ascii", errors="replace")


def kitchen_receipt_bytes(order) -> bytes:
    return build_kitchen_receipt(order).to_bytes()


def kitchen_receipt_text(order) -> str:
    return build_kitchen_receipt(order).to_text()
