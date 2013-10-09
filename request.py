import urlparse
import Cookie
import tempfile
import StringIO
import cgi
import base64

import stash

missing = object()

class Server(object):
    config = None

    def __init__(self, request):
        self.stash = stash.Stash(request.url_parts.path)

class InputFile(object):
    max_buffer_size = 1024*1024

    def __init__(self, rfile, length):
        self._file = rfile
        self.length = length

        self._file_position = 0

        if length > self.max_buffer_size:
            self._buf = tempfile.TemporaryFile(mode="rw+b")
        else:
            self._buf = StringIO.StringIO()

    @property
    def _buf_position(self):
        rv = self._buf.tell()
        assert rv <= self._file_position
        return rv

    def read(self, bytes=-1):
        assert self._buf_position <= self._file_position

        if bytes < 0:
            bytes = self.length - self._buf_position
        bytes_remaining = min(bytes, self.length - self._buf_position)

        if bytes_remaining == 0:
            return ""

        if self._buf_position != self._file_position:
            buf_bytes = min(bytes_remaining, self._file_position - self._buf_position)
            old_data = self._buf.read(buf_bytes)
            bytes_remaining -= buf_bytes
        else:
            old_data = ""

        assert self._buf_position == self._file_position
        new_data = self._file.read(bytes_remaining)
        self._buf.write(new_data)
        self._file_position += bytes_remaining
        assert self._buf_position == self._file_position

        return old_data + new_data

    def tell(self):
        return self._buf_position

    def seek(self, offset):
        if offset > self.length or offset < 0:
            raise ValueError
        if offset <= self._file_position:
            self._buf.seek(offset)
        else:
            self.file.read(offset - self._file_position)

    def readline(self, max_bytes=None):
        if max_bytes is None:
            max_bytes = self.length - self._buf_position

        if self._buf_position < self._file_position:
            data = self._buf.readline(max_bytes)
            if data.endswith("\n") or len(data) == max_bytes:
                return data
        else:
            data = ""

        assert self._buf_position == self._file_position

        initial_position = self._file_position
        found = False
        buf = []
        max_bytes -= len(data)
        while not found:
            readahead = self.read(min(2, max_bytes))
            max_bytes -= len(readahead)
            for i, c in enumerate(readahead):
                if c == "\n":
                    buf.append(readahead[:i+1])
                    found = True
                    break
            if not found:
                buf.append(readahead)
            if not readahead or not max_bytes:
                break
        new_data = "".join(buf)
        data += new_data
        self.seek(initial_position + len(new_data))
        return data

    def readlines(self):
        rv = []
        while True:
            data = self.readline()
            if data:
                rv.append(data)
            else:
                break
        return rv

    def next(self):
        data = self.readline()
        if data:
            return data
        else:
            raise StopIteration

    def __iter__(self):
        return self

class Request(object):
    """Object representing a HTTP request.

    :param handler: The RequestHandler being used for this request

    .. attribute:: doc_root

    The local directory to use as a base when resolving paths

    .. attribute:: protocol_version

    HTTP version specified in the request.

    .. attribute:: method

    HTTP method in the request.

    .. attribute:: path

    Raw request path.

    .. attribute:: headers

    List of request headers.

    ..attribute:: raw

    Raw request.

    ..attribute:: url_parts

    Parts of the requested URL as obtained by urlparse.urlsplit(path)
    """

    def __init__(self, request_handler):
        self.doc_root = request_handler.server.router.doc_root
        request_handler.parse_request()
        self.protocol_version = request_handler.protocol_version
        self.method = request_handler.command

        scheme = request_handler.server.scheme
        host = request_handler.server.server_address[0]
        port = request_handler.server.server_address[1]
        self.request_path = request_handler.path

        if self.request_path.startswith(scheme + "://"):
            self.url = request_handler.path
        else:
            self.url = "%s://%s:%s%s"%(scheme,
                                       host,
                                       port,
                                       self.request_path)
        self.url_parts = urlparse.urlsplit(self.url)

        self._raw_headers = request_handler.headers
        self._headers = None
        self.request_line = request_handler.raw_requestline

        self.raw_input = InputFile(request_handler.rfile,
                                   int(self.headers.get("Content-Length", 0)))
        self._body = None

        self._GET = None
        self._POST = None
        self._cookies = None
        self._auth = None

        self.server = Server(self)

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)

    @property
    def GET(self):
        if self._GET is None:
            params = urlparse.parse_qsl(self.url_parts.query, keep_blank_values=True)
            self._GET = MultiDict()
            for key, value in params:
                self._GET.add(key, value)
        return self._GET

    @property
    def POST(self):
        if self._POST is None:
            #Work out the post parameters
            pos = self.raw_input.tell()
            self.raw_input.seek(0)
            fs = cgi.FieldStorage(fp=self.raw_input,
                                  environ = {"REQUEST_METHOD": self.method},
                                  headers=self.headers,
                                  keep_blank_values=True)
            self._POST = MultiDict.from_field_storage(fs)
            self.raw_input.seek(pos)
        return self._POST

    @property
    def cookies(self):
        if self._cookies is None:
            parser = Cookie.BaseCookie()
            cookie_headers = self.headers.get("cookie", "")
            data = parser.load(cookie_headers)
            cookies = Cookies()
            for key, value in parser.iteritems():
                cookies[key] = CookieValue(value)
            self._cookies = cookies
        return self._cookies

    @property
    def headers(self):
        if self._headers is None:
            self._headers = RequestHeaders(self._raw_headers)
        return self._headers

    @property
    def body(self):
        if self._body is None:
            pos = self.raw_input.tell()
            self._body = self.raw_input.read()
            self.raw_input.seek(pos)
        return self._body

    @property
    def auth(self):
        if self._auth is None:
            self._auth = Authentication(self.headers)
        return self._auth


