#!/bin/bash

set -u

umask 077


# ==================================================
# PixelSentinel Application Backup
# ==================================================

SCRIPT_DIR="$(
    cd "$(dirname "$0")" \
        && pwd
)"

PROJECT_DIR="$SCRIPT_DIR"

PYTHON="$PROJECT_DIR/pixelsentinel_env/bin/python3.14"

DATABASE="$PROJECT_DIR/pixelsentinel.db"

ENV_FILE="$PROJECT_DIR/.env"

VAPID_DIR="$PROJECT_DIR/vapid_keys"

PRIVATE_KEY="$VAPID_DIR/private_key.pem"

PUBLIC_KEY="$VAPID_DIR/public_key.pem"

BACKUP_ROOT="$PROJECT_DIR/backups"

# Keep application-consistent backups for 14 actual days.
RETENTION_DAYS=14


TIMESTAMP="$(
    date -u '+%Y%m%dT%H%M%SZ'
)"

FINAL_BACKUP="$BACKUP_ROOT/backup-$TIMESTAMP"

TEMP_BACKUP="$BACKUP_ROOT/.backup-$TIMESTAMP.tmp"


# ==================================================
# Helper functions
# ==================================================

fail() {

    echo "ERROR: $1" >&2

    if [ -d "$TEMP_BACKUP" ]; then
        rm -rf "$TEMP_BACKUP"
    fi

    exit 1

}


cleanup_temp() {

    if [ -d "$TEMP_BACKUP" ]; then
        rm -rf "$TEMP_BACKUP"
    fi

}


trap cleanup_temp EXIT


echo
echo "PixelSentinel Backup"
echo "===================="
echo


# ==================================================
# Validate required files
# ==================================================

[ -x "$PYTHON" ] \
    || fail "Python virtual environment was not found."

[ -f "$DATABASE" ] \
    || fail "pixelsentinel.db was not found."

[ -f "$ENV_FILE" ] \
    || fail ".env was not found."

[ -f "$PRIVATE_KEY" ] \
    || fail "VAPID private key was not found."

[ -f "$PUBLIC_KEY" ] \
    || fail "VAPID public key was not found."


# ==================================================
# Prepare protected backup directory
# ==================================================

mkdir -p "$BACKUP_ROOT" \
    || fail "Unable to create backup root."

chmod 700 "$BACKUP_ROOT" \
    || fail "Unable to secure backup root."


if [ -e "$TEMP_BACKUP" ]; then

    fail \
        "Temporary backup destination already exists: $TEMP_BACKUP"

fi


if [ -e "$FINAL_BACKUP" ]; then

    fail \
        "Backup destination already exists: $FINAL_BACKUP"

fi


mkdir "$TEMP_BACKUP" \
    || fail "Unable to create temporary backup directory."

chmod 700 "$TEMP_BACKUP" \
    || fail "Unable to secure temporary backup directory."


# ==================================================
# Create SQLite-consistent database backup
# ==================================================

echo "Creating SQLite database snapshot..."


if ! "$PYTHON" \
    - "$DATABASE" "$TEMP_BACKUP/pixelsentinel.db" <<'PY'
import sqlite3
import sys


source_path = sys.argv[1]
backup_path = sys.argv[2]


source = sqlite3.connect(
    f"file:{source_path}?mode=ro",
    uri=True,
    timeout=30,
)

destination = sqlite3.connect(
    backup_path,
    timeout=30,
)


try:

    source.backup(
        destination
    )

    result = destination.execute(
        "PRAGMA quick_check"
    ).fetchone()

    if not result or result[0] != "ok":

        raise RuntimeError(
            f"SQLite quick_check failed: {result}"
        )

finally:

    destination.close()
    source.close()
PY
then

    fail \
        "Database backup or SQLite integrity check failed."

fi


chmod 600 \
    "$TEMP_BACKUP/pixelsentinel.db" \
    || fail "Unable to secure database backup."


# ==================================================
# Back up private configuration
# ==================================================

echo "Backing up private configuration..."


cp "$ENV_FILE" \
    "$TEMP_BACKUP/.env" \
    || fail "Unable to back up .env."


chmod 600 \
    "$TEMP_BACKUP/.env" \
    || fail "Unable to secure .env backup."


# ==================================================
# Back up VAPID identity
# ==================================================

echo "Backing up VAPID identity..."


mkdir "$TEMP_BACKUP/vapid_keys" \
    || fail "Unable to create VAPID backup directory."


