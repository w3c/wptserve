import uuid
from multiprocessing.managers import SyncManager, DictProxy


#TODO: Consider expiring values after some fixed time for long-running
#servers


def start_server(address, authkey):
    shared_data = {}

    class DictManager(SyncManager):
        pass

    DictManager.register("get_dict", callable=lambda:shared_data, proxytype=DictProxy)
    manager = SyncManager(("127.0.0.1", 8910), "abc")
    manager.get_server().serve_forever()


class Stash(object):
    """Key-value store for persisting data across HTTP requests.

    This data store specifically designed for persisting data across
    HTTP requests. It is entirely in-memory so data will not be
    persisted across server restarts.

    This has several unusual properties. Keys are of the form (path,
    uuid), where path is, by default, the path in the HTTP request and
    uuid is a unique id. In addition, the store is write-once, read-once,
    i.e. the value associated with a particular key cannot be changed once
    written and the read operation (called "take") is destructive. Taken together,
    these properties make it difficult for data to accidentally leak
    between different resources or different requests for the same
    resource.

    """

    data = {}

    def __init__(self, address, auth, default_path):
        self.data = self._get_proxy(address, auth)
        self.default_path = default_path

    def _get_proxy(self, address, auth):
        class DictManager(SyncManager):
            pass

        DictManager.register("get_dict")
        manager = SyncManager(address, auth)
        manager.connect()
        d = manager.dict()

    def put(self, key, value, path=None):
        """Place a value in the stash.

        :param key: A UUID to use as the data's key.
        :param value: The data to store. This can be any python object.
        :param path: The path that has access to read the data (by default
                     the current request path)"""
        if path is None:
            path = self.default_path

        if value is None:
            raise ValueError("Stash value may not be set to None")

        id = (path, uuid.UUID(key))

        if id in self.data:
            raise StashError("Tried to overwrite existing stash value "
                             "for path %s and key %s (old value was %s, new value is %s)" %
                             (self.path, key, self.data[(path, key)], value))

        self.data[id] = value

    def take(self, key, path=None):
        """Remove a value from the stash and return it.

        :param key: A UUID to use as the data's key.
        :param path: The path that has access to read the data (by default
                     the current request path)"""
        if path is None:
            path = self.default_path

        id = (path, uuid.UUID(key))

        if id in self.data:
            value = self.data[id]
            del self.data[id]
        else:
            value = None
        return value


class StashError(Exception):
    pass
