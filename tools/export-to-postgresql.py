# export-to-postgresql.py: export perf data to a postgresql database
# Copyright (c) 2014, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.

import os
import sys
import struct
import datetime
import multiprocessing
import platform
import re

# To use this script you will need to have installed package python-pyside which
# provides LGPL-licensed Python bindings for Qt.  You will also need the package
# libqt4-sql-psql for Qt postgresql support.
#
# The script assumes postgresql is running on the local machine and that the
# user has postgresql permissions to create databases. Examples of installing
# postgresql and adding such a user are:
#
# fedora:
#
#	$ sudo yum install postgresql postgresql-server python-pyside qt-postgresql
#	$ sudo su - postgres -c initdb
#	$ sudo service postgresql start
#	$ sudo su - postgres
#	$ createuser <your user id here>
#	Shall the new role be a superuser? (y/n) y
#
# ubuntu:
#
#	$ sudo apt-get install postgresql python-pyside.qtsql libqt4-sql-psql
#	$ sudo su - postgres
#	$ createuser -s <your user id here>
#
# An example of using this script with Intel PT:
#
#	$ perf record -e intel_pt//u ls
#	$ perf script -s ~/libexec/perf-core/scripts/python/export-to-postgresql.py pt_example branches calls
#	2015-05-29 12:49:23.464364 Creating database...
#	2015-05-29 12:49:26.281717 Writing to intermediate files...
#	2015-05-29 12:49:27.190383 Copying to database...
#	2015-05-29 12:49:28.140451 Removing intermediate files...
#	2015-05-29 12:49:28.147451 Adding primary keys
#	2015-05-29 12:49:28.655683 Adding foreign keys
#	2015-05-29 12:49:29.365350 Done
#
# To browse the database, psql can be used e.g.
#
#	$ psql pt_example
#	pt_example=# select * from samples_view where id < 100;
#	pt_example=# \d+
#	pt_example=# \d+ samples_view
#	pt_example=# \q
#
# An example of using the database is provided by the script
# call-graph-from-sql.py.  Refer to that script for details.
#
# Tables:
#
#	The tables largely correspond to perf tools' data structures.  They are largely self-explanatory.
#
#	samples
#
#		'samples' is the main table. It represents what instruction was executing at a point in time
#		when something (a selected event) happened.  The memory address is the instruction pointer or 'ip'.
#
#	calls
#
#		'calls' represents function calls and is related to 'samples' by 'call_id' and 'return_id'.
#		'calls' is only created when the 'calls' option to this script is specified.
#
#	call_paths
#
#		'call_paths' represents all the call stacks.  Each 'call' has an associated record in 'call_paths'.
#		'calls_paths' is only created when the 'calls' option to this script is specified.
#
#	branch_types
#
#		'branch_types' provides descriptions for each type of branch.
#
#	comm_threads
#
#		'comm_threads' shows how 'comms' relates to 'threads'.
#
#	comms
#
#		'comms' contains a record for each 'comm' - the name given to the executable that is running.
#
#	dsos
#
#		'dsos' contains a record for each executable file or library.
#
#	machines
#
#		'machines' can be used to distinguish virtual machines if virtualization is supported.
#
#	selected_events
#
#		'selected_events' contains a record for each kind of event that has been sampled.
#
#	symbols
#
#		'symbols' contains a record for each symbol.  Only symbols that have samples are present.
#
#	threads
#
#		'threads' contains a record for each thread.
#
# Views:
#
#	Most of the tables have views for more friendly display.  The views are:
#
#		calls_view
#		call_paths_view
#		comm_threads_view
#		dsos_view
#		machines_view
#		samples_view
#		symbols_view
#		threads_view
#
# More examples of browsing the database with psql:
#   Note that some of the examples are not the most optimal SQL query.
#   Note that call information is only available if the script's 'calls' option has been used.
#
#	Top 10 function calls (not aggregated by symbol):
#
#		SELECT * FROM calls_view ORDER BY elapsed_time DESC LIMIT 10;
#
#	Top 10 function calls (aggregated by symbol):
#
#		SELECT symbol_id,(SELECT name FROM symbols WHERE id = symbol_id) AS symbol,
#			SUM(elapsed_time) AS tot_elapsed_time,SUM(branch_count) AS tot_branch_count
#			FROM calls_view GROUP BY symbol_id ORDER BY tot_elapsed_time DESC LIMIT 10;
#
#		Note that the branch count gives a rough estimation of cpu usage, so functions
#		that took a long time but have a relatively low branch count must have spent time
#		waiting.
#
#	Find symbols by pattern matching on part of the name (e.g. names containing 'alloc'):
#
#		SELECT * FROM symbols_view WHERE name LIKE '%alloc%';
#
#	Top 10 function calls for a specific symbol (e.g. whose symbol_id is 187):
#
#		SELECT * FROM calls_view WHERE symbol_id = 187 ORDER BY elapsed_time DESC LIMIT 10;
#
#	Show function calls made by function in the same context (i.e. same call path) (e.g. one with call_path_id 254):
#
#		SELECT * FROM calls_view WHERE parent_call_path_id = 254;
#
#	Show branches made during a function call (e.g. where call_id is 29357 and return_id is 29370 and tid is 29670)
#
#		SELECT * FROM samples_view WHERE id >= 29357 AND id <= 29370 AND tid = 29670 AND event LIKE 'branches%';
#
#	Show transactions:
#
#		SELECT * FROM samples_view WHERE event = 'transactions';
#
#		Note transaction start has 'in_tx' true whereas, transaction end has 'in_tx' false.
#		Transaction aborts have branch_type_name 'transaction abort'
#
#	Show transaction aborts:
#
#		SELECT * FROM samples_view WHERE event = 'transactions' AND branch_type_name = 'transaction abort';
#
# To print a call stack requires walking the call_paths table.  For example this python script:
#   #!/usr/bin/python2
#
#   import sys
#   from PySide.QtSql import *
#
#   if __name__ == '__main__':
#           if (len(sys.argv) < 3):
#                   print >> sys.stderr, "Usage is: printcallstack.py <database name> <call_path_id>"
#                   raise Exception("Too few arguments")
#           dbname = sys.argv[1]
#           call_path_id = sys.argv[2]
#           db = QSqlDatabase.addDatabase('QPSQL')
#           db.setDatabaseName(dbname)
#           if not db.open():
#                   raise Exception("Failed to open database " + dbname + " error: " + db.lastError().text())
#           query = QSqlQuery(db)
#           print "    id          ip  symbol_id  symbol                          dso_id  dso_short_name"
#           while call_path_id != 0 and call_path_id != 1:
#                   ret = query.exec_('SELECT * FROM call_paths_view WHERE id = ' + str(call_path_id))
#                   if not ret:
#                           raise Exception("Query failed: " + query.lastError().text())
#                   if not query.next():
#                           raise Exception("Query failed")
#                   print "{0:>6}  {1:>10}  {2:>9}  {3:<30}  {4:>6}  {5:<30}".format(query.value(0), query.value(1), query.value(2), query.value(3), query.value(4), query.value(5))
#                   call_path_id = query.value(6)

