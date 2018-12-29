#!/usr/bin/env python3
# -*- coding: utf_8 -*-

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

# simple JSON API server
# read LoRaWAN JSON structure from loraserver, parse tracker data, write to PostGIS

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

args = parser.parse_args()

import json
import datetime
import base64
import http.server

class CustomHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    # only accept POST requests of JSON smaller than 4096 bytes
    def do_POST(self):
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
        if(self.path == '/uplink'):
            # handle uplink data
            app_id = payload['applicationID']
            dev_eui = payload['devEUI']
            gateway_id = payload['rxInfo'][0]['gatewayID']
            gw_rx_time = payload['rxInfo'][0]['time']
            gw_rssi = payload['rxInfo'][0]['rssi']
            gw_snr = payload['rxInfo'][0]['loRaSNR']
            gw_lat = payload['rxInfo'][0]['location']['latitude']
            gw_lon = payload['rxInfo'][0]['location']['longitude']
            gw_alt = payload['rxInfo'][0]['location']['altitude']
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
            gps_timestamp = datetime.datetime.strptime("{0:0>6} {1:0>8}".format(gps_date, gps_time), '%d%m%y %H%M%S%f').replace(tzinfo=datetime.timezone.utc)

            print(gw_rx_timestamp.isoformat())
            print(gps_timestamp.isoformat())

            self.send_response(204)
            self.end_headers()
        else:
            print(self.path)
            print(payload)
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

httpd = http.server.ThreadingHTTPServer(
    (args.listen, args.port),
    CustomHTTPRequestHandler,
)
httpd.serve_forever()