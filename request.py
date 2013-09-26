import urlparse
import Cookie

missing = object()

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

    ..attribute:: urlparts

    Parts of the requested URL as obtained by urlparse.urlsplit(path)
    """

    server_config = None

    def __init__(self, request_handler):
        self.doc_root = request_handler.server.router.doc_root
        request_handler.parse_request()
        self.protocol_version = request_handler.protocol_version
        self.method = request_handler.command
        self.path = request_handler.path
        self._raw_headers = request_handler.headers
        self._headers = None
        self.raw = request_handler.raw_requestline

        self.urlparts = urlparse.urlsplit(self.path)

        self._GET = None
        self._cookies = None

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)

    @property
    def GET(self):
        if self._GET is None:
            params = urlparse.parse_qsl(self.urlparts.query)
            self._GET = MultiDict()
            for key, value in params:
                self._GET[key] = value
        return self._GET

    @property
    def cookies(self):
        if self._cookies is None:
            parser = Cookie.BaseCookie()
            cookie_headers = self.headers.get("cookie", "")
            print cookie_headers
            data = parser.load(cookie_headers)
            cookies = MultiDict()
            for key, value in parser.iteritems():
                cookies[key] = CookieValue(value)
            self._cookies = cookies
        return self._cookies

    @property
    def headers(self):
        if self._headers is None:
            self._headers = RequestHeaders(self._raw_headers)
        return self._headers

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

    def get(self, key, default):
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

class MultiDict(dict):
    def __init__(self):
        pass

    def __setitem__(self, name, value):
        if name in self:
            self[name].append(value)
        else:
            dict.__setitem__(self, name, [value])

    def first(self, key, default=missing):
        if key in self and self[key]:
            return self[key][0]
        elif default is not missing:
            return default
        raise KeyError
