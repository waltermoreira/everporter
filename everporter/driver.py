import hashlib
import binascii
import math
from functools import wraps
import thrift.protocol.TBinaryProtocol as TBinaryProtocol
import thrift.transport.THttpClient as THttpClient
import evernote.edam.userstore.UserStore as UserStore
import evernote.edam.userstore.constants as UserStoreConstants
import evernote.edam.notestore.NoteStore as NoteStore
import evernote.edam.type.ttypes as Types
import evernote.edam.notestore.ttypes as NTypes

authToken = "S=s1:U=88856:E=142aa964ffc:C=13b52e523fc:P=1cd:A=en-devtoken:H=bedb6afa586c565eb2d9233d552ec8a0"


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

    def _export_note(self, note):
        content = self._get_content(note.guid)
        tags = self._get_tags(note.guid)
        resources = self._get_resouces(note)
        return {'content': content,
                'tags': tags,
                'resources': list(resources)}

    def _get_content(self, guid):
        return self.note_store.getNoteContent(self.auth_token, guid)

    def _get_tags(self, guid):
        return self.note_store.getNoteTagNames(self.auth_token, guid)

    def _get_resouces(self, note):
        for resource in note.resources:
            yield self.note_store.getResource(self.auth_token, resource.guid,
                                              True, True, True, True)

