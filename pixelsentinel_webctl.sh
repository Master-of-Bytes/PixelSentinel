#!/bin/bash

# Function to print error messages with the current working directory
print_error() {
  echo "Error: $1"
  echo "Current working directory: $(pwd)"
  exit 1
}

# Check if python3.14 is available
if ! command -v python3.14 &>/dev/null; then
  print_error "python3.14 is not installed or not in PATH."
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

  # Check if pixelsentinel_web.py exists
  if [ ! -f "pixelsentinel_web.py" ]; then
    print_error "pixelsentinel_web.py not found."
  fi

  echo "Running PixelSentinel Webserver..."
  python3.14 pixelsentinel_web.py
else
  print_error "Virtual environment not found. Please run setup.sh."
fi
