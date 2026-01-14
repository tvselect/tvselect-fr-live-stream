import json
import logging
import os
import re
import requests
import sentry_sdk
import subprocess
import sys
import time

from pathlib import Path
from datetime import datetime, timedelta
from shlex import quote
from logging.handlers import RotatingFileHandler

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
)

def get_tf1_credentials():
    """Retrieve TF1 credentials and return environment dict."""
    env = os.environ.copy()

    if not CRYPTED_CREDENTIALS:
        return env

    try:
        username = get_pass_entry("tf1/email")
        password = get_pass_entry("tf1/password")

        if username is None:
            logger.error("Failed to retrieve 'username' from pass for 'tf1'.")
            return env

        if password is None:
            logger.error("Failed to retrieve 'password' from pass for 'tf1'.")
            return env

        env["TF1_EMAIL"] = username
        env["TF1_PASSWORD"] = password
        return env

    except Exception as e:
        logging.exception("An error occurred while retrieving credentials from pass.")
        return env


SAFE_PASS_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.environ["HOME"],
    "LC_ALL": "C",
}

def get_pass_entry(entry):
    """
    Securely retrieve an entry from pass.

    - Restricted execution environment
    - Validates output for control characters
    """
    try:
        result = subprocess.run(
            ["pass", entry],
            capture_output=True,
            text=True,
            env=SAFE_PASS_ENV,
            timeout=5,
            check=False,
        )
    except Exception:
        logger.exception(f"Error executing pass for entry '{entry}'")
        return None

    if result.returncode != 0:
        logger.error(f"pass returned non-zero exit for entry '{entry}'")
        return None

    value = result.stdout.strip()
    if not value:
        logger.error(f"pass returned empty value for entry '{entry}'")
        return None

    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        logger.error(f"pass returned unsafe characters for entry '{entry}'")
        return None

    return value


def get_time_from_config():
    """Extracts CURL_HOUR and CURL_MINUTE from config.py."""
    if not os.path.isfile(CONFIG_PY_FILE):
        logger.error("Error: Unable to retrieve scheduled hour from config file.")
        return None, None

    with open(CONFIG_PY_FILE, "r", encoding='utf-8') as f:
        config_content = f.read()

    hour = next((line.split("=")[1].strip() for line in config_content.splitlines() if "CURL_HOUR" in line), None)
    minute = next((line.split("=")[1].strip() for line in config_content.splitlines() if "CURL_MINUTE" in line), None)

    if hour and minute:
        return f"{int(hour):02d}", f"{int(minute):02d}"

    logger.error("Error: Could not extract CURL_HOUR or CURL_MINUTE from config.")
    return None, None

def update_info_json(tv_email, tv_password):
    """Fetch program data and update info_progs.json securely."""

    try:
        response = requests.get(API_URL,
                                auth=(tv_email, tv_password),
                                headers={"Accept": "application/json; indent=4"},
                                timeout=5
                            )
        response.raise_for_status()
    except Exception:
        logger.exception("API request failed")
        return False

    try:
        data = response.json()
    except Exception:
        logger.exception("Invalid JSON received from API")
        return False

    dest = f"/home/{user}/.local/share/tvselect-fr-live-stream/info_progs.json"

    try:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception:
        logger.exception("Failed to write info_progs.json")
        return False

    return True

if SENTRY_MONITORING_SDK:
    sentry_sdk.init(
        dsn="https://0b40b1a24c605fd77fddb9219a45e594@o4508778574381056.ingest.de.sentry.io/4509938023268432",
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0,
        before_send=scrub_event,
    )
    client = sentry_sdk.get_client()
    if client and client.options.get("traces_sample_rate", 0) > 0:
        sentry_sdk.profiler.start_profiler()


log_file = f"/home/{user}/.local/share/tvselect-fr-live-stream/logs/stream_record.log"
max_bytes = 10 * 1024 * 1024  # 10 MB
backup_count = 5

log_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
log_format = '%(asctime)s %(levelname)s %(name)s: %(message)s'
log_datefmt = '%d-%m-%Y %H:%M:%S'
formatter = logging.Formatter(log_format, log_datefmt)

log_handler.setFormatter(formatter)

logger = logging.getLogger("__name__")
logger.addHandler(log_handler)

sentry_handler = logging.StreamHandler()
sentry_handler.setLevel(logging.WARNING)

logger.addHandler(sentry_handler)
logger.setLevel(logging.INFO)

logging.basicConfig(level=logging.INFO,
                    format=log_format,
                    datefmt=log_datefmt,
                    handlers=[log_handler, sentry_handler])

OUTPUT_FILE = os.path.expanduser("~/.local/share/tvselect-fr-live-stream/info_progs.json")
API_URL = "https://www.tv-select.fr/api/v1/prog"
CONFIG_PY_FILE = os.path.expanduser("~/.config/tvselect-fr-live-stream/config.py")


if __name__ == "__main__":

    sensitive_filter = global_sanitizer

    log_handler.addFilter(sensitive_filter)
    sentry_handler.addFilter(sensitive_filter)
    logger.addFilter(sensitive_filter)

    tv_email = get_pass_entry("tv-select/email")
    tv_password = get_pass_entry("tv-select/password")
    env_with_creds = get_tf1_credentials()

    sensitive_filter.update_patterns(
        {
            "TV_SELECT_EMAIL": tv_email or "",
            "TV_SELECT_PASSWORD": tv_password or "",
            "TF1_EMAIL": env_with_creds.get("TF1_EMAIL", ""),
            "TF1_PASSWORD": env_with_creds.get("TF1_PASSWORD", ""),
        }
    )

    if not tv_email or not tv_password:
        logger.error("Error: Missing credentials.")
        exit(1)

    last_config_check = time.time()
    curl_hour, curl_minute = get_time_from_config()

    while True:
        if time.time() - last_config_check >= 3600:
            curl_hour, curl_minute = get_time_from_config()
            last_config_check = time.time()

        current_time = time.strftime("%H:%M")
        if current_time == f"{curl_hour}:{curl_minute}":
            update_json = update_info_json(tv_email, tv_password)

            time.sleep(61)

            if update_json:
                try:
                    result = subprocess.run(
                        [
                            f"/home/{user}/.local/share/tvselect-fr-live-stream/"
                            ".venv/bin/python3",
                            f"/home/{user}/tvselect-fr-live-stream/"
                            "launch_stream_pass.py"
                        ],
                        env=env_with_creds,
                        timeout=300
                    )
                except subprocess.TimeoutExpired:
                    logger.error(
                        "launch_stream_pass.py timed out after 5 minutes"
                    )


        time.sleep(30)
