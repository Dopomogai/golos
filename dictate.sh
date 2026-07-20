#!/bin/bash
# dictate launcher: ./dictate.sh [start|quit|restart]
cd "$(dirname "$0")"
LOCK="$HOME/.golos/dictate.lock"

lock_pid() {
    sed -n 's/^pid \([0-9][0-9]*\).*/\1/p' "$LOCK" 2>/dev/null | head -1
}

cmd_quit() {
    p=$(lock_pid)
    if [ -z "$p" ]; then
        echo "no pid in $LOCK; removing stale lock"
        rm -f "$LOCK"
        return 1
    fi
    cmd=$(ps -p "$p" -o command= 2>/dev/null)
    if [ -z "$cmd" ] || [ "$cmd" = "-" ]; then
        echo "pid $p is gone; stale lock removed"
        rm -f "$LOCK"
        return 0
    fi
    case "$cmd" in
        *"-m dictate"*)
            kill "$p" 2>/dev/null
            for i in 1 2 3 4; do
                kill -0 "$p" 2>/dev/null || break
                sleep 0.5
            done
            if kill -0 "$p" 2>/dev/null; then
                # suspended (Ctrl+Z) processes can't run the Python SIGTERM
                # handler — unstick and force it
                kill -CONT "$p" 2>/dev/null
                kill -9 "$p" 2>/dev/null
                echo "force-killed dictate (pid $p)"
            else
                echo "quit dictate (pid $p)"
            fi
            ;;
        *)
            echo "pid $p is not dictate ('$cmd'); not touching it" >&2
            return 1
            ;;
    esac
}

case "${1:-start}" in
    start)
        shift 2>/dev/null
        exec .venv/bin/python -m dictate "$@"
        ;;
    quit)
        cmd_quit
        ;;
    restart)
        cmd_quit || true
        sleep 0.5
        exec "$0" start
        ;;
    *)
        echo "usage: $0 [start|quit|restart]" >&2
        exit 2
        ;;
esac
