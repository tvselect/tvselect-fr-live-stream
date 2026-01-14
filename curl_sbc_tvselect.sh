#!/bin/bash

LOG_FILE="$HOME/.local/share/tvselect-fr-live-stream/logs/cron_curl.log"
OUTPUT_FILE="$HOME/.local/share/tvselect-fr-live-stream/info_progs.json"
API_URL="https://www.tv-select.fr/api/v1/prog"
CONFIG_PY_FILE="/home/$USER/.config/tvselect-fr-live-stream/config.py"

umask 077

mkdir -p "$(dirname "$LOG_FILE")"

USERNAME="$(pass tv-select/email)"
PASSWORD="$(pass tv-select/password)"

if [[ -z "$USERNAME" || -z "$PASSWORD" ]]; then
    printf '%s\n' "Error: Unable to retrieve credentials from pass." >> "$LOG_FILE"
    exit 1
fi

get_time_from_config() {
    if [[ -f "$CONFIG_PY_FILE" ]]; then

        CURL_HOUR="$(grep -oP 'CURL_HOUR\s*=\s*\K\d+' "$CONFIG_PY_FILE")"
        CURL_MINUTE="$(grep -oP 'CURL_MINUTE\s*=\s*\K\d+' "$CONFIG_PY_FILE")"

        if [[ ! "$CURL_HOUR" =~ ^[0-9]+$ ]] || [[ ! "$CURL_MINUTE" =~ ^[0-9]+$ ]]; then
            printf '%s\n' "Error: Invalid CURL_HOUR or CURL_MINUTE in config.py" >> "$LOG_FILE"
            exit 1
        fi

        CURL_HOUR="$(printf '%02d' "$CURL_HOUR")"
        CURL_MINUTE="$(printf '%02d' "$CURL_MINUTE")"

    else
        printf '%s\n' "Error: Unable to retrieve scheduled hour from the config file." >> "$LOG_FILE"
        exit 1
    fi
}

get_time_from_config
printf 'Script started at %s. Scheduled time: %s:%s\n' "$(date)" "$CURL_HOUR" "$CURL_MINUTE" >> "$LOG_FILE"

LAST_CONFIG_CHECK="$(date +%s)"

while true; do

    # Reload config at the top of the hour
    if [[ "$(date +%M)" = "00" ]]; then
        get_time_from_config
    fi

    current_hour="$(date +%H)"
    current_minute="$(date +%M)"

    if [[ "$current_hour" = "$CURL_HOUR" && "$current_minute" = "$CURL_MINUTE" ]]; then
        printf 'Running scheduled task at %s\n' "$(date)" >> "$LOG_FILE"

        CONFIG_FILE="$(mktemp)"
        printf 'user = %s:%s\n' "$USERNAME" "$PASSWORD" > "$CONFIG_FILE"
        chmod 600 "$CONFIG_FILE"

        TMP_OUTPUT="$(mktemp)"

        if curl -H "Accept: application/json;indent=4" \
                --config "$CONFIG_FILE" \
                "$API_URL" > "$TMP_OUTPUT" 2>> "$LOG_FILE"; then

            mv "$TMP_OUTPUT" "$OUTPUT_FILE"

        else
            printf '%s: curl failed, keeping previous JSON\n' "$(date)" >> "$LOG_FILE"
            rm -f "$TMP_OUTPUT"
            shred -u "$CONFIG_FILE" 2>/dev/null || rm -f "$CONFIG_FILE"
            sleep 60
            continue
        fi

        shred -u "$CONFIG_FILE" 2>/dev/null || rm -f "$CONFIG_FILE"

        printf 'Task completed at %s\n' "$(date)" >> "$LOG_FILE"

        sleep 60
    fi

    sleep 30
done
