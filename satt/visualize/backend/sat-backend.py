'''
// Copyright (c) 2015 Intel Corporation
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
'''
import os
import sys
import psycopg2
import psycopg2.extras
import datetime
import math
import simplejson as json
import subprocess
import re
from operator import itemgetter
from flask import Flask, request, jsonify, send_file, abort
from werkzeug import secure_filename
import glob
from flask import g
if not sys.platform.startswith('win'):
    from redis import Redis
    from rq import Queue

SAT_HOME = os.environ.get('SAT_HOME')
# Set SAT_HOME for rest of the backend
if SAT_HOME is None:
    satHome = os.path.realpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
    os.environ['SAT_HOME'] = satHome

import status as stat
import worker

if SAT_HOME:
    app = Flask(__name__, static_url_path='',
                static_folder=os.path.join(SAT_HOME, 'satt', 'visualize', 'webui'))
else:
    SAT_HOME = '.'
    app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(SAT_HOME, 'satt', 'visualize', 'backend', 'tmp')
ALLOWED_EXTENSIONS = set(['tgz'])

status = stat.getStatus()

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.debug = True
DEBUG = False

INS_MORE_LIMIT = 1000

def get_db():
    if getattr(g, '_database', None) is None:
        g._database = psycopg2.connect(
            dbname=status.getDbConfig('dbname'),
            user=status.getDbConfig('user'),
            password=status.getDbConfig('password'))
        g._database.autocommit = True
    return g._database


@app.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

dthandler = lambda obj: (
    obj.isoformat()
    if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date)
    else None)

# Work Queues
if not sys.platform.startswith('win'):
    queue = Queue(connection=Redis())


def begin_db_request():
    db = get_db()
    return (db.cursor(),
            db.cursor(cursor_factory=psycopg2.extras.NamedTupleCursor))


@app.route('/api/1/upload', methods=['GET'])
def upload_resume():
    flowCurrentChunkSize = request.args.get('flowCurrentChunkSize', False)
    flowFilename = request.args.get('flowFilename', False)
    if (flowCurrentChunkSize and flowFilename):
        filename = secure_filename(flowFilename)
        chunk = int(request.args.get('flowChunkNumber'))
        chunkname = os.path.join(UPLOAD_FOLDER, filename + '_' + str(chunk))
        if (os.path.isfile(chunkname)):
            if (os.path.getsize(chunkname) == int(flowCurrentChunkSize)):
                return json.dumps({"OK": 1})
            else:
                # if file size does not match, remove the file and request again
                os.path.remove(chunkname)
    abort(404)


@app.route('/api/1/upload', methods=['POST'])
def upload():
    if request.method == 'POST':
        for key, file in request.files.iteritems():
            if file:
                filename = secure_filename(request.form['flowFilename'])
                chunks = int(request.form['flowTotalChunks'])
                chunk = int(request.form['flowChunkNumber'])
                if DEBUG:
                    print "chunks {0} of chunk {1}".format(chunks, chunk)
                    print '***> ' + str(filename) + ' <***'
                    print str(request.form['flowFilename'])

                file.save(os.path.join(UPLOAD_FOLDER, filename + '_' + str(chunk).zfill(3)))

                # Just simple check, not really checking if those were uploaded succesfully
                if chunk == chunks:
                    read_files = sorted(glob.glob(os.path.join(UPLOAD_FOLDER, filename + '_*')))

                    with open(os.path.join(UPLOAD_FOLDER, filename), "wb") as outfile:
                        for f in read_files:
                            with open(f, "rb") as infile:
                                outfile.write(infile.read())

                    for tmp_files in glob.glob(os.path.join(UPLOAD_FOLDER, filename + '_*')):
                        os.remove(tmp_files)

                    print 'Quenue done'
                    # Setup up the work Queue
                    trace_id = status.create_id(os.path.join(UPLOAD_FOLDER, filename), filename)
                    if not sys.platform.startswith('win'):
                        result = queue.enqueue(worker.process_trace, trace_id, timeout=7200)
                        if not result:
                            print "Queuenue failed"

                    return json.dumps({"OK": 1, "info": "All chunks uploaded successful."})

    return json.dumps({"OK": 1, "info": "Chunk " + str(chunk) + " uploaded succesfully"})


