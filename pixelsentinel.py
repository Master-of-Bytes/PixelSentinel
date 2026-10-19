"""
Program Name: PixelSentinel (c) Larry Zande

Description: This program checks the 'photos' folder and sub folders
of the synology photos app for uploaded photos and then alerts end users.
On first run this program sets up the database, files and albums tables and then calls the sentinelmanage program to let the
user set up the groups and members tables or add new albums.
Later runs check and update the files and albums tables.

Date: 11/25/2024

V2: 9/22/26 - Push alert system to replace email alerts
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

# Administrator-only email alert configuration
ADMIN_ALERT_EMAIL = os.getenv(
    "ADMIN_ALERT_EMAIL",
    ""
).strip()

SMTP_SERVER = os.getenv(
    "SMTP_SERVER",
    ""
).strip()

SMTP_PORT = os.getenv(
    "SMTP_PORT",
    ""
).strip()

SMTP_USER = os.getenv(
    "SMTP_USER",
    ""
).strip()

SMTP_APP_PASSWORD = os.getenv(
    "APP_PASS",
    ""
).strip()

SENDER_EMAIL = os.getenv(
    "SENDER_EMAIL",
    ""
).strip()


# Validate the administrator-only SMTP configuration.

def validate_admin_email_configuration():

    problems = []


    if not ADMIN_ALERT_EMAIL:
        problems.append(
            "ADMIN_ALERT_EMAIL is missing."
        )


    if not SMTP_SERVER:
        problems.append(
            "SMTP_SERVER is missing."
        )


    if not SMTP_PORT:
        problems.append(
            "SMTP_PORT is missing."
        )

    else:

        try:

            port = int(
                SMTP_PORT
            )


            if (
                port < 1
                or port > 65535
            ):

                problems.append(
                    "SMTP_PORT is invalid."
                )


        except ValueError:

            problems.append(
                "SMTP_PORT is invalid."
            )


    if not SMTP_USER:
        problems.append(
            "SMTP_USER is missing."
        )


    if not SMTP_APP_PASSWORD:
        problems.append(
            "APP_PASS is missing."
        )


    if not SENDER_EMAIL:
        problems.append(
            "SENDER_EMAIL is missing."
        )


    return problems
    
def db_execute(query, params=(), fetch=False):
    connection = sqlite3.connect(db_file)
    connection.execute("PRAGMA foreign_keys = ON")
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

# Initialize notification tables
def initialize_notification_tables():
    try:
        db_execute('''
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                platform TEXT,
                user_agent TEXT,
                device_label TEXT,
                enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (enabled IN (0, 1)),
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_success_at TEXT,
                admin_alert_sent_at TEXT,
                FOREIGN KEY (member_id)
                    REFERENCES members(member_id)
                    ON DELETE CASCADE
            );
        ''')

        db_execute('''
            CREATE INDEX IF NOT EXISTS
            idx_push_subscriptions_member_id
            ON push_subscriptions(member_id);
        ''')

        db_execute('''
            CREATE TABLE IF NOT EXISTS member_invites (
                invite_id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                revoked_at TEXT,
                FOREIGN KEY (member_id)
                    REFERENCES members(member_id)
                    ON DELETE CASCADE
            );
        ''')

        db_execute('''
            CREATE INDEX IF NOT EXISTS
            idx_member_invites_member_id
            ON member_invites(member_id);
        ''')

        print("Push notification tables initialized.")

    except ValueError as e:
        print(f"Error initializing notification tables: {e}")

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

# Get all unique members assigned to an album
def get_album_members(album_name):
    """
    Return each unique member who should receive alerts
    for an album.

    A member is returned only once even if that person
    belongs to multiple groups linked to the same album.
    """

    try:

        members = db_execute(
            '''
            SELECT DISTINCT
                members.member_id,
                members.name

            FROM albums

            JOIN groups
                ON albums.group_id =
                   groups.group_id

            JOIN member_groups
                ON groups.group_id =
                   member_groups.group_id

            JOIN members
                ON member_groups.member_id =
                   members.member_id

            WHERE albums.name = ?

            ORDER BY
                members.name COLLATE NOCASE,
                members.member_id
            ''',
            (
                album_name,
            ),
            fetch=True
        )

        return members or []

    except ValueError as e:

        print(
            f"Error retrieving members for "
            f"album '{album_name}': {e}"
        )

        return []

# Get all enabled push devices for a member
def get_enabled_push_subscriptions(
    member_id
):
    """
    Return every enabled Web Push subscription for
    a member.
    """

    try:

        subscriptions = db_execute(
            '''
            SELECT
                subscription_id,
                endpoint,
                p256dh,
                auth,
                platform,
                device_label

            FROM push_subscriptions

            WHERE member_id = ?
              AND enabled = 1

            ORDER BY subscription_id
            ''',
            (
                member_id,
            ),
            fetch=True
        )

        results = []

        for (
            subscription_id,
            endpoint,
            p256dh,
            auth,
            platform,
            device_label
        ) in subscriptions or []:

            results.append(
                {
                    "subscription_id":
                        subscription_id,

                    "platform":
                        platform or "other",

                    "device_label":
                        device_label or "Unknown",

                    "subscription_info": {
                        "endpoint":
                            endpoint,

                        "keys": {
                            "p256dh":
                                p256dh,

                            "auth":
                                auth
                        }
                    }
                }
            )


        return results

    except ValueError as e:

        print(
            f"Error retrieving push devices "
            f"for member ID {member_id}: {e}"
        )

        return []

def get_album_delivery_summary(
    album_name
):
    """
    Build a safe administrative summary of who would
    receive a notification for an album.
    """

    summary = []

    members = get_album_members(
        album_name
    )

    for (
        member_id,
        member_name
    ) in members:

        subscriptions = (
            get_enabled_push_subscriptions(
                member_id
            )
        )

        summary.append(
            {
                "member_id":
                    member_id,

                "member_name":
                    member_name,

                "enabled_devices":
                    len(
                        subscriptions
                    ),

                "subscription_ids": [
                    subscription[
                        "subscription_id"
                    ]
                    for subscription
                    in subscriptions
                ]
            }
        )


    return summary

# Build PixelSentinelWeb Push
def build_web_push(
    member_name,
    album_name,
    photo_count,
    send_time=None
):
    """
    Build the Web Push payload.
    """

    if not isinstance(
        member_name,
        str
    ) or not member_name.strip():

        raise ValueError(
            "member_name must be a non-empty string"
        )


    if not isinstance(
        album_name,
        str
    ) or not album_name.strip():

        raise ValueError(
            "album_name must be a non-empty string"
        )


    if (
        not isinstance(
            photo_count,
            int
        )
        or isinstance(
            photo_count,
            bool
        )
        or photo_count < 1
    ):

        raise ValueError(
            "photo_count must be a positive integer"
        )


    if send_time is None:

        send_time = datetime.now()


    senddt = send_time.strftime(
        '%m/%d/%Y at %I:%M %p'
    )


    if photo_count == 1:

        photo_text = (
            "1 new photo"
        )

    else:

        photo_text = (
            f"{photo_count} new photos"
        )


    title = (
        "PixelSentinel: New Photo(s) Added"
    )


    body = (
        f"{member_name}, "
        f"{photo_text} added to the album "
        f"{album_name} on {senddt}."
    )


    return {
        "title":
            title,

        "body":
            body,

        "type":
            "photo_alert",

        "album":
            album_name,

        "photo_count":
            photo_count
    }

"""
Send one PixelSentinel Web Push payload to every
enabled push subscription belonging to a member.

