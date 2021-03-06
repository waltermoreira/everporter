import sys
import glob
import socket
import hashlib
import binascii
import base64
import json
import math
import os
import datetime
import threading
from functools import wraps
from numbers import Real
from collections import Sequence, Mapping
import thrift.protocol.TBinaryProtocol as TBinaryProtocol
import thrift.transport.THttpClient as THttpClient
import evernote.edam.userstore.UserStore as UserStore
import evernote.edam.userstore.constants as UserStoreConstants
import evernote.edam.notestore.NoteStore as NoteStore
import evernote.edam.type.ttypes as Types
import evernote.edam.notestore.ttypes as NTypes

DEFAULT_SYNC_DIR = os.path.expanduser('~/evernote_sync')

def cached(f):
    @wraps(f)
    def wrapper(*args):
        try:
            return wrapper._cache[args]
        except KeyError:
            return wrapper._cache.setdefault(args, f(*args))
    def _clear():
        wrapper._cache.clear()
    wrapper._cache = {}
    wrapper.clear = _clear
    return wrapper

def persistent_property(filename, default=None):
    def _get(self):
        try:
            return int(open(self.local_file(filename)).read())
        except IOError:
            _set(self, default)
            return default
    def _set(self, value):
        with open(self.local_file(filename), 'w') as f:
            f.write(str(value))
    return property(_get, _set)

def property_with_default(x):
    """A decorator to create a property with a default value.

    Use as:

        @property_with_default(5)
        def f(self, value):
            print 'setting with', value

    Then 'x.f' will return 5 if it hasn't been set before, and 'x.f =
    0' will set the value for 'x.f' and will execute its body.
    """
    def wrapper(f):
	attr = '_' + f.func_name
	def _do_set(obj, value):
	    setattr(obj, attr, value)
	    f(obj, value)
	def _do_get(obj):
	    return getattr(obj, attr, x)
	return property(_do_get, _do_set)
    return wrapper

def get_auth_token(filename):
    try:
        return open(filename).readline().strip()
    except IOError:
        raise Exception("Need a config file with the devtoken: '{0}'".format(filename))

