#!/bin/bash
cwd=$(pwd)
venvdir="$cwd/bin/venv"
pidfile="$cwd/python.pid"
appdir="$cwd/src/ui"
logfile="$cwd/pt-vis.log"
dbconfigdir="$cwd/conf"
dbconfig="$dbconfigdir/db_config"
backenddir="$cwd/pt-visualizer/backend"

function show_help {
    echo "Usage $(basename -- $0) [command1] [command2] ..."
    echo "Available commands: "
    echo " -v/--venv : Installs Python VirtualEnv"
    echo " -s/--serv : Start Flask web app"
    echo " -k/--kill : Kill Flask web app"
    echo " -b/--build : Build web app"
    echo " -c/--clean : Clean web app"
    echo " -d/--db : Setup the database"
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
    python "$backenddir/sat-backend.py" >> "$logfile" 2>&1 &
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

function gendbconfig {
    if [ -z "$RANDOM" ]; then
        echo "Fatal error: RANDOM is not available in this shell"
        exit -1
    fi
    read -r dbname nothing <<< `echo $RANDOM$RANDOM$RANDOM | md5sum`
    read -r dbuser nothing <<< `echo $RANDOM$RANDOM$RANDOM | md5sum`
    read -r dbpassword nothing <<< `echo $RANDOM$RANDOM$RANDOM | md5sum`
    dbname="_$dbname"
    dbuser="_$dbuser"
    echo "[DB]" > "$dbconfig"
    echo "dbname: $dbname" >> "$dbconfig"
    echo "user: $dbuser" >> "$dbconfig"
    echo "password: $dbpassword" >> "$dbconfig"
    chmod 400 "$dbconfig"
}

function dbsetup {
    if [ ! -d "$dbconfigdir" ]; then
        mkdir -p "$dbconfigdir"
    fi
    if [ ! -f "$dbconfig" ]; then
        gendbconfig
        founduname=`sudo -u postgres psql -q -t --command "SELECT usename FROM pg_user WHERE usename = '$dbuser';" | xargs`
        if [ -z $founduname ]; then
            sudo -u postgres psql -q --command "CREATE USER $dbuser WITH PASSWORD '$dbpassword';"
            sudo -u postgres psql -q --command "CREATE DATABASE $dbname OWNER $dbuser;"
        else
            echo "User $dbuser already present in the database"
        fi
    else
        echo "Database was already setup!"
    fi
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
    -d|--db)
        dbsetup
    ;;
    *)
        echo "Unrecognized command: $key, ignoring..."
        show_help
    ;;
    esac
    shift
done