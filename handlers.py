import os
import logging

from constants import content_types

logger = logging.getLogger(__name__)
logger.info("Logging started")

class HTTPException(Exception):
    def __init__(self, code):
        self.code = code

def filesystem_path(request):
    path = request.path
    if path.startswith("/"):
        path = path[1:]

    if ".." in path:
        raise HTTPException(500)

    return os.path.join(request.doc_root, path)

def guess_content_type(path):
    ext = os.path.splitext(path)[1].lstrip(".")
    if ext in content_types:
        return content_types[ext]
        
    return "application/octet-stream"

class MozBaseHandler(object):
    def __init__(self, handler):
        self.handler = handler

    def __call__(self, request, response):
        status_code, headers, data = self.handler(request, response)
        response.write_response_line(status_code)

        if hasattr(headers, "iteritems"):
            headers_iter = headers.iteritems()
        else:
            headers_iter = headers

        for key, value in headers_iter:
            response.write_header(key, value)
        response.end_headers()

        response.write_content(data)

#tobie has the idea that it should be possible to pass file responses through
#arbitary middleware, identified through the query string, something like
# GET /foo/bar?pipe=delay("10,1d,100,1d")|status(200)
#If this turns out to be useful, it needs to be supported somehow by making
#each piped thing a function that is composed and applied to the response 
#just before it is sent. For example consider
#GET /foo/bar?pipe=delay("10,1d,100,2d")|delay("1000,3d")
#this should send 100 bytes, wait for 1s, send 100 bytes wait for 2s, then 
#collect the first 1000 bytes from the previous step, wait for 3s and send the
#rest of the content. This seems quite useless but it would be quite surprising
#if it doesn't work

class FileHandler(object):
    def __call__(self, request, response):
        path = filesystem_path(request)

        try:
            data = open(path).read()
            headers = self.get_headers(path, data)
            return 200, headers, data
        except IOError:
            raise HTTPException(404)

    def get_headers(self, path, data):
        try:
            headers_file = open(path + ".headers")
        except IOError:
            return self.default_headers(path)
        else:
            headers = [tuple(line.split(":", 1)) for line in headers_file if line]
        return headers

    def default_headers(self, path):
        return [("Content-Type", guess_content_type(path))]


file_handler = MozBaseHandler(FileHandler())

def as_is_handler(request, response):
    path = filesystem_path(request)

    try:
        data = open(path)
        response.write_content(data.read())
    except IOError:
        raise HTTPException(404)
