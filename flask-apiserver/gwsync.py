#!/usr/bin/env python3
# -*- coding: utf_8 -*-

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

# sync tracker_data by comparing timestamps, then pull & push data

# handle arguments
import argparse
parser = argparse.ArgumentParser(description='HTTP JSON server')

parser.add_argument('-r', '--remote-host',
                    type=str,
                    required=True,
                    help='Remote host to connect to',
)

parser.add_argument('-l', '--local-host',
                    type=str,
                    default='127.0.0.1',
                    help='Local host to connect to (default 127.0.0.1)',
)

parser.add_argument('-s', '--https',
                    type=bool,
                    default=False,
                    help='Use HTTPS instead of HTTP (default use HTTP)',
)

parser.add_argument('-b', '--uri-base',
                    type=str,
                    default='',
                    help='Remote URI base for constructing request URLs (default /)',
)

parser.add_argument('-B', '--local-uri-base',
                    type=str,
                    default='',
                    help='Local URI base for constructing request URLs (default /)',
)

args = parser.parse_args()

import http.client
import json
from datetime import datetime

if args.https:
    l_conn = http.client.HTTPSConnection(args.local_host)
else:
    l_conn = http.client.HTTPConnection(args.local_host)

if args.https:
    r_conn = http.client.HTTPSConnection(args.remote_host)
else:
    r_conn = http.client.HTTPConnection(args.remote_host)

headers = {
    'Content-type': 'application/json',
    'Accept': 'application/json',
}

# grab timestamps
l_conn.request('GET', args.local_uri_base + '/gwlatest', None, headers)
local_latest = json.loads(l_conn.getresponse().read().decode())

r_conn.request('GET', args.uri_base + '/gwlatest', None, headers)
remote_latest = json.loads(r_conn.getresponse().read().decode())

push_list = {}
pull_list = {}
