#!/bin/bash

# -------------------------------
# Dynamic Cron Setup for Invoice Processing
# -------------------------------

# Paths
PROJECT_DIR="/home/abhishek/Projects/Trooinbound/ccit-ai-invoice-processing/scheduler"
VENV_DIR="$HOME/.pyenv/versions/ccit_invoice"
LOG_DIR="$PROJECT_DIR"
LOG_FILE="$LOG_DIR/daily_processor.log"
PYTHON_SCRIPT="$PROJECT_DIR/daily_processor.py"
CONFIG_FILE="$PROJECT_DIR/scheduler_config.json"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Check if jq is installed
if ! command -v jq &>/dev/null; then
    echo "Error: 'jq' is required but not installed. Install it first."
    exit 1
fi

# Read schedule from JSON
SCHEDULE_TIME=$(jq -r '.schedule.time' "$CONFIG_FILE")  # e.g., "09:00"
TIME_HOUR=$(echo "$SCHEDULE_TIME" | cut -d':' -f1)
TIME_MIN=$(echo "$SCHEDULE_TIME" | cut -d':' -f2)
WEEKDAYS_ONLY=$(jq -r '.schedule.weekdays_only' "$CONFIG_FILE")

# Determine cron weekdays
if [ "$WEEKDAYS_ONLY" = "true" ]; then
    CRON_WEEKDAYS="1-5"
else
    CRON_WEEKDAYS="*"
fi

# Cron schedule
CRON_SCHEDULE="$TIME_MIN $TIME_HOUR * * $CRON_WEEKDAYS"

# Remove old cron for safety
crontab -l | grep -v "$PYTHON_SCRIPT" | crontab -

# Add new cron job (paths quoted to handle spaces)
(crontab -l 2>/dev/null; echo "$CRON_SCHEDULE cd \"$PROJECT_DIR\" && /bin/bash -c 'source \"$VENV_DIR/bin/activate\" && python \"$PYTHON_SCRIPT\"' >> \"$LOG_FILE\" 2>&1") | crontab -

echo "Cron job added successfully!"
echo "Project: $PROJECT_DIR"
echo "Log file: $LOG_FILE"
echo "Scheduled time: $SCHEDULE_TIME UTC"
