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
l_conn.close()

r_conn.request('GET', args.uri_base + '/gwlatest', None, headers)
remote_latest = json.loads(r_conn.getresponse().read().decode())
r_conn.close()

push_list = {}
pull_list = {}

for gw_id in local_latest.keys():
    # timestamps are in iso8601 format, eg 2019-01-03T22:48:16.080583+00:00
    # python <3.7 doesn't have datetime.fromisoformat() so use strptime
    local_ts = datetime.strptime(local_latest[gw_id], '%Y-%m-%dT%H:%M:%S.%f%z')
    if gw_id in remote_latest:
        remote_ts = datetime.strptime(remote_latest[gw_id], '%Y-%m-%dT%H:%M:%S.%f%z')
        # remove key from remote_latest, because anything left will be added to the pull list
        del remote_latest[gw_id]
        if local_ts < remote_ts:
            print('PULL {} at {}'.format(gw_id, local_ts.isoformat()))
            pull_list[gw_id] = local_ts.isoformat()
        elif local_ts > remote_ts:
            print('PUSH {} at {}'.format(gw_id, remote_ts.isoformat()))
            push_list[gw_id] = remote_ts.isoformat()
        else:
            # if timestamps match then no need to push or pull
            print('MATCH {} at {}'.format(gw_id, local_ts.isoformat()))
    else:
        # remote doesn't have this gw, push all
        print('PUSH {} at min'.format(gw_id))
        push_list[gw_id] = datetime.min.isoformat()

for gw_id in remote_latest.keys():
    # anything left in remote_latest will be new, pull all
    print('PULL {} at min'.format(gw_id))
    pull_list[gw_id] = datetime.min.isoformat()

if len(push_list) > 0:
    # push_list: pull from local, push to remote
    print('PULL local, PUSH remote')
    l_conn.connect()
    r_conn.connect()
    l_conn.request('POST', args.local_uri_base + '/pull', json.dumps(push_list), headers)
    r_conn.request('POST', args.uri_base + '/push', l_conn.getresponse().read(), headers)
    l_conn.close()
    r_conn.close()

if len(pull_list) > 0:
    # pull_list: pull from remote, push to local
    print('PULL remote, PUSH local')
    l_conn.connect()
    r_conn.connect()
    r_conn.request('POST', args.uri_base + '/pull', json.dumps(pull_list), headers)
    l_conn.request('POST', args.local_uri_base + '/push', r_conn.getresponse().read(), headers)
    l_conn.close()
    r_conn.close()
