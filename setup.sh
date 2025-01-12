#!/bin/bash

# Set the folder and virtual environment name
FOLDER_NAME="pixelsentinel_env"
PYTHON_EXECUTABLE="python3.11"

# Check if the folder exists
if [ ! -d "$FOLDER_NAME" ]; then
  echo "Folder '$FOLDER_NAME' does not exist. Creating it..."
  mkdir "$FOLDER_NAME"
  
  # Navigate to the folder
  cd "$FOLDER_NAME" || exit

  # Check if Python 3.11 is available
  if command -v "$PYTHON_EXECUTABLE" &>/dev/null; then
    echo "Creating Python 3.11 virtual environment..."
    $PYTHON_EXECUTABLE -m venv .
    echo "Virtual environment created successfully in '$FOLDER_NAME'."
  else
    echo "Error: Python 3.11 is not installed or not found in PATH."
    exit 1
  fi
else
  echo "Folder '$FOLDER_NAME' already exists."
fi