from PySide.QtSql import *

# Need to access PostgreSQL C library directly to use COPY FROM STDIN
from ctypes import *
libpq = CDLL("libpq.so.5")
PQconnectdb = libpq.PQconnectdb
PQconnectdb.restype = c_void_p
PQfinish = libpq.PQfinish
PQfinish.argtypes = [c_void_p]
PQstatus = libpq.PQstatus
PQstatus.argtypes = [c_void_p]
PQexec = libpq.PQexec
PQexec.restype = c_void_p
PQexec.argtypes = [c_void_p, c_char_p]
PQresultStatus = libpq.PQresultStatus
PQresultStatus.argtypes = [c_void_p]
PQputCopyData = libpq.PQputCopyData
PQputCopyData.argtypes = [ c_void_p, c_void_p, c_int ]
PQputCopyEnd = libpq.PQputCopyEnd
PQputCopyEnd.argtypes = [ c_void_p, c_void_p ]

sys.path.append(os.environ['PERF_EXEC_PATH'] + \
	'/scripts/python/Perf-Trace-Util/lib/Perf/Trace')

# These perf imports are not used at present
#from perf_trace_context import *
#from Core import *

perf_db_export_mode = True
perf_db_export_calls = False
perf_db_export_callchains = False
perf_collapse_jit_dsos = False

