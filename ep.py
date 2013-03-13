#!/usr/bin/env python

import everporter.driver as d

if __name__ == '__main__':
    x = d.Evernote(d.authToken)
    x.full_sync()