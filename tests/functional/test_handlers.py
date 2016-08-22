from __future__ import unicode_literals

import json
import os
import pytest
import six
import unittest
import uuid

from six.moves.urllib.error import HTTPError

import wptserve
from .base import TestUsingServer, check_multiple_headers, doc_root

class TestFileHandler(TestUsingServer):
    def test_GET(self):
        resp = self.request("/document.txt")
        self.assertEqual(200, resp.getcode())
        self.assertEqual("text/plain", resp.info()["Content-Type"])
        self.assertEqual(open(os.path.join(doc_root, "document.txt"), 'rb').read(), resp.read())

    def test_headers(self):
        resp = self.request("/with_headers.txt")
        self.assertEqual(200, resp.getcode())
        self.assertEqual("PASS", resp.info()["Custom-Header"])
        # This will fail if it isn't a valid uuid
        uuid.UUID(resp.info()["Another-Header"])
        self.assertEqual(resp.info()["Same-Value-Header"], resp.info()["Another-Header"])
        self.assertEqual(*check_multiple_headers(resp, "Double-Header", ["PA", "SS"]))


    def test_range(self):
        resp = self.request("/document.txt", headers={"Range":"bytes=10-19"})
        self.assertEqual(206, resp.getcode())
        data = resp.read()
        expected = open(os.path.join(doc_root, "document.txt"), 'rb').read()
        self.assertEqual(10, len(data))
        self.assertEqual("bytes 10-19/%i" % len(expected), resp.info()['Content-Range'])
        self.assertEqual("10", resp.info()['Content-Length'])
        self.assertEqual(expected[10:20], data)

    def test_range_no_end(self):
        resp = self.request("/document.txt", headers={"Range":"bytes=10-"})
        self.assertEqual(206, resp.getcode())
        data = resp.read()
        expected = open(os.path.join(doc_root, "document.txt"), 'rb').read()
        self.assertEqual(len(expected) - 10, len(data))
        self.assertEqual("bytes 10-%i/%i" % (len(expected) - 1, len(expected)), resp.info()['Content-Range'])
        self.assertEqual(expected[10:], data)

    def test_range_no_start(self):
        resp = self.request("/document.txt", headers={"Range":"bytes=-10"})
        self.assertEqual(206, resp.getcode())
        data = resp.read()
        expected = open(os.path.join(doc_root, "document.txt"), 'rb').read()
        self.assertEqual(10, len(data))
        self.assertEqual("bytes %i-%i/%i" % (len(expected) - 10, len(expected) - 1, len(expected)),
                         resp.info()['Content-Range'])
        self.assertEqual(expected[-10:], data)

    def test_multiple_ranges(self):
        resp = self.request("/document.txt", headers={"Range":"bytes=1-2,5-7,6-10"})
        self.assertEqual(206, resp.getcode())
        data = resp.read()
        expected = open(os.path.join(doc_root, "document.txt"), 'rb').read()

        content_type = resp.info()["Content-Type"]
        self.assertTrue(content_type.startswith("multipart/byteranges; boundary="))

        boundary = content_type.split("boundary=")[1].encode('utf-8')
        parts = data.split(b"--" + boundary)

        self.assertEqual(b"\r\n", parts[0])
        self.assertEqual(b"--", parts[-1])
        expected_parts = [(b"1-2", expected[1:3]), (b"5-10", expected[5:11])]
        for expected_part, part in zip(expected_parts, parts[1:-1]):
            header_string, body = part.split(b"\r\n\r\n")
            headers = dict(item.split(b": ", 1) for item in header_string.split(b"\r\n") if item.strip())
            self.assertEqual(headers[b"Content-Type"], b"text/plain")
            self.assertEqual(headers[b"Content-Range"], b"bytes %s/%i" % (expected_part[0], len(expected)))
            self.assertEqual(expected_part[1] + b"\r\n", body)

    def test_range_invalid(self):
        with self.assertRaises(HTTPError) as cm:
            self.request("/document.txt", headers={"Range":"bytes=11-10"})
        self.assertEqual(cm.exception.code, 416)

        expected = open(os.path.join(doc_root, "document.txt"), 'rb').read()
        with self.assertRaises(HTTPError) as cm:
            self.request("/document.txt", headers={"Range":"bytes=%i-%i" % (len(expected), len(expected) + 10)})
        self.assertEqual(cm.exception.code, 416)