def usage():
	print >> sys.stderr, "Usage is: export-to-postgresql.py <database name> [collapse-jit-dsos]  [all/branches] [calls]"
	raise Exception("Wrong usage")

if (len(sys.argv) < 2):
	usage()
else:
	if len(sys.argv) > 2:
		if sys.argv[2] != 'collapse-jit-dsos':
			usage()
		else:
			perf_collapse_jit_dsos = True

if (len(sys.argv) >= 4):
	columns = sys.argv[3]
else:
	columns = "all"

if columns not in ("all", "branches"):
	usage()

branches = (columns == "branches")

for i in range(4,len(sys.argv)):
	if (sys.argv[i] == "calls"):
		perf_db_export_calls = True
	elif (sys.argv[i] == "callchains"):
		perf_db_export_callchains = True
	else:
		usage()

dbname = 'sat'
dbuser = 'sat'
dbpass = 'uranus'
dbgivenname = sys.argv[1]

def do_query(q, s):
	if (q.exec_(s)):
		return
	raise Exception("Query failed: " + q.lastError().text())

print datetime.datetime.today(), "Creating database schema..."

db = QSqlDatabase.addDatabase('QPSQL')
query = QSqlQuery(db)
db.setDatabaseName(dbname)
db.setUserName(dbuser)
db.setPassword(dbpass)
db.open()

uname = os.uname()
linux_distr = platform.linux_distribution()
cpu_count = multiprocessing.cpu_count()
device = uname[1] + "/" + " ".join(linux_distr)
build = uname[3] + "/" + uname[0]
do_query(query, 'INSERT INTO public.traces (name, cpu_count, device, created, build) '
				'values (\'' + dbgivenname + '\', \'' + str(cpu_count) + '\', ' + '\'' + device + '\','
				' now(), \'' + build + '\') RETURNING id')
if not query.next():
	raise Exception("Error retrieving schema id")
else:
	schema_id = query.value(0)
dbschema = "pt" + str(schema_id)

output_dir_name = os.getcwd() + "/" + dbschema + "-perf-data"
os.mkdir(output_dir_name)

try:
    do_query(query, 'CREATE SCHEMA ' + dbschema)
except:
    os.rmdir(output_dir_name)
    raise

do_query(query, 'SET search_path TO ' + dbschema)
do_query(query, 'SET client_min_messages TO WARNING')

do_query(query, 'CREATE TABLE threads ('
		'tid		integer		NOT NULL,'
		'pid		integer)')
do_query(query, 'CREATE TABLE dsos ('
		'id	smallint		NOT NULL,'
		'name	varchar(256))')
do_query(query, 'CREATE TABLE instructions ('
		'id		integer		NOT NULL,'
		'symbol_id	integer,'
		'ip		bigint,'
		'exec_count	integer,'
		'sym_offset	bigint,'
		'opcode		bytea)')
do_query(query, 'CREATE TABLE symbols ('
		'id		integer		NOT NULL,'
		'dso_id		smallint,'
		'name		varchar(256),'
		'sym_start	bigint,'
		'sym_end	bigint)')
do_query(query, 'CREATE TABLE samples ('
		'id			integer		NOT NULL,'
		'cpu_id			smallint,'
		'time			bigint,'
		'instruction_id	integer,'
		'thread_id		integer)')
if perf_db_export_calls or perf_db_export_callchains:
	do_query(query, 'CREATE TABLE call_paths ('
		'id             integer         NOT NULL,'
		'parent_id      integer,'
		'symbol_id      integer,'
		'ip             bigint)')
