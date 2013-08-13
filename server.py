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
    def __init__(self, doc_root, routes):
        self.doc_root = doc_root
        self.routes = defaultdict(list)
        for route in reversed(routes):
            self.register(*route)

    def register(self, methods, path_regexp, handler):
        if type(methods) in types.StringTypes:
            methods = [methods]
        for method in methods:
            self.routes[method].append((re.compile(path_regexp), handler))

    def get_handler(self, request):
        routes = self.routes[request.method]
        for regexp, handler in reversed(routes):
            if regexp.match(request.path):
                return handler
        logger.error("No handler found")
        return None

#TODO: support SSL
class WebTestServer(BaseHTTPServer.HTTPServer, ThreadingMixIn):
    def __init__(self, router, *args, **kwargs):
        self.router = router
        #super doesn't work here because BaseHTTPServer.HTTPServer is old-style
        BaseHTTPServer.HTTPServer.__init__(self, *args, **kwargs)


class Request(object):
    def __init__(self, handler):
        self.doc_root = handler.server.router.doc_root
        handler.parse_request()
        self.protocol_version = handler.protocol_version
        self.method = handler.command
        self.path = handler.path
        self.headers = handler.headers
        self.raw = handler.raw_requestline

        self.urlparts = urlparse.urlsplit(self.path)

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)

    @property
    def query(self):
        return urlparse.parse_qsl(self.urlparts)

class Response(object):
    def __init__(self, handler, request):
        self.request = request
        self.encoding = "utf8"

        self.add_required_headers = True
        self.explicit_flush = False

        self.writer = ResponseWriter(handler, self)

        self._status = (200, None)
        self.headers = []
        self._content = []

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
            
    def write(self):
        self.writer.write_response_line(*self.status)
        for item in self.headers:
            self.writer.write_header(*item)
        self.writer.end_headers()
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
    def __init__(self, handler, response):
        self._wfile = handler.wfile
        self._response = response
        self._handler = handler
        self._headers_seen = set()
        self._headers_complete = False
        self.content_written = False

    def write_response_line(self, code, message=None):
        if message is None:
            if code in response_codes:
                message = response_codes[code][0]
            else:
                message = ''
        self.write("%s %d %s\r\n" %
                   (self._response.request.protocol_version, code, message))

    def write_header(self, name, value):
        #Need to case convert
        self._headers_seen.add(name)
        self.write("%s: %s\r\n" % (name, value))
        if not self._response.explicit_flush:
            self.flush()

    def end_headers(self):
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
        self.write(self.encode(data))
        if not self._response.explicit_flush:
            self.flush()

    def write(self, data):
        self.content_written = True
        self._wfile.write(self.encode(data))

    def encode(self, data):
        if isinstance(data, str):
            return data
        elif isinstance(data, unicode):
            return data.encode(self._response.encoding)
        else:
            raise ValueError

    def flush(self):
        self._wfile.flush()
    

class WebTestRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
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
            ### FIXME: There is no shutdown() method in Python 2.4...
            try:
                self.httpd.shutdown()
            except AttributeError:
                pass
        self.httpd = None
