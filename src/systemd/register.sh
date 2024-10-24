#!/bin/bash

SERVICE_FILE_IN="$1"
SERVICE_FILE="$2"

TIMER_FILE_IN="$3"
TIMER_FILE="$4"

echo "Service File Input: "$1""
echo "Service File Dest:  "$2""
echo "Timer File Input:   "$3""
echo "Timer File Dest:    "$4""

# Copy the service file
if sudo cp "$SERVICE_FILE_IN" "$SERVICE_FILE" && sudo cp "$TIMER_FILE_IN" "$TIMER_FILE"; then
    echo "Files copied successfully."
else
    echo "Error: Failed to copy service or timer files."
    exit 1
fi

# Reload systemd to recognize the new service
if sudo systemctl daemon-reload; then
    echo "systemd reloaded."
else
    echo "Error: Failed to reload systemd."
    exit 1
fi

# Enable the service to start on boot
if sudo systemctl enable "$(basename "$SERVICE_FILE")"; then
    echo "Service $(basename "$SERVICE_FILE") enabled."
else
    echo "Error: Failed to enable service."
    exit 1
fi

# Start the service
if sudo systemctl start "$(basename "$SERVICE_FILE")"; then
    echo "Service $(basename "$SERVICE_FILE") started."
else
    echo "Error: Failed to start service."
    exit 1
fi

# Enable the timer to start on boot
if sudo systemctl enable "$(basename "$TIMER_FILE")"; then
    echo "Timer $(basename "$TIMER_FILE") enabled."
else
    echo "Error: Failed to enable timer."
    exit 1
fi

# Start the timer service
if sudo systemctl start "$(basename "$TIMER_FILE")"; then
    echo "Timer $(basename "$TIMER_FILE") started."
else
    echo "Error: Failed to start timer."
    exit 1
fi

# Delete the temp file
rm "$SERVICE_FILE_IN"

echo "Service $(basename "$SERVICE_FILE") successfully registered and started."