if perf_db_export_calls:
	do_query(query, 'CREATE TABLE calls ('
		'id             integer         NOT NULL,'
		'call_path_id   integer,'
		'call_time      bigint,'
		'return_time    bigint,'
		'branch_count   integer,'
		'call_id        integer,'
		'return_id      integer,'
		'parent_call_path_id    integer,'
		'flags          integer)')
do_query(query, 'CREATE TABLE dso_jumps ('
		'id			integer		NOT NULL,'
		'from_time		bigint,'
		'from_instruction_id	integer,'
		'to_time		bigint,'
		'to_instruction_id	integer)')

do_query(query, 'CREATE VIEW samples_view AS '
	'SELECT '
		'samples.id,'
		'time,'
		'cpu_id,'
		'(SELECT pid FROM threads WHERE tid = thread_id) AS pid,'
		'(SELECT tid FROM threads WHERE tid = thread_id) AS tid,'
		'(SELECT to_hex(ip) FROM instructions WHERE instructions.id = instruction_id) AS ip_hex,'
		'(SELECT name FROM symbols WHERE symbols.id = '
			'(SELECT symbol_id from instructions WHERE instructions.id = instruction_id)) AS symbol,'
		'(SELECT name FROM dsos WHERE dsos.id = '
			'(SELECT dso_id FROM symbols WHERE symbols.id = '
				'(SELECT symbol_id FROM instructions WHERE instructions.id = instruction_id))) AS dso_name,'
		'instructions.opcode,'
		'instructions.exec_count'
	' FROM samples'
	' LEFT JOIN instructions '
		'ON instructions.id = samples.instruction_id')
do_query(query, 'CREATE VIEW instructions_view AS '
	'SELECT '
		'instructions.id,'
		'(SELECT name FROM symbols WHERE symbols.id = symbol_id) AS symbol_name,'
		'(SELECT name FROM dsos WHERE dsos.id = '
		'(SELECT dso_id FROM symbols WHERE symbols.id = symbol_id)) AS dso_name,'
		'instructions.ip,'
		'instructions.exec_count,'
		'instructions.sym_offset,'
		'instructions.opcode'
		' FROM instructions')
if perf_db_export_calls or perf_db_export_callchains:
	do_query(query, 'CREATE VIEW call_paths_view AS '
		'SELECT '
			'c.id,'
			'to_hex(c.ip) AS ip,'
			'c.symbol_id,'
			'(SELECT name FROM symbols WHERE id = c.symbol_id) AS symbol,'
			'(SELECT dso_id FROM symbols WHERE id = c.symbol_id) AS dso_id,'
			'(SELECT name FROM dsos WHERE dsos.id = '
				'(SELECT dso_id FROM symbols WHERE symbols.id = c.symbol_id)) AS dso_name,'
			'c.parent_id,'
			'to_hex(p.ip) AS parent_ip,'
			'p.symbol_id AS parent_symbol_id,'
			'(SELECT name FROM symbols WHERE id = p.symbol_id) AS parent_symbol,'
			'(SELECT dso_id FROM symbols WHERE id = p.symbol_id) AS parent_dso_id,'
			'(SELECT name FROM dsos WHERE dsos.id = '
				'(SELECT dso_id FROM symbols WHERE symbols.id = p.symbol_id)) AS parent_dso_name'
			' FROM call_paths c INNER JOIN call_paths p ON p.id = c.parent_id')
if perf_db_export_calls:
	do_query(query, 'CREATE VIEW calls_view AS '
		'SELECT '
			'calls.id,'
			'call_path_id,'
			'to_hex(ip) AS ip,'
			'symbol_id,'
			'(SELECT name FROM symbols WHERE id = symbol_id) AS symbol,'
			'call_time,'
			'return_time,'
			'return_time - call_time AS elapsed_time,'
			'branch_count,'
			'call_id,'
			'return_id,'
			'CASE WHEN flags=1 THEN \'no call\' WHEN flags=2 THEN \'no return\' WHEN flags=3 THEN \'no call/return\' ELSE \'\' END AS flags,'
			'parent_call_path_id'
		' FROM calls INNER JOIN call_paths ON call_paths.id = call_path_id')