@app.route('/', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def main():
    return app.send_static_file('index.html')


@app.route('/admin', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def admin():
    return app.send_static_file('index.html')


@app.route('/trace/<int:id>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def trace_id(id):
    return app.send_static_file('index.html')


@app.route('/transitiongraph/<int:id>',
           methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def transitiongraph(id):
    return app.send_static_file('index.html')


@app.route('/admin/views/admin/<string:endpoint>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def admin_view(endpoint):
    print '/views/admin/' + endpoint
    return app.send_static_file('views/admin/' + endpoint)


def create_bookmark():
    cur, named_cur = begin_db_request()
    cur.execute("""create table if not exists public.bookmark
    (id serial, traceId int, title varchar(1024), description text, data text, PRIMARY KEY(id))""")


@app.route('/api/1/bookmark', methods=['GET'])
def getBookmarks():
    cur, named_cur = begin_db_request()
    try:
        named_cur.execute("select * from public.bookmark")
    except:
        create_bookmark()
        named_cur.execute("select * from public.bookmark")
    data = named_cur.fetchall()

    return json.dumps(data)


@app.route('/api/1/bookmark/<int:bookmarkId>', methods=['GET'])
def getBookmarksById(bookmarkId):
    cur, named_cur = begin_db_request()
    named_cur.execute("select * from public.bookmark where id = %s", (bookmarkId,))
    data = named_cur.fetchone()
    if data:
        return json.dumps(data)
    else:
        return jsonify(error=404, text='Bookmark was not found!'), 404


@app.route('/api/1/bookmark', methods=['POST', 'PATCH'])
def saveBookmark():
    cur, named_cur = begin_db_request()
    if request.method == 'POST':
        data = request.get_json()
        try:
            named_cur.execute("INSERT INTO public.bookmark (traceId, title, description, data) VALUES (%s,%s,%s,%s) RETURNING id",
                              (data['traceId'], data['title'], data['description'], data['data'], ))
        except:
            create_bookmark()
            named_cur.execute("INSERT INTO public.bookmark (traceId, title, description, data) VALUES (%s,%s,%s,%s) RETURNING id",
                              (data['traceId'], data['title'], data['description'], data['data'],))
        insertedId = named_cur.fetchone()
        if DEBUG:
            print named_cur.query
    return json.dumps(insertedId)


@app.route('/api/1/bookmark/<int:bookmarkId>', methods=['DELETE'])
def deleteBookmark(bookmarkId):
    cur, named_cur = begin_db_request()
    named_cur.execute("delete from public.bookmark where id = %s", (bookmarkId,))
    return json.dumps({"ok": "ok"})


@app.route('/api/1/bookmark', methods=['PUT'])
def updateBookmark():
    cur, named_cur = begin_db_request()
    data = request.get_json()
    cur.execute("UPDATE public.bookmark SET title=%s, description=%s WHERE id=%s", (data['title'], data['description'], data['id'],))
    return json.dumps({"ok": "ok"})


@app.route('/api/1/traceinfo/<int:traceId>')
def traceinfo(traceId):
    cur, named_cur = begin_db_request()
    data = {}
    data['infos'] = []

    named_cur.execute("select * from public.traces where id=%s", (traceId, ))
    rows = named_cur.fetchall()
    data['trace'] = rows[0]

    return json.dumps(data, default=dthandler)


# Helper funtion to merge insflow arrays
# - Will check last existing line and it's timestamps
#   and merge only after that timestamps. So that three formation is kept
def merge_insflow_overflow_sections(old_rows,new_rows):
    ret_rows = []
    if len(old_rows) > 0:
        old_start_ts = old_rows[-1][1]
        old_start_duration = old_rows[-1][3] + old_rows[-1][4]
        old_end = old_start_ts + old_start_duration
        for r in new_rows:
            # Filter our functions that should be inside old last function
            if old_end <= r[1]:
               ret_rows = ret_rows + [r]
        return old_rows + ret_rows
    else:
        return old_rows + new_rows

@app.route('/api/1/insflownode/<int:traceId>/<string:pid>/<int:start>/<int:end>/<int:level>', methods=['GET', 'POST'])
def graph_insflownode(traceId, pid, start, end, level):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    # Searching next level from 'start' ts onwards. We can include 'start' ts
    #  into search because we anyway search one step deeper in stack, so we
    #  don't include the parent level item and cause duplicate line.

    if end == 0:

        cur.execute("""SELECT count(*)
            FROM """+schema+""".ins
            WHERE thread_id = %s and level = %s and ts > %s
            """,(pid,level,start,))
        max_row_count = cur.fetchone()
        cur.execute("""SELECT ins.id, ins.ts, ins.level, ins.ts_oot, ins.ts_int, ins.ins_count, ins.call, ins.cpu, ins.thread_id, module, sym.symbol
            FROM """+schema+""".ins
            JOIN """+schema+""".module as mod ON (mod.id = module_id)
            JOIN """+schema+""".symbol as sym ON (sym.id = symbol_id)
            WHERE thread_id = %s and level = %s and ts >= %s
            ORDER BY ts
            LIMIT %s""",(pid,level,start,INS_MORE_LIMIT,))
        rows = cur.fetchall()

        if DEBUG:
            print cur.query
    else:
        cur.execute("""SELECT count(*)
            FROM """+schema+""".ins
            WHERE thread_id = %s and level = %s and ts > %s and ts <= %s
            """,(pid,level,start,end))
        max_row_count = cur.fetchone()
        cur.execute("""SELECT ins.id, ins.ts, ins.level, ins.ts_oot, ins.ts_int, ins.ins_count, ins.call, ins.cpu, ins.thread_id, module, sym.symbol
                    FROM """+schema+""".ins
                    JOIN """+schema+""".module as mod ON (mod.id = module_id)
                    JOIN """+schema+""".symbol as sym ON (sym.id = symbol_id)
                    WHERE thread_id = %s and level = %s and ts >= %s and ts <= %s
                    ORDER BY ts
                    LIMIT %s""",(pid,level,start,end,INS_MORE_LIMIT,))
        rows = cur.fetchall()

        if DEBUG:
            print cur.query

    data = []
    for r in rows:
        call = r[6]
        if r[6] == "r":
            call = 'e'
        data.append({"id":r[0],"ts":r[1],"l":r[2],"of":r[3],"it":r[4],"in":r[5],"cl":call,"cpu":r[7],"tgid":r[8],"mod":r[9],"sym": r[10],} )

    if max_row_count[0] > INS_MORE_LIMIT:
        # Add info to data
        data.append({"id":r[0],"ts":r[1],"l":r[2],"of":0,"it":0,"in":0,"cl":"m","row_count":max_row_count[0],"cpu":0,"tgid":0,"mod":0,"sym":0,} )

    return jsonify({"data":data})


# thread 0/0
@app.route('/api/1/insflow/<int:traceId>/<string:pid>/<int:start>/<int:end>', methods=['GET', 'POST'])
def graph_insflow(traceId, pid, start, end):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)

    cur.execute("""select Min(level) from """+schema+""".ins where thread_id = %s and ts >= %s and ts <= %s """,(pid,start,end,))
    min_level_in_set = cur.fetchone()

    if DEBUG:
        print cur.query

    """ CALCULATE DURATION FOR THE CALLS
    SELECT CASE WHEN call = 'c' THEN lead(ts) over(partition by level order by ts)
    ELSE lead(ts) over(order by ts) END
    - ts -1 as duration,
    """

    overflow_rows = []
    rows = []

    cur.execute("""select id from """+schema+""".symbol where symbol = 'overflow' """,(pid,start,end,))
    overflow_symbol_id = cur.fetchone()
    if overflow_symbol_id:
        print "OVERFLOW ID"
        overflow_symbol_id = overflow_symbol_id[0]

        # get timestamps for the overflows
        named_cur.execute("""SELECT * FROM """+schema+""".ins
            WHERE thread_id = %s AND ts >= %s AND ts <= %s and symbol_id =%s
        ORDER BY ts
        LIMIT %s;""",(pid,start,end,overflow_symbol_id, INS_MORE_LIMIT))

        overflow_rows = []
        if DEBUG:
            print named_cur.query

        overflow_rows = named_cur.fetchall()

    if len(overflow_rows):
        for i, r in enumerate(overflow_rows):
            if i == 0:
                start_time = start
                end_time = r.ts
            elif i == len(overflow_rows)-1:
                start_time = r.ts
                end_time = end
            else:
                start_time = end_time
                end_time = r.ts

            cur.execute("""SELECT ins.id, ins.ts, ins.level, ins.ts_oot, ins.ts_int, ins.ins_count, ins.call, ins.cpu, ins.thread_id, module, sym.symbol
            FROM
            (select *, min(level) over (order by ts) as min_level from
            """+schema+""".ins as s2 where thread_id = %s AND ts >= %s AND ts <= %s
            ) ins
            JOIN """+schema+""".module as mod ON (mod.id = module_id)
            JOIN """+schema+""".symbol as sym ON (sym.id = symbol_id)
            WHERE level <= min_level
            ORDER BY ts
            LIMIT %s;""",(pid,start_time,end_time,INS_MORE_LIMIT))
            #if DEBUG:
                #print cur.query
            rows = merge_insflow_overflow_sections(rows, cur.fetchall())
            if len(rows) >= INS_MORE_LIMIT:
                break
    else:
        cur.execute("""SELECT ins.id, ins.ts, ins.level, ins.ts_oot, ins.ts_int, ins.ins_count, ins.call, ins.cpu, ins.thread_id, module, sym.symbol
        FROM
        (select *, min(level) over (order by ts) as min_level from
        """+schema+""".ins as s2 where thread_id = %s AND ts >= %s AND ts <= %s
        ) ins
        JOIN """+schema+""".module as mod ON (mod.id = module_id)
        JOIN """+schema+""".symbol as sym ON (sym.id = symbol_id)
        WHERE level <= min_level
        ORDER BY ts
        LIMIT %s;""",(pid,start,end,INS_MORE_LIMIT))
        rows = rows + cur.fetchall()

    data = []
    found_min_level = 0xFFFFFF
    for r in rows:
        data.append({"id":r[0],"ts":r[1],"l":r[2],"of":r[3],"it":r[4],"in":r[5],"cl":r[6],"cpu":r[7],"tgid":r[8],"mod":r[9],"sym":r[10],} )
        if found_min_level > r[2]:
            found_min_level = r[2]

    if len(rows) >= INS_MORE_LIMIT:
        # Check if bottom of the call stack was found to change behavior of more button in UI
        if min_level_in_set[0] < found_min_level:
            data.append({"id":r[0],"ts":r[1],"l":r[2],"of":0,"it":0,"in":0,"cl":"m","row_count":"???","cpu":0,"tgid":0,"mod":0,"sym":0,"min_level":min_level_in_set,} )
        else:
            data.append({"id":r[0],"ts":r[1],"l":r[2],"of":0,"it":0,"in":0,"cl":"m","row_count":"???","cpu":0,"tgid":0,"mod":0,"sym":0,} )

    return jsonify({"min_level":found_min_level,"data":data})

################################################################
#
# Statistics grouping by threads
#
################################################################
@app.route('/api/1/statistics/groups/thread/<int:traceId>/<int:start>/<int:end>', methods=['GET', 'POST'])
def statistics_groups_thread(traceId, start, end):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""select round((ins::real * 100 / ( select sum(sum) from """ +schema +""".graph where gen_ts >= %s and gen_ts <= %s ))::numeric , 4)::real as percent, * from (
        select sum(sum) as ins, tgid, pid, name from """ +schema +""".graph
        join """+schema+""".tgid on thread_id = tgid.id
        where gen_ts >= %s and gen_ts <= %s
        group by tgid, name, pid
        order by 1 desc
        ) s1""",(start,end,start,end,))

        if DEBUG:
            print named_cur.query
        rows = named_cur.fetchall()
        rows.insert(0,{"id":"0", "percent":"100","name":"Showing all Threads"})
        return json.dumps({'data':rows}, use_decimal=True)
    except Exception, e:
        print e
        return jsonify({"ERROR":100})

################################################################
#
# Statistics grouping by Process
#
################################################################
@app.route('/api/1/statistics/groups/process/<int:traceId>/<int:start>/<int:end>', methods=['GET', 'POST'])
def statistics_groups_process(traceId, start, end):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""select round((ins::real * 100 / ( select sum(sum) from """ +schema +""".graph where gen_ts >= %s and gen_ts <= %s ))::numeric , 4)::real as percent, * from (
        select sum(sum) as ins, tgid, name from """ +schema +""".graph
        join """+schema+""".tgid on thread_id = tgid.id
        where gen_ts >= %s and gen_ts <= %s
        group by tgid, name
        order by 1 desc
        ) s1""",(start,end,start,end,))

        if DEBUG:
            print named_cur.query

        rows = named_cur.fetchall()
        rows.insert(0,{'id':0, 'percent':100,'name':'Showing all Processes'})
        return json.dumps({'data':rows}, use_decimal=True)
    except Exception, e:
        print e
        return jsonify({"ERROR":100})

################################################################
#
# Statistics grouping by Module
#
################################################################
@app.route('/api/1/statistics/groups/module/<int:traceId>/<int:start>/<int:end>', methods=['GET', 'POST'])
def statistics_groups_module(traceId, start, end):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""
        select round((ins::real * 100 / ( select sum(ins_count) from """ +schema +""".ins as s2 where ts >= %s and ts <= %s))::numeric , 4)::real as percent, * from (
            select sum(ins_count) as ins, module as name, module_id from """ +schema +""".ins
            join """ +schema +""".module on module.id = ins.module_id
            where ts >= %s and ts <= %s
            group by module, module_id
            order by 1 desc
            limit 100 )s1""",(start,end,start,end,))

        if DEBUG:
            print named_cur.query
        rows = named_cur.fetchall()
        rows.insert(0,{"id":"0", "percent":'100',"name":"Showing all Modules"})
        return json.dumps({'data':rows}, use_decimal=True)
    except Exception, e:
        print "problem".format(e)

################################################################
#
# Statistics items from a process
#
################################################################
@app.route('/api/1/statistics/process/<int:traceId>/<int:start>/<int:end>/<int:tgid>', methods=['GET', 'POST'])
def statistics_process(traceId, start, end, tgid):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""
            select symbol,
            sum(ins_count) as ins,
            sum(
            CASE when call = 'c' THEN
            1
            END
            ) as call_count,
            sum(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as in_thread,
            round ( avg(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) )::real as avg_in_thread,
            sum (
            CASE WHEN call = 'e' THEN
            ts_int
            END
            ) as in_abs_thread,
            min(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as min_in_thread,
            max(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as max_in_thread,
            sum(
            CASE WHEN call = 'c' THEN
            ts_oot
            END
            ) as out_thread,
            symbol_id from """ + schema + """.ins
            join """ + schema + """.tgid on thread_id = tgid.id
            join """ + schema + """.symbol on symbol_id = symbol.id
            where tgid = %s and ts >= %s and ts <= %s
            group by symbol_id, symbol
            order by ins desc
            limit 1000""",(tgid,start,end))

        if DEBUG:
            print named_cur.query
        rows = named_cur.fetchall()
        return json.dumps({'data':rows}, use_decimal=True)
    except Exception, e:
        print "problem".format(e)

################################################################
#
# Statistics items from a thread
#
################################################################
@app.route('/api/1/statistics/thread/<int:traceId>/<int:start>/<int:end>/<int:pid>', methods=['GET', 'POST'])
def statistics_thread(traceId, start, end, pid):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""
            select symbol,
            sum(ins_count) as ins,
            sum(
            CASE when call = 'c' THEN
            1
            END
            ) as call_count,
            sum(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as in_thread,
            round ( avg(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) )::real as avg_in_thread,
            sum (
            CASE WHEN call = 'e' THEN
            ts_int
            END
            ) as in_abs_thread,
            min(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as min_in_thread,
            max(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as max_in_thread,
            sum(
            CASE WHEN call = 'c' THEN
            ts_oot
            END
            ) as out_thread,
            symbol_id from """ + schema + """.ins
            join """ + schema + """.tgid on thread_id = tgid.id
            join """ + schema + """.symbol on symbol_id = symbol.id
            where pid = %s and ts >= %s and ts <= %s
            group by symbol_id, symbol
            order by ins desc
            limit 1000""",(pid,start,end))

        if DEBUG:
            print named_cur.query
        rows = named_cur.fetchall()
        return json.dumps({'data':rows}, use_decimal=True)
    except Exception, e:
        print "problem".format(e)

################################################################
#
# Statistics items from a module
#
################################################################
@app.route('/api/1/statistics/module/<int:traceId>/<int:start>/<int:end>/<int:module_id>', methods=['GET', 'POST'])
def statistics_module(traceId, start, end, module_id):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""
            select symbol,
            sum(ins_count) as ins,
            sum(
            CASE when call = 'c' THEN
            1
            END
            ) as call_count,
            sum(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as in_thread,
            round ( avg(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) )::real as avg_in_thread,
            sum (
            CASE WHEN call = 'e' THEN
            ts_int
            END
            ) as in_abs_thread,
            min(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as min_in_thread,
            max(
            CASE WHEN call = 'c' THEN
            ts_int
            END
            ) as max_in_thread,
            sum(
            CASE WHEN call = 'c' THEN
            ts_oot
            END
            ) as out_thread,
            symbol_id from """ + schema + """.ins
            join """ + schema + """.tgid on thread_id = tgid.id
            join """ + schema + """.symbol on symbol_id = symbol.id
            where module_id = %s and ts >= %s and ts <= %s
            group by symbol_id, symbol
            order by ins desc
            limit 1000""",(module_id,start,end))

        if DEBUG:
            print named_cur.query
        rows = named_cur.fetchall()
        return json.dumps({'data':rows}, use_decimal=True)
    except Exception, e:
        print "problem".format(e)

################################################################
#
# Statistics get callers
#
################################################################
#
# CREATE INDEX t66_multi2_idx on t66.ins(symbol_id, call, level, ts)
#
# CREATE INDEX t66_multi_idx on t66.ins(symbol_id, call, level, ts)
#
@app.route('/api/1/statistics/callers/<int:traceId>/<int:start>/<int:end>/<int:tgid>/<int:symbol_id>', methods=['GET', 'POST'])
def statistics_callers(traceId, start, end, tgid, symbol_id):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    try:
        named_cur.execute("""
            select count(*) as call_count, avg(ts_int) as avg_ts_int, symbol_id, symbol from """+schema+""".ins as A
                join """+schema+""".tgid on thread_id = tgid.id
                join """+schema+""".symbol on symbol_id = symbol.id
            where call = 'c' and tgid = %s and symbol_id <> %s
            and exists ( select * from """+schema+""".ins as B where call = 'c' and level = A.level +1 and symbol_id = %s and ts > A.ts and ts < (A.ts + A.ts_int) )
            group by symbol_id, symbol
            order by 1
            limit 50
            """,(tgid,symbol_id,symbol_id,))
        if DEBUG:
            print named_cur.query
        return "hello"
        #return jsonify({"data":rows})
    except Exception, e:
        print "problem".format(e)


################################################################
#
# Delete trace permanetly
#
################################################################
@app.route('/api/1/trace/<int:traceId>', methods=['DELETE'])
def delete_trace(traceId):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    try:
        cur.execute("DROP SCHEMA IF EXISTS "+schema+" CASCADE;")
        cur.execute("DELETE FROM public.traces WHERE id = %s",(traceId,))
        db.commit()
        return jsonify({"status":"ok"})
    except Exception, e:
        print "error ".format(e)
        return jsonify({"status":"error"})

################################################################
#
# Handle Admin Post to modify trace names
#
################################################################
@app.route('/api/1/trace/<int:traceId>', methods=['POST'])
def post_trace(traceId):
    cur, named_cur = begin_db_request()
    js = request.json
    try:
        for key in js:
            cur.execute("UPDATE public.traces SET " + key + "=%s WHERE id = %s", (js[key], traceId,))
            print key, 'corresponds to', js[key]
            db.commit()
        return jsonify({"status":"ok"})
    except Exception, e:
        print "error ".format(e)
        return jsonify({"status":"error"})

################################################################
#
# Handle Admin / Public Get list of trace
#
################################################################
@app.route('/api/1/trace/<int:traceId>', methods=['GET'])
def get_trace(traceId):
    cur, named_cur = begin_db_request()
    named_cur.execute("SELECT * FROM public.traces WHERE id = %s",(traceId,))
    row = named_cur.fetchone()
    return json.dumps(row, default= dthandler)


@app.route('/api/1/traces/', methods=['GET', 'POST'])
def get_traces():
    cur, named_cur = begin_db_request()
    named_cur.execute("SELECT * FROM public.traces order by id")
    results = named_cur.fetchall()
    return json.dumps(results, default= dthandler)


#
#  SEARCH
#
#  Search matching symbol name - limiting to 100 results
#
@app.route('/api/1/search/<int:traceId>', methods=['GET', 'POST'])
def search(traceId):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    if "search" in request.json and len(request.json['search']):
        named_cur.execute("""SELECT symbol.id, symbol from """+schema+""".symbol
                             WHERE symbol LIKE %s
                             ORDER BY symbol
                             LIMIT 100""",('%' + request.json['search'] + '%',))

        r = [dict((named_cur.description[i][0], value) \
               for i, value in enumerate(row)) for row in named_cur.fetchall()]
        if DEBUG:
            print named_cur.query
        return jsonify({"data":r})

    return jsonify({"error":"error"})
#
#  2.nd phase Search hit count for following symbol ids
#
@app.route('/api/1/search/hits/<int:traceId>', methods=['GET', 'POST'])
def search_hits(traceId):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    if "ids" in request.json and len(request.json['ids']):
        ids = ""
        comma = ""

        for id in request.json['ids']:
            ids = ids + comma + str(id)
            comma = ", "
        print ids
        named_cur.execute("""SELECT symbol.id, count(*) as hits from """+schema+""".symbol
                LEFT JOIN """+schema+""".ins on symbol.id = ins.symbol_id
                WHERE symbol.id IN %s
                AND call = 'c'
                GROUP BY 1""",(tuple(request.json['ids']),))
        if DEBUG:
            print named_cur.query
        r = [dict((named_cur.description[i][0], value) \
               for i, value in enumerate(row)) for row in named_cur.fetchall()]
        return jsonify({"data":r})
    return jsonify({"error":"error"})

#
#  3.rd phase Search places for search hits
#
@app.route('/api/1/search/<int:traceId>/<int:pixels>/<int:start_time>/<int:end_time>/<int:symbol_id>', methods=['GET', 'POST'])
def search_full(traceId,pixels,start_time,end_time,symbol_id):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    time_slice = (end_time - start_time -1) / pixels
    if DEBUG:
        print "Search Full"
        print "Start=%d"%start_time
        print "End=%d"%end_time
        print "timeslice=%d"%time_slice
        print "pixels Wanted=%d"%pixels

    named_cur.execute("""SELECT (ts/%s)*%s as ts, count(*) as hits, cpu
            from """+schema+""".ins
            full join
                (select ts from generate_series(%s,%s,%s) ts) s1
                using (ts)
            WHERE symbol_id = %s and ts > %s and ts < %s and call = 'c'
            group by 1,3
            order by ts""",(time_slice,time_slice,start_time,end_time,time_slice,symbol_id,start_time-1,end_time+1,))

    if DEBUG:
        print named_cur.query
    rows = named_cur.fetchall()

    r = [dict((named_cur.description[i][0], value) \
           for i, value in enumerate(row)) for row in rows]
    return jsonify({"data":r})

#
#  Search overflows
#
@app.route('/api/1/search/overflow/<int:traceId>/<int:pixels>/<int:start_time>/<int:end_time>', methods=['GET', 'POST'])
def search_full_overflow(traceId,pixels,start_time,end_time):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    time_slice = (end_time - start_time -1) / pixels
    if DEBUG:
        print "Search Full"
        print "Start=%d"%start_time
        print "End=%d"%end_time
        print "timeslice=%d"%time_slice
        print "pixels Wanted=%d"%pixels

    # TODO symbol like overflow is SLOW!!!!! Change look for ID so that it can be indexed
    named_cur.execute("""SELECT id from """+schema+""".symbol where symbol LIKE 'overflow'""")
    symbol_id = named_cur.fetchone()

    # Same as below, but now with cpu info
    named_cur.execute("""SELECT (ts/%s)*%s as ts, count(*) as hits, cpu
            from """+schema+""".ins
            full join
                (select ts from generate_series(%s,%s,%s) ts) s1
                using (ts)
            WHERE symbol_id = %s and ts > %s and ts < %s
            group by 1,3
            order by ts""",(time_slice,time_slice,start_time,end_time,time_slice,symbol_id,start_time-1,end_time+1,))

    if DEBUG:
        print named_cur.query
    rows = named_cur.fetchall()

    r = [dict((named_cur.description[i][0], value) \
           for i, value in enumerate(row)) for row in rows]
    return jsonify({"data":r})

#
#  Search overflows
#
@app.route('/api/1/search/lost/<int:traceId>/<int:pixels>/<int:start_time>/<int:end_time>', methods=['GET', 'POST'])
def search_full_lost(traceId,pixels,start_time,end_time):
    cur, named_cur = begin_db_request()
    schema = "t" + str(traceId)
    time_slice = (end_time - start_time -1) / pixels
    if DEBUG:
        print "Search Full"
        print "Start=%d"%start_time
        print "End=%d"%end_time
        print "timeslice=%d"%time_slice
        print "pixels Wanted=%d"%pixels

    named_cur.execute("""SELECT id from """+schema+""".symbol where symbol LIKE 'lost'""")
    symbol_id = named_cur.fetchone()

    # Same as below, but now with cpu info
    named_cur.execute("""SELECT (ts/%s)*%s as ts, count(*) as hits, cpu
            from """+schema+""".ins
            full join
                (select ts from generate_series(%s,%s,%s) ts) s1
                using (ts)
            WHERE symbol_id = %s and ts > %s and ts < %s
            group by 1,3
            order by ts""",(time_slice,time_slice,start_time,end_time,time_slice,symbol_id,start_time-1,end_time+1,))

    if DEBUG:
        print named_cur.query
    rows = named_cur.fetchall()

    r = [dict((named_cur.description[i][0], value) \
           for i, value in enumerate(row)) for row in rows]
    return jsonify({"data":r})


#
# Memory Heatmap Full Dataset
#

# Gets the smallest value >= val which is a multiple of 'to'
def alignValueTo(val, to):
    if val == 0:
        return to
    md = val % to
    return int(val if md == 0 else val + (to - md))

# Gets the largest value <= val which is a multiple of 'to'
def closestAlignedValueTo(val, to):
    return val - (val % to)

@app.route('/api/1/heatmap/<int:traceId>/full/<int:bytes_per_sample>',
           methods=['GET'])
def memheatmap_full(traceId, bytes_per_sample):
    class MemoryRange:
        def __init__(self, start_address, end_address, dso_name):
            self.start_address = start_address
            self.end_address = end_address
            self.dso_name = dso_name
            self.data_raw = None
            self.data_normalized = None
            self.wss = 0

        def update_range_info(self):
            self.start_address_aligned = closestAlignedValueTo(
                                                    self.start_address,
                                                    bytes_per_sample)
            self.end_address_aligned = alignValueTo(
                                                    self.end_address,
                                                    bytes_per_sample)
            self.byte_size = self.end_address - self.start_address + 1
            self.byte_size_aligned = self.end_address_aligned - \
                                     self.start_address_aligned + 1
            self.sample_count = self.byte_size_aligned // bytes_per_sample
            self.data_raw = [0] * self.sample_count
            self.data_normalized = [0] * self.sample_count

        def add_sample(self, ip, length, count):
            if ip < self.start_address or ip > self.end_address:
                raise Exception(
                            "Invalid IP %x for DSO: %s" % (ip, self.dso_name))
            start_address = ip - self.start_address_aligned
            end_address = (start_address + length) - 1
            start_sample = start_address // bytes_per_sample
            end_sample = end_address // bytes_per_sample
            for pidx in range(start_sample, end_sample + 1):
                self.data_raw[pidx] += count
            self.wss += length

        def process_data(self, log_scale=True):
            self.max_raw = max(self.data_raw)
            if log_scale:
                for idx in range(len(self.data_raw)):
                    if self.data_raw[idx] > 0:
                        self.data_normalized[idx] = math.log(
                                                        self.data_raw[idx], 2)
                self.max_normalized = max(self.data_normalized)
            else:
                self.data_normalized = self.data_raw[:]
                self.max_normalized = self.max_raw

        def normalize_data(self, scale_max=2047.0, global_max=None):
            m = self.max_scaled if global_max is None else global_max
            for idx in range(0, len(self.data_normalized)):
                if self.data_normalized[idx] > 0:
                    self.data_normalized[idx] = int(
                        math.floor(scale_max * self.data_normalized[idx] / m))

        def to_dict(self, index):
            data = {}
            for idx in range(len(self.data_raw)):
                if self.data_raw[idx] != 0:
                    data[idx] = [self.data_normalized[idx],
                                 self.data_raw[idx]]
            return {
                "index": index,
                "startAddress": self.start_address,
                "endAddress": self.end_address,
                "totalSize": self.byte_size,
                "startAddressAligned": self.start_address_aligned,
                "endAddressAligned": self.end_address_aligned,
                "dsoName": self.dso_name,
                "wss": self.wss,
                "data": data
            }

    log_scale = True
    use_global_max_for_norm = True
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    t_instr = schema + ".instructions"
    t_sym = schema + ".symbols"
    t_dso = schema + ".dsos"

    cur.execute("select ip, octet_length(opcode), exec_count, dso_name from " +
                schema + ".instructions_view order by ip")

    rows = cur.fetchall()
    rows.sort(key=itemgetter(0))
    address_ranges = {}

    for row in rows:
        start_address = row[0]
        end_address = start_address + row[1] - 1
        current_dso = row[3]
        if current_dso not in address_ranges:
            address_ranges[current_dso] = \
                        MemoryRange(start_address, end_address, current_dso)
        else:
            address_ranges[current_dso].end_address = end_address

    ranges_count = len(address_ranges)

    # Update range internals (get aligned addresses, calculate height etc.)
    for ar in address_ranges.values():
        ar.update_range_info()

    # Sort ranges by start_address_aligned
    address_ranges_list = sorted(address_ranges.values(),
                                 key=lambda x: x.start_address_aligned)

    # Add samples to ranges
    for row in rows:
        address_ranges[row[3]].add_sample(row[0], row[1], row[2])

    # Process data (create logarithmic scale, calculate max)
    for ar in address_ranges_list:
        ar.process_data(log_scale)

    # If global max is required, calculate it as the max of all ranges' maxes
    global_max = None
    if use_global_max_for_norm:
        global_max = max(
                    [ar.max_normalized for ar in address_ranges_list])

    # Normalize data in ranges to [0, 2047] based on either local or global max
    for ar in address_ranges_list:
        ar.normalize_data(2047.0, global_max)

    # Create result data
    return jsonify({
        "bytesPerSample": bytes_per_sample,
        "ranges":
            [ar.to_dict(idx) for idx, ar in enumerate(address_ranges_list)]
        })


#
# Get working set size, per DSO and total
#
@app.route('/api/1/wss/<int:traceId>/',
           methods=['GET'])
def wss_per_dso(traceId):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select dso_name, sum(octet_length(opcode)) from " +
                schema + ".instructions_view group by dso_name;")
    rows = cur.fetchall()
    rows.sort(key=itemgetter(1))
    total_wss = 0
    wss_dict = {}
    for row in rows:
        wss_dict[row[0]] = row[1]
        total_wss += row[1]
    wss_dict["TOTAL"] = total_wss
    return json.dumps(wss_dict)


#
# Get working set size for a DSO and its symbols
#
@app.route('/api/1/dsosymwss/<int:traceId>/<dsoName>',
           methods=['GET'])
def wss_per_sym(traceId, dsoName):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select symbol_name, sum(octet_length(opcode)) from " +
                schema + ".instructions_view where dso_name = \'" +
                dsoName + "\' group by symbol_name;")
    rows = cur.fetchall()
    rows.sort(key=itemgetter(1))
    total_dso_wss = 0
    wss_sym_dict = {}
    for row in rows:
        wss_sym_dict[row[0]] = row[1]
        total_dso_wss += row[1]
    wss_sym_dict["total"] = total_dso_wss
    return json.dumps(wss_sym_dict)


#
# Get symbols names found between two addresses
#
@app.route('/api/1/symbolsataddr/<int:traceId>/<int:start_addr>/<int:end_addr>',
           methods=['GET'])
def symbols_at_addr(traceId, start_addr, end_addr):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select distinct symbol_name from " + schema +
                ".instructions_view where ip >= " + str(start_addr) +
                " and ip <= " + str(end_addr))
    return jsonify([elem[0] for elem in cur.fetchall()])

#
# Get symbols names + assembly found between two addresses
#
instr_extr = re.compile('SHORT: (.*)')

@app.route('/api/1/symbolsataddrfull/<int:traceId>/<int:start_addr>/'
           '<int:end_addr>', methods=['GET'])
def symbols_at_addr_full(traceId, start_addr, end_addr):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select symbol_name, opcode, exec_count, ip, sym_offset, "
                "octet_length(opcode) from " +
                schema + ".instructions_view where ip >= " + str(start_addr) +
                " and ip <= " + str(end_addr) +
                " order by symbol_name, ip;")
    result_data = {}
    total_exec_count = 0
    for elem in cur.fetchall():
        if elem[0] not in result_data:
            result_data[elem[0]] = {
                "symbol": elem[0],
                "instructions": []
            }
        instr_string = ["%0.2X" % (ord(b)) for b in elem[1]]
        result = subprocess.check_output(["xed", "-64", "-d"] + instr_string,
                 stderr=subprocess.STDOUT)
        decoded_instr = "unknown"
        if result:
            for line in result.splitlines():
                res = instr_extr.match(line)
                if res:
                    decoded_instr = res.group(1)
                    break
        result_data[elem[0]]["instructions"].append({
                                                "instr": decoded_instr,
                                                "count": elem[2],
                                                "ip": elem[3],
                                                "offset": elem[4],
                                                "length": elem[5]})
        total_exec_count += elem[2]
    return jsonify({"totalHits": total_exec_count,
                    "symbols": result_data.values()})