Each device's delivery state is updated independently.

One failed device does not prevent delivery attempts
to the member's other enabled devices.
"""
def send_member_web_push(
    member_id,
    payload,
    ttl=60
):

    if (
        not isinstance(member_id, int)
        or isinstance(member_id, bool)
        or member_id < 1
    ):

        raise ValueError(
            "member_id must be a positive integer"
        )

    if not isinstance(
        payload,
        dict
    ):

        raise ValueError(
            "payload must be a dictionary"
        )


    if (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or ttl < 0
    ):

        raise ValueError(
            "ttl must be a non-negative integer"
        )

    subscriptions = (
        get_enabled_push_subscriptions(
            member_id
        )
    )

    result = {
        "member_id":
            member_id,

        "attempted":
            0,

        "sent":
            0,

        "failed":
            0,

        "successful_subscription_ids":
            [],

        "failed_subscription_ids":
            []
    }

    if not subscriptions:

        return result

    import pixelsentinel_web

    for subscription in subscriptions:

        subscription_id = (
            subscription[
                "subscription_id"
            ]
        )

        subscription_info = (
            subscription[
                "subscription_info"
            ]
        )

        result["attempted"] += 1


        try:

            pixelsentinel_web.send_web_push(
                subscription_info,
                payload,
                ttl=ttl
            )

            # Record successful delivery.
            pixelsentinel_web\
                .record_subscription_delivery_result(
                    subscription_id,
                    True
                )

            result["sent"] += 1


            result[
                "successful_subscription_ids"
            ].append(
                subscription_id
            )


        except pixelsentinel_web.PushDeliveryError:

            # Record only a generic failure state.
            pixelsentinel_web\
                .record_subscription_delivery_result(
                    subscription_id,
                    False,
                    failure_code=
                        "push_send_failed"
                )

            result["failed"] += 1

            result[
                "failed_subscription_ids"
            ].append(
                subscription_id
            )

    return result

"""
Return only safe subscription metadata for an
administrator failure alert.
"""  
def get_admin_failure_subscription_info(
    subscription_id
):

    if (
        not isinstance(subscription_id, int)
        or isinstance(subscription_id, bool)
        or subscription_id < 1
    ):

        return None

    try:

        result = db_execute(
            """
            SELECT
                subscription_id,
                member_id,
                platform,
                device_label,
                enabled,
                failure_count,
                last_error,
                last_success_at

            FROM push_subscriptions

            WHERE subscription_id = ?
            """,
            (
                subscription_id,
            ),
            fetch=True
        )


        if not result:

            return None


        row = result[0]


        return {
            "subscription_id":
                row[0],

            "member_id":
                row[1],

            "platform":
                row[2] or "other",

            "device_label":
                row[3] or "Unknown",

            "enabled":
                row[4],

            "failure_count":
                row[5],

            "last_error":
                row[6] or "push_send_failed",

            "last_success_at":
                row[7]
        }


    except ValueError:

        return None

"""
Convert a value to safe single-line text for the
administrator alert email.
"""
def sanitize_admin_email_text(
    value,
    max_length=200
):
	
    if value is None:

        return "Unknown"

    value = str(
        value
    )

    value = (
        value
        .replace(
            "\r",
            " "
        )
        .replace(
            "\n",
            " "
        )
        .replace(
            "\t",
            " "
        )
        .strip()
    )


    if not value:

        return "Unknown"


    return value[
        :max_length
    ]

"""
Build one aggregated administrator email describing failed Web Push deliveries.
"""
def build_admin_failure_email(
    delivery_summary,
    alert_time=None
):
    if not isinstance(
        delivery_summary,
        dict
    ):

        raise ValueError(
            "delivery_summary must be a dictionary"
        )

    failed_count = (
        delivery_summary.get(
            "failed",
            0
        )
    )

    failed_deliveries = (
        delivery_summary.get(
            "failed_deliveries",
            []
        )
    )

    if (
        not isinstance(failed_count, int)
        or isinstance(failed_count, bool)
        or failed_count < 1
    ):

        raise ValueError(
            "delivery_summary contains no failures"
        )

    if not isinstance(
        failed_deliveries,
        list
    ):

        raise ValueError(
            "failed_deliveries must be a list"
        )

    if alert_time is None:

        alert_time = datetime.now()

    alert_time_text = (
        alert_time.strftime(
            "%m/%d/%Y at %I:%M %p"
        )
    )

    subject = (
        "PixelSentinel: "
        "Web Push Delivery Failure"
    )

    lines = [
        "PixelSentinel detected one or more "
        "Web Push delivery failures.",
        "",
        f"Time: {alert_time_text}",
        (
            "Albums processed: "
            f"{delivery_summary.get('albums_processed', 0)}"
        ),
        (
            "Members processed: "
            f"{delivery_summary.get('members_processed', 0)}"
        ),
        (
            "Push attempts: "
            f"{delivery_summary.get('attempted', 0)}"
        ),
        (
            "Successful deliveries: "
            f"{delivery_summary.get('sent', 0)}"
        ),
        (
            "Failed deliveries this batch: "
            f"{delivery_summary.get(
            'batch_failed',
            failed_count
            )}"
        ),
        (
            "New failure incidents in this alert: "
            f"{failed_count}"
        ),
        "",
        "Failure details:",
        ""
    ]

    for failure in failed_deliveries:

        if not isinstance(
            failure,
            dict
        ):

            continue

        album_name = (
            sanitize_admin_email_text(
                failure.get(
                    "album"
                )
            )
        )

        member_name = (
            sanitize_admin_email_text(
                failure.get(
                    "member_name"
                )
            )
        )

        member_id = (
            failure.get(
                "member_id"
            )
        )

        subscription_ids = (
            failure.get(
                "subscription_ids",
                []
            )
        )

        if not isinstance(
            subscription_ids,
            list
        ):

            continue


        for subscription_id in subscription_ids:

            info = (
                get_admin_failure_subscription_info(
                    subscription_id
                )
            )


            lines.append(
                f"Album: {album_name}"
            )

            lines.append(
                f"Member: {member_name} "
                f"(ID {member_id})"
            )

            lines.append(
                f"Subscription ID: "
                f"{subscription_id}"
            )


            if info is not None:

                lines.append(
                    "Device: "
                    + sanitize_admin_email_text(
                        info[
                            "device_label"
                        ]
                    )
                )

                lines.append(
                    "Platform: "
                    + sanitize_admin_email_text(
                        info[
                            "platform"
                        ]
                    )
                )

                lines.append(
                    "Failure count: "
                    f"{info['failure_count']}"
                )

                lines.append(
                    "Status: "
                    + sanitize_admin_email_text(
                        info[
                            "last_error"
                        ]
                    )
                )

                lines.append(
                    "Last successful delivery: "
                    + sanitize_admin_email_text(
                        info[
                            "last_success_at"
                        ]
                    )
                )

            else:

                lines.append(
                    "Device information: "
                    "Unavailable"
                )


            lines.append(
                ""
            )

    body = "\n".join(
        lines
    )


    message = MIMEMultipart()

    message[
        "From"
    ] = SENDER_EMAIL

    message[
        "To"
    ] = ADMIN_ALERT_EMAIL

    message[
        "Subject"
    ] = subject


    message.attach(
        MIMEText(
            body,
            "plain"
        )
    )

    return message

"""
Send one aggregated Web Push failure alert to the
    configured PixelSentinel administrator.