do_query(query, 'CREATE VIEW dso_jumps_view AS '
	'SELECT '
		'dso_jumps.id,'
		'dso_jumps.from_time,'
		'(SELECT name FROM symbols WHERE symbols.id = '
			'(SELECT symbol_id from instructions WHERE instructions.id = from_instruction_id)) AS from_symbol,'
		'(SELECT name FROM dsos WHERE dsos.id = '
			'(SELECT dso_id FROM symbols WHERE symbols.id = '
				'(SELECT symbol_id FROM instructions WHERE instructions.id = from_instruction_id))) AS from_dso_name,'
		'(SELECT dso_id FROM symbols WHERE symbols.id = '
			'(SELECT symbol_id FROM instructions WHERE instructions.id = from_instruction_id)) AS from_dso_id,'
		'dso_jumps.to_time,'
		'(SELECT name FROM symbols WHERE symbols.id = '
			'(SELECT symbol_id from instructions WHERE instructions.id = to_instruction_id)) AS to_symbol,'
		'(SELECT name FROM dsos WHERE dsos.id = '
			'(SELECT dso_id FROM symbols WHERE symbols.id = '
				'(SELECT symbol_id FROM instructions WHERE instructions.id = to_instruction_id))) as to_dso_name,'
		'(SELECT dso_id FROM symbols WHERE symbols.id = '
			'(SELECT symbol_id FROM instructions WHERE instructions.id = to_instruction_id)) AS to_dso_id'
		' FROM dso_jumps')


file_header = struct.pack("!11sii", "PGCOPY\n\377\r\n\0", 0, 0)
file_trailer = "\377\377"

def open_output_file(file_name):
	path_name = output_dir_name + "/" + file_name
	file = open(path_name, "w+")
	file.write(file_header)
	return file

def close_output_file(file):
	file.write(file_trailer)
	file.close()

def copy_output_file_direct(file, table_name):
	close_output_file(file)
	sql = "COPY " + table_name + " FROM '" + file.name + "' (FORMAT 'binary')"
	do_query(query, sql)

# Use COPY FROM STDIN because security may prevent postgres from accessing the files directly
def copy_output_file(file, table_name):
	conn = PQconnectdb("dbname = " + dbname + " user = " + dbuser + " password = " + dbpass)
	if (PQstatus(conn)):
		raise Exception("COPY FROM STDIN PQconnectdb failed")
	sql = "SET search_path TO " + dbschema
	res = PQexec(conn, sql)
	if (PQresultStatus(res) != 1):
		raise Exception("COPY FROM STDIN PQexec failed - setting schema search path")
	file.write(file_trailer)
	file.seek(0)
	sql = "COPY " + table_name + " FROM STDIN (FORMAT 'binary')"
	res = PQexec(conn, sql)
	if (PQresultStatus(res) != 4):
		raise Exception("COPY FROM STDIN PQexec failed")
	data = file.read(65536)
	while (len(data)):
		ret = PQputCopyData(conn, data, len(data))
		if (ret != 1):
			raise Exception("COPY FROM STDIN PQputCopyData failed, error " + str(ret))
		data = file.read(65536)
	ret = PQputCopyEnd(conn, None)
	if (ret != 1):
		raise Exception("COPY FROM STDIN PQputCopyEnd failed, error " + str(ret))
	PQfinish(conn)

def remove_output_file(file):
	name = file.name
	file.close()
	os.unlink(name)

thread_file		= open_output_file("thread_table.bin")
dso_file		= open_output_file("dso_table.bin")
instr_file		= open_output_file("instr_table.bin")
symbol_file		= open_output_file("symbol_table.bin")
sample_file		= open_output_file("sample_table.bin")
dso_jump_file		= open_output_file("dso_jump_table.bin")
if perf_db_export_calls or perf_db_export_callchains:
	call_path_file          = open_output_file("call_path_table.bin")
