"""
Program Name: PixelSentinel (c) Larry Zande

Description: This program checks the 'photos' folder and sub folders
of the synology photos app for uploaded photos and then using Gmail
sends an email message to end users alerting them.
On first run this program sets up the database, files and albums tables and then calls the sentinelmanage program to let the
user set up the groups and members tables or add new albums.
Later runs check and update the files and albums tables.

Date: 11/25/2024
"""
import sys
import time
import os
import sqlite3
import hashlib
import smtplib
import subprocess
import ssl
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
try:
    from dotenv import load_dotenv, set_key
except ModuleNotFoundError:
    print(f"The module dotenv is not found. Please install with 'pip install python-dotenv.'")
    exit(1)

# Loading variables from .env file
load_dotenv()

# Configuration
shared_photos = os.getenv('SHARED_PHOTOS')
db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pixelsentinel.db')
requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')


def db_execute(query, params=(), fetch=False):
    connection = sqlite3.connect(db_file)
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        if fetch:
            return cursor.fetchall()
        connection.commit()
    except sqlite3.Error as e:
        connection.rollback()  # Rollback in case of error
        raise ValueError(f"An error occurred while executing the query: {query} : error: {e}")
    finally:
        cursor.close()
        connection.close()

# SQLite database setup
def initialize_database():
    try:
        db_execute('''
            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                checksum TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
        ''')
        print(f"Database initialized at {db_file}.")
    except ValueError as e:
        print(f"Error initializing the database: {e}")

# Initialize albums based on files
def initialize_albums():
    try:
        db_execute('''
            CREATE TABLE IF NOT EXISTS albums (
                album_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_id INTEGER,
                FOREIGN KEY (group_id) REFERENCES groups (group_id) ON DELETE CASCADE
            );
        ''')
        print("Albums table initialized.\nStarting data import...")

        # Fetch all file paths from the 'files' table
        file_list = db_execute('''
                        SELECT path FROM files
                        ''', fetch=True)

        albums = set()
        for file_entry in file_list:
            full_path = file_entry[0]
            # Extract the directory structure, excluding the file name
            current_path = os.path.dirname(full_path)
            if current_path not in albums:
                albums.add(current_path)

        # Sort the album paths alphabetically
        sorted_albums = sorted(albums)

        # Replace os sep with ' - ' in sorted_albums
        formatted_albums = [album.replace(os.sep, ' - ') for album in sorted_albums]

        for album_name in formatted_albums:
            db_execute('''
            INSERT INTO albums (name, group_id)
            VALUES (?, ?)
            ''', (album_name, 1))
        print("Data import complete")

    except Exception as e:  # Use Exception to catch all possible errors
        print(f"Error initializing albums table: {e}")

# Checks for albums that need to be removed
def check_removed_albums(file_entries):
    try:
        # Fetch existing album names from the database
        db_albums = db_execute('SELECT name FROM albums', fetch=True)
        existing_albums = {row[0] for row in db_albums}

        # Compute current albums based on file entries
        current_albums = {
            os.path.normpath(os.path.dirname(entry['path'])).replace(os.sep, ' - ') for entry in file_entries
        }

        # Identify albums to be removed
        albums_to_remove = existing_albums - current_albums

        # Remove albums from the database
        for album_name in albums_to_remove:
            db_execute('DELETE FROM albums WHERE name = ?', (album_name,))
            print(f"Album '{album_name}' removed from the database.")

    except Exception as e:
        print(f"Error in check_removed_albums: {e}")

# Preprocess requirements file
def preprocess_requirements_file(file_path):
    with open(file_path, 'rb') as f:
        raw_data = f.read()
    # Attempt to decode as utf-16, replacing invalid characters
    return raw_data.decode('utf-16', errors='replace')

# Check and install required dependencies
def install_requirements():
    if os.getenv("REQUIREMENTS_CHECKED") == "1":
        print("Dependencies have already been checked. Skipping further checks.")
        return
    if os.path.exists(requirements_file):
        try:
            print("Checking for required dependencies...")

            # Preprocess the file to remove invalid characters
            content = preprocess_requirements_file(requirements_file)
            required_packages = [
                line.strip() for line in content.splitlines() if line.strip() and not line.startswith('#')
            ]

            # Print required packages
            print(f"Required packages from requirements.txt: {', '.join(required_packages)}")

            # Get installed packages
            installed_packages = subprocess.check_output(['pip', 'freeze']).decode().splitlines()
            installed_packages = {pkg.split('==')[0].lower() for pkg in installed_packages}

            # Determine missing packages
            missing_packages = [
                pkg for pkg in required_packages if pkg.split('==')[0].lower() not in installed_packages
            ]

            # Print missing packages
            print(f"Missing packages to install: {', '.join(missing_packages)}")

            if missing_packages:
                print(f"Installing missing dependencies: {', '.join(missing_packages)}")
                subprocess.check_call(['pip', 'install'] + missing_packages)
                print("All required dependencies are installed.")
            else:
                print("All dependencies are already satisfied. Skipping installation.")
        except subprocess.CalledProcessError as e:
            print(f"Error installing requirements: {e}")
            exit(1)
        set_key(".env", "REQUIREMENTS_CHECKED", "1")
        print("Marked dependencies as checked")
    else:
        print("No requirements.txt file found. Skipping dependency installation.")

