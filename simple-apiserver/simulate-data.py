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

parser.add_argument('-g', '--gateways',
                    type=int,
                    default=10,
                    help='Number of gateways to simulate',
)

parser.add_argument('-G', '--gateway-id',
                    type=str,
                    default=[],
                    nargs='*',
                    help='Gateway IDs to include in simulated list',
)

parser.add_argument('-l', '--gwlat',
                    type=float,
                    default=-37.812305,
                    help='Latitude (decimal) of first gateway',
)

parser.add_argument('-o', '--gwlon',
                    type=float,
                    default=144.962594,
                    help='Longitude (decimal) of first gateway',
)

parser.add_argument('-a', '--gwalt',
                    type=float,
                    default=41.0,
                    help='Latitude (MASL) of first gateway',
)

parser.add_argument('-r', '--gwradius',
                    type=int,
                    default=[10000,14000,15000,17500,25000],
                    nargs=5,
                    help='Weighted average distance (M) between random gateways (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-m', '--gwmaxrange',
                    type=int,
                    default=15000,
                    help='Maximum distance (M) a gateway can hear a tracker',
)

parser.add_argument('-s', '--gwspeed',
                    type=int,
                    default=[3,11,16,25,33],
                    nargs=5,
                    help='Weighted average velocity (M/S) of gateway while moving (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-i', '--gwlift',
                    type=int,
                    default=[-20,-5,0,5,20],
                    nargs=5,
                    help='Weighted average lift (degrees) of gateway while moving (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-n', '--gwtime',
                    type=int,
                    default=[15*60,25*60,30*60,35*60,45*60],
                    nargs=5,
                    help='Weighted average time (S) that gateway moves for (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-e', '--gwdwell',
                    type=int,
                    default=[3600,6300,7200,8100,9600],
                    help='Weighted average time (S) that the gateway stays still for (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-t', '--trackers',
                    type=int,
                    default=100,
                    help='Number of trackers to simulate',
)

parser.add_argument('-T', '--tracker-eui',
                    type=str,
                    default=[],
                    nargs='*',
                    help='Tracker DevEUIs to include',
)

parser.add_argument('-R', '--trackerradius',
                    type=int,
                    default=[0,2500,5000,7500,15000],
                    nargs=5,
                    help='Weighted average distance (M) between random gateways (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-S', '--trackerspeed',
                    type=float,
                    default=[0,1,1.5,2.5,10],
                    nargs=5,
                    help='Weighted average velocity (M/S) of tracker while moving (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-I', '--trackerlift',
                    type=int,
                    default=[-40,-5,0,5,40],
                    nargs=5,
                    help='Weighted average lift (degrees) of tracker while moving (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-N', '--trackertime',
                    type=int,
                    default=[60,85,90,95,120],
                    help='Weighted average time (S) that tracker moves for (0%%, 25%%, 50%%, 75%%, 100%%)',
)

parser.add_argument('-C', '--catchtime',
                    type=int,
                    default=900,
                    help='Time reduction (S) of gateway move time when a tracker catches its gateway',
)

parser.add_argument('-z', '--outrangetime',
                    type=int,
                    default=1800,
                    help='Time reduction (S) of gateway move time when no trackers in range',
)

parser.add_argument('-Z', '--runtime',
                    type=int,
                    default=8,
                    help='Simulation start time hours before now',
)

parser.add_argument('-X', '--delete-existing-data',
                    type=bool,
                    default=False,
                    help='Delete any existing tracker data (recommended if using existing tracer/gateway locations)',
)

args = parser.parse_args()

gateways = args.gateway_id
trackers = args.tracker_eui

dbname = args.database
dbhost = args.dbhost
dbport = args.dbport
dbuser = args.dbuser
dbpass = args.dbpass

if dbuser == None:
    dbuser = dbname

# DB connection
import psycopg2
dbconn = psycopg2.connect(dbname=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport)
dbconn.autocommit = False
cur = dbconn.cursor()