chmod 700 \
    "$TEMP_BACKUP/vapid_keys" \
    || fail "Unable to secure VAPID backup directory."


cp "$PRIVATE_KEY" \
    "$TEMP_BACKUP/vapid_keys/private_key.pem" \
    || fail "Unable to back up VAPID private key."


cp "$PUBLIC_KEY" \
    "$TEMP_BACKUP/vapid_keys/public_key.pem" \
    || fail "Unable to back up VAPID public key."


chmod 600 \
    "$TEMP_BACKUP/vapid_keys/private_key.pem" \
    "$TEMP_BACKUP/vapid_keys/public_key.pem" \
    || fail "Unable to secure VAPID key backups."


# ==================================================
# Create SHA-256 integrity manifest
# ==================================================

echo "Creating integrity manifest..."


if ! "$PYTHON" \
    - "$TEMP_BACKUP" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys


backup_dir = Path(
    sys.argv[1]
).resolve()


files = [
    backup_dir / "pixelsentinel.db",
    backup_dir / ".env",
    backup_dir / "vapid_keys" / "private_key.pem",
    backup_dir / "vapid_keys" / "public_key.pem",
]


lines = []


for path in files:

    if not path.is_file():

        raise RuntimeError(
            f"Required backup file is missing: {path}"
        )

    digest = sha256(
        path.read_bytes()
    ).hexdigest()

    relative = path.relative_to(
        backup_dir
    )

    lines.append(
        f"{digest}  {relative}"
    )


manifest = backup_dir / "SHA256SUMS"

manifest.write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)
PY
then

    fail \
        "Unable to create integrity manifest."

fi


chmod 600 \
    "$TEMP_BACKUP/SHA256SUMS" \
    || fail "Unable to secure integrity manifest."


# ==================================================
# Finalize backup atomically
# ==================================================

echo "Finalizing backup..."


mv "$TEMP_BACKUP" "$FINAL_BACKUP" \
    || fail "Unable to finalize backup."


chmod 700 "$FINAL_BACKUP" \
    || fail "Unable to secure finalized backup."


# Temporary directory no longer exists.
trap - EXIT


# ==================================================
# Apply true 14-day retention policy
# ==================================================

echo "Applying backup retention policy..."


if ! "$PYTHON" \
    - "$BACKUP_ROOT" "$RETENTION_DAYS" "$FINAL_BACKUP" <<'PY'
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import shutil
import sys


backup_root = Path(
    sys.argv[1]
).resolve()

retention_days = int(
    sys.argv[2]
)

current_backup = Path(
    sys.argv[3]
).resolve()


if retention_days < 1:

    raise RuntimeError(
        "Retention days must be at least 1."
    )


if current_backup.parent != backup_root:

    raise RuntimeError(
        "Current backup is not inside the backup root."
    )


pattern = re.compile(
    r"^backup-(\d{8}T\d{6}Z)$"
)


now = datetime.now(
    timezone.utc
)

cutoff = now - timedelta(
    days=retention_days
)


retained = 0
removed = 0
skipped = 0


for path in sorted(
    backup_root.iterdir()
):

    if not path.is_dir():
        continue

    if path.parent != backup_root:
        continue

    match = pattern.fullmatch(
        path.name
    )

    if not match:

        # Ignore temporary, manually-created,
        # or otherwise unrecognized directories.
        continue


    timestamp_text = match.group(1)


    try:

        backup_time = datetime.strptime(
            timestamp_text,
            "%Y%m%dT%H%M%SZ",
        ).replace(
            tzinfo=timezone.utc
        )

    except ValueError:

        print(
            f"Skipping backup with invalid timestamp: "
            f"{path.name}"
        )

        skipped += 1
        continue


    # Never delete the backup that was just created,
    # even if the NAS clock were somehow incorrect.
    if path.resolve() == current_backup:

        retained += 1
        continue


    if backup_time < cutoff:

        shutil.rmtree(
            path
        )

        print(
            f"Removed expired backup: "
            f"{path.name}"
        )

        removed += 1

    else:

        retained += 1


print(
    f"Retention period: {retention_days} day(s)"
)

print(
    f"Backups retained: {retained}"
)

print(
    f"Expired backups removed: {removed}"
)

if skipped:

    print(
        f"Unrecognized backups skipped: {skipped}"
    )
PY
then

    fail \
        "Backup retention cleanup failed."

fi


# ==================================================
# Final result
# ==================================================

echo
echo "Backup completed successfully."
echo "Backup: $FINAL_BACKUP"
echo
