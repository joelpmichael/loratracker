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
    dbconn.autocommit = True
    cur = dbconn.cursor()
    cur.execute("""INSERT INTO tracker_data (gw_id, gw_location, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, gps_location) 
        VALUES (%s, ST_SetSRID(st_makepoint(%s,%s,%s),4326), %s, %s, %s, %s, %s, %s, ST_SetSRID(st_makepoint(%s,%s,%s),4326));""", 
        (gw_id, gw_lon, gw_lat, gw_alt, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, f_lon, f_lat, f_alt)
    )

    return ('', 204) # 204 = HTTP no content

@app.route('/gwlocation/<gateway>', methods = ['GET'])
#@limit_content_type('application/json')
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
        # return the geometric middle of all gateway last known locations
        pass
    elif gateway == 'all':
        # return the last known location of all gateways
        cur.execute("""SELECT DISTINCT ON (gw_id) gw_id, ST_AsText(gw_location)
            FROM tracker_data
            ORDER BY gw_id, gw_rx_timestamp DESC;""")
        
        pass
    else:
        # return the last known location of the requested gateway
        cur.execute("""SELECT DISTINCT ON (gw_id) gw_id, ST_AsText(gw_location)
            FROM tracker_data
            WHERE gw_id = %s
            ORDER BY gw_id, gw_rx_timestamp DESC;""",
            (gateway,)
        )
        pass

@app.route('/gwarea/<gateway>', methods = ['GET'])
@limit_content_type('application/json')
def gwarea(gateway):
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
        # return the geometric middle of all gateway last known locations
        pass
    elif gateway == 'all':
        # return the last known location of all gateways
        pass
    else:
        # return the last known location of the requested gateway
        pass

if __name__ == '__main__':
    app.run()