Returns True when Gmail accepts the message and
    False when the administrator email cannot be sent.
"""
def send_admin_failure_email(
    delivery_summary
):

    configuration_problems = (
        validate_admin_email_configuration()
    )

    if configuration_problems:

        print(
            "Administrator email alert "
            "configuration is invalid."
        )

        return False

    try:

        message = (
            build_admin_failure_email(
                delivery_summary
            )
        )


        context = (
            ssl.create_default_context()
        )


        with smtplib.SMTP_SSL(
            SMTP_SERVER,
            int(
                SMTP_PORT
            ),
            context=context
        ) as smtp:

            smtp.login(
                SMTP_USER,
                SMTP_APP_PASSWORD
            )


            smtp.send_message(
                message
            )


        print(
            "Administrator Web Push failure "
            "alert sent successfully."
        )


        return True


    except (
        smtplib.SMTPException,
        OSError,
        ValueError
    ):

        print(
            "Administrator Web Push failure "
            "alert could not be sent."
        )


        return False

"""
    Handle administrator notification for failed Web Push
    deliveries without repeatedly emailing for the same
    ongoing device failure.

    Returns:
        None  - no administrator email was needed
        True  - administrator email sent and recorded
        False - administrator alert handling failed
"""
def handle_admin_failure_alert(
    delivery_summary
):
    if not isinstance(
        delivery_summary,
        dict
    ):
        raise ValueError(
            "delivery_summary must be a dictionary"
        )

    failed_count = (
        delivery_summary.get(
            "failed",
            0
        )
    )

    if (
        not isinstance(
            failed_count,
            int
        )
        or isinstance(
            failed_count,
            bool
        )
        or failed_count < 0
    ):
        raise ValueError(
            "delivery_summary contains an "
            "invalid failure count"
        )

    if failed_count == 0:

        return None

    subscription_ids = (
        get_unalerted_failed_subscription_ids(
            delivery_summary
        )
    )

    # All failed subscriptions have already generated
    # an administrator alert for their current incident.
    if not subscription_ids:

        return None

    alert_summary = (
        build_admin_alert_summary(
            delivery_summary,
            subscription_ids
        )
    )

    email_sent = (
        send_admin_failure_email(
            alert_summary
        )
    )

    if not email_sent:

        # Do not mark the subscriptions. This allows a
        # later failed batch to retry the administrator
        # email.
        return False

    recorded = (
        mark_admin_failure_alert_sent(
            subscription_ids
        )
    )

    if not recorded:

        print(
            "Administrator alert was sent, "
            "but alert tracking could not "
            "be recorded."
        )
        return False

    return True

"""
Return failed subscription IDs that have not yet
    generated an administrator alert for their current
    failure incident.