if perf_db_export_calls:
	 call_file               = open_output_file("call_table.bin")
# dictionary containing instruction stats, where ip is key
ip_dict = {}
dso_ids = []
pcre_dso_ids = []
dso_jump_dict = {}
prev_sample = {}

def trace_begin():
	print datetime.datetime.today(), "Writing to intermediate files..."
	thread_table(0, 0, 0, -1, -1)
	dso_table(0, 0, "unknown", "unknown", "")
	symbol_table(0, 0, 0, 0, 0, "unknown")
	if perf_db_export_calls or perf_db_export_callchains:
		call_path_table(0, 0, 0, 0)
unhandled_count = 0

def trace_end():
	print datetime.datetime.today(), "Writing instructions summary to file..."
	instruction_table()
	dso_jump_table()

	print datetime.datetime.today(), "Copying to database..."
	copy_output_file(thread_file,		"threads")
	copy_output_file(dso_file,		"dsos")
	copy_output_file(instr_file,		"instructions")
	copy_output_file(symbol_file,		"symbols")
	copy_output_file(sample_file,		"samples")
	copy_output_file(thread_file,		"threads")
	copy_output_file(dso_jump_file,		"dso_jumps")
	if perf_db_export_calls or perf_db_export_callchains:
		copy_output_file(call_path_file,        "call_paths")
	if perf_db_export_calls:
		copy_output_file(call_file,             "calls")
 
	print datetime.datetime.today(), "Removing intermediate files..."
	remove_output_file(thread_file)
	remove_output_file(dso_file)
	remove_output_file(instr_file)
	remove_output_file(symbol_file)
	remove_output_file(sample_file)
	remove_output_file(dso_jump_file)
	if perf_db_export_calls or perf_db_export_callchains:
		remove_output_file(call_path_file)
	if perf_db_export_calls:
		remove_output_file(call_file)
 	os.rmdir(output_dir_name)
	print datetime.datetime.today(), "Adding primary keys"
	do_query(query, 'ALTER TABLE threads         ADD PRIMARY KEY (tid)')
	do_query(query, 'ALTER TABLE dsos            ADD PRIMARY KEY (id)')
	do_query(query, 'ALTER TABLE instructions    ADD PRIMARY KEY (id)')
	do_query(query, 'ALTER TABLE symbols         ADD PRIMARY KEY (id)')
	do_query(query, 'ALTER TABLE samples         ADD PRIMARY KEY (id)')
	do_query(query, 'ALTER TABLE dso_jumps       ADD PRIMARY KEY (id)')
	if perf_db_export_calls or perf_db_export_callchains:
		do_query(query, 'ALTER TABLE call_paths      ADD PRIMARY KEY (id)')
	if perf_db_export_calls:
		do_query(query, 'ALTER TABLE calls           ADD PRIMARY KEY (id)')

	print datetime.datetime.today(), "Adding foreign keys"
	do_query(query, 'ALTER TABLE symbols '
					'ADD CONSTRAINT dsofk		FOREIGN KEY (dso_id)			REFERENCES dsos			(id)')
	do_query(query, 'ALTER TABLE instructions '
					'ADD CONSTRAINT symfk		FOREIGN KEY (symbol_id)			REFERENCES symbols		(id)')
	do_query(query, 'ALTER TABLE samples '
					'ADD CONSTRAINT threadfk	FOREIGN KEY (thread_id)			REFERENCES threads		(tid),'
					'ADD CONSTRAINT instrfk		FOREIGN KEY (instruction_id)	REFERENCES instructions	(id)')
	do_query(query, 'ALTER TABLE dso_jumps '
					'ADD CONSTRAINT instrjumpfromfk	FOREIGN KEY (from_instruction_id)	REFERENCES instructions	(id),'
					'ADD CONSTRAINT instrjumptofk	FOREIGN KEY (to_instruction_id)		REFERENCES instructions	(id)')
	if perf_db_export_calls or perf_db_export_callchains:
		do_query(query, 'ALTER TABLE call_paths '
					'ADD CONSTRAINT parentfk    FOREIGN KEY (parent_id)    REFERENCES call_paths (id),'
					'ADD CONSTRAINT symbolfk    FOREIGN KEY (symbol_id)    REFERENCES symbols    (id)')
	if perf_db_export_calls:
		do_query(query, 'ALTER TABLE calls '
					'ADD CONSTRAINT call_pathfk FOREIGN KEY (call_path_id) REFERENCES call_paths (id),'
					'ADD CONSTRAINT callfk      FOREIGN KEY (call_id)      REFERENCES samples    (id),'
					'ADD CONSTRAINT returnfk    FOREIGN KEY (return_id)    REFERENCES samples    (id),'
					'ADD CONSTRAINT parent_call_pathfk FOREIGN KEY (parent_call_path_id) REFERENCES call_paths (id)')
		do_query(query, 'CREATE INDEX pcpid_idx ON calls (parent_call_path_id)')
  	if (unhandled_count):
		print datetime.datetime.today(), "Warning: ", unhandled_count, " unhandled events"
	print datetime.datetime.today(), "Done"

