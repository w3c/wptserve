import os
import logging
import pipes
import urlparse
import cgi
import traceback

from pipes import Pipeline
from constants import content_types

logger = logging.getLogger("wptserve")

class HTTPException(Exception):
    def __init__(self, code, message=""):
        self.code = code
        self.message = message

def filesystem_path(request):
    path = request.url_parts.path
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
        response.status = status_code
        response.headers.update(headers)
        response.content = data

        return response

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

class DirectoryHandler(object):
    def __call__(self, request, response):
        path = filesystem_path(request)

        assert os.path.isdir(path)

        response.headers = [("Content-Type", "text/html")]
        response.content = """<!doctype html>
<h1>%(path)s</h1>
<ul>
%(items)s
</li>
""" % {"path": cgi.escape(request.url_parts.path), "items": "\n".join(self.list_items(request, path))}

    def list_items(self, request, path):
        base_path = request.url_parts.path
        if not base_path.endswith("/"):
            base_path += "/"
        if base_path != "/":
            link = urlparse.urljoin(base_path, "..")
            yield """<li><a href="%(link)s">%(name)s</a>""" % {"link":link, "name": ".."}
        for item in sorted(os.listdir(path)):
            link = cgi.escape(base_path + item)
            yield """<li><a href="%(link)s">%(name)s</a>""" % {"link":link, "name": cgi.escape(item)}

class FileHandler(object):
    def __call__(self, request, response):
        path = filesystem_path(request)

        if os.path.isdir(path):
            return directory_handler(request, response)
        try:
            #This is probably racy with some other process trying to change the file
            file_size = os.stat(path).st_size
            response.headers.update(self.get_headers(path))
            if "Range" in request.headers:
                byte_ranges = RangeParser()(request.headers['Range'], file_size)
            else:
                byte_ranges = None
            data = self.get_data(response, path, byte_ranges)
            response.content = data
            query = urlparse.parse_qs(request.url_parts.query)
            if "pipe" in query:
                pipeline = Pipeline(query["pipe"][-1])
                response = pipeline(request, response)

            return response

        except OSError, IOError:
            raise HTTPException(404)

    def get_headers(self, path):
        rv = self.default_headers(path)
        rv.extend(self.load_headers(os.path.join(os.path.split(path)[0], "__dir__")))
        rv.extend(self.load_headers(path))
        return rv

    def load_headers(self, path):
        try:
            headers_file = open(path + ".headers")
        except IOError:
            return []
        else:
            return [tuple(item.strip() for item in line.split(":", 1))
                    for line in headers_file if line]


    def get_data(self, response, path, byte_ranges):
        with open(path) as f:
            if byte_ranges is None:
                return f.read()
            else:
                response.status = 206
                if len(byte_ranges) > 1:
                    parts_content_type, content = self.set_response_multipart(response, byte_ranges, f)
                    for byte_range in byte_ranges:
                        content.append_part(self.get_range_data(f, byte_range),
                                            parts_content_type,
                                            [("Content-Range", byte_range.header_value())])
                    return content
                else:
                    response.headers.set("Content-Range", byte_ranges[0].header_value())
                    return self.get_range_data(f, byte_ranges[0])

    def set_response_multipart(self, response, ranges, f):
        parts_content_type = response.headers.get("Content-Type")[-1]
        response.headers.set("Content-Type", "multipart/byteranges; boundary=%s" % content.boundary)
        content = MultipartContent()
        return parts_content_type, content

    def get_range_data(self, f, byte_range):
        lower, upper = byte_range.abs()
        f.seek(lower)
        return f.read(upper - lower)

    def default_headers(self, path):
        return [("Content-Type", guess_content_type(path))]

class RangeParser(object):
    def __call__(self, header, file_size):
        prefix = "bytes="
        if not header.startswith(prefix):
            raise HTTPException(400, message="Unrecognised range type %s" % (header,))

        parts = header[len(prefix):].split(",")
        ranges = []
        for item in parts:
            components = item.split("-")
            if len(components) != 2:
                raise HTTPException(400, "Bad range specifier %s" % (item))
            data = []
            for component in components:
                if component == "":
                    data.append(None)
                else:
                    try:
                        data.append(int(component))
                    except ValueError:
                        raise HTTPException(400, "Bad range specifier %s" % (item))
            ranges.append(Range(data[0], data[1], file_size))

        return self.coalesce_ranges(ranges, file_size)

    def coalesce_ranges(self, ranges, file_size):
        rv = []
        target = None
        for current in reversed(sorted(ranges)):
            if target is None:
                target = current
            else:
                new = target.coalesce(current)
                target = new[0]
                if len(new) > 1:
                    rv.append(new[1])
        rv.append(target)

        return rv[::-1]

class Range(object):
    def __init__(self, lower, upper, file_size):
        self.lower = lower
        self.upper = upper
        self.file_size = file_size


    def __repr__(self):
        return "<Range %s-%s>" % (self.lower, self.upper)

    def __lt__(self, other):
        return self.abs()[0] < other.abs()[0]

    def __gt__(self, other):
        return self.abs()[0] > other.abs()[0]

    def __eq__(self, other):
        self_lower, self_upper = self.abs()
        other_lower, other_upper = other.abs()

        return self_lower == other_lower and self_upper == other_upper

    def abs(self):
        if self.lower is None and self.upper is None:
            lower, upper = 0, self.file_size - 1
        elif self.lower is None:
            lower, upper = max(0, self.file_size - self.upper), self.file_size - 1
        elif self.upper is None:
            lower, upper = self.lower, self.file_size - 1
        else:
            lower, upper = self.lower, min(self.file_size - 1, self.upper)

        return lower, upper

    def coalesce(self, other):
        assert self.file_size == other.file_size
        self_lower, self_upper = self.abs()
        other_lower, other_upper = other.abs()

        if (self_upper < other_lower - 1 or self_lower - 1 > other_upper):
            return sorted([self, other])
        else:
            return [Range(min(self_lower, other_lower), max(self_upper, other_upper), self.file_size)]

    def header_value(self):
        lower, upper = self.abs()
        return "bytes %i-%i/%i" % (lower, upper, self.file_size)

directory_handler = DirectoryHandler()
file_handler = FileHandler()

def python_handler(request, response):
    path = filesystem_path(request)

    try:
        environ = {"__file__": path}
        execfile(path, environ, environ)
        if "main" in environ:
            try:
                rv = environ["main"](request, response)
            except:
                msg = traceback.format_exc()
                raise HTTPException(500, message=msg)
            if rv is not None:
                if isinstance(rv, tuple):
                    if len(rv) == 3:
                        status, headers, content = rv
                        response.status = status
                    elif len(rv) == 2:
                        headers, content = rv
                    else:
                        raise HTTPException(500)
                    response.headers.update(headers)
                else:
                    content = rv
                response.content = content
        else:
            raise HTTPException(500)
    except IOError:
        raise HTTPException(404)

def as_is_handler(request, response):
    path = filesystem_path(request)

    try:
        response.writer.write(open(path).read())
    except IOError:
        raise HTTPException(404)

class ErrorHandler(object):
    def __init__(self, status):
        self.status = status

    def __call__(self, request, response):
        response.set_error(self.status)
