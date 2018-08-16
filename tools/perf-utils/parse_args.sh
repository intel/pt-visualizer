#!/bin/bash

function print_usage {
    echo >&2 "Usage:"
    echo >&2 "    $0 -o [out_dir] -p [perf_binary]"
    echo >&2 "    args:"
    echo >&2 "        -h|--help -- prints this message"
    echo >&2 "        -p|--perf-binary /PATH/TO/PERF -- REQUIRED"
    echo >&2 "        -o|--out /PATH/TO/RESULTS/DIR -- REQUIRED"
}

function error_exit {
    print_usage
    exit -1
}

function check_args {
    if ! [ -f "$perf_binary" ]; then
        echo >&2 "Cannot find perf binary! Please specify correct path to perf"
        exit -1
    fi

    if [ -z "$out_dir" ]; then
        echo >&2 "Please specify an output directory"
        exit -1
    fi

    mkdir -p "$out_dir"
}

function parse_args {
    cwd=$(pwd)

    while [[ $# > 0 ]]
    do
        key="$1"
        case $key in
        -p|--perf-binary)
            if [ -z "$2" ]; then
                echo >&2 "Perf binary not found"
                error_exit
            fi
            perf_binary="$2"
            shift
            ;;
        -o|--out)
            if [ -z "$2" ]; then
                echo >&2 "Out folder not found"
                error_exit
            fi
            out_dir="$2"
            shift
            ;;
        -h|--help)
            echo >&2 "Help called"
            print_usage
            exit 0
            ;;
        *)
            echo >&2 "Key not recognized: $key"
            error_exit
        ;;
        esac
        shift
    done
}

