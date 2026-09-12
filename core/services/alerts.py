"""Server-side audible alert service.

Plays a fire-and-forget sound on the POS server host when a kitchen auto-print
attempt (#237) fails because no printer answers. The sound is meant for the
staff member near the server machine — it is *not* played in the browser — so
the playback path has no Python audio dependency and no dependency on a running
audio server: on Windows it uses the built-in ``winsound`` module, and on
Linux it shells out to whichever player executable it finds on ``PATH``
(``aplay``, ``paplay``, ``ffplay``, or an explicit command from the
``KARAOKE_ALERT_PLAYER_COMMAND`` environment variable).

The single public entry point is :func:`play_alert`. It spawns a daemon
thread that attempts playback and swallows every exception, so it never blocks
or fails the request that triggered it: a missing player, a missing file or a
broken audio subsystem all degrade to a log entry and nothing more. That way
the order-creation response cannot be delayed or broken by the alert, even
when the host has no audio hardware at all.
"""
import logging
import os
import platform
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Path to the built-in alert sound shipped with the project, so a fresh
# install can alert out of the box before any custom sound is uploaded. The
# asset lives under ``static/vendor/audio/alert.wav`` and is resolved relative
# to the Django project root (``settings.BASE_DIR``).
BUILTIN_ALERT_SOUND = "vendor/audio/alert.wav"


def _builtin_alert_path() -> Path:
    """Absolute path to the bundled alert sound."""
    return Path(settings.BASE_DIR) / "static" / BUILTIN_ALERT_SOUND


def resolve_alert_sound_path() -> Path:
    """Return the path to the sound file that should play.

    The uploaded sound on the singleton site-configuration row
    (:class:`core.models.Configuracao.alert_sound`) wins when one is present;
    otherwise the built-in bundled sound is used. The function is cheap and
    side-effect free so it can be called from the playback thread without
    holding the database connection open.
    """
    from core.models import get_config

    config = get_config()
    uploaded = config.alert_sound
    if uploaded:
        # ``FileField.name`` is the path relative to ``MEDIA_ROOT``. Resolve it
        # to an absolute filesystem path the player subprocess can read.
        return Path(settings.MEDIA_ROOT) / uploaded.name
    return _builtin_alert_path()


# --- Windows ---------------------------------------------------------------


def _play_windows(path: Path) -> bool:
    """Play the sound on Windows using the built-in ``winsound`` module.

    Returns ``True`` when the call was accepted (``winsound.PlaySound`` with
    ``SND_ASYNC`` returns immediately), ``False`` when the module is missing or
    the call raised. ``SND_FILENAME | SND_ASYNC`` is what makes it
    fire-and-forget at the OS level.
    """
    try:
        import winsound  # type: ignore

        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC,
        )
        return True
    except Exception:
        return False


# --- Linux -----------------------------------------------------------------


#: Candidate player commands tried in order on Linux, after any explicit
#: ``KARAOKE_ALERT_PLAYER_COMMAND``. Each entry is the executable name looked
#: up on ``PATH``; the argument list is built alongside.
LINUX_PLAYERS = [
    ("aplay", ["{path}"]),
    ("paplay", ["{path}"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", "{path}"]),
]


def _linux_command_candidates(path: Path) -> list[list[str]]:
    """Build the ordered list of player commands to try on Linux.

    An explicit ``KARAOKE_ALERT_PLAYER_COMMAND`` env var wins first: it is
    ``shlex``-split and every ``{path}`` placeholder is replaced with the
    resolved sound path. After that, the built-in list
    (:data:`LINUX_PLAYERS`) is tried in order, keeping only the executables
    that are actually found on ``PATH``.
    """
    candidates: list[list[str]] = []

    explicit = os.environ.get("KARAOKE_ALERT_PLAYER_COMMAND", "")
    if explicit:
        parts = shlex.split(explicit)
        candidates.append(
            [part.replace("{path}", str(path)) for part in parts]
        )

    for exe, args in LINUX_PLAYERS:
        if shutil.which(exe):
            candidates.append(
                [exe] + [a.replace("{path}", str(path)) for a in args]
            )

    return candidates


def _play_linux(path: Path) -> bool:
    """Try each Linux player candidate in order; the first that exits 0 wins.

    Returns ``True`` on success, ``False`` when no player is available or all
    of them fail. Each attempt is a short-lived subprocess with a timeout so a
    hung player cannot hold the daemon thread forever.
    """
    for command in _linux_command_candidates(path):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            continue
    return False


# --- public API ------------------------------------------------------------

#: Set once after the first time no player is available, so the warning is
#: logged a single time instead of on every failed alert.
_no_player_warned: bool = False


def _play_sound_sync(path: Path) -> None:
    """Run the playback synchronously, swallowing every exception.

    This is the body the daemon thread runs. It picks the right strategy for
    the host platform and attempts playback. When no player is available it
    logs a warning *once* and stays silent on subsequent calls. Any exception
    — a missing file, a broken player, a permissions error — is logged at
    warning level and swallowed, so the thread always exits cleanly.
    """
    global _no_player_warned

    try:
        if not path.exists():
            logger.warning(
                "Alerta sonoro: arquivo de som não encontrado em %s — "
                "tocando silenciosamente.",
                path,
            )
            return

        system = platform.system().lower()
        if system == "windows":
            played = _play_windows(path)
        else:
            played = _play_linux(path)

        if not played and not _no_player_warned:
            logger.warning(
                "Alerta sonoro: nenhum reprodutor de áudio disponível no "
                "servidor (tentou %s). Defina KARAOKE_ALERT_PLAYER_COMMAND "
                "ou instale aplay/paplay/ffplay. O alerta será silencioso.",
                "winsound" if system == "windows" else "aplay/paplay/ffplay",
            )
            _no_player_warned = True
    except Exception:
        logger.warning(
            "Alerta sonoro: falha ao tocar %s — exceção capturada, o "
            "fluxo do pedido não é afetado.",
            path,
            exc_info=True,
        )


def play_alert(sound_path: Optional[Path] = None) -> None:
    """Fire-and-forget playback of the configured alert sound.

    Spawns a daemon thread that attempts playback and never blocks the
    caller. Every exception is swallowed inside the thread, so a missing
    player, a missing file or a broken audio subsystem all degrade to a log
    entry and nothing more — the request that triggered the alert is never
    delayed or failed.

    When ``sound_path`` is ``None`` the path is resolved from the singleton
    site-configuration row: the uploaded sound, if any, otherwise the built-in
    bundled sound. Passing an explicit path is mainly for testing.
    """
    if sound_path is None:
        try:
            sound_path = resolve_alert_sound_path()
        except Exception:
            logger.warning(
                "Alerta sonoro: não foi possível resolver o caminho do "
                "som — tocando silenciosamente.",
                exc_info=True,
            )
            return

    thread = threading.Thread(
        target=_play_sound_sync,
        args=(sound_path,),
        daemon=True,
        name="karaoke-alert-sound",
    )
    thread.start()