def trace_unhandled(event_name, context, event_fields_dict):
	global unhandled_count
	unhandled_count += 1

def sched__sched_switch(*x):
	pass

def evsel_table(evsel_id, evsel_name, *x):
	pass

def machine_table(machine_id, pid, root_dir, *x):
	pass

def thread_table(thread_id, machine_id, process_id, pid, tid, *x):
	value = struct.pack("!hiiii", 2, 4, tid, 4, pid)
	thread_file.write(value)

def comm_table(comm_id, comm_str, *x):
	pass

def comm_thread_table(comm_thread_id, comm_id, thread_id, *x):
	pass

def dso_table(dso_id, machine_id, short_name, long_name, build_id, *x):
	if perf_collapse_jit_dsos:
		jit_re = re.compile('jitted-[0-9]+-[0-9]+\.so')
		if jit_re.match(short_name):
			dso_ids.append(dso_id)
			if len(dso_ids) == 1:
				short_name = "hhvm-jitted.so"
			elif len(dso_ids) == 2:
				short_name = "hhvm-pcre.so"
			else:
				return
			dso_id = dso_ids[-1]
	n = len(short_name)
	if n > 255:
		n = 255
		short_name = short_name[:255]
		print datetime.datetime.today(), "Warning: DSO name longer than max allowed by DB. Truncating"
	fmt = "!hihi" + str(n) + "s"
	value = struct.pack(fmt, 2, 2, dso_id, n, short_name)
	dso_file.write(value)

def symbol_table(symbol_id, dso_id, sym_start, sym_end, binding, symbol_name, *x):
	n = len(symbol_name)
	if n > 255:
		n = 255
		symbol_name = symbol_name[:255]
		print datetime.datetime.today(), "Warning: Symbol name longer than max allowed by DB. Truncating"
	if perf_collapse_jit_dsos:
		if dso_id in dso_ids:
			if symbol_name.startswith('HHVM::pcre_jit'):
				pcre_dso_ids.append(dso_id)
				dso_id = dso_ids[1]
			else:
				dso_id = dso_ids[0]
	fmt = "!hiiihi" + str(n) + "s" + "iqiq"
	value = struct.pack(fmt, 5, 4, symbol_id, 2, dso_id, n, symbol_name, 8, sym_start, 8, sym_end)
	symbol_file.write(value)

def branch_type_table(branch_type, name, *x):
	pass

def sample_table(sample_id, evsel_id, machine_id, tid, comm_id, dso_id, symbol_id, sym_offset, ip, time, cpu, to_dso_id, to_symbol_id, to_sym_offset, to_ip, period, weight, transaction, data_src, branch_type, in_tx, call_path_id, insn, *x):
	instr_id = get_instruction_id(ip)
	instr_dict_insert(instr_id, symbol_id, ip, insn, sym_offset)
	dso_jump_dict_insert(instr_id, dso_id, time)
	fmt = "!hiiihiqiiii"
	value = struct.pack(fmt, 5, 4, sample_id, 2, cpu, 8, time, 4, instr_id, 4, tid)
	sample_file.write(value)

