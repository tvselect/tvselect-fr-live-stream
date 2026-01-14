import json
import logging
import os
import re
import sentry_sdk
import subprocess
import sys

from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from channels_url import CHANNELS_URL
from security_sanitizer import global_sanitizer, scrub_event

def get_validated_user():
    """Securely get and validate the USER environment variable."""
    user = os.getenv("USER")
    if not user:
        raise ValueError("USER environment variable is not set")

    if not re.match(r'^[a-zA-Z0-9_-]+$', user):
        raise ValueError(f"Invalid USER environment variable: contains unsafe characters")

    home_path = Path.home()
    expected_home = Path(f"/home/{user}")

    if home_path != expected_home:
        user = home_path.name
        if not re.match(r'^[a-zA-Z0-9_-]+$', user):
            raise ValueError("Home directory name contains unsafe characters")

    return user

try:
    user = get_validated_user()
except ValueError as e:
    print(f"SECURITY ERROR: {e}", file=sys.stderr)
    sys.exit(1)

sys.path.append(f"/home/{user}/.config/tvselect-fr-live-stream")

from config import (
    CRYPTED_CREDENTIALS,
    SENTRY_MONITORING_SDK,
    TF1_EMAIL,
    TF1_PASSWORD,
)


def get_tf1_credentials_from_ev():
    """Retrieve TF1 credentials from environment variables if CRYPTED_CREDENTIALS is enabled."""
    if not CRYPTED_CREDENTIALS:
        return False

    try:
        username = os.environ.get("TF1_EMAIL")
        password = os.environ.get("TF1_PASSWORD")

        if username is None:
            logger.error("Failed to retrieve 'tf1 email' from environment variable.")
            return False

        if password is None:
            logger.error("Failed to retrieve 'tf1 password' from environment variable.")
            return False

        # No globals: credentials are returned securely
        return {"email": username, "password": password}

    except Exception:
        logger.exception("An error occurred while retrieving credentials from environment variables.")
        return False

def can_process_tf1_video(TF1_EMAIL, TF1_PASSWORD, channel):
    """Check if TF1 videos can be processed based on credential availability."""
    if CRYPTED_CREDENTIALS:
        return tf1_credentials_available
    else:
        return False

def subtract_one_minute(time_str: str) -> str:
    dt = datetime.strptime(time_str, "%H:%M")
    dt -= timedelta(minutes=1)
    return dt.strftime("%H:%M")

if SENTRY_MONITORING_SDK:
    sentry_sdk.init(
        dsn="https://0b40b1a24c605fd77fddb9219a45e594@o4508778574381056.ingest.de.sentry.io/4509938023268432",
        send_default_pii=False,
        include_local_variables=False,
        before_send=scrub_event,
        traces_sample_rate=0,
    )
    client = sentry_sdk.get_client()
    if client and client.options.get("traces_sample_rate", 0) > 0:
        sentry_sdk.profiler.start_profiler()


log_file = f"/home/{user}/.local/share/tvselect-fr-live-stream/logs/stream_record.log"
max_bytes = 10 * 1024 * 1024  # 10 MB
backup_count = 5

log_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
log_datefmt = "%d-%m-%Y %H:%M:%S"
formatter = logging.Formatter(log_format, log_datefmt)

log_handler.setFormatter(formatter)

logger = logging.getLogger("__name__")
logger.addHandler(log_handler)

sentry_handler = logging.StreamHandler()
sentry_handler.setLevel(logging.WARNING)

logger.addHandler(sentry_handler)
logger.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt=log_datefmt,
    handlers=[log_handler, sentry_handler]
)


try:
    with open(
        f"/home/{user}/.local/share/tvselect-fr-live-stream/info_progs.json",
        "r",
        encoding="utf-8",
    ) as jsonfile:
        data = json.load(jsonfile)
except FileNotFoundError:
    logger.error(
        "No info_progs.json file. Need to check curl command or "
        "internet connection. Exit programme."
    )
    exit()
except json.JSONDecodeError:
    logger.error(
        "Invalid JSON data in info_progs.json file. The file may be empty or corrupted."
    )
    exit()


