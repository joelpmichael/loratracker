#!/usr/bin/env python3
# -*- coding: utf_8 -*-

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

# simple JSON API server
# read LoRaWAN JSON structure from loraserver, parse tracker data, write to PostGIS

# make sure running on python3
import sys
assert (sys.version_info[0] == 3), "This code requires python3"

# handle arguments
import argparse
parser = argparse.ArgumentParser(description='HTTP JSON server')

parser.add_argument('-p', '--port',
                    type=int,
                    default=8088,
                    help='TCP port to listen on (default 8088)',
)

parser.add_argument('-l', '--listen',
                    type=str,
                    default="127.0.0.1",
                    help='IP address to listen on (default 127.0.0.1)',
)

parser.add_argument('-d', '--database',
                    type=str,
                    default="loratracker",
                    help='Database name to connect to (default loratracker)',
)

parser.add_argument('-H', '--dbhost',
                    type=str,
                    default=None,
                    help='Database IP host to connect to (default None - use local socket)',
)

parser.add_argument('-O', '--dbport',
                    type=int,
                    default=5432,
                    help='Database TCP Port to connect to (default 5432)',
)

parser.add_argument('-U', '--dbuser',
                    type=str,
                    default=None,
                    help='Database user name to use (default same as database name)',
)

parser.add_argument('-P', '--dbpass',
                    type=str,
                    default=None,
                    help='Database password to use (default no password)',
)

args = parser.parse_args()

import json
import datetime
import base64
import http.server

dbname = args.database
dbhost = args.dbhost
dbport = args.dbport
dbuser = args.dbuser
dbpass = args.dbpass

if dbuser == None:
    dbuser = dbname

import psycopg2
dbconn = psycopg2.connect(dbname=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport)
dbconn.autocommit = True

class CustomHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        # create new DB cursor for this request
        # this may be in a new thread if using Python 3.7
        cur = dbconn.cursor()
        self.close_connection = True
        content_length = int(self.headers['Content-Length'])
        if not content_length: 
            # check for a content length header
            self.send_error(411)
            return
        if(content_length > 4096): 
            # check that content length is 4096 bytes or less
            self.send_error(413)
            return
        if(self.headers['Content-Type'].casefold() != 'application/json'.casefold()):
            # check content type is JSON
            self.send_error(415)
            return
        body = self.rfile.read(content_length)
        payload = json.loads(body.decode())
        print(self.path)
        print(payload)
        if(self.path == '/uplink'):
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
            cur.execute("""INSERT INTO tracker_data (gw_id, gw_location, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, gps_location) 
                VALUES (%s, ST_SetSRID(st_makepoint(%s,%s,%s),4326), %s, %s, %s, %s, %s, %s, ST_SetSRID(st_makepoint(%s,%s,%s),4326);""", 
                (gw_id, gw_lat, gw_lon, gw_alt, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, f_lat, f_lon, f_alt)
            )
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)
    def _Err405(self):
        self.send_response(405)
        self.send_header('Allow','POST')
        self.end_headers()
    def do_GET(self):
        self._Err405()
    def do_HEAD(self):
        self._Err405()
    def do_PUT(self):
        self._Err405()
    def do_DELETE(self):
        self._Err405()
    def do_CONNECT(self):
        self._Err405()
    def do_OPTIONS(self):
        self._Err405()
    def do_TRACE(self):
        self._Err405()
    def do_PATCH(self):
        self._Err405()

httpd = http.server.HTTPServer(
        (args.listen, args.port),
        CustomHTTPRequestHandler,
)
if sys.version_info[1] >= 7: # python 3.7 has ThreadingHTTPServer, use that if available
    httpd = http.server.ThreadingHTTPServer(
        (args.listen, args.port),
        CustomHTTPRequestHandler,
    )
httpd.serve_forever()