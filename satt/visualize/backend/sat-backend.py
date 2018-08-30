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
def alignValueTo(val, to):
    if val == 0:
        return to
    md = val % to
    return int(val if md == 0 else val + (to - md))

@app.route('/api/1/heatmap/<int:traceId>/full/<int:plot_w>/<int:plot_h>',
           methods=['GET'])
def memheatmap_full(traceId, plot_w, plot_h):
    log_scale = True
    cur, named_cur = begin_db_request()
    schema = "pt" + str(traceId)
    cur.execute("select ip, length(opcode), exec_count, dso_name from " +
                schema + ".instructions_view")
    rows = cur.fetchall()
    rows.sort(key=itemgetter(0))
    address_ranges = [[rows[0][0],               # start address
                       rows[0][0] + rows[0][1],  # end address
                       0,                        # length <- bytes
                       0,                        # length <- units
                       None,                     # result array <- absolute
                       None,                     # result array <- normalized
                       rows[0][3]]               # DSO name
                      ]
    for row in rows:
        start_address = row[0]
        end_address = start_address + row[1] - 1
        current_dso = row[3]
        if address_ranges[-1][6] != current_dso:
            address_ranges.append([row[0], end_address, 0, 0,
                                  None, None, current_dso])
        else:
            address_ranges[-1][1] = end_address
    total_cells = 0
    for idx in range(0, len(address_ranges)):
        address_ranges[idx][2] = address_ranges[idx][1] - \
                                 address_ranges[idx][0] + 1
        total_cells += address_ranges[idx][2]

    ranges_count = len(address_ranges)
    available_lines = plot_h - (ranges_count - 1)
    available_cells = plot_w * available_lines
    mapping = max(1, math.ceil(1.0 * total_cells / available_cells))

    # Make sure that our mapping won't result in more data than we can display
    total_lines = 0
    for addr_range in address_ranges:
        total_lines += alignValueTo(addr_range[2] // mapping, plot_w)/plot_w
    if total_lines > available_lines:
        mapping += 1

    # Calculate mapped length
    for addr_range in address_ranges:
        addr_range[3] = alignValueTo(addr_range[2] // mapping, plot_w)

    current_range = 0
    current_result = [0] * address_ranges[current_range][3]
    for row in rows:
        if row[0] > address_ranges[current_range][1]:
            address_ranges[current_range][4] = current_result
            current_range += 1
            current_result = [0] * address_ranges[current_range][3]
        start_address = (row[0] - address_ranges[current_range][0]) // mapping
        start = int(start_address)
        end = start + int(row[1] // mapping)
        for idx in range(start, end + 1):
            current_result[idx] += row[2]
    address_ranges[-1][4] = current_result

    # Delete ranges with a mapped length of less than 1 px
    for idx in range(len(address_ranges) - 1, -1, -1):
        if address_ranges[idx][2] // mapping < 1:
            del address_ranges[idx]

    m = 1
    if log_scale:
        for addr_range in address_ranges:
            addr_range[5] = addr_range[4][:]
            for idx in range(0, len(addr_range[4])):
                if addr_range[4][idx] > 0:
                    addr_range[5][idx] = math.log(addr_range[5][idx], 2)
                    if addr_range[5][idx] > m:
                        m = addr_range[5][idx]
    else:
        m = max([max(x[5]) for x in address_ranges])

    # Normalize result
    # TODO: when displaying one range only, we should be probably normalize to
    # max of that range (not global max)
    for addr_range in address_ranges:
        for idx in range(0, len(addr_range[4])):
            if addr_range[5][idx] > 0:
                addr_range[5][idx] = int(math.floor(
                                         2047.0 * addr_range[5][idx] / m))
    # Create result data
    result_ranges = []
    for addr_range in address_ranges:
        data = {}
        for idx in range(len(addr_range[4])):
            if addr_range[4][idx] != 0:
                data[idx] = [addr_range[5][idx], addr_range[4][idx]]
        if len(data) == 0:
            continue
        dataLength = alignValueTo(addr_range[2] // mapping, plot_w)
        plotByteLength = dataLength * mapping
        result_ranges.append({
                    "startAddress": addr_range[0],
                    "endAddress": addr_range[1],
                    "bytesLength": addr_range[2],
                    "dataLength": addr_range[3],
                    "plotByteLength": plotByteLength,
                    "bytesPerPoint": mapping,
                    "data": data,
                    "dso": addr_range[6]
                })
    return jsonify({"ranges":result_ranges})

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
    wss_sym_dict["TOTAL"] = total_dso_wss
    return json.dumps(wss_sym_dict)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5005)