"""
def get_unalerted_failed_subscription_ids(
    delivery_summary
):

    if not isinstance(
        delivery_summary,
        dict
    ):
        
        raise ValueError(
            "delivery_summary must be a dictionary"
        )

    failed_deliveries = (
        delivery_summary.get(
            "failed_deliveries",
            []
        )
    )

    if not isinstance(
        failed_deliveries,
        list
    ):

        raise ValueError(
            "failed_deliveries must be a list"
        )

    subscription_ids = set()

    for failure in failed_deliveries:

        if not isinstance(
            failure,
            dict
        ):
            continue

        ids = failure.get(
            "subscription_ids",
            []
        )

        if not isinstance(
            ids,
            list
        ):

            continue

        for subscription_id in ids:

            if (
                isinstance(
                    subscription_id,
                    int
                )
                and not isinstance(
                    subscription_id,
                    bool
                )
                and subscription_id > 0
            ):

                subscription_ids.add(
                    subscription_id
                )

    if not subscription_ids:

        return []

    ordered_ids = sorted(
        subscription_ids
    )

    placeholders = ",".join(
        "?"
        for _ in ordered_ids
    )

    try:

        rows = db_execute(
            f"""
            SELECT subscription_id

            FROM push_subscriptions

            WHERE subscription_id
                IN ({placeholders})

              AND failure_count > 0

              AND admin_alert_sent_at
                  IS NULL

            ORDER BY subscription_id
            """,
            tuple(
                ordered_ids
            ),
            fetch=True
        )

        return [
            row[0]
            for row in rows
        ]

    except ValueError:

        return []

"""
Filter a failed-delivery summary so the administrator
    email contains only failure incidents that have not
    already generated an alert.
