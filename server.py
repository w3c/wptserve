import sys
import BaseHTTPServer
from SocketServer import ThreadingMixIn
import traceback
import socket
import threading
import re
import types
import logging

import handlers
from request import Request
from response import Response

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
                    response.set_error(e.code, e.message)
                except Exception as e:
                    if e.message:
                        err = e.message
                    else:
                        err = traceback.format_exc()
                    response.set_error(500, err)
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
