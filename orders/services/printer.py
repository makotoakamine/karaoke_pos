"""Delivery of the receipts to the thermal printer (ESC/POS).

Supports Windows (production) and Linux (development). The strategies are tried
in order and the first one that works ends the process:

1. ``KARAOKE_PRINTER_DEVICE`` — explicit device path (the most reliable).
2. The system print queue (CUPS on Linux, the spooler on Windows).
3. Common USB/serial devices.

If none of them works and ``KARAOKE_PRINTER_DRY_RUN`` is on, the receipt is
written to a file — that is how you develop without a printer attached.

Tested with Elgin i9 / Bematech and generic ESC/POS printers. Ported from the
Okinawa POS project (``app/services/printer.py``); the only adaptation is that
the settings now come from Django's ``settings`` instead of a bare module.
"""
import platform
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

# Queue names most commonly found in thermal-printer installations.
QUEUE_NAMES = [
    "thermal_printer",
    "ThermalPrinter",
    "Thermal Printer",
    "POSPrinter",
    "POS Printer",
    "ReceiptPrinter",
    "Receipt Printer",
    "Elgin_i9",
    "usb_printer",
]

DEVICES_LINUX = [
    "/dev/usb/lp0",
    "/dev/usb/lp1",
    "/dev/lp0",
    "/dev/ttyUSB0",
    "/dev/ttyACM0",
]

DEVICES_WINDOWS = ["LPT1", "COM1", "COM2", "COM3", "COM4"]


class PrinterError(Exception):
    """No printer was able to take the receipt."""


@dataclass
class PrintResult:
    method: str
    target: str

    @property
    def message(self) -> str:
        return f"Impresso via {self.method} ({self.target})."


def _write_device(path: str, payload: bytes) -> bool:
    """Write the raw bytes straight to the device. Returns False if unavailable."""
    try:
        with open(path, "wb") as device:
            device.write(payload)
            device.flush()
        return True
    except (FileNotFoundError, PermissionError, OSError):
        return False


def _run(command: list[str], payload: bytes | None = None, shell: bool = False) -> bool:
    try:
        result = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            timeout=20,
            shell=shell,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _dump_to_file(payload: bytes, label: str) -> PrintResult:
    """Write the receipt to disk (printerless mode)."""
    dump_dir = Path(settings.KARAOKE_PRINTER_DUMP_DIR)
    dump_dir.mkdir(parents=True, exist_ok=True)
    target = dump_dir / f"{label}.bin"
    target.write_bytes(payload)

    # A human-readable copy alongside it, without the ESC/POS commands.
    from orders.services.receipts import strip_escpos

    target.with_suffix(".txt").write_text(strip_escpos(payload), encoding="utf-8")
    return PrintResult("arquivo (modo de teste)", str(target))


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------


def _print_linux(payload: bytes) -> PrintResult | None:
    name = settings.KARAOKE_PRINTER_NAME
    queues = ([name] if name else []) + QUEUE_NAMES

    for queue in queues:
        # -o raw stops CUPS from trying to interpret the ESC/POS commands.
        if _run(["lp", "-d", queue, "-o", "raw", "-"], payload):
            return PrintResult("CUPS", queue)

    # The system default printer.
    if _run(["lp", "-o", "raw", "-"], payload):
        return PrintResult("CUPS", "impressora padrão")

    for device in DEVICES_LINUX:
        if Path(device).exists() and _write_device(device, payload):
            return PrintResult("device USB", device)

    return None


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def _print_windows(payload: bytes) -> PrintResult | None:
    # Preferred route: the spooler API in RAW mode (it preserves ESC/POS).
    try:
        import win32print  # type: ignore

        name = settings.KARAOKE_PRINTER_NAME or win32print.GetDefaultPrinter()
        handle = win32print.OpenPrinter(name)
        try:
            win32print.StartDocPrinter(handle, 1, ("Cupom Karaoke POS", None, "RAW"))
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, payload)
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)
        return PrintResult("spooler RAW", name)
    except ImportError:
        pass  # pywin32 not installed — fall through to the file-based methods.
    except Exception:
        pass  # printer busy or name invalid — try the alternatives.

    # Binary copy to the shared printer or to a local port.
    temporary = Path(tempfile.gettempdir()) / "karaoke_cupom.prn"
    temporary.write_bytes(payload)

    name = settings.KARAOKE_PRINTER_NAME
    targets = ([name] if name else []) + DEVICES_WINDOWS
    try:
        for target in targets:
            if _run(["cmd", "/c", "copy", "/b", str(temporary), target], shell=False):
                return PrintResult("copy /b", target)

        for device in DEVICES_WINDOWS:
            if _write_device(device, payload):
                return PrintResult("porta local", device)
    finally:
        temporary.unlink(missing_ok=True)

    return None


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def print_raw(payload: bytes, label: str = "cupom") -> PrintResult:
    """Send ESC/POS bytes to the printer.

    Raises :class:`PrinterError` when no printer answers and test mode is off.
    """
    if settings.KARAOKE_PRINTER_DRY_RUN:
        return _dump_to_file(payload, label)

    # An explicit device wins: that is what production usually configures.
    device = settings.KARAOKE_PRINTER_DEVICE
    if device and _write_device(device, payload):
        return PrintResult("device configurado", device)

    system = platform.system().lower()
    result = _print_windows(payload) if system == "windows" else _print_linux(payload)

    if result:
        return result

    if system == "windows":
        raise PrinterError(
            "Nenhuma impressora térmica respondeu. Verifique se ela está ligada e "
            "instalada no Windows, e defina KARAOKE_PRINTER_NAME com o nome exato "
            "da impressora."
        )
    raise PrinterError(
        "Nenhuma impressora térmica respondeu. Verifique a conexão USB, a fila do "
        "CUPS (lpstat -p) e as permissões de /dev/usb/lp0. Para desenvolver sem "
        "impressora, defina KARAOKE_PRINTER_DRY_RUN=1."
    )


def list_printers() -> list[str]:
    """Print queues visible on the system (used when diagnosing a bad setup)."""
    system = platform.system().lower()
    try:
        if system == "windows":
            import win32print  # type: ignore

            return [
                p[2]
                for p in win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                )
            ]
        output = subprocess.run(
            ["lpstat", "-a"], capture_output=True, text=True, timeout=10
        ).stdout
        return [line.split()[0] for line in output.splitlines() if line.strip()]
    except Exception:
        return []