def call_path_table(cp_id, parent_id, symbol_id, ip, *x):
	fmt = "!hiiiiiiiq"
	value = struct.pack(fmt, 4, 4, cp_id, 4, parent_id, 4, symbol_id, 8, ip)
	call_path_file.write(value)

def call_return_table(cr_id, thread_id, comm_id, call_path_id, call_time, return_time, branch_count, call_id, return_id, parent_call_path_id, flags, *x):
	fmt = "!hiiiiiqiqiiiiiiiiii"
	if return_id != 0:
		value = struct.pack(fmt, 9, 4, cr_id, 4, call_path_id, 8, call_time, 8, return_time, 4, branch_count, 4, call_id, 4, return_id, 4, parent_call_path_id, 4, flags)
		call_file.write(value)

def instruction_table():
	for ip in ip_dict:
		value = bytearray()
		opcode_len = len(ip_dict[ip]["opcode"])
		instr_id = ip_dict[ip]["id"]
		symbol_id = ip_dict[ip]["symbol_id"]
		exec_count = ip_dict[ip]["exec_count"]
		sym_offset = ip_dict[ip]["sym_offset"]
		value.extend(struct.pack("!hiiiiiqiiiqi", 6, 4, instr_id, 4, symbol_id, 8, ip, 4, exec_count, 8, sym_offset, opcode_len))
		value.extend(ip_dict[ip]["opcode"])
		instr_file.write(value)

def dso_jump_table():
	for id in dso_jump_dict:
		value = bytearray()
		from_instr_id = dso_jump_dict[id]["from_instr_id"]
		from_time = dso_jump_dict[id]["from_time"]
		to_instr_id = dso_jump_dict[id]["to_instr_id"]
		to_time = dso_jump_dict[id]["to_time"]
		value.extend(struct.pack("!hiiiqiiiqii", 5, 4, id, 8, from_time, 4, from_instr_id, 8, to_time, 4, to_instr_id))
		dso_jump_file.write(value)

def get_instruction_id(ip):
	if ip in ip_dict:
		return ip_dict[ip]["id"]
	else:
		ip_dict[ip] = {}
		# lock in id
		instr_id = len(ip_dict)
		ip_dict[ip]["id"] = instr_id
		ip_dict[ip]["exec_count"] = -1
		return instr_id

def instr_dict_insert(instr_id, symbol_id, ip, opcode, sym_offset):
	if ip_dict[ip]["exec_count"] > -1:
		ip_dict[ip]["exec_count"] += 1
	else:
		ip_dict[ip]["exec_count"] = 1
		ip_dict[ip]["symbol_id"] = symbol_id
		ip_dict[ip]["opcode"] = opcode
		ip_dict[ip]["sym_offset"] = sym_offset

def dso_jump_dict_add_entry(from_time, from_instr_id, to_time, to_instr_id):
	id = len(dso_jump_dict) + 1
	dso_jump_dict[id] = {}
	dso_jump_dict[id]["from_time"] = from_time
	dso_jump_dict[id]["from_instr_id"] = from_instr_id
	dso_jump_dict[id]["to_time"] = to_time
	dso_jump_dict[id]["to_instr_id"] = to_instr_id

def dso_jump_dict_insert(instr_id, dso_id, time):
	actual_dso_id = dso_id
	if perf_collapse_jit_dsos:
		if dso_id in pcre_dso_ids:
			actual_dso_id = dso_ids[1]
		elif dso_id in dso_ids:
			actual_dso_id = dso_ids[0]
	if len(prev_sample) > 0 and actual_dso_id != prev_sample["dso_id"]:
		dso_jump_dict_add_entry(prev_sample["time"], prev_sample["instr_id"], time, instr_id)
	# update prev_sample
	prev_sample["time"] = time
	prev_sample["instr_id"] = instr_id
	prev_sample["dso_id"] = actual_dso_id
