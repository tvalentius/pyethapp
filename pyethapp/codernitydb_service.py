from hashlib import md5
import os
from CodernityDB.database import Database, DatabasePathException,  \
    RecordNotFound
from CodernityDB.hash_index import HashIndex
from devp2p.service import BaseService
from ethereum.db import BaseDB
from gevent.event import Event
from ethereum import compress
from ethereum.slogging import get_logger


log = get_logger('db')


class MD5Index(HashIndex):

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '16s'
        super(MD5Index, self).__init__(*args, **kwargs)

    def make_key_value(self, data):
        return md5(data['key']).digest(), None

    def make_key(self, key):
        return md5(key).digest()


class CodernityDB(BaseDB, BaseService):

    """A service providing a codernity db interface."""

    name = 'db'
    default_config = dict(db=dict(path=''), app=dict(dir=''))

    def __init__(self, app):
        super(CodernityDB, self).__init__(app)
        self.dbfile = os.path.join(self.app.config['app']['dir'],
                                   self.app.config['db']['path'])
        self.db = None
        self.uncommitted = dict()
        self.stop_event = Event()
        self.db = Database(self.dbfile)
        try:
            log.info('opening db', path=self.dbfile)
            self.db.open()
        except DatabasePathException:
            log.info('db does not exist, creating it', path=self.dbfile)
            self.db.create()
            self.db.add_index(MD5Index(self.dbfile, 'key'))

    def _run(self):
        self.stop_event.wait()

    def stop(self):
        # commit?
        log.info('closing db')
        if self.started:
            self.db.close()
            self.stop_event.set()

    def get(self, key):
        log.debug('getting entry', key=key)
        if key in self.uncommitted:
            if self.uncommitted[key] is None:
                raise KeyError("key not in db")
            return self.uncommitted[key]
        try:
            value = self.db.get('key', key, with_doc=True)['doc']['value']
        except RecordNotFound:
            raise KeyError("key not in db")
        return compress.decompress(value)

    def put(self, key, value):
        log.debug('putting entry', key=key, value=value)
        self.uncommitted[key] = value

    def commit(self):
        log.debug('committing', db=self)
        for k, v in list(self.uncommitted.items()):
            if v is None:
                doc = self.db.get('key', k, with_doc=True)['doc']
                self.db.delete(doc)
            else:
                self.db.insert({'key': k, 'value': compress.compress(v)})
        self.uncommitted.clear()

    def delete(self, key):
        log.debug('deleting entry', key=key)
        self.uncommitted[key] = None

    def __contains__(self, key):
        try:
            self.get(key)
        except KeyError:
            return False
        return True

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.db == other.db

    def __repr__(self):
        return '<DB at %d uncommitted=%d>' % (id(self.db), len(self.uncommitted))

    def inc_refcount(self, key, value):
        self.put(key, value)

    def dec_refcount(self, key):
        pass

    def revert_refcount_changes(self, epoch):
        pass

    def commit_refcount_changes(self, epoch):
        pass

    def cleanup(self, epoch):
        pass

    def put_temporarily(self, key, value):
        self.inc_refcount(key, value)
        self.dec_refcount(key)
