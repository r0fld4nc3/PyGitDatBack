#!/bin/bash

SERVICE_FILE="$(basename $1)"
TIMER_FILE="$(basename $2)"

SERVICE_DEST="/etc/systemd/system"

echo "Service File: '$1'"
echo "Timer File:   '$2'"

# Stop the timer
if sudo systemctl stop "$(basename "$TIMER_FILE")"; then
    echo "Stopped $(basename "$TIMER_FILE")"
 else
    echo "Error: Failed to stop '$TIMER_FILE'"
    exit 1
fi

# Disable the service
if sudo systemctl stop "$(basename "$SERVICE_FILE")"; then
    echo "Disabled $(basename "$SERVICE_FILE")"
else
    echo "Error: Failed to disable '$SERVICE_FILE'"
    exit 1
fi

# Remove the service file
echo "Removing "$SERVICE_DEST"/$SERVICE_FILE"
if sudo rm ""$SERVICE_DEST"/$SERVICE_FILE"; then
    echo "Removed '$SERVICE_FILE'"
else
    echo "Error: Failed to delete "$SERVICE_FILE""
    exit 1
fi

# Remove the timer file
echo "Removing "$SERVICE_DEST"/$TIMER_FILE"
if sudo rm ""$SERVICE_DEST"/$TIMER_FILE"; then
    echo "Removed '$TIMER_FILE'"
else
    echo "Error: Failed to delete "$SERVICE_DEST"/$TIMER_FILE"
    exit 1
fi

# Reload daemon to apply changes
sudo systemctl daemon-reload

echo "Service $(basename $SERVICE_FILE) successfully stopped and unregistered."