class TestFunctionHandler(TestUsingServer):
    def test_string_rv(self):
        @wptserve.handlers.handler
        def handler(request, response):
            return "test data"

        route = ("GET", "/test/test_string_rv", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(200, resp.getcode())
        self.assertEqual("9", resp.info()["Content-Length"])
        self.assertEqual(b"test data", resp.read())

    def test_tuple_2_rv(self):
        @wptserve.handlers.handler
        def handler(request, response):
            return [("Content-Length", 4), ("test-header", "test-value")], "test data"

        route = ("GET", "/test/test_tuple_2_rv", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(200, resp.getcode())
        self.assertEqual("4", resp.info()["Content-Length"])
        self.assertEqual("test-value", resp.info()["test-header"])
        self.assertEqual(b"test", resp.read())

    def test_tuple_3_rv(self):
        @wptserve.handlers.handler
        def handler(request, response):
            return 202, [("test-header", "test-value")], "test data"

        route = ("GET", "/test/test_tuple_3_rv", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(202, resp.getcode())
        self.assertEqual("test-value", resp.info()["test-header"])
        self.assertEqual(b"test data", resp.read())

    def test_tuple_3_rv_1(self):
        @wptserve.handlers.handler
        def handler(request, response):
            return (202, "Some Status"), [("test-header", "test-value")], "test data"

        route = ("GET", "/test/test_tuple_3_rv_1", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(202, resp.getcode())
        self.assertEqual("Some Status", resp.msg)
        self.assertEqual("test-value", resp.info()["test-header"])
        self.assertEqual(b"test data", resp.read())

class TestJSONHandler(TestUsingServer):
    def test_json_0(self):
        @wptserve.handlers.json_handler
        def handler(request, response):
            return {"data": "test data"}

        route = ("GET", "/test/test_json_0", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(200, resp.getcode())
        self.assertEqual({"data": "test data"}, json.loads(resp.read().decode('utf-8')))

    def test_json_tuple_2(self):
        @wptserve.handlers.json_handler
        def handler(request, response):
            return [("Test-Header", "test-value")], {"data": "test data"}

        route = ("GET", "/test/test_json_tuple_2", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(200, resp.getcode())
        self.assertEqual("test-value", resp.info()["test-header"])
        self.assertEqual({"data": "test data"}, json.loads(resp.read().decode('utf-8')))

    def test_json_tuple_3(self):
        @wptserve.handlers.json_handler
        def handler(request, response):
            return (202, "Giraffe"), [("Test-Header", "test-value")], {"data": "test data"}

        route = ("GET", "/test/test_json_tuple_2", handler)
        self.server.router.register(*route)
        resp = self.request(route[1])
        self.assertEqual(202, resp.getcode())
        self.assertEqual("Giraffe", resp.msg)
        self.assertEqual("test-value", resp.info()["test-header"])
        self.assertEqual({"data": "test data"}, json.loads(resp.read().decode('utf-8')))

@pytest.mark.skipif(six.PY3, reason="Cannot use execfile from python 3")
class TestPythonHandler(TestUsingServer):
    def test_string(self):
        resp = self.request("/test_string.py")
        self.assertEqual(200, resp.getcode())
        self.assertEqual("text/plain", resp.info()["Content-Type"])
        self.assertEqual("PASS", resp.read())

    def test_tuple_2(self):
        resp = self.request("/test_tuple_2.py")
        self.assertEqual(200, resp.getcode())
        self.assertEqual("text/html", resp.info()["Content-Type"])
        self.assertEqual("PASS", resp.info()["X-Test"])
        self.assertEqual("PASS", resp.read())

    def test_tuple_3(self):
        resp = self.request("/test_tuple_3.py")
        self.assertEqual(202, resp.getcode())
        self.assertEqual("Giraffe", resp.msg)
        self.assertEqual("text/html", resp.info()["Content-Type"])
        self.assertEqual("PASS", resp.info()["X-Test"])
        self.assertEqual("PASS", resp.read())

class TestDirectoryHandler(TestUsingServer):
    def test_directory(self):
        resp = self.request("/")
        self.assertEqual(200, resp.getcode())
        self.assertEqual("text/html", resp.info()["Content-Type"])
        #Add a check that the response is actually sane

class TestAsIsHandler(TestUsingServer):
    def test_as_is(self):
        resp = self.request("/test.asis")
        self.assertEqual(202, resp.getcode())
        self.assertEqual("Giraffe", resp.msg)
        self.assertEqual("PASS", resp.info()["X-Test"])
        self.assertEqual(b"Content", resp.read())
        #Add a check that the response is actually sane

if __name__ == '__main__':
    unittest.main()
