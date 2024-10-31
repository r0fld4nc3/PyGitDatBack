#!/bin/bash

SESSION_USER="$(whoami)"
WORK_DIR="/home/"$SESSION_USER"/.local/share/r0fld4nc3/PyGitDatBack"
VENV_PATH=""$WORK_DIR"/PyGitDatBack.venv"
THIS_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd ) #h ttps://stackoverflow.com/a/246128
REQUIREMENTS=""$THIS_DIR"/src/requirements.txt"

echo "Creating virtual environment at "$VENV_PATH""

python3 -m venv "$VENV_PATH" 
source "$VENV_PATH/bin/activate"
pip install -r "$REQUIREMENTS"
python3 ""$THIS_DIR"/src/main.py"