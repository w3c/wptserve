import sys
import json
import Cookie
import types
from collections import OrderedDict
import uuid

from constants import response_codes

missing = object()

class Response(object):
    """Object representing the response to a HTTP request

    :param handler: RequestHandler being used for this response
    :param request: Request that this is the response for

    .. attribute:: request

       Request associated with this Response.

    .. attribute:: encoding

       The encoding to use when converting unicode to strings for output.

    .. attribute:: add_required_headers

       Boolean indicating whether mandatory headers should be added to the
       response.

    .. attribute:: explicit_flush

       Boolean indicating whether ouptput should be flushed automatically or only
       when requested.

    .. attribute:: writer

       The ResponseWriter for this response

    .. attribute:: status

       Status tuple (code, message). Can be set to an integer, in which case the
       message part is filled in automatically, or a tuple.

    .. attribute:: headers

       List of HTTP headers to send with the response. Each item in the list is a
       tuple of (name, value).

    .. attribute:: content

       The body of the response. This can either be a string or a iterable of response
       parts. If it is an iterable, any item may be a string or a function of zero
       parameters which, when called, returns a string."""

    def __init__(self, handler, request):
        self.request = request
        self.encoding = "utf8"

        self.add_required_headers = True
        self.explicit_flush = False

        self.writer = ResponseWriter(handler, self)

        self._status = (200, None)
        self.headers = ResponseHeaders()
        self.content = []

        self.headers_written = False
        self.content_written = False

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        if hasattr(value, "__len__"):
            if len(value) != 2:
                raise ValueError
            else:
                self._status = (int(value[0]), str(value[1]))
        else:
            self._status = (int(value), None)

    def set_cookie(self, name, value, max_age=None,
                   path="/", domain=None, secure=False,
                   httponly=False, comment=None, expires=None):
        #TODO: deal with max age and expires in some sane way
        m = Cookie.Morsel()
        m.set(name, value, value)
        m.path = path
        m.domain = domain
        m.comment = comment
        m.expires = expires
        m.max_age = max_age
        m.secure = secure
        m.httponly = httponly

        self.headers.append("Set-Cookie", m.OutputString())

    def unset_cookie(self, name):
        cookies = self.headers.get("Set-Cookie")
        parser = Cookie.BaseCookie()
        for cookie in cookies:
            parser.load(cookie)

        if name in parser.keys():
            del self.headers["Set-Cookie"]
            for m in parser.values():
                if m.name != name:
                    self.headers.append(("Set-Cookie", m.OutputString()))

    def delete_cookie(self, name, path="/", domain=None):
        self.set_cookie(name, "", path=path, domain=domain, max_age=0)

    def iter_content(self):
        """Iterator returning chunks of response body content.

        If any part of the content is a function, this will be called
        and the resulting value (if any) returned."""
        if type(self.content) in types.StringTypes:
            yield self.content
        else:
            for item in self.content:
                if hasattr(item, "__call__"):
                    value = item()
                else:
                    value = item
                if value:
                    yield value

    def write_status_headers(self):
        self.writer.write_status(*self.status)
        for item in self.headers:
            self.writer.write_header(*item)
        self.writer.end_headers()

    def write_content(self):
        if self.request.method != "HEAD":
            for item in self.iter_content():
                self.writer.write_content(item)

    def write(self):
        self.write_status_headers()
        self.write_content()

    def set_error(self, code, message=""):
        err ={"code":code,
              "message":message}
        data = json.dumps({"error": err})
        self.status = code
        self.headers = [("Content-Type", "text/json"),
                        ("Content-Length", len(data))]
        print >> sys.stderr, "Error %i\n%s" % (err["code"], err["message"])
        if code == 500:
            raise
        self.content = data

class MultipartContent(object):
    def __init__(self, boundary=None, default_content_type=None):
        self.items = []
        if boundary is None:
            boundary = str(uuid.uuid4())
        self.boundary = boundary
        self.default_content_type = default_content_type

    def __call__(self):
        boundary = "--" + self.boundary
        rv = ["", boundary]
        for item in self.items:
            rv.append(str(item))
            rv.append(boundary)
        rv[-1] += "--"
        rv.append("")
        return "\r\n".join(rv)

    def append_part(self, data, content_type=None, headers=None):
        if content_type is None:
            content_type = self.default_content_type
        self.items.append(MultipartPart(data, content_type, headers))