"""
def build_admin_alert_summary(
    delivery_summary,
    subscription_ids
):
    allowed_ids = set(
        subscription_ids
    )

    filtered_failures = []

    for failure in delivery_summary.get(
        "failed_deliveries",
        []
    ):

        if not isinstance(
            failure,
            dict
        ):

            continue

        matching_ids = [
            subscription_id

            for subscription_id
            in failure.get(
                "subscription_ids",
                []
            )

            if subscription_id
            in allowed_ids
        ]

        if not matching_ids:

            continue

        filtered_failure = dict(
            failure
        )

        filtered_failure[
            "subscription_ids"
        ] = matching_ids

        filtered_failures.append(
            filtered_failure
        )

    alert_summary = dict(
        delivery_summary
    )

    # Preserve how many failures actually happened
    # in the complete Web Push batch.
    alert_summary[
        "batch_failed"
    ] = delivery_summary.get(
        "failed",
        0
    )

    # "failed" now represents only failures that
    # are included in this administrator email.
    alert_summary[
        "failed"
    ] = len(
        subscription_ids
    )

    alert_summary[
        "failed_deliveries"
    ] = filtered_failures


    return alert_summary

"""
Mark failure incidents as administrator-alerted.

    This is called only after the administrator email
    has been successfully accepted by SMTP.