class RequestHeaders(dict):
    def __init__(self, items):
        for key, value in zip(items.keys(), items.values()):
            key = key.lower()
            if key in self:
                self[key].append(value)
            else:
                dict.__setitem__(self, key, [value])

    def __getitem__(self, key):
        values = dict.__getitem__(self, key.lower())
        if len(values) == 1:
            return values[0]
        else:
            return ", ".join(values)

    def __setitem__(self, name, value):
        raise Exception

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def get_list(self, key, default=missing):
        try:
            return dict.__getitem__(self, key.lower())
        except:
            if default is not missing:
                return default
            else:
                raise

    def __contains__(self, key):
        return dict.__contains__(self, key.lower())

class CookieValue(object):
    def __init__(self, morsel):
        self.key = morsel.key
        self.value = morsel.value

        for attr in ["expires", "path",
                     "comment", "domain", "max-age",
                     "secure", "version", "httponly"]:
            setattr(self, attr.replace("-", "_"), morsel[attr])

        self._str = morsel.OutputString()

    def __str__(self):
        return self._str

    def __repr__(self):
        return self._str

    def __eq__(self, other):
        if hasattr(other, "value"):
            return self.value == other.value
        return self.value == other

class MultiDict(dict):
    def __init__(self):
        pass

    def __setitem__(self, name, value):
        dict.__setitem__(self, name, [value])

    def add(self, name, value):
        if name in self:
            dict.__getitem__(self, name).append(value)
        else:
            dict.__setitem__(self, name, [value])

    def __getitem__(self, name):
        return self.first(name)

    def first(self, key, default=missing):
        if key in self and dict.__getitem__(self, key):
            return dict.__getitem__(self, key)[0]
        elif default is not missing:
            return default
        raise KeyError

    def last(self, key, default=missing):
        if key in self and dict.__getitem__(self, key):
            return dict.__getitem__(self, key)[-1]
        elif default is not missing:
            return default
        raise KeyError

    def get_list(self):
        return dict.__getitem__(self, key)

    @classmethod
    def from_field_storage(cls, fs):
        self = cls()
        for key in fs:
            values = fs[key]
            if type(values) != type([]):
                values = [values]

            for value in values:
                if value.filename:
                    value = value
                else:
                    value = value.value
                self.add(key, value)
        return self

class Cookies(MultiDict):
    def __init__(self):
        pass

    def __getitem__(self, key):
        return self.last(key)


class Authentication(object):
    def __init__(self, headers):
        self.username = None
        self.password = None

        auth_schemes = {"Basic": self.decode_basic}

        if "authorization" in headers:
            header = headers.get("authorization")
            auth_type, data = header.split(" ", 1)
            if auth_type in auth_schemes:
                self.username, self.password = auth_schemes[auth_type](data)
            else:
                raise HTTPException(400, "Unsupported authentication scheme %s" % auth_type)

    def decode_basic(self, data):
        decoded_data = base64.decodestring(data)
        return decoded_data.split(":", 1)
