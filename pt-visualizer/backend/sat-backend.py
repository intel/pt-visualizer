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
    SAT_HOME = os.path.realpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    os.environ['SAT_HOME'] = SAT_HOME

import status as stat

app = Flask(__name__, static_url_path='',
            static_folder=os.path.join(SAT_HOME, 'pt-visualizer', 'webui'))

status = stat.getStatus()

app.debug = True
DEBUG = False

INS_MORE_LIMIT = 1000

def get_db():
    if getattr(g, '_database', None) is None:
        g._database = psycopg2.connect(
            dbname=status.getDbConfig('dbname'),
            user=status.getDbConfig('user'),
            password=status.getDbConfig('password'),
            host='localhost')
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


@app.route('/', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def main():
    return app.send_static_file('index.html')

@app.route('/trace/<int:id>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def trace_id(id):
    return app.send_static_file('index.html')


@app.route('/transitiongraph/<int:id>',
           methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def transitiongraph(id):
    return app.send_static_file('index.html')

"""
@app.route('/admin/views/admin/<string:endpoint>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def admin_view(endpoint):
    print '/views/admin/' + endpoint
    return app.send_static_file('views/admin/' + endpoint)

@app.route('/admin', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
def admin():
    return app.send_static_file('index.html')
"""

@app.route('/api/1/traceinfo/<int:traceId>')
def traceinfo(traceId):
    cur, named_cur = begin_db_request()
    data = {}
    data['infos'] = []

    named_cur.execute("select * from public.traces where id=%s", (traceId, ))
    rows = named_cur.fetchall()
    data['trace'] = rows[0]

    return json.dumps(data, default=dthandler)


################################################################
#
# Delete trace permanetly
#
################################################################
@app.route('/api/1/trace/<int:traceId>', methods=['DELETE'])
def delete_trace(traceId):
    db = get_db()
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
    db = get_db()
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
                                     self.start_address_aligned + \
                                     bytes_per_sample
            self.sample_count = self.byte_size_aligned // bytes_per_sample
            self.data_raw = [0] * self.sample_count
            self.data_normalized = [0] * self.sample_count

        def add_sample(self, ip, length, count):
            if ip < self.start_address or ip > self.end_address:
                if DEBUG:
                    print("Invalid sample skipped")
                return
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

    named_cur.execute("select ip, octet_length(opcode) as length, exec_count, "
                      "dso_name from " + schema +
                      ".instructions_view order by ip")

    rows = named_cur.fetchall()
    rows.sort(key=itemgetter(0))
    address_ranges = {}
    range_slices = {}
    MAX_RANGE_GAP = 128 * 1024 * 1024

    for row in rows:
        start_address = row.ip
        current_dso = row.dso_name
        if start_address == 0:
            continue
        end_address = start_address + row.length - 1
        if current_dso not in address_ranges:
            address_ranges[current_dso] = \
                        MemoryRange(start_address, end_address, current_dso)
        else:
            if current_dso in range_slices:
                found_slice = False
                for name in range_slices[current_dso]:
                    if start_address - \
                       address_ranges[name].end_address <= MAX_RANGE_GAP:
                        address_ranges[name].end_address = end_address
                        found_slice = True
                        break
                if not found_slice:
                    added_dso_name = "%s_%d" % (current_dso,
                                                len(range_slices[current_dso]))
                    range_slices[current_dso].append(added_dso_name)
                    address_ranges[added_dso_name] = \
                        MemoryRange(start_address, end_address, added_dso_name)
            else:
                if start_address - \
                   address_ranges[current_dso].end_address > MAX_RANGE_GAP:
                    added_dso_name = "%s_%d" % (current_dso, 1)
                    range_slices[current_dso] = [current_dso, added_dso_name]
                    address_ranges[added_dso_name] = \
                        MemoryRange(start_address, end_address, added_dso_name)
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
        if row.ip == 0:
            continue
        target_dso = None
        start_address = row.ip
        end_address = start_address + row.length - 1
        if row.dso_name in range_slices:
            for name in range_slices[row.dso_name]:
                if address_ranges[name].start_address <= start_address and \
                   address_ranges[name].end_address >= end_address:
                    target_dso = name
                    break
        else:
            target_dso = row.dso_name
        if target_dso is None:
            print ("Dropping from %s" % (row.dso_name))
        else:
            address_ranges[target_dso].add_sample(start_address, row.length,
                                                  row.exec_count)

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

    # Total WSS
    total_wss = sum([ar.wss for ar in address_ranges_list])

    # Create result data
    return jsonify({
        "bytesPerSample": bytes_per_sample,
        "wss": total_wss,
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

    named_cur.execute("select * from ("
                "select cpf.symbol_id as from_symbol_id, "
                "(select name from " + schema +
                ".symbols where id = cpf.symbol_id) as from_symbol_name, "
                "(select dso_id from " + schema +
                ".symbols where id = cpf.symbol_id) as from_dso, "
                "cpt.symbol_id as to_symbol_id, "
                "(select name from " + schema +
                ".symbols where id = cpt.symbol_id) as to_symbol_name, "
                "(select dso_id from " + schema +
                ".symbols where id = cpt.symbol_id) as to_dso, "
                "flags from " + schema + ".calls cls "
                "inner join " + schema + ".call_paths cpt on "
                "cls.call_path_id = cpt.id " +
                "inner join " + schema + ".call_paths cpf on "
                "cls.parent_call_path_id = cpf.id "
                ") as filterThis where (from_dso = " + str(one) +
                " and to_dso = " + str(two) + ") or (from_dso = " + str(two) +
                " and to_dso = " + str(one) + ")")

    one_symbols = []
    two_symbols = []
    one_dict = {}
    two_dict = {}
    result_dict = {}
    def get_idx(dct, lst, sym):
        if sym not in dct:
            idx = len(lst)
            lst.append({ "name": sym,
                         "in": 0,
                         "out": 0,
                         "idx": idx})
            dct[sym] = idx
            return idx
        else:
            return dct[sym]
    for item in named_cur.fetchall():
        reverse = one == item.to_dso
        src = item.from_symbol_name if not reverse else  \
              item.to_symbol_name
        src_idx = get_idx(one_dict, one_symbols, src)
        dest = item.to_symbol_name if not reverse else   \
               item.from_symbol_name
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
