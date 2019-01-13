#!/usr/bin/env python3
# -*- coding: utf_8 -*-

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

# flask-based JSON API server
# read LoRaWAN JSON structure from loraserver, parse tracker data, write to PostGIS

from flask import Flask, jsonify, request, abort
app = Flask(__name__)
app.config.from_json('global_config.json', silent=False)
app.config.from_json('local_config.json', silent=True)

# taken from https://stackoverflow.com/questions/25036498/is-it-possible-to-limit-flask-post-data-size-on-a-per-route-basis
from functools import wraps
def limit_content_length(max_length):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cl = request.content_length
            if cl == None:
                abort(411)
            elif cl > max_length:
                abort(413)
            return f(*args, **kwargs)
        return wrapper
    return decorator
def limit_content_type(allowed_type):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ct = request.content_type
            if ct == None or ct != allowed_type:
                abort(415)
            return f(*args, **kwargs)
        return wrapper
    return decorator

import datetime # for datetime.strptime()
import base64 # for base64.decode()
import psycopg2 # for database
import string # for string.hexdigits()
import json # for json.dumps() and json.loads()

@app.route('/uplink', methods = ['POST'])
@limit_content_length(4096)
@limit_content_type('application/json')
def uplink():
    payload = request.get_json()
    # this is just copy-paste from lora-apiserver.py
    # handle uplink data
    app_id = payload['applicationID']
    dev_eui = payload['devEUI']
    gw_id = payload['rxInfo'][0]['gatewayID']
    gw_lat = payload['rxInfo'][0]['location']['latitude']
    gw_lon = payload['rxInfo'][0]['location']['longitude']
    gw_alt = payload['rxInfo'][0]['location']['altitude']
    gw_rx_time = payload['rxInfo'][0]['time']
    gw_rx_rssi = payload['rxInfo'][0]['rssi']
    gw_rx_snr = payload['rxInfo'][0]['loRaSNR']
    uplink_data = base64.decodebytes(payload['data'].encode())

    # uplink_data is the byte stream coming out of the tracker
    # output is 20 bytes of packed data (5 x 32bit words):
    # long i_lat: decimal latitude millionths - divide by 1,000,000 for decimal
    # long i_lon: decimal longitude millionths
    # long i_alt: cm above sea level - divide by 100 for decimal M
    # u_long gps_date: date stamp of GPS in DDMMYY
    # u_long gps_time: time stamp of GPS in HHMMSSff - divide by 100 for decimal S
    
    f_lat = int.from_bytes(uplink_data[0:4], byteorder='big', signed=True) / 1000000
    f_lon = int.from_bytes(uplink_data[4:8], byteorder='big', signed=True) / 1000000
    f_alt = int.from_bytes(uplink_data[8:12], byteorder='big', signed=True) / 100
    gps_date = int.from_bytes(uplink_data[12:16], byteorder='big', signed=False)
    gps_time = int.from_bytes(uplink_data[16:20], byteorder='big', signed=False)

    gw_rx_timestamp = datetime.datetime.strptime(gw_rx_time, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
    if gps_time == 0:
        # LoRa packet received without GPS fix, insert a dummy timestamp
        gps_timestamp = datetime.datetime.min().replace(tzinfo=datetime.timezone.utc)
    else:
        gps_timestamp = datetime.datetime.strptime("{0:0>6} {1:0>8}".format(gps_date, gps_time), '%d%m%y %H%M%S%f').replace(tzinfo=datetime.timezone.utc)

    # insert into the db
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = False
    cur = dbconn.cursor()
    cur.execute("""INSERT INTO tracker_data (gw_id, gw_location, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, gps_location) 
        VALUES (%s, ST_SetSRID(st_makepoint(%s,%s,%s),4326), %s, %s, %s, %s, %s, %s, ST_SetSRID(st_makepoint(%s,%s,%s),4326));""", 
        (gw_id, gw_lon, gw_lat, gw_alt, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, f_lon, f_lat, f_alt)
    )
    if cur.rowcount != 1:
        # insert failed?
        dbconn.rollback()
        abort(500)
    
    dbconn.commit()

    return ('', 204) # 204 = HTTP no content

# return location of a requested gateway
# gateway ID must be one of:
# - 16 hex digits
# - "self" (return gateway ID defined in config, or "mid" if not defined)
# - "mid" (return middle of all gateway locations)
# - "all" (return all gateway locations)
@app.route('/gwlocation/<gateway>', methods = ['GET'])
@limit_content_type('application/json')
def gwlocation(gateway):
    # set up DB connection
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = True
    cur = dbconn.cursor()

    if gateway == 'self':
        # we are trying to find ourself
        if app.config['GATEWAYID'] == None:
            gateway = 'mid'
        else:
            gateway = app.config['GATEWAYID']
    if gateway == 'mid':
        # return the middle of all gateway last known locations
        cur.execute("""SELECT 'ffffffffffffffff'::char(16), ST_AsGeoJSON(ST_Centroid(ST_Collect(gw.gw_location)))
            FROM (
	            SELECT DISTINCT ON (gw_id) gw_id, gw_location::geometry
	            FROM tracker_data
	            ORDER BY gw_id, gw_rx_timestamp DESC
            ) AS gw;""")
    elif gateway == 'all':
        # return the location of all gateway last known locations
        cur.execute("""SELECT DISTINCT ON (gw_id) gw_id, ST_AsGeoJSON(gw_location)
            FROM tracker_data
            ORDER BY gw_id, gw_rx_timestamp DESC;""",
        )
    else:
        if len(gateway) != 16: # gateway ID is 16 hex characters, make sure it is
            abort(404)
        if not all(c in string.hexdigits for c in gateway):
            abort(404)
        # return the last known location of the requested gateway
        cur.execute("""SELECT DISTINCT ON (gw_id) gw_id, ST_AsGeoJSON(gw_location)
            FROM tracker_data
            WHERE gw_id = %s
            ORDER BY gw_id, gw_rx_timestamp DESC;""",
            (gateway,)
        )

    if cur.rowcount == 0:
        # gateway not found
        abort(404)
        
    gateways = {}
    for record in cur:
        geojson = json.loads(record[1])
        gateways[record[0]] = geojson
    
    return jsonify(gateways)

@app.route('/gwarea/<gateway>', methods = ['GET'])
@limit_content_type('application/json')
def gwarea(gateway):
    # set up DB connection
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = True
    cur = dbconn.cursor()

    if app.config['GATEWAYRADIUS'] == 0:
        # you definitely need to configure this...
        print("Configure GATEWAYRADIUS to non-zero in M from gateway")
        abort(500)
    if gateway == 'self':
        # we are trying to find ourself
        if app.config['GATEWAYID'] == None:
            gateway = 'mid'
        else:
            gateway = app.config['GATEWAYID']
    if gateway == 'mid':
        # return the middle of all gateway last known locations
        cur.execute("""SELECT 'ffffffffffffffff'::char(16), ST_AsGeoJSON(Box2D(ST_Buffer(ST_SetSRID(ST_Centroid(ST_Collect(gw.gw_location)),4326)::geography,%s,'quad_segs=1')::geometry))
            FROM (
                SELECT DISTINCT ON (gw_id) gw_id, gw_location::geometry
                FROM tracker_data
                ORDER BY gw_id, gw_rx_timestamp DESC
            ) AS gw;""",
            (app.config['GATEWAYRADIUS'],)
        )
    else:
        # return the last known location of the requested gateway
        if len(gateway) != 16: # gateway ID is 16 hex characters, make sure it is
            abort(404)
        if not all(c in string.hexdigits for c in gateway):
            abort(404)
        cur.execute("""SELECT gw.gw_id, ST_AsGeoJSON(Box2D(ST_Buffer(ST_SetSRID(ST_Centroid(ST_Collect(gw.gw_location)),4326)::geography,%s,'quad_segs=1')::geometry))
            FROM (
                SELECT DISTINCT ON (gw_id) gw_id, gw_location::geometry
                FROM tracker_data
                WHERE gw_id = %s
                ORDER BY gw_id, gw_rx_timestamp DESC
            ) AS gw
            GROUP BY 1;""",
            (app.config['GATEWAYRADIUS'],gateway)
        )
    if cur.rowcount == 0:
        # gateway not found
        abort(404)
        
    gateways = {}
    for record in cur:
        geojson = json.loads(record[1])
        gateways[record[0]] = geojson
    
    return jsonify(gateways)

# return location of a requested tracker
# tracker ID must be one of:
# - 16 hex digits
# - "all" (return all tracker locations)
@app.route('/trlocation/<tracker>', methods = ['GET'])
@limit_content_type('application/json')
def trlocation(tracker):
    # set up DB connection
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = True
    cur = dbconn.cursor()

    if tracker == 'all':
        # return the location of all gateway last known locations
        cur.execute("""SELECT DISTINCT ON (dev_eui) dev_eui, ST_AsGeoJSON(gps_location)
            FROM tracker_data
            ORDER BY dev_eui, gps_timestamp DESC;""",
        )
    else:
        if len(tracker) != 16: # gateway ID is 16 hex characters, make sure it is
            abort(404)
        if not all(c in string.hexdigits for c in tracker):
            abort(404)
        # return the last known location of the requested gateway
        cur.execute("""SELECT DISTINCT ON (dev_eui) dev_eui, ST_AsGeoJSON(gps_location)
            FROM tracker_data
            WHERE dev_eui = %s
            ORDER BY dev_eui, gps_timestamp DESC;""",
            (tracker,)
        )

    if cur.rowcount == 0:
        # gateway not found
        abort(404)
        
    trackers = {}
    for record in cur:
        geojson = json.loads(record[1])
        trackers[record[0]] = geojson
    
    return jsonify(trackers)

# return latest timestamp of requested gateway (for sync purposes)
# gateway ID must be one of:
# - 16 hex digits
# - "self" (return gateway ID defined in config, or "mid" if not defined)
# - "all" (return all gateway locations)
@app.route('/gwlatest', methods = ['GET'])
@limit_content_type('application/json')
def gwlatest():
    # set up DB connection
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = True
    cur = dbconn.cursor()

    # return the latest timestamp of all gateway rx timestamps
    cur.execute("""SELECT DISTINCT ON (gw_id) gw_id, gw_rx_timestamp
        FROM tracker_data
        ORDER BY gw_id, gw_rx_timestamp DESC;""",
    )

    gateways = {}
    for record in cur:
        gateways[record[0]] = record[1].isoformat()
    
    return jsonify(gateways)

# return tracker data later than the given timestamp for the given gateway
# allow to specify multiple gateways with different timestamps
# JSON request data format:
# {
#    "gateway id": "timestamp"
# }
@app.route('/pull', methods = ['POST'])
@limit_content_type('application/json')
def pull():
    payload = request.get_json()
    
    # set up DB connection
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = True
    cur = dbconn.cursor()

    # construct SQL statement with appropriate number of boolean operators in the WHERE clause
    sql = """SELECT gw_id, gw_location, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, gps_location
FROM tracker_data
"""
    where = " WHERE "
    first = True
    args = []
    for gw_id in payload.keys():
        args.append(gw_id)
        args.append(payload[gw_id])
        sql += where
        sql += "(gw_id = %s AND gw_rx_timestamp > %s)\n"
        if first:
            first = False
            where = " OR "
    cur.execute(sql, args)
    if cur.rowcount == 0:
        # data not found
        abort(404)
    
    # can't use fetchall because jsonify(datetime) doesn't keep microsecond timestamps, need to use .isoformat() instead
    data = []
    for record in cur:
        data.append([record[0], record[1], record[2], record[3], record[4].isoformat(), record[5], record[6], record[7].isoformat(), record[8]])
    
    return jsonify(data)

# insert tracker data from remote gateways
# JSON request data format:
# [
#   [
#       gw_id,
#       gw_location,
#       app_id,
#       dev_eui,
#       gw_rx_timestamp,
#       gw_rx_rssi,
#       gw_rx_snr,
#       gps_timestamp,
#       gps_location
#   ]
# ]
@app.route('/push', methods = ['POST'])
@limit_content_type('application/json')
def push():
    payload = request.get_json()
    
    # set up DB connection
    dbconn = psycopg2.connect(dbname=app.config['DBNAME'], user=app.config['DBUSER'], password=app.config['DBPASS'], host=app.config['DBHOST'], port=app.config['DBPORT'])
    dbconn.autocommit = False # run inserts inside a transaction
    cur = dbconn.cursor()

    # construct SQL statement with appropriate number of boolean operators in the WHERE clause
    sql = """INSERT INTO tracker_data(gw_id, gw_location, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, gps_location)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
    for record in payload:
        cur.execute(sql, record)
        if cur.rowcount != 1:
            # insert failed?
            dbconn.rollback()
            abort(500)
    
    dbconn.commit()

    return ('', 204) # 204 = HTTP no content

if __name__ == '__main__':
    app.run()