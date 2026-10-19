#!/bin/bash

set -u

umask 077


SCRIPT_DIR="$(
    cd "$(dirname "$0")" || exit 1
    pwd
)"

PROJECT_DIR="$SCRIPT_DIR"

VENV_DIR="$PROJECT_DIR/pixelsentinel_env"

GUNICORN="$VENV_DIR/bin/gunicorn"

PYTHON="$VENV_DIR/bin/python3.14"

APP="pixelsentinel_web:app"

BIND="127.0.0.1:5055"


RUN_DIR="$PROJECT_DIR/run"

PID_FILE="$RUN_DIR/pixelsentinel_web.pid"


LOG_DIR="$PROJECT_DIR/logs"

ERROR_LOG="$LOG_DIR/pixelsentinel_web_error.log"


print_error() {
    echo "Error: $1" >&2
    exit 1
}


prepare_directories() {

    mkdir -p \
        "$RUN_DIR" \
        "$LOG_DIR" \
        || print_error \
            "Unable to create runtime directories."

}


check_installation() {

    if [ ! -x "$GUNICORN" ]; then

        print_error \
            "Gunicorn was not found in the virtual environment."

    fi


    if [ ! -f "$PROJECT_DIR/pixelsentinel_web.py" ]; then

        print_error \
            "pixelsentinel_web.py was not found."

    fi
    
    if [ ! -x "$PYTHON" ]; then

    print_error \
        "Python was not found in the virtual environment."

	fi

}


get_pid() {

    if [ ! -f "$PID_FILE" ]; then

        return 1

    fi


    pid="$(
        cat "$PID_FILE" 2>/dev/null
    )"


    case "$pid" in

        ''|*[!0-9]*)

            return 1

            ;;

    esac


    echo "$pid"

}


is_pixelsentinel_process() {

    pid="$1"


    if [ ! -d "/proc/$pid" ]; then

        return 1

    fi


    if ! kill -0 "$pid" 2>/dev/null; then

        return 1

    fi


    if [ ! -r "/proc/$pid/cmdline" ]; then

        return 1

    fi


    command_line="$(
        tr '\000' ' ' \
            < "/proc/$pid/cmdline"
    )"


    echo "$command_line" \
        | grep -q "gunicorn" \
        || return 1


    echo "$command_line" \
        | grep -q "pixelsentinel_web:app" \
        || return 1


    return 0

}


is_running() {

    pid="$(
        get_pid
    )" || return 1


    is_pixelsentinel_process \
        "$pid"

}


start_service() {

    prepare_directories

    check_installation


    if is_running; then

        pid="$(
            get_pid
        )"

        echo \
            "PixelSentinel Web is already running (PID $pid)."

        return 0

    fi


    # Remove stale PID file if one exists.
    if [ -f "$PID_FILE" ]; then

        rm -f "$PID_FILE"

    fi


    echo \
        "Starting PixelSentinel Web..."


    cd "$PROJECT_DIR" \
        || print_error \
            "Unable to enter PixelSentinel directory."


    # DSM Task Scheduler may launch user-defined tasks
    # through /webapi/entry.cgi and provide CGI environment
    # variables to child processes.
    #
    # Gunicorn honors SCRIPT_NAME from the process
    # environment. PixelSentinel is mounted at the root,
    # so SCRIPT_NAME must not be inherited.
    unset SCRIPT_NAME


    # PixelSentinel supplies all Gunicorn arguments
    # explicitly. Prevent inherited Gunicorn arguments
    # from changing the service configuration.
    unset GUNICORN_CMD_ARGS


    "$GUNICORN" \
        --daemon \
        --pid "$PID_FILE" \
        --bind "$BIND" \
        --workers 1 \
        --threads 4 \
        --worker-class gthread \
        --timeout 30 \
        --graceful-timeout 30 \
        --keep-alive 5 \
        --umask 0077 \
        --error-logfile "$ERROR_LOG" \
        --capture-output \
        "$APP"


    # Give Gunicorn a few seconds to create the
    # master process and PID file.
    count=0


    while [ "$count" -lt 10 ]; do

        if is_running; then

            pid="$(
                get_pid
            )"


            # Normalize runtime file permissions.
            if [ -f "$PID_FILE" ]; then
                chmod 600 "$PID_FILE"
            fi


            if [ -f "$ERROR_LOG" ]; then
                chmod 600 "$ERROR_LOG"
            fi


            echo \
                "PixelSentinel Web started successfully (PID $pid)."


            return 0

        fi


        sleep 1

        count=$((count + 1))

    done


    print_error \
        "PixelSentinel Web failed to start."

}