# Calculate SHA256 checksum of a file
def calculate_checksum(file_path):
    hash_sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()

def process_file(full_path, relative_path, modified_time):
    try:
        result = db_execute('SELECT checksum, timestamp FROM files WHERE path = ?', (relative_path,), fetch=True)

        if not result or result[0][1] != modified_time:
            checksum = calculate_checksum(full_path)
            db_execute('''
                INSERT OR REPLACE INTO files (path, checksum, timestamp)
                VALUES (?, ?, ?)
            ''', (relative_path, checksum, modified_time))
        else:
            checksum = result[0][0]

        return {"path": relative_path, "checksum": checksum, "timestamp": modified_time}

    except FileNotFoundError:
        print(f"Error: File not found - {full_path}")
    except sqlite3.DatabaseError as e:
        print(f"Database error while processing {full_path}: {e}")
    except Exception as e:
        print(f"Unexpected error while processing {full_path}: {e}")

def get_file_list():
    file_tasks = []
    excluded_dirs = {'#snapshot', '@eaDir'}
    excluded_files = {'Thumbs.db'}

    for root, dirs, files in os.walk(shared_photos):
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        for file in files:
            if file not in excluded_files:
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, shared_photos)
                modified_time = os.path.getmtime(full_path)
                file_tasks.append((full_path, relative_path, modified_time))

    results = []
    for task in file_tasks:
        full_path, relative_path, modified_time = task
        result = process_file(full_path, relative_path, modified_time)
        if result:
            results.append(result)

    return results

# Load prior state
def load_prior_state():
    rows = db_execute("SELECT path, checksum, timestamp FROM files", fetch=True)
    return {row[0]: {"checksum": row[1], "timestamp": row[2]} for row in rows} if rows else {}


# Detect if files are new, have been moved, or have been deleted
def detect_files(mode, _current_state, _prior_state):
    if mode == 'new':
        new_files = [
            current_file for current_file in _current_state
            if current_file["path"] not in _prior_state or _prior_state[current_file["path"]]["checksum"] != current_file["checksum"]
        ]
        return new_files

    if mode == 'move':
        prior_checksums = {v["checksum"]: k for k, v in _prior_state.items()}
        moved_files = [
            {
                "old_path": prior_checksums[current_file["checksum"]],
                "new_path": current_file["path"]
            }
            for current_file in _current_state
            if current_file["checksum"] in prior_checksums and prior_checksums[current_file["checksum"]] != current_file["path"]
        ]
        for file_entry in moved_files:
            db_execute('''
                UPDATE files
                SET path = ?
                WHERE path = ?
            ''', (file_entry["new_path"], file_entry["old_path"]))
        return moved_files

    if mode == 'delete':
        deleted_files = [
            path for path in _prior_state.keys()
            if path not in {current_file["path"] for current_file in _current_state}
        ]
        for path in deleted_files:
            db_execute('DELETE FROM files WHERE path = ?', (path,))
        return deleted_files

# Calculate the total number of photos in each album based on file paths
def get_album_photo_counts(file_entries):
    album_photo_counts = defaultdict(int)

    for current_file in file_entries:
        # Extract the full directory path (excluding the file name)
        full_path = current_file['path']
        album_name = os.path.dirname(full_path).replace(os.sep, ' - ')
        album_photo_counts[album_name] += 1

    return dict(album_photo_counts)

 # List all album groups based on album name
def get_album_groups(album_name):
    try:
        group_names = db_execute('''
        SELECT groups.name AS GroupName
        FROM albums JOIN
        groups ON albums.group_id = groups.group_id
        WHERE 
        albums.name = ? 
                ''',(album_name,), fetch=True)

        if not group_names:
            print("No groups found.\n")
            return
        else:
            return group_names
    except ValueError as e:
        print(f"Error interacting with the database: {e}")
        return

