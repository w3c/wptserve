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

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)

class Response(object):
    def __init__(self, handler, request):
        self.request = request
        self._handler = handler
        self.wfile = handler.wfile

        self.add_required_headers = True
        self.explicit_flush = False
        self._headers_complete = False
        self._headers_seen = set()

    def send_error(self, code, message=None):
        self._handler.send_message(code, message)

    def write_response_line(self, code, message=None):
        if message is None:
            if code in response_codes:
                message = response_codes[code][0]
            else:
                message = ''
        self.wfile.write("%s %d %s\r\n" %
                         (self.request.protocol_version, code, message))

    def write_header(self, name, value):
        #Need to case convert
        self._headers_seen.add(name)
        self.wfile.write("%s: %s\r\n" % (name, value))
        if not self.explicit_flush:
            self.wfile.flush()

    def end_headers(self):
        if self.add_required_headers:
            for name, f in [("Server", self._handler.version_string),
                            ("Date", self._handler.date_time_string)]:
                if name.lower() not in self._headers_seen:
                    self.write_header(name, f())

        self.wfile.write("\r\n")
        if not self.explicit_flush:
            self.wfile.flush()
        self._headers_complete = True

    def write_content(self, data):
        self.wfile.write(data)
        if not self.explicit_flush:
            self.wfile.flush()

    def send_error(self, code, message=""):
        data = json.dumps({"error":{"code":code,
                                    "message":message}})
        self.write_response_line(code)
        self.write_header("Content-Type", "text/json")
        self.write_header("Content-Length", len(data))
        self.end_headers()
        self.write_content(data)

class WebTestRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = 1
                return
            request = Request(self)
            response = Response(self, request)

            handler = self.server.router.get_handler(request)
            try:
                handler(request, response)
            except handlers.HTTPException as e:
                print "got http exception %s for request %r" % (e.code, request)
                response.send_error(e.code)
            except:
                msg = traceback.format_exc()
                print "got exception\n %s"%msg
                response.send_error(500, message=msg)

        except socket.timeout, e:
            self.log_error("Request timed out: %r", e)
            self.close_connection = 1
            return

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