class Evernote(object):

    HOST = "www.evernote.com"
    BATCH_SIZE = 30

    def __init__(self, config_file):
        """Create Evernote object from config file.

        `config_file` contains a line with the devtoken from Evernote.
        """
        self.user_store = self.store(self.user_store_uri, UserStore)
        self.check_version()
        self.auth_token = get_auth_token(config_file)
        self.note_store_url = self.user_store.getNoteStoreUrl(self.auth_token)
        self.note_store = self.store(self.note_store_url, NoteStore)
        self.sync_dir = DEFAULT_SYNC_DIR

    def store(self, url, store_class):
        http_client = THttpClient.THttpClient(url)
        protocol = TBinaryProtocol.TBinaryProtocol(http_client)
        return getattr(store_class, 'Client')(protocol)

    @property
    def user_store_uri(self):
        return "https://" + self.HOST + "/edam/user"

    def check_version(self):
        assert self.user_store.checkVersion(
            "(Ever)note Ex(porter)",
            UserStoreConstants.EDAM_VERSION_MAJOR,
            UserStoreConstants.EDAM_VERSION_MINOR)

    # -----

    def local_file(self, filename):
        return os.path.join(self.sync_dir, filename)

    last_usn = persistent_property('last_usn', 0)
    last_sync_time = persistent_property('last_sync_time', 0)

    def real_sync(self):
        sync_state = self.note_store.getSyncState(self.auth_token)
        if sync_state.fullSyncBefore > self.last_sync_time:
            self.full_sync()
        if self.last_usn == sync_state.updateCount:
            print 'No new changes'
        else:
            self.inc_sync()

    def _synced_chunks(self, full):
        while True:
            print ' Before getSyncChunk'
            sys.stdout.flush()
            def thunk():
                return self.note_store.getSyncChunk(self.auth_token,
                                                    self.last_usn,
                                                    self.BATCH_SIZE,
                                                    full)
            chunk = perform(thunk, retries=3, retry_errors=[socket.error])
            self.last_sync_time = chunk.currentTime
            print ' After getSyncChunk and before yield'
            sys.stdout.flush()
            if chunk.chunkHighUSN is None:
                break
            yield chunk 
            print ' After yield and before writing last_usn'
            sys.stdout.flush()
            self.last_usn = chunk.chunkHighUSN
            print ' After writing last_usn'
            sys.stdout.flush()
            if chunk.chunkHighUSN == chunk.updateCount:
                break

    def _get_many(self, chunk, attr):
        print '  Requesting', attr
        objs = getattr(chunk, attr)
        if objs is not None:
            for obj in objs:
                print '    Object', getattr(obj, 'guid', str(obj))
                yield obj
            
    def _write(self, objects):
        for obj in objects:
            name = type(obj).__name__
            with open(self.local_file(
                    '{}_{}.json'.format(name, obj.guid)), 'w') as f:
                f.write(json.dumps(thrift_to_json(obj)))

    def _expunge(self, objects):
        for obj in objects:
            print 'Removing', obj,
            try:
                filenames = glob.glob(self.local_file('*{}.json'.format(obj)))
                [filename] = filenames
            except ValueError:
                print 'Weird... got {} files to delete!?'.format(len(filenames))
                return
            print filename
            os.unlink(filename)

    def _get_content(self, note):
        print ' Getting note content', note.guid,
        note.content = self.note_store.getNoteContent(self.auth_token, note.guid)
        print 'done'
        return note

    def _get_resource(self, resource):
        print ' Getting resource', resource.guid,
        res = self.note_store.getResource(self.auth_token, resource.guid,
                                          True, True, True, True)
        print 'done'
        return res

    def _do_sync(self, full=True):
        for chunk in self._synced_chunks(full):
            print 'Processing chunk with high USN', chunk.chunkHighUSN, 'last_usn =', self.last_usn
            sys.stdout.flush()
            self._write(self._get_many(chunk, 'tags'))
            self._write(self._get_many(chunk, 'searches'))
            self._write(self._get_many(chunk, 'notebooks'))
            self._write(map(self._get_content, self._get_many(chunk, 'notes')))
            if full:
                self._write(map(self._get_resource, self._get_many(chunk, 'resources')))
            else:
                self._write(self._get_resource(resource)
                            for note in self._get_many(chunk, 'notes')
                            if note.resources is not None
                            for resource in note.resources)
                self._expunge(self._get_many(chunk, 'expungedNotes'))
                self._expunge(self._get_many(chunk, 'expungedNotebooks'))
                self._expunge(self._get_many(chunk, 'expungedTags'))
                self._expunge(self._get_many(chunk, 'expungedSearches'))
            print
        
    def full_sync(self):
        print 'Doing full sync'
        self._do_sync(full=True)
        
    def inc_sync(self):
        print 'Doing inc sync'
        self._do_sync(full=False)
        
def thrift_to_json(obj):
    if obj is None:
        return None
    if isinstance(obj, Types.LazyMap):
        return None
    if isinstance(obj, Real):
        return obj
    if isinstance(obj, str):
        try:
            json.dumps(obj)
            return obj
        except UnicodeDecodeError:
            return {'b': base64.encodestring(obj)}
    if isinstance(obj, Sequence):
        return [thrift_to_json(x) for x in obj]
    dic = obj if isinstance(obj, Mapping) else obj.__dict__
    return {k:thrift_to_json(v) for k, v in dic.items()}


def perform(f, retries, retry_errors, timeout=None):
    for attempt in range(retries):
        try:
            return f()
        except tuple(retry_errors) as exc:
            print ('Execution of {} failed, {} retries remaining'
                   .format(str(f), retries-attempt-1))
            continue
    raise exc 
