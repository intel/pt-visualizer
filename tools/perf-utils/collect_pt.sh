#!/bin/bash
# Script to start perf collection. For description of arguments,
# see parse_args.sh

script_args="$@"
WORKING_DIR=$(cd $(dirname "$0") && pwd)
source "$WORKING_DIR"/parse_args.sh

parse_args "$@"
check_args

for pid in `pgrep hhvm | tac`; do
    TTY=$(ps -p "$pid" -o tty | tail -n 1)
    if [ "$TTY" != "?" ]; then
        HHVM_PID="$pid"
        break
    fi
done

if [ -z "$HHVM_PID" ]; then
    echo "No HHVM process running. Abort..."
    exit 1
fi

$perf_binary record -m 512,100000 -e intel_pt/mtc_period=3/u -T     \
                    --pid "$HHVM_PID" -o "$out_dir"/perf.data       \
                     wget --no-proxy http://localhost:8090/index.php?title=Main_Page
$perf_binary inject --jit -i "$out_dir"/perf.data -o "$out_dir"/perf.jitted.data