# Get member info with album based on album/group name
def get_member_info(album_name,group_name):
    try:
        member_info = db_execute('''
        SELECT members.name AS member_name, members.email
        FROM albums
        JOIN groups ON albums.group_id = groups.group_id
        JOIN members ON groups.group_id = members.group_id
        WHERE albums.name = ? 
        AND groups.name = ? 
                ''',(album_name,group_name,), fetch=True)

        if not member_info:
            print("No members found.\n")
            return
        else:
            return member_info
    except ValueError as e:
        print(f"Error interacting with the database: {e}")
        return

def sendalerts(_new_photo_count):
    members = {}  # Initialize members as a dictionary

    # Loop through the albums and their counts
    for album, count in _new_photo_count.items():
        # Get a list of groups for the current album
        group_list = get_album_groups(album)

        # Initialize the album in the members dictionary if not already present
        if album not in members:
            members[album] = set()  # Use a set to ensure uniqueness

        # Process each group in the group list
        for group in group_list:  # group_list contains tuples
            group_name = group[0]  # Extract the group name from the tuple
            member_info_list = get_member_info(album, group_name)  # This returns a list of tuples

            # Add each member info to the set (deduplication happens here)
            for member_info in member_info_list:
                members[album].add(member_info)

    # Convert the sets back to lists for the final result
    members = {album: list(member_set) for album, member_set in members.items()}

    # Create the message
    for album, member_list in members.items():
        photo_count = _new_photo_count[album]  # Get the photo count for the album
        now = datetime.now()
        senddt = now.strftime('%m/%d/%Y at %I:%M %p')
        for member_name, email in member_list:
            subject = 'PixelSentinel: New Photo(s) Added'
            message = f'{member_name}, {photo_count} new photo(s) added to the album {album} on {senddt}.'
            msg = MIMEMultipart()
            msg['From'] = os.getenv('SENDER_EMAIL')
            msg['To'] = email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))

            # Create a secure SSL context
            context = ssl.create_default_context()
            try:
                with smtplib.SMTP_SSL(os.getenv('SMTP_SERVER'), int(os.getenv('PORT')), context=context) as smtp:
                    smtp.login(os.getenv('SMTP_USER'), os.getenv('APP_PASS'))

                    # Send the alert
                    smtp.send_message(msg)
                    print('Alert sent successfully.')
                    time.sleep(300) # Wait for 5 minutes
            except Exception as e:
                print(f'Error: {e}')

def main():
    # Start the timer
    start_time = time.time()

    if not os.path.exists(shared_photos):
        print(f"Directory '{shared_photos}' does not exist. Exiting.")
        exit(1)

    # Initialize database
    initialize_database()

    # Install requirements on first run
    install_requirements()

    # Load prior state
    prior_state = load_prior_state()

    # Initialize if no prior state
    if not prior_state:
        print("No prior state found. Creating initial state...")
        get_file_list()
        print("Initial state saved to the database.")

        # Initialize albums based on files found
        initialize_albums()

        # Call sentinelmanage to set up groups and members or update albums
        print(
            "First Run of PixelSentinel.\nRunning sentinelmanage to allow you to set up groups and group membership or update groups on albums...\n")
        subprocess.run([sys.executable, "sentinelmanage.py"])

        # Stop the timer
        end_time = time.time()

        # Calculate execution time
        elapsed_time = end_time - start_time

        # Convert seconds to hours, minutes, and seconds
        hours, remainder = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Print the formatted execution time
        print(f"Total execution time: {int(hours)} hour(s), {int(minutes)} minute(s), {seconds:.2f} second(s)")
        exit(0)

    # Get current file list
    current_state = get_file_list()

    # Check for albums that need to be removed
    check_removed_albums(current_state)

    # Detect files
    files_new = detect_files('new', current_state, prior_state)
    files_moved = detect_files('move', current_state, prior_state)
    files_deleted = detect_files('delete', current_state, prior_state)

    # Handle new files
    if files_new:
        # New files already added to database via process_file_with_db in get_file_list
        new_photo_count = get_album_photo_counts(files_new)

        # Send alerts
        sendalerts(new_photo_count)

        for file in files_new:
            print(f"New File: {file['path']} (Checksum: {file['checksum']})")

    # Handle moved files
    if files_moved:
        print(f"{len(files_moved)} file(s) moved.")
        print(f"Files Moved: {files_moved}")

    # Handle deleted files
    if files_deleted:
        print(f"{len(files_deleted)} file(s) removed.")
        print(f"Files Removed: {files_deleted}")

    # Stop the timer
    end_time = time.time()

    # Calculate execution time
    elapsed_time = end_time - start_time

    # Convert seconds to hours, minutes, and seconds
    hours, remainder = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Print the formatted execution time
    print(f"Total execution time: {int(hours)} hour(s), {int(minutes)} minute(s), {seconds:.2f} second(s)")

if __name__ == "__main__":
    main()