#!/bin/bash

export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"

SERVICE="tv-select"
PYTHON="$HOME/.local/share/tvselect-fr-live-stream/.venv/bin/python"

LOG_FILE="$HOME/.local/share/tvselect-fr-live-stream/logs/cron_curl.log"
OUTPUT_FILE="$HOME/.local/share/tvselect-fr-live-stream/info_progs.json"
API_URL="https://www.tv-select.fr/api/v1/prog"

umask 077

CRYPTED_CREDENTIALS="$("$PYTHON" -c "import sys; sys.path.insert(0, '$HOME/.config/tvselect-fr-live-stream'); import config; print(config.CRYPTED_CREDENTIALS)")"

if [[ "$CRYPTED_CREDENTIALS" == "True" ]]; then

    USERNAME="$("$PYTHON" -c "import keyring; print(keyring.get_password('$SERVICE', 'username'))")"
    PASSWORD="$("$PYTHON" -c "import keyring; print(keyring.get_password('$SERVICE', 'password'))")"

    if [[ -z "$USERNAME" || -z "$PASSWORD" ]]; then
        printf '%s\n' "Error: Unable to retrieve credentials from keyring." >> "$LOG_FILE"
        exit 1
    fi

    CONFIG_FILE="$(mktemp)"
    printf 'user = %s:%s\n' "$USERNAME" "$PASSWORD" > "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"

    unset USERNAME PASSWORD

    TMP_OUTPUT="$(mktemp)"

    if curl -H "Accept: application/json;indent=4" \
            --config "$CONFIG_FILE" \
            "$API_URL" > "$TMP_OUTPUT" 2>> "$LOG_FILE"; then

        mv "$TMP_OUTPUT" "$OUTPUT_FILE"

    else
        printf '%s: curl failed, keeping previous JSON\n' "$(date)" >> "$LOG_FILE"
        rm -f "$TMP_OUTPUT"
        shred -u "$CONFIG_FILE" 2>/dev/null || rm -f "$CONFIG_FILE"
        exit 1
    fi

    shred -u "$CONFIG_FILE" 2>/dev/null || rm -f "$CONFIG_FILE"

else
    TMP_OUTPUT="$(mktemp)"

    if curl -H "Accept: application/json;indent=4" \
            -n "$API_URL" > "$TMP_OUTPUT" 2>> "$LOG_FILE"; then

        mv "$TMP_OUTPUT" "$OUTPUT_FILE"

    else
        printf '%s: curl failed (no-credential mode), keeping previous JSON\n' "$(date)" >> "$LOG_FILE"
        rm -f "$TMP_OUTPUT"
        exit 1
    fi
fi
