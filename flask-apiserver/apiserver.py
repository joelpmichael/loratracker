#!/usr/bin/env python3
# -*- coding: utf_8 -*-

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

# flask-based JSON API server
# read LoRaWAN JSON structure from loraserver, parse tracker data, write to PostGIS

from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello World!'

if __name__ == '__main__':
    app.run()