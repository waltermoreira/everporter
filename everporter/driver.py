import hashlib
import binascii
import thrift.protocol.TBinaryProtocol as TBinaryProtocol
import thrift.transport.THttpClient as THttpClient
import evernote.edam.userstore.UserStore as UserStore
import evernote.edam.userstore.constants as UserStoreConstants
import evernote.edam.notestore.NoteStore as NoteStore
import evernote.edam.type.ttypes as Types

authToken = "S=s1:U=88856:E=142aa964ffc:C=13b52e523fc:P=1cd:A=en-devtoken:H=bedb6afa586c565eb2d9233d552ec8a0"


class Evernote(object):

    HOST = "www.evernote.com"

    def __init__(self, auth_token):
        self.user_store_http_client = THttpClient.THttpClient(self.user_store_uri)
        self.user_store_protocol = TBinaryProtocol.TBinaryProtocol(
            self.user_store_http_client)
        self.user_store = UserStore.Client(self.user_store_protocol)

        self.check_version()

    @property
    def user_store_uri(self):
        return "https://" + self.HOST + "/edam/user"

    def check_version(self):
        assert self.user_store.checkVersion(
            "Evernote EDAMTest (Python)",
            UserStoreConstants.EDAM_VERSION_MAJOR,
            UserStoreConstants.EDAM_VERSION_MINOR)
