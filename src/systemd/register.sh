#!/bin/bash

VENV_PATH="$1"
REQUIREMENTS="$2"

SERVICE_FILE_IN="$3"
SERVICE_FILE="$4"

TIMER_FILE_IN="$5"
TIMER_FILE="$6"

echo "Venv Path Setup:    "$VENV_PATH""
echo "Venv Requirements:  "$REQUIREMENTS""
echo "Service File Input: "$SERVICE_FILE_IN""
echo "Service File Dest:  "$SERVICE_FILE""
echo "Timer File Input:   "$TIMER_FILE_IN""
echo "Timer File Dest:    "$TIMER_FILE""

# Create/Setup the venv
python3 -m venv "$VENV_PATH" 
source "$VENV_PATH/bin/activate"
pip install -r "$REQUIREMENTS"

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
echo "sudo systemctl enable $(basename "$SERVICE_FILE")"
if sudo systemctl enable "$(basename "$SERVICE_FILE")"; then
    echo "Service $(basename "$SERVICE_FILE") enabled."
else
    echo "Error: Failed to enable service."
    exit 1
fi

# Start the service - We don't start it yet
# echo "sudo systemctl start $(basename "$SERVICE_FILE")"
# if sudo systemctl start "$(basename "$SERVICE_FILE")"; then
    # echo "Service $(basename "$SERVICE_FILE") started."
# else
    # echo "Error: Failed to start service."
    # exit 1
# fi

# Enable the timer to start on boot
echo "sudo systemctl enable $(basename "$TIMER_FILE")"
if sudo systemctl enable "$(basename "$TIMER_FILE")"; then
    echo "Timer $(basename "$TIMER_FILE") enabled."
else
    echo "Error: Failed to enable timer."
    exit 1
fi

# Start the timer service
echo "sudo systemctl start $(basename "$TIMER_FILE")"
if sudo systemctl start "$(basename "$TIMER_FILE")"; then
    echo "Timer $(basename "$TIMER_FILE") started."
else
    echo "Error: Failed to start timer."
    exit 1
fi

# Delete the temp file
rm "$SERVICE_FILE_IN"

echo "Service $(basename "$SERVICE_FILE") successfully registered and started."
