#!/bin/bash

SERVICE_FILE_IN="$1"
SERVICE_FILE="$(basename "$SERVICE_FILE_IN")"

TIMER_FILE_IN="$2"
TIMER_FILE="$(basename "$TIMER_FILE_IN")"

SERVICE_DEST="/etc/systemd/system"

echo "Service File Input: $SERVICE_FILE_IN"
echo "Service File Dest:  $SERVICE_DEST/$SERVICE_FILE"
echo "Timer File Input:   $TIMER_FILE_IN"
echo "Timer File Dest:    $SERVICE_DEST/$SERVICE_FILE"

echo ""

# Copy the service file(s)
echo "Copying '$SERVICE_FILE_IN' to '$SERVICE_DEST'/$SERVICE_FILE"
echo "Copying '$TIMER_FILE_IN' to '$SERVICE_DEST'/$TIMER_FILE"
if sudo cp "$SERVICE_FILE_IN" "$SERVICE_DEST/$SERVICE_FILE" && sudo cp "$TIMER_FILE_IN" "$SERVICE_DEST/$TIMER_FILE"; then
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
echo "sudo systemctl enable $SERVICE_FILE"
if sudo systemctl enable "$SERVICE_FILE"; then
    echo "Service "$SERVICE_FILE" enabled."
else
    echo "Error: Failed to enable service."
    exit 1
fi

# Start the service - We don't start it yet
echo "sudo systemctl start $(basename "$SERVICE_FILE")"
if sudo systemctl start "$(basename "$SERVICE_FILE")"; then
    echo "Service $(basename "$SERVICE_FILE") started."
else
    echo "Error: Failed to start service."
    exit 1
fi

# Enable the timer to start on boot
echo "sudo systemctl enable $TIMER_FILE"
if sudo systemctl enable "$TIMER_FILE"; then
    echo "Timer '$TIMER_FILE' enabled."
else
    echo "Error: Failed to enable timer."
    exit 1
fi

# Start the timer service
echo "sudo systemctl start $TIMER_FILE"
if sudo systemctl start "$TIMER_FILE"; then
    echo "Timer '$TIMER_FILE' started."
else
    echo "Error: Failed to start timer."
    exit 1
fi

# Delete the temp files
# rm "$SERVICE_FILE_IN"
# rm "$TIMER_FILE_IN"

echo "Service '$SERVICE_FILE' successfully registered and started."