@app.route('/api/1/alldsos/<int:traceId>', methods=['GET'])
def get_all_dsos(traceId):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select id, name from " + schema + ".dsos order by name")
    return jsonify([{"id": item[0],
                     "name": item[1]} for item in cur.fetchall()])


@app.route('/api/1/dsotransitions/<int:traceId>/<int:one>/<int:two>',
           methods=['GET'])
def get_dsos_jumps(traceId, one, two):
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select from_time, from_symbol, from_dso_name, from_dso_id,"
                " to_time, to_symbol, to_dso_name, to_dso_id from " + schema +
                ".dso_jumps_view where (from_dso_id = " + str(one) +
                " and to_dso_id = " + str(two) + ") or (from_dso_id = " +
                str(two) + " and to_dso_id = " + str(one) +
                ") order by from_time")
    one_symbols = []
    two_symbols = []
    one_dict = {}
    two_dict = {}
    one_name = None
    two_name = None
    result_dict = {}
    def get_idx(dct, lst, sym):
        if sym not in dct:
            lst.append({ "name": sym,
                         "in": 0,
                         "out": 0})
            idx = len(lst) - 1
            dct[sym] = idx
            return idx
        else:
            return dct[sym]
    for item in cur.fetchall():
        reverse = one == item[7]
        if one_name is None:
            one_name = item[2] if not reverse else item[6]
        if two_name is None:
            two_name = item[6] if not reverse else item[2]
        src = item[1] if not reverse else item[5]
        src_idx = get_idx(one_dict, one_symbols, src)
        dest = item[5] if not reverse else item[1]
        dest_idx = get_idx(two_dict, two_symbols, dest)
        if (src_idx, dest_idx) not in result_dict:
            result_dict[(src_idx, dest_idx)] = [1, 0] if not reverse else [0, 1]
        else:
            dir_idx = 0 if not reverse else 1
            result_dict[(src_idx, dest_idx)][dir_idx] += 1
        if reverse:
            one_symbols[src_idx]["in"] += 1
            two_symbols[dest_idx]["out"] += 1
        else:
            one_symbols[src_idx]["out"] += 1
            two_symbols[dest_idx]["in"] += 1
    return jsonify({"symbolsLeft": one_symbols,
                    "symbolsRight": two_symbols,
                    "edges" : [{"left": k[0],
                                "right": k[1],
                                "count": result_dict[k]}
                                for k in result_dict]})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5005)
