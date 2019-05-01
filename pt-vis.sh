#!/bin/bash
cwd=$(pwd)
venvdir="$cwd/bin/venv"
pidfile="$cwd/python.pid"
appdir="$cwd/src/ui"
logfile="$cwd/pt-vis.log"
backenddir="$cwd/pt-visualizer/backend"

function show_help {
    echo "Usage $(basename -- $0) [command1] [command2] ..."
    echo "Available commands: "
    echo " -v/--venv : Installs Python VirtualEnv"
    echo " -s/--serv : Start Flask web app"
    echo " -k/--kill : Kill Flask web app"
    echo " -b/--build : Build web app"
    echo " -c/--clean : Clean web app"
}

function venv {
    echo "Creating Python VirtualEnv"
    if [ -d "$venvdir" ]; then
        rm -rf "$venvdir"
    fi
    mkdir -p "$venvdir"
    python -m virtualenv "$venvdir"
    source "$venvdir/bin/activate"
    pip install -r "$backenddir/requirement.txt"
    deactivate
    echo "Done!"
}

function killserv {
    echo "Killing Python processes"
    if [ -f "$pidfile" ]; then
        pypid=`cat "$pidfile"`
        pypid="$pypid `ps -o pid= --ppid $pypid`"
        echo "Killing $pypid"
        kill -9 $pypid
        rm "$pidfile"
        echo "----------------------------------------------">> "$logfile"
        echo "Server killed at `date`">> "$logfile"
        echo "----------------------------------------------">> "$logfile"
        echo "Done!"
    else
        echo "PID file not found"
    fi
}

function startserv {
    if [ ! -d $venvdir ]; then
        echo "Python VirtualEnv not found, creating..."
        venv
    fi
    if [ -f "$pidfile" ]; then
        killserv
    fi
    echo "Starting server"
    echo "----------------------------------------------">> "$logfile"
    echo "Server started at `date`">> "$logfile"
    echo "----------------------------------------------">> "$logfile"
    source "$venvdir/bin/activate"
    python "$backenddir/sat-backend.py" &>> "$logfile" &
    echo $! > "$pidfile"
    echo "Running server"
}

function buildapp {
    echo "Building web app"
    cd "$appdir"
    npm install
    node_modules/bower/bin/bower install
    node_modules/gulp/bin/gulp.js build
    cd "$cwd"
    echo "Done!"
}

function cleanapp {
    echo "Cleaning app"
    cd "$appdir"
    node_modules/gulp/bin/gulp.js clean
    cd "$cwd"
}

while [[ $# > 0 ]]
do
    key="$1"
    case $key in
    -v|--venv)
        venv
    ;;
    -s|--serv)
        startserv
    ;;
    -k|--kill)
        killserv
    ;;
    -b|--build)
        buildapp
    ;;
    -c|--clean)
        cleanapp
    ;;
    *)
        echo "Unrecognized command: $key, ignoring..."
        show_help
    ;;
    esac
    shift
done