# roll-your-own weighted random function
import random
random.seed()
def wrand(min,q1,half,q3,max):
    weight = 0
    a = []
    # interpolate over 100 steps
    for i in range(100):
        if i < 50:
            weight += 1
        elif i > 50:
            weight -= 1
        if i < 25:
            step = (q1 - min) / 25
            cur = min + (step * i)
        elif i < 50:
            step = (half - q1) / 25
            cur = q1 + (step * (i - 25))
        elif i < 75:
            step = (q3 - half) / 25
            cur = half + (step * (i - 50))
        else:
            step = (max - q3) / 25
            cur = q3 + (step * (i - 75))
        for j in range(weight):
            a.append(cur)
    return(a[random.randrange(len(a))])

# find simulation start time
from datetime import datetime, timezone, timedelta
sim_end = datetime.utcnow().replace(tzinfo=timezone.utc)
sim_cur = sim_end - timedelta(seconds=3600 * args.runtime)
# create temp table to store gateways
cur.execute("DROP TABLE IF EXISTS sim_gateway;")
cur.execute("""CREATE TABLE sim_gateway (
        gw_id CHAR(16) PRIMARY KEY,
        gw_location GEOGRAPHY(POINTZ, 4326) NOT NULL,
        gw_nextmovetime TIMESTAMPTZ NOT NULL,
        gw_nextstoptime TIMESTAMPTZ NOT NULL,
        gw_rxenable BOOLEAN NOT NULL,
        gw_direction FLOAT NOT NULL
    )"""
)
dbconn.commit()

# create gateways that already exist
for gateway in gateways:
    cur.execute("""SELECT DISTINCT ON (gw_id) gw_id, gw_location
        FROM tracker_data
        WHERE gw_id = %s
        ORDER BY gw_id, gw_rx_timestamp DESC;""",
        (gateway,)
    )
    if cur.rowcount == 0:
        raise ValueError('-G {} not found'.format(gateway))
    gw_location = cur.fetchone()[1]
    gw_nextmovetime = sim_cur + timedelta(seconds=random.randrange(args.gwdwell[4])) # use a fully random time so we don't have a simultaneous gateway march
    gw_nextstoptime = gw_nextmovetime + timedelta(seconds=wrand(*args.gwtime))

    cur.execute("INSERT INTO sim_gateway VALUES (%s, %s, %s, %s, TRUE, 0.0);", (gateway, gw_location, gw_nextmovetime, gw_nextstoptime))

# add new random gateways until we reach max
if len(gateways) == 0:
    # manually add the first gateway using supplied lat/long
    gateway = "{0:016x}".format(random.randrange(2**64))
    cur.execute("SELECT ST_SetSRID(st_makepoint(%s,%s,%s),4326);", (args.gwlon, args.gwlat, args.gwalt))
    gw_location = cur.fetchone()[0]
    gw_nextmovetime = sim_cur + timedelta(seconds=random.randrange(args.gwdwell[4]))
    gw_nextstoptime = gw_nextmovetime + timedelta(seconds=wrand(*args.gwtime))
    cur.execute("INSERT INTO sim_gateway VALUES (%s, %s, %s, %s, TRUE, 0.0);", (gateway, gw_location, gw_nextmovetime, gw_nextstoptime))
    gateways.append(gateway)

# add more gateways until we reach max
for i in range(args.gateways - len(gateways)):
    gateway = "{0:016x}".format(random.randrange(2**64))
    from_gateway = gateways[random.randrange(len(gateways))]
    cur.execute("SELECT ST_Project(gw_location, %s, radians(%s)) FROM sim_gateway WHERE gw_id = %s;", (wrand(*args.gwradius), random.random() * 360, from_gateway))
    gw_location = cur.fetchone()[0]
    gw_nextmovetime = sim_cur + timedelta(seconds=random.randrange(args.gwdwell[4]))
    gw_nextstoptime = gw_nextmovetime + timedelta(seconds=wrand(*args.gwtime))
    cur.execute("INSERT INTO sim_gateway VALUES (%s, ST_SetSRID(ST_Force3D(%s),4326), %s, %s, TRUE, 0.0);", (gateway, gw_location, gw_nextmovetime, gw_nextstoptime))
    gateways.append(gateway)

