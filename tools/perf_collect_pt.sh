#!/bin/bash

function print_usage {
    echo >&2 "Usage:"
    echo >&2 "    $0 [args] [extra_oss_performance_args]"
    echo >&2 "    args:"
    echo >&2 "        -h|--help -- prints this message"
    echo >&2 "        -p|--path /PATH/TO/HHVM/BINARY/TO/BENCHMARK -- default is hhvm in PATH"
    echo >&2 "        -d|--default  /PATH/TO/DEFAULT/HHVM/BIN/DIR -- default is hhvm dir specified with -p"
    echo >&2 "        -t|--target TARGET; target must be supported by oss-performance -- default is $target"
    echo >&2 "        -o|--out /PATH/TO/RESULTS/DIR -- default is $cwd/results/$target'"
    echo >&2 "        --oss  /PATH/TO/OSS-PERFORMANCE/ -- default is $oss_path"
    echo >&2 "        --perf /PATH/TO/PERF -- default is $perf_binary"
    echo >&2 "        --db-script /PATH/TO/DB/DUMP/SCRIPT"
    echo >&2 "        --trace-name TRACE_NAME -- default is current timestamp"
}

function error_exit {
    print_usage
    exit -1
}

function check_args {
    if [ -z "$hhvm_path" ]; then
        hhvm_path=$(which hhvm)
        if [ $? -gt 0 ]; then
            echo >&2 "Cannot find HHVM binary! Please specify path to binary with \"--path\""
            exit -1
        fi
    fi

    if [ -z "$default_hhvm" ]; then
        default_hhvm=$hhvm_path
        default_hhvm_path=$(dirname $default_hhvm)
    fi

    if ! [ -f "$oss_path"/perf.php ]; then
        echo >&2 "Cannot find perf.php in $oss_path ! Please specify path to oss-performance with \"--oss\""
        exit -1
    fi

    if ! [ -f "$perf_binary" ]; then
        echo >&2 "Cannot find perf binary! Please specify perf binary path with \"--perf\""
        exit -1
    fi

    collect_pt="\"$PERF_UTILS/collect_pt.sh\" -p \"$perf_binary\" -o \"$out_dir/processor-trace\""

    if [ -z "$out_dir" ]; then
        out_dir="$cwd/results/$target"
    fi
    mkdir -p "$out_dir"

    if [ -z "$db_script" ]; then
        echo >&2 "No perf DB script provided! Trace will not be copied to DB!"
    fi
}

WORKING_DIR=$(cd $(dirname "$0") && pwd)
PERF_UTILS="$WORKING_DIR/perf-utils"
cwd=$(pwd)

#default values
oss_path="$cwd"
target=wordpress
perf_binary=$(which perf)
trace_name=$(date +%s)

collect_pt="\"$PERF_UTILS/collect_pt.sh\" -p \"$perf_binary\" -o \"$out_dir/processor-trace\""
while [[ $# > 0 ]]
do
    key="$1"
    case $key in
    -h|--help)
        print_usage
        exit 0
        ;;
    -p|--path)
        if [ -z "$2" ]; then
            error_exit
        fi
        hhvm_path="$2"
        shift
        ;;
    -d|--default)
        if [ -z "$2" ]; then
            error_exit
        fi
        default_path="$2"
        shift
        ;;
    -t|--target)
        if [ -z "$2" ]; then
            error_exit
        fi
        target="$2"
        shift
        ;;
    -o|--out)
        if [ -z "$2" ]; then
            error_exit
        fi
        out_dir="$2"
        shift
        ;;
    --perf)
        if [ -z "$2" ]; then
            error_exit
        fi
        perf_binary="$2"
        shift
        ;;
    --oss)
        if [ -z "$2" ]; then
            error_exit
        fi
        oss_path="$2"
        shift
        ;;
    --db-script)
        if [ -z "$2" ]; then
            error_exit
        fi
        db_script="$2"
        shift
        ;;
    --trace-name)
        if [ -z "$2" ]; then
            error_exit
        fi
        trace_name="$2"
        shift
        ;;
    *)
        break
    ;;
    esac
    shift
done

check_args

extra_args=${@:1}

echo "Cleaning perf buildid cache for HHVM"
"$perf_binary" buildid-cache --remove "$hhvm_path"

mkdir -p "$out_dir"/processor-trace
echo "Running workload"
echo | http_proxy="" PATH="$default_hhvm_path:$PATH" "$default_hhvm" "$oss_path/perf.php"  \
            --"$target"                                                             \
            --hhvm="$hhvm_path"                                                     \
            --wait-at-end                                                           \
            --hhvm-extra-arguments "-vEval.MaxHotTextHugePages=0"                   \
            --hhvm-extra-arguments "-vEval.PerfJitDump=1"                           \
            --i-am-not-benchmarking                                                 \
            --client-threads=1                                                      \
            --server-threads=1                                                      \
            --exec-after-benchmark="$collect_pt"                                    \
            $extra_args  > "$out_dir"/processor-trace/allout.txt 2>&1

if ! [ -z "$db_script" ]; then
    echo "Inserting perf data into the database"
    "$perf_binary" script -i "$out_dir"/processor-trace/perf.jitted.data --itrace=i0nse -s "$db_script" "$trace_name" collapse-jit-dsos
fi
