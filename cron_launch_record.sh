echo --- crontab start: $(date) >> ~/.local/share/tvselect-fr-live-stream/logs/cron_launch_record.log
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
export TZ='Europe/Paris'
cd $HOME/tvselect-fr-live-stream
. $HOME/.local/share/tvselect-fr-live-stream/.venv/bin/activate
python3 launch_stream_record.py >> ~/.local/share/tvselect-fr-live-stream/logs/cron_launch_record.log 2>&1
deactivate
echo --- crontab end: $(date) >> ~/.local/share/tvselect-fr-live-stream/logs/cron_launch_record.log