dbconn.commit()

# create temp table to store trackers
cur.execute("DROP TABLE IF EXISTS sim_tracker;")
cur.execute("""CREATE TABLE sim_tracker (
        tr_id CHAR(16) PRIMARY KEY,
        tr_location GEOGRAPHY(POINTZ, 4326) NOT NULL,
        tr_nextchirptime TIMESTAMPTZ NOT NULL,
        tr_direction FLOAT NOT NULL
    )"""
)
dbconn.commit()

# create trackers that already exist
for tracker in trackers:
    cur.execute("""SELECT DISTINCT ON (dev_eui) dev_eui, gps_location
        FROM tracker_data
        WHERE dev_eui = %s
        ORDER BY dev_eui, gps_timestamp DESC;""",
        (tracker,)
    )
    if cur.rowcount == 0:
        raise ValueError('-T {} not found'.format(tracker))
    tr_location = cur.fetchone()[1]
    tr_nextchirptime = sim_cur + timedelta(seconds=random.randrange(args.trackertime[4])) # use a fully random time so we don't have a simultaneous tracker chirp

    cur.execute("INSERT INTO sim_tracker VALUES (%s, %s, %s, %s);", (tracker, tr_location, tr_nextchirptime, random.random() * 360))

# add more trackers until we reach max
for i in range(args.trackers - len(trackers)):
    tracker = "{0:016x}".format(random.randrange(2**64))
    from_gateway = gateways[random.randrange(len(gateways))]
    cur.execute("SELECT ST_Project(gw_location, %s, radians(%s)) FROM sim_gateway WHERE gw_id = %s;", (random.randrange(args.gwmaxrange), random.random() * 360, from_gateway))
    tr_location = cur.fetchone()[0]
    tr_nextchirptime = sim_cur + timedelta(seconds=random.randrange(args.trackertime[4]))
    cur.execute("INSERT INTO sim_tracker VALUES (%s, ST_SetSRID(ST_Force3D(%s),4326), %s, %s);", (tracker, tr_location, tr_nextchirptime, random.random() * 360))
    trackers.append(tracker)

dbconn.commit()

