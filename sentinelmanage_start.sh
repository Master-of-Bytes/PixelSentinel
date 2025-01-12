#!/bin/bash

# Function to print error messages with the current working directory
print_error() {
  echo "Error: $1"
  echo "Current working directory: $(pwd)"
  exit 1
}

# Check if python3.11 is available
if ! command -v python3.11 &>/dev/null; then
  print_error "python3.11 is not installed or not in PATH."
  exit 1
fi

# Find the pixelsentinel folder, excluding directories starting with @ or #
PIXELSENTINEL_PATH=$(find / -type d \( -name "@*" -o -name "#*" \) -prune -o -type d -name "pixelsentinel" -print 2>/dev/null | head -n 1)

if [ -z "$PIXELSENTINEL_PATH" ]; then
  print_error "pixelsentinel folder not found."
fi

cd "$PIXELSENTINEL_PATH" || print_error "Failed to change directory to pixelsentinel folder."

# Check if the virtual environment exists
if [ -d "pixelsentinel_env" ]; then
  cd "pixelsentinel_env" || print_error "Failed to change directory to pixelsentinel_env."

  # Check if the activation script exists
  if [ ! -f "bin/activate" ]; then
    print_error "Virtual environment activation script not found."
  fi

  echo "Activating virtual environment..."
  source bin/activate
  cd .. || print_error "Failed to change directory back to pixelsentinel."

  # Check if sentinelmanage.py exists
  if [ ! -f "sentinelmanage.py" ]; then
    print_error "sentinelmanage.py not found."
    exit 1
  fi

  echo "Running sentinelmanage..."
  python3.11 sentinelmanage.py
else
  print_error "Virtual environment not found. Please run setup.sh."
  exit 1
fi
