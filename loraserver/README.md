# Install guide for standalone LoRa gateway + tracking web app

## LoRa Server
1. Install LoRa Server per docs at https://www.loraserver.io/
1. Configure LoRa Server to talk to hardware gateway (you might need https://raw.githubusercontent.com/TheThingsNetwork/gateway-conf/master/AU-global_conf.json)
1. Create Network Server, Gateway Profile, Gateway, Application
1. Add device EUIDs
1. Add HTTP integration

## mod_tile
1. Install PostgreSQL, PostGIS and Python3 PGSQL library: `apt install postgresql postgresql-client postgis osm2pgsql python3-psycopg2`
1. Create tracker database
    1. `su - postgres`
    1. `createuser -D -E -P -S loratracker`
    1. `createdb -E UTF8 -O loratracker loratracker`
    1. `psql -c "create extension hstore;" -d loratracker`
    1. `psql -c "create extension postgis;" -d loratracker`
1. Install passenger per docs at https://www.phusionpassenger.com/library/walkthroughs/start/python.html#install-passenger
1. Install and configure mod_tile
    1. `git clone https://github.com/openstreetmap/mod_tile.git`
    1. `apt install build-essential fakeroot devscripts libmapnik-dev apache2-dev apache2 curl unzip gdal-bin mapnik-utils node-carto`
    1. `cd mod_tile/`
    1. `debuild -b -uc -us`
    1. `cd ..`
    1. `dpkg -i libapache2-mod-tile_0.4-12~precise2_*.deb renderd_0.4-12~precise2_*.deb`
    1. `a2enmod tile`
    1. `vi /etc/renderd.conf`
    1. `wget https://github.com/gravitystorm/openstreetmap-carto/archive/v2.29.1.tar.gz`
    1. `wget http://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf`
    1. `osm2pgsql --slim -d loratracker -U loratracker -W -H localhost -C 6000 --hstore --number-processes 6 -v --drop -S openstreetmap-carto-2.29.1/openstreetmap-carto.style australia-latest.osm.pbf`
    1. `cd openstreetmap-carto-2.29.1/`
    1. `./get-shapefiles.sh`
    1. `vi project.mml`
    1. `carto project.mml > style.xml`
    1. `cd ..`
    1. `rm /etc/apache2/sites-enabled/tileserver_site.conf`
    1. `vi /etc/apache2/conf-available/tracker.conf`
    1. `cd /etc/apache2/conf-enabled`
    1. `ln -s ../conf-available/tracker.conf .`
    1. `apache2ctl restart`
    1. `wget --spider http://localhost/osm/0/0/0.png`
            Spider mode enabled. Check if remote file exists.
            --2019-01-10 06:10:58--  http://localhost/osm/0/0/0.png
            Resolving localhost (localhost)... ::1, 127.0.0.1
            Connecting to localhost (localhost)|::1|:80... connected.
            HTTP request sent, awaiting response... 200 OK
            Length: 6811 (6.7K) [image/png]
            Remote file exists.
## Tracker web app
1. `cd /var/www`
1. `git clone https://github.com/joelpmichael/loratracker.git`