# start the simulation
while sim_cur <= sim_end:
    print("sim timestamp={}".format(sim_cur))

    # chirp any trackers that are due
    cur.execute("SELECT tr_id FROM sim_tracker WHERE tr_nextchirptime <= %s", (sim_cur,))
    for record in cur:
        tracker = record[0]
        c2 = dbconn.cursor()
        c2.execute("""SELECT DISTINCT ON (tr.tr_id) gw.gw_id, gw.gw_location, tr.tr_id, tr.tr_location, st_distance(tr.tr_location, gw.gw_location) AS distance, degrees(st_azimuth(tr.tr_location, gw.gw_location)) AS bearing
            FROM sim_gateway gw, sim_tracker tr
            WHERE tr.tr_id = %s
            AND gw.gw_rxenable = TRUE
            ORDER BY tr.tr_id, distance ASC, gw.gw_id;""",
            (record[0],)
        )
        chirp_data = c2.fetchone()
        if chirp_data[4] > args.gwmaxrange:
            print("tracker {} chirp not heard, gateway {} is {}M away".format(tracker, chirp_data[0], chirp_data[4]))
            # all gateways too far away to hear the chirp
            # 50% chance tracker will turn towards the closest gateway
            if random.random() >= 0.5:
                print("tracker moving new direction")
                c2.execute("UPDATE sim_tracker SET tr_direction = %s where tr_id = %s;", (chirp_data[5], tracker))
        else:
            # send a chirp to the closest gateway
            c2.execute("""INSERT INTO tracker_data (gw_id, gw_location, app_id, dev_eui, gw_rx_timestamp, gw_rx_rssi, gw_rx_snr, gps_timestamp, gps_location) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);""", 
                (chirp_data[0], chirp_data[1], 1, tracker, sim_cur, 0, 0, sim_cur.replace(microsecond=0), chirp_data[3])
            )
        tr_nextchirptime = sim_cur + timedelta(seconds=wrand(*args.trackertime))
        c2.execute("UPDATE sim_tracker SET tr_nextchirptime = %s where tr_id = %s", (tr_nextchirptime, tracker))

    # move all trackers
    cur.execute("SELECT tr_id, tr_location, tr_direction FROM sim_tracker")
    for record in cur:
        tracker = record[0]
        c2 = dbconn.cursor()
        c2.execute("SELECT ST_Project(%s, %s, radians(%s));", (record[1], wrand(*args.trackerspeed), (record[2] + wrand(-45,-5,0,5,45))))
        new_location = c2.fetchone()[0]
        c2.execute("""UPDATE sim_tracker 
            SET tr_location = ST_SetSRID(ST_Force3D(%s),4326)
            WHERE tr_id = %s;""",
            (new_location, tracker)
        )

    # move gateways
    # find gateways that started moving, disable RX and set direction to furthest tracker
    cur.execute("SELECT gw_id FROM sim_gateway WHERE gw_nextmovetime <= %s AND gw_rxenable = TRUE;", (sim_cur,))
    for record in cur:
        gateway = record[0]
        print("start move gateway {}".format(gateway))
        c2 = dbconn.cursor()
        c2.execute("""SELECT gw.gw_id, gw.gw_location, tr.tr_id, tr.tr_location, st_distance(gw.gw_location, tr.tr_location) AS distance, degrees(st_azimuth(gw.gw_location, tr.tr_location)) AS bearing
            FROM sim_gateway gw, sim_tracker tr
            WHERE gw.gw_id = %s
            ORDER BY distance DESC;""",
            (gateway,)
        )
        loc_data = c2.fetchone()
        c2.execute("""UPDATE sim_gateway
            SET gw_rxenable = FALSE, 
                gw_direction = %s
            WHERE gw_id = %s
            """,
            (loc_data[5], gateway)
        )

    # move gateways with RX disabled
    cur.execute("SELECT gw_id, gw_location, gw_direction FROM sim_gateway WHERE gw_rxenable = FALSE;")
    for record in cur:
        gateway = record[0]
        c2 = dbconn.cursor()
        c2.execute("SELECT ST_Project(%s, %s, radians(%s));", (record[1], wrand(*args.gwspeed), (record[2] + wrand(-45,-5,0,5,45))))
        new_location = c2.fetchone()[0]
        c2.execute("""UPDATE sim_gateway 
            SET gw_location = ST_SetSRID(ST_Force3D(%s),4326)
            WHERE gw_id = %s;""",
            (new_location, gateway)
        )

    # find gateways that have finished moving, enable RX, and set new move time
    cur.execute("SELECT gw_id FROM sim_gateway WHERE gw_nextstoptime <= %s;", (sim_cur,))
    for record in cur:
        gateway = record[0]
        print("stop move gateway {}".format(gateway))
        gw_nextmovetime = sim_cur + timedelta(seconds=wrand(*args.gwdwell))
        gw_nextstoptime = gw_nextmovetime + timedelta(seconds=wrand(*args.gwtime))

        c2 = dbconn.cursor()
        c2.execute("""UPDATE sim_gateway
            SET gw_rxenable = TRUE, 
                gw_nextmovetime = %s,
                gw_nextstoptime = %s
            WHERE gw_id = %s
            """,
            (gw_nextmovetime, gw_nextstoptime, gateway)
        )

    dbconn.commit()

    # advance the clock by 0-2 seconds (average 1 second)
    sim_cur = sim_cur + timedelta(seconds=1 + random.random() - random.random())