"""
def mark_admin_failure_alert_sent(
    subscription_ids
):
    if not isinstance(
        subscription_ids,
        list
    ):
        return False

    subscription_ids = sorted({
        subscription_id

        for subscription_id
        in subscription_ids

        if (
            isinstance(
                subscription_id,
                int
            )
            and not isinstance(
                subscription_id,
                bool
            )
            and subscription_id > 0
        )
    })

    if not subscription_ids:

        return False

    placeholders = ",".join(
        "?"
        for _ in subscription_ids
    )

    connection = None

    try:

        connection = sqlite3.connect(
            db_file,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        connection.execute(
            "BEGIN IMMEDIATE"
        )


        cursor = connection.execute(
            f"""
            UPDATE push_subscriptions

            SET
                admin_alert_sent_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE subscription_id
                IN ({placeholders})

              AND failure_count > 0

              AND admin_alert_sent_at
                  IS NULL
            """,
            tuple(
                subscription_ids
            )
        )

        if cursor.rowcount != len(
            subscription_ids
        ):

            connection.rollback()

            return False

        connection.commit()

        return True

    except sqlite3.Error:

        if connection is not None:

            connection.rollback()

        return False

    finally:

        if connection is not None:

            connection.close()

"""
Build and send Web Push photo alerts for each album.

    photo_counts is expected to contain:

        {
            "Album Name": number_of_new_photos
        }

    Returns a safe batch summary.
"""
def send_new_photo_alerts(
    photo_counts,
    send_time=None
):
    if not isinstance(
        photo_counts,
        dict
    ):

        raise ValueError(
            "photo_counts must be a dictionary"
        )

    if send_time is None:

        send_time = datetime.now()

    summary = {
        "albums_processed":
            0,

        "members_processed":
            0,

        "members_without_devices":
            0,

        "attempted":
            0,

        "sent":
            0,

        "failed":
            0,

        "failed_deliveries":
            []
    }

    for album_name, photo_count in (
        photo_counts.items()
    ):

        if (
            not isinstance(album_name, str)
            or not album_name.strip()
        ):

            raise ValueError(
                "album name must be a "
                "non-empty string"
            )

        if (
            not isinstance(photo_count, int)
            or isinstance(photo_count, bool)
            or photo_count < 1
        ):

            raise ValueError(
                "photo count must be a "
                "positive integer"
            )

        members = get_album_members(
            album_name
        )

        summary[
            "albums_processed"
        ] += 1

        for (
            member_id,
            member_name
        ) in members:

            summary[
                "members_processed"
            ] += 1

            payload = build_web_push(
                member_name,
                album_name,
                photo_count,
                send_time
            )

            result = (
                send_member_web_push(
                    member_id,
                    payload
                )
            )

            summary[
                "attempted"
            ] += result[
                "attempted"
            ]

            summary[
                "sent"
            ] += result[
                "sent"
            ]

            summary[
                "failed"
            ] += result[
                "failed"
            ]

            if result[
                "attempted"
            ] == 0:

                summary[
                    "members_without_devices"
                ] += 1

            if result[
                "failed"
            ] > 0:

                summary[
                    "failed_deliveries"
                ].append(
                    {
                        "album":
                            album_name,

                        "member_id":
                            member_id,

                        "member_name":
                            member_name,

                        "subscription_ids":
                            result[
                                "failed_subscription_ids"
                            ]
                    }
                )

    return summary

def main():
    # Start the timer
    start_time = time.time()

    if not os.path.exists(shared_photos):
        print(f"Directory '{shared_photos}' does not exist. Exiting.")
        exit(1)

    # Initialize database
    initialize_database()

    # Initialize push notification tables
    initialize_notification_tables()

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
        # New files were already added to the database by process_file in get_file_list.
        new_photo_counts = (
            get_album_photo_counts(
                files_new
            )
        )

        for file in files_new:

            print(
                f"New File: {file['path']} "
                f"(Checksum: {file['checksum']})"
            )

        delivery_summary = (
            send_new_photo_alerts(
                new_photo_counts
            )
        )

        print(
            "Web Push delivery summary: "
            f"Albums="
            f"{delivery_summary['albums_processed']}, "
            f"Members="
            f"{delivery_summary['members_processed']}, "
            f"Attempts="
            f"{delivery_summary['attempted']}, "
            f"Sent="
            f"{delivery_summary['sent']}, "
            f"Failed="
            f"{delivery_summary['failed']}, "
            f"No devices="
            f"{delivery_summary['members_without_devices']}"
        )
        
        admin_alert_result = (handle_admin_failure_alert(delivery_summary))

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