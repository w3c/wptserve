import sys
from collections import defaultdict
import BaseHTTPServer
import traceback
import socket
import threading
from SocketServer import ThreadingMixIn
import re
import json
import types
import logging
import urlparse

import handlers
from constants import response_codes

logger = logging.getLogger(__name__)

class Router(object):
    """Object for matching handler functions to requests.

    :param doc_root: Absolute path of the filesystem location from
                     which to serve tests
    :param routes: Initial routes to add; a list of three item tuples
                   (method, path_regexp_string, handler_function), defined
                   as for register()
    """

    def __init__(self, doc_root, routes):
        self.doc_root = doc_root
        self.routes = []
        for route in reversed(routes):
            self.register(*route)

    def register(self, methods, path_regexp, handler):
        """Register a handler for a set of paths.

        :param methods: Set of methods this should match. "*" is a
                        special value indicating that all methods should
                        be matched.

        :param path_regexp: String that can be compiled into a regexp that
                            is matched against the request path.

        :param handler: Function that will be called to process matching
                        requests. This must take two parameters, the request
                        object and the response object.
        """
        if type(methods) in types.StringTypes:
            methods = [methods]
        for method in methods:
            self.routes.append((method, re.compile(path_regexp), handler))

    def get_handler(self, request):
        """Get a handler for a request or None if there is no handler.

        :param request: Request to get a handler for.
        :rtype: Callable or None
        """
        for method, regexp, handler in reversed(self.routes):
            if (request.method == method or
                method == "*" or
                (request.method == "GET" and method == "HEAD")):
                if regexp.match(request.path):
                    return handler
        logger.error("No handler found")
        return None

#TODO: support SSL
class WebTestServer(ThreadingMixIn, BaseHTTPServer.HTTPServer):
    """Server for non-SSL HTTP requests"""
    def __init__(self, router, *args, **kwargs):
        self.router = router
        if "config" in kwargs:
            Request.server_config = kwargs.pop("config")
        else:
            Request.server_config = {"host":args[0][0],
                                     "domains":{"": args[0][0]},
                                     "ports":{"http":[args[0][1]]}}
        #super doesn't work here because BaseHTTPServer.HTTPServer is old-style
        BaseHTTPServer.HTTPServer.__init__(self, *args, **kwargs)


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

    def __init__(self, handler):
        self.doc_root = handler.server.router.doc_root
        handler.parse_request()
        self.protocol_version = handler.protocol_version
        self.method = handler.command
        self.path = handler.path
        self.headers = handler.headers
        self.raw = handler.raw_requestline

        self.urlparts = urlparse.urlsplit(self.path)

        self._GET = None

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)

    @property
    def GET(self):
        if self._GET is None:
            self._GET = Params(urlparse.parse_qs(self.urlparts.query))
        return self._GET

class Params(dict):
    def __init__(self, data):
        for key, value in data.iteritems():
            if type(value) in types.StringTypes:
                value = [value]
            dict.__setitem__(self, key, value)

    def __setitem__(self, name, value):
        raise Exception

    def first(self, key):
        if key in self and self[key]:
            return self[key][0]
        raise KeyError

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
        self.headers = []
        self.content = []

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

    def write(self):
        self.write_status_headers()
        if self.request.method != "HEAD":
            for item in self.iter_content():
                self.writer.write_content(item)

    def set_error(self, code, message=""):
        data = json.dumps({"error":{"code":code,
                                    "message":message}})
        self.status = code
        self.headers = [("Content-Type", "text/json"),
                        ("Content-Length", len(data))]
        self.content = data


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


class WebTestRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """RequestHandler for WebTestHttpd"""

    def handle_one_request(self):
        try:
            self.close_connection = False
            request_is_valid = self.get_request_line()
            if self.close_connection:
                return

            request = Request(self)
            response = Response(self, request)

            if not request_is_valid:
                response.set_error(414)
                response.write()
                return

            handler = self.server.router.get_handler(request)
            if handler is None:
                response.set_error(404)
            else:
                try:
                    handler(request, response)
                except handlers.HTTPException as e:
                    response.set_error(e.code)
                except:
                    msg = traceback.format_exc()
                    sys.stderr.write(msg + "\n")
                    response.set_error(500, message=msg)
            if not response.writer.content_written:
                response.write()

        except socket.timeout, e:
            self.log_error("Request timed out: %r", e)
            self.close_connection = 1
            return

    def get_request_line(self):
        self.raw_requestline = self.rfile.readline(65537)
        if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                return False
        if not self.raw_requestline:
            self.close_connection = 1
        return True


class WebTestHttpd(object):
    """
    :param router: Router to use when matching URLs to handlers
    :param host: Host from which to serve (default: 127.0.0.1)
    :param port: Port from which to serve (default: 8000)
    :param server_cls: Class to use for the server (default depends on ssl vs non-ssl)
    :param handler_cls: Class to use for the RequestHandler
    :param use_ssl: Use a SSL server if no explicit server_cls is supplied

    HTTP server designed for testing scenarios.

    Takes a router class which provides one method get_handler which takes a Request
    and returns a handler function."
    """
    def __init__(self, router, host="127.0.0.1", port=8000,
                 server_cls=None, handler_cls=WebTestRequestHandler,
                 use_ssl=False):

        self.router = router

        self.host = host
        self.port = port

        if server_cls is None:
            if not use_ssl:
                server_cls = WebTestServer
            else:
                raise NotImplementedError

        self.httpd = server_cls(router, (self.host, self.port), handler_cls)

    def start(self, block=True):
        """Start the server.

        :param block: True to run the server on the current thread, blocking,
                      False to run on a seperate thread."""
        if block:
            self.httpd.serve_forever()
        else:
            self.server = threading.Thread(target=self.httpd.serve_forever)
            self.server.setDaemon(True) # don't hang on exit
            self.server.start()

    def stop(self):
        """
        Stops the server.

        If the server is not running, this method has no effect.
        """
        if self.httpd:
            try:
                self.httpd.shutdown()
            except AttributeError:
                pass
        self.httpd = None
