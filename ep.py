#!/usr/local/bin/python

import datetime
from os.path import abspath, dirname, join
import sys

import everporter.driver as d

if __name__ == '__main__':
    config = join(abspath(dirname(__file__)), 'ep.conf')
    print('Reading devtoken from: {0}'.format(config))
    print('Starting sync on: {0}'.format(datetime.datetime.now().isoformat(' ')))
    x = d.Evernote(config)
    x.real_sync()
