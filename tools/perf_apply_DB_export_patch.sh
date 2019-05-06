#! /bin/bash

WORKING_DIR=$(cd $(dirname "$0") && pwd)
cd $WORKING_DIR
LOG_FILE="$WORKING_DIR"/output_log.txt
LOG_FILENAME="output_log.txt"

# Download kernel source. This script is intended for Linux kernel 4.8
# and it might not work for a different kernel version.
INTENDED_KERNEL_VERSION="4.15"
KERNEL_VERSION=$(uname -r | awk --field-separator "." '{ print $1 "." $2 }')
if [ "$KERNEL_VERSION" != "$INTENDED_KERNEL_VERSION" ]; then
    echo
    echo -n "*** WARNING *** This script is intended for Linux kernel "
    echo -n "v$INTENDED_KERNEL_VERSION, while current kernel version is "
    echo "$KERNEL_VERSION. This might lead to incorrect results"
    echo
fi

rm -rf "$LOG_FILE"
rm -rf linux-"$KERNEL_VERSION".tar.gz linux-"$KERNEL_VERSION"

echo -n "Downloading perf source..." | tee -a "$LOG_FILE"
echo &>> "$LOG_FILE"
wget https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux-stable.git/snapshot/linux-"$KERNEL_VERSION".tar.gz &>> "$LOG_FILE"
res="$?"
if [ "$res" -ne 0 ]; then
    echo
    echo -n "wget: Error retrieving kernel source for version $KERNEL_VERSION."
    echo "Please check $LOG_FILENAME for details. Exiting"
    exit "$res"
fi
echo "OK"

tar -xf linux-"$KERNEL_VERSION".tar.gz
cd linux-"$KERNEL_VERSION"
echo -en "\nPatching perf..." | tee -a "$LOG_FILE"
echo &>> "$LOG_FILE"
patch -p1 < ../0001-Implement-DB-structure-for-heatmap-tool.patch &>> "$LOG_FILE"
res="$?"
if [ "$res" -ne "0" ]; then
    echo
    echo -en "\nError applying DB export patch. "
    echo "Please check $LOG_FILENAME for details. Exiting"
    exit "$res"
fi
echo "OK"

INSTALL_FOLDER="$WORKING_DIR"/perf_install

echo | tee -a "$LOG_FILE"
echo "==================================================================" | tee -a "$LOG_FILE"
echo "======================= Building perf ============================" | tee -a "$LOG_FILE"
echo "==================================================================" | tee -a "$LOG_FILE"
mkdir -p "$INSTALL_FOLDER"
cd tools/perf
make prefix="$INSTALL_FOLDER" install | tee -a "$LOG_FILE"
res="$?"
if [ "$res" -ne "0" ]; then
    echo
    echo -en "\nError building perf. "
    echo "Please check $LOG_FILENAME for details. Exiting"
    exit "$res"
fi

