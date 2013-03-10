import hashlib
import binascii
import base64
import json
import math
import os
import datetime
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

authToken = "S=s1:U=88856:E=14493fe99dd:C=13d3c4d6dde:P=1cd:A=en-devtoken:V=2:H=1190e8b7ed88f7530e7c3b176f41904c"

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


class Evernote(object):

    HOST = "www.evernote.com"
    BATCH_SIZE = 10

    def __init__(self, auth_token):
        self.user_store = self.store(self.user_store_uri, UserStore)
        self.check_version()
        self.auth_token = auth_token
        self.note_store_url = self.user_store.getNoteStoreUrl(self.auth_token)
        self.note_store = self.store(self.note_store_url, NoteStore)

    def notebooks(self):
        return self.note_store.listNotebooks(self.auth_token)

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

    @cached
    def tags(self):
        tags = self.note_store.listTags(self.auth_token)
        return {tag.name:tag for tag in tags}

    def tag_id(self, tag_name):
        if tag_name not in self.tags():
            self.tags.clear()
        return self.tags()[tag_name].guid

    @cached
    def notebooks(self):
        notebooks = self.note_store.listNotebooks(self.auth_token)
        return {notebook.name:notebook for notebook in notebooks}

    def notebook_id(self, notebook_name):
        if notebook_name not in self.notebooks():
            self.notebooks.clear()
        return self.notebooks()[notebook_name].guid

    def _find_notes(self, offset, count, **kwargs):
        note_filter = NTypes.NoteFilter()
        if 'notebook' in kwargs:
            kwargs['notebookGuid'] = self.notebook_id(kwargs['notebook'])
            del kwargs['notebook']
        if 'tags' in kwargs:
            kwargs['tagGuids'] = [self.tag_id(tag) for tag in kwargs['tags']]
            del kwargs['tags']
        note_filter.__dict__.update(kwargs)
        note_filter.order = Types.NoteSortOrder.UPDATED
        note_filter.ascending = True
        print '_find notes with offset = {} and count = {}'.format(offset, count)
        return self.note_store.findNotes(
            self.auth_token, note_filter, offset, count)
        
    def count(self, **kwargs):
        a_note = self._find_notes(0, 1, **kwargs)
        return a_note.totalNotes
        
    def find_notes(self, **kwargs):
        count = self.count(**kwargs)
        batches_number = int(math.ceil(float(count)/self.BATCH_SIZE))
        for batch in range(batches_number):
            print 'Processing batch number:', batch
            notes = self._find_notes(batch*self.BATCH_SIZE, self.BATCH_SIZE,
                                     **kwargs)
            for note in notes.notes:
                yield note

    def export(self, **kwargs):
        for note in self.find_notes(**kwargs):
            yield self._export_note(note)

    def json_export(self, **kwargs):
        for obj in self.export(**kwargs):
            yield thrift_to_json(obj)

    def _export_note(self, note):
        content = self._get_content(note.guid)
        tags = self._get_tags(note.guid)
        resources = self._get_resouces(note)
        return {'content': content,
                'tags': tags,
                'note': note,
                'resources': list(resources)}

    def _get_content(self, guid):
        return self.note_store.getNoteContent(self.auth_token, guid)

    def _get_tags(self, guid):
        return self.note_store.getNoteTagNames(self.auth_token, guid)

    def _get_resouces(self, note):
        if note.resources is None:
            return
        for resource in note.resources:
            yield self.note_store.getResource(self.auth_token, resource.guid,
                                              True, True, True, True)

    def write(self, directory, **kwargs):
        with open(os.path.join(directory, 'notebooks.json'), 'w') as f:
            f.write(json.dumps(thrift_to_json(self.notebooks())))

        with open(os.path.join(directory, 'tags.json'), 'w') as f:
            f.write(json.dumps(thrift_to_json(self.tags())))
            
        for obj in self.json_export(**kwargs):
            filename = os.path.join(directory,
                                    '{}.json'.format(obj['note']['guid']))
            with open(filename, 'w') as f:
                print 'Writing note', obj['note']['guid']
                print ' updated on', obj['note']['updated']
                f.write(json.dumps(obj))
                self.set_last_sync_to(directory,
                                      datetime.datetime.utcfromtimestamp(
                                          obj['note']['updated']/1e3))
                

    def sync(self, directory):
        last_sync = self.get_last_sync(directory)
        kwargs = ({'words': 'updated:{}'.format(last_sync)}
                  if last_sync is not None else {})
        print 'last_sync:', last_sync
        self.write(directory, **kwargs)

    def set_last_sync(self, directory):
        self.set_last_sync_to(directory, datetime.datetime.utcnow())

    def set_last_sync_to(self, directory, utc_datetime):
        last_sync_file = os.path.join(directory, 'last_sync')
        with open(last_sync_file, 'w') as f:
            f.write(utc_datetime.strftime('%Y%m%dT%H%M%SZ'))

    def get_last_sync(self, directory):
        last_sync_file = os.path.join(directory, 'last_sync')
        try:
            f = open(last_sync_file)
            return f.readline().strip()
        except IOError:
            return None
        
        
def thrift_to_json(obj):
    if obj is None:
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

