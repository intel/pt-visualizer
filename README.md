# PT (Processor Trace) Visualizer

Experimental Linux SW tool to collect an Intel Processor Trace (PT) using Linux perf and visualize it as an instruction heat map.

## Overview

The tool was tailored for collecting a PT for HHVM running the one URL of the Mediawiki workload present in [oss-performance](https://github.com/facebookarchive/oss-performance), but it can be easily be modified to work for any other Linux binary and use case. The PT Visualizer works on Linux based OSes running in X86 which has Intel PT tracing block.

The PT visualizer uses a modified perf to collect the PT for one Mediawiki request, which is then inserted into a PostgreSQL database. The visualization front-end uses the trace information in the database to offer insights on the amount of code executed (working set size) and to construct an instruction access heat map for HHVM and all shared libraries used for the web request.

The PT Visualizer's web ui displays the PT as an instruction heat ma, a color-coded representation of the program’s memory space, where each pixel summarizes the access count for a particular memory range. Clicking a pixel will offer information on the instruction hit count per each function in that address space, as well as ASM annotations to identify hot instructions within one function.

## License

 * perf patch and export_to_postgresql.py under GNU General Public License version 2.
 * Rest of the PT Visualizer tool is licensed under Apache License, Version 2.0.

## Dependencies

  Needed libraries to build and use the PT Visualizer

  packages (Ubuntu):
```
  build-essential scons libelf-dev python-pip git binutils-dev autoconf libtool libiberty-dev zlib1g-dev python-dev python-virtualenv python-psycopg2 postgresql-9.x libpq-dev elfutils libunwind-dev libperl-dev numactl libaudit-dev libgtk2.0-dev libdw-dev
```

## Install PT Visualizer

### Clone or Download PT Visualizer tool
```
git clone https://github.com/intel/pt-visualizer
```

### Download and patch Linux perf tool
```
cd pt-visualizer/tools
./perf_apply_DB_export_patch.sh

```

### Build UI
```
cd pt-visualizer
./pt-vis.sh --build

```

### Set up DB
```
./pt-vis.sh --db
```
sudo access required to set up the new DB user
The command above will create random DB credentials and store them in
`conf/db_config`, which can only be read by the current user. This will
ensure that the current user is the only one who can access the PT data in
the DB.

### Set up Python virtualenv
```
./pt-vis.sh --venv
```

### Start the Flask webserver
```
./pt-vis.sh
```
The web UI of the PT visualizer is now accessible at localhost:5005.

## Collect a PT
```
cd tools
./perf_collect_pt.sh -p /usr/bin/hhvm -t mediawiki -o `pwd`/results --oss ~/oss-performance --perf ~/pt-visualizer/tools/perf_install/bin/perf --db-script ~/pt-visualizer/tools/export-to-postgresql.py --trace-name pt_vis_trace_hhvm_mediawiki
```
The command line above assumes you have a functional oss-performance installation
in `~/oss-performance` and hhvm installed on the system. If you need to collect
a PT for a different binary and use case, please see `tools/perf_collect_pt.sh`
and `tools/perf-utils/collect_pt.sh`.

## Visualize the PT
Use a browser to navigate to http://localhost:5005 to see a list of all your
traces. After the previous command completes, the new trace should be present
in the list.

## Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