creds = get_tf1_credentials_from_ev()
if creds:
    TF1_EMAIL = creds["email"]
    TF1_PASSWORD = creds["password"]

tf1_credentials_available = bool(creds)

sensitive_filter = global_sanitizer

log_handler.addFilter(sensitive_filter)
sentry_handler.addFilter(sensitive_filter)
logger.addFilter(sensitive_filter)

sensitive_filter.update_patterns({
    "TF1_EMAIL": TF1_EMAIL, "TF1_PASSWORD": TF1_PASSWORD
})

safe_env_base = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.environ["HOME"],
    "TZ": "Europe/Paris",
}

secure_env_with_creds = {
    **safe_env_base,
    "STREAMLINK_TF1_EMAIL": TF1_EMAIL,
    "STREAMLINK_TF1_PASSWORD": TF1_PASSWORD,
}

TF1_CHANNELS = ["TF1", "TMC", "TFX", "TF1 Séries Films", "L'Equipe"]

for video in data:

    try:
        channel_url = CHANNELS_URL[video["channel"]]
    except KeyError:
        logger.error(
            "La chaine " + video["channel"] + " n'est pas "
            "présente dans le fichier channels_urls.py"
        )
        continue

    channel_name = video["channel"].replace("'", "-").replace(" ", "_")

    cmd = ["at", video["start"]]

    if (
        video["channel"] in TF1_CHANNELS
        and can_process_tf1_video(TF1_EMAIL, TF1_PASSWORD, video["channel"])
    ):
        cmd_purge = ["at", subtract_one_minute(video["start"])]

        purge_script = (
            ". $HOME/.local/share/tvselect-fr-live-stream/.venv/bin/activate "
            "&& streamlink --tf1-purge-credentials "
            "--tf1-email \"$STREAMLINK_TF1_EMAIL\" "
            "--tf1-password \"$STREAMLINK_TF1_PASSWORD\" "
            "https://www.tf1.fr/tf1/direct"
        )
        with open(log_file, "a", encoding="utf-8") as log:
            launch = subprocess.Popen(
                cmd_purge,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
                env=secure_env_with_creds,
            )
            _, _ = launch.communicate(input=purge_script.encode())

        if launch.returncode != 0:
            logger.error("TF1 purge command failed for channel %s", video["channel"])
            continue

        record_script = (
            ". $HOME/.local/share/tvselect-fr-live-stream/.venv/bin/activate "
            f"&& timeout {video['duration']} streamlink "
            "--hls-live-edge 5 "
            f"-o $HOME/videos_select/{video['title'][:-3]}_{channel_name}.ts "
            "--tf1-email \"$STREAMLINK_TF1_EMAIL\" "
            "--tf1-password \"$STREAMLINK_TF1_PASSWORD\" "
            f"{channel_url} best >> ~/.local/share/tvselect-fr-live-stream/logs/"
            f"record_{video['title']}.log 2>&1"
        )

    elif (
        video["channel"] in TF1_CHANNELS
        and not can_process_tf1_video(TF1_EMAIL, TF1_PASSWORD, video["channel"])
    ):
        logger.error(
            f"The video {video['title'][:-3]}_{channel_name}.ts cannot be "
            "recorded because of TF1 missing credentials."
        )
        continue

    else:
        record_script = (
            ". $HOME/.local/share/tvselect-fr-live-stream/.venv/bin/activate "
            f"&& timeout {video['duration']} streamlink "
            "--hls-live-edge 5 "
            f"-o $HOME/videos_select/{video['title'][:-3]}_{channel_name}.ts "
            f"{channel_url} best >> ~/.local/share/tvselect-fr-live-stream/logs/"
            f"record_{video['title']}.log 2>&1"
        )

    with open(log_file, "a", encoding="utf-8") as log:
        launch = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
            env=secure_env_with_creds
            if video["channel"] in TF1_CHANNELS
            else safe_env_base,
        )
        _, _ = launch.communicate(input=record_script.encode())

    if launch.returncode != 0:
        logger.error(
            "Recording command failed for video %s on channel %s",
            video["title"],
            video["channel"],
        )