stop_service() {

    if ! is_running; then

        if [ -f "$PID_FILE" ]; then

            rm -f "$PID_FILE"

        fi


        echo \
            "PixelSentinel Web is not running."

        return 0

    fi


    pid="$(
        get_pid
    )"


    echo \
        "Stopping PixelSentinel Web (PID $pid)..."


    # SIGTERM tells Gunicorn to shut down
    # gracefully.
    kill -TERM "$pid" \
        || print_error \
            "Unable to signal Gunicorn."


    count=0


    while [ "$count" -lt 35 ]; do

        if ! kill -0 "$pid" 2>/dev/null; then

            rm -f "$PID_FILE"

            echo \
                "PixelSentinel Web stopped successfully."

            return 0

        fi


        sleep 1

        count=$((count + 1))

    done


    echo \
        "Graceful shutdown timed out."

    echo \
        "Forcing PixelSentinel Web to stop."


    kill -KILL "$pid" 2>/dev/null


    sleep 1


    rm -f "$PID_FILE"


    if kill -0 "$pid" 2>/dev/null; then

        print_error \
            "PixelSentinel Web could not be stopped."

    fi


    echo \
        "PixelSentinel Web stopped."

}


status_service() {

    if is_running; then

        pid="$(
            get_pid
        )"


        echo \
            "PixelSentinel Web is RUNNING."

        echo \
            "Master PID: $pid"

        echo \
            "Bind: $BIND"


        if command -v netstat >/dev/null 2>&1; then

            if netstat -lnt 2>/dev/null \
                | grep -q "127.0.0.1:5055"; then

                echo \
                    "Listener: OK"

            else

                echo \
                    "Listener: WARNING - port 5055 not detected."

            fi

        fi


        return 0

    fi


    echo \
        "PixelSentinel Web is STOPPED."

    return 1

}

health_check() {

    "$PYTHON" - <<'PY' >/dev/null 2>&1
import urllib.request


try:

    with urllib.request.urlopen(
        "http://127.0.0.1:5055/service-worker.js",
        timeout=5
    ) as response:

        raise SystemExit(
            0
            if response.status == 200
            else 1
        )


except Exception:

    raise SystemExit(1)
PY

}

recover_service() {

    prepare_directories

    check_installation


    # --------------------------------------------------
    # Master process is missing
    # --------------------------------------------------

    if ! is_running; then

        echo \
            "PixelSentinel Web is not running. Recovering..."

        # Allow any orphaned Gunicorn worker a moment
        # to notice that its parent has disappeared.
        sleep 2

        start_service

        return $?

    fi


    # --------------------------------------------------
    # Master exists and the application responds
    # --------------------------------------------------

    if health_check; then

        echo \
            "PixelSentinel Web is healthy."

        return 0

    fi


    # --------------------------------------------------
    # Process exists but application is unhealthy
    # --------------------------------------------------

    echo \
        "PixelSentinel Web is running but unhealthy."

    echo \
        "Restarting PixelSentinel Web..."


    restart_service

}

restart_service() {

    stop_service

    sleep 1

    start_service

}


case "${1:-}" in

    start)

        start_service

        ;;


    stop)

        stop_service

        ;;


    restart)

        restart_service

        ;;


    status)

        status_service

        ;;
        
    recover)

    recover_service

    ;;


    *)

        echo \
            "Usage: $0 {start|stop|restart|status|recover}"

        exit 2

        ;;

esac