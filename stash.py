import time
import uuid

#TODO: Consider expiring values after some fixed time for long-running
#servers

class Stash(object):
    data = {}

    def __init__(self, default_path):
        self.default_path = default_path

    def put(self, key, value, path=None):
        if path is None:
            path = self.default_path
        print "store", path, key, value
        if path not in self.data:
            self.data[path] = PathStash(path)

        self.data[path][key] = value

    def take(self, key, path=None):
        if path is None:
            path = self.default_path

        value = self.data[path][key]
        return value


class PathStash(dict):
    def __init__(self, path):
        self.path = path

    def __setitem__(self, key, value):
        key = uuid.UUID(key)
        if key in self:
            raise StashError("Tried to overwrite existing stash value for path %s and key %s (old value was %s, new value is %s)" % (self.path, key, self[str(key)], value))
        else:
            dict.__setitem__(self, key, value)

    def __getitem__(self, key):
        key = uuid.UUID(key)
        rv = dict.__getitem__(self, key)
        del self[key]
        return rv

class StashError(Exception):
    pass