class MultipartPart(object):
    def __init__(self, data, content_type=None, headers=None):
        self.headers = ResponseHeaders()

        if content_type is not None:
            self.headers.set("Content-Type", content_type)

        if headers is not None:
            for name, value in headers:
                if name.lower() == "content-type":
                    func = self.headers.set
                else:
                    func = self.headers.append
                func(name, value)

        self.data = data

    def __str__(self):
        rv = []
        for item in self.headers:
            rv.append("%s: %s" % item)
        rv.append("")
        rv.append(self.data)
        return "\r\n".join(rv)

class ResponseHeaders(object):
    def __init__(self):
        self.data = OrderedDict()

    def set(self, key, value):
        self.data[key.lower()] = (key, [value])

    def append(self, key, value):
        if key.lower() in self.data:
            self.data[key.lower()][1].append(value)
        else:
            self.set(key, value)

    def get(self, key, default=missing):
        try:
            return self[key]
        except KeyError:
            if default is missing:
                return []
            return default

    def __getitem__(self, key):
        self.data[key.lower()][1]

    def __delitem__(self, key):
        del self.data[key.lower()]

    def __contains__(self, key):
        return key.lower() in self.data

    def __setitem__(self, key, value):
        self.set(key, value)

    def __iter__(self):
        for key, values in self.data.itervalues():
            for value in values:
                yield key, value

    def items(self):
        return list(self)

    def update(self, items_iter):
        for name, value in items_iter:
            self.set(name, value)

    def __repr__(self):
        return repr(self.data)

class ResponseWriter(object):
    """Object providing an API to write out a HTTP response.

    :param handler: The RequestHandler being used.
    :param response: The Response associated with this writer.

    After each part of the response is written, the output is
    flushed unless response.explicit_flush is False, in which case
    the user must call .flush() explicitly."""
    def __init__(self, handler, response):
        self._wfile = handler.wfile
        self._response = response
        self._handler = handler
        self._headers_seen = set()
        self._headers_complete = False
        self.content_written = False

    def write_status(self, code, message=None):
        """Write out the status line of a response.

        :param code: The integer status code of the response.
        :param message: The message of the response. Defaults to the message commonly used
                        with the status code."""
        if message is None:
            if code in response_codes:
                message = response_codes[code][0]
            else:
                message = ''
        self.write("%s %d %s\r\n" %
                   (self._response.request.protocol_version, code, message))

    def write_header(self, name, value):
        """Write out a single header for the response.

        :param name: Name of the header field
        :param value: Value of the header field
        """
        self._headers_seen.add(name)
        self.write("%s: %s\r\n" % (name, value))
        if not self._response.explicit_flush:
            self.flush()

    def end_headers(self):
        """Finish writing headers and write the seperator.

        Unless add_required_headers on the response is False,
        this will also add HTTP-mandated headers that have not yet been supplied
        to the response headers"""

        if self._response.add_required_headers:
            for name, f in [("Server", self._handler.version_string),
                            ("Date", self._handler.date_time_string)]:
                if name.lower() not in self._headers_seen:
                    self.write_header(name, f())

        self.write("\r\n")
        if not self._response.explicit_flush:
            self.flush()
        self._headers_complete = True

    def write_content(self, data):
        """Write the body of the response."""
        self.write(self.encode(data))
        if not self._response.explicit_flush:
            self.flush()

    def write(self, data):
        """Write directly to the response, converting unicode to bytes
        according to response.encoding. Does not flush."""
        self.content_written = True
        self._wfile.write(self.encode(data))

    def encode(self, data):
        """Convert unicode to bytes according to response.encoding."""
        if isinstance(data, str):
            return data
        elif isinstance(data, unicode):
            return data.encode(self._response.encoding)
        else:
            raise ValueError

    def flush(self):
        """Flush the output."""
        self._wfile.flush()
