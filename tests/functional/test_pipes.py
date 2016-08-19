import os
import unittest
import urllib2
import json
import time
import gzip as gzip_module
from cStringIO import StringIO

import wptserve
from base import TestUsingServer, doc_root

class TestStatus(TestUsingServer):
    def test_status(self):
        resp = self.request("/document.txt", query="pipe=status(202)")
        self.assertEquals(resp.getcode(), 202)

class TestHeader(TestUsingServer):
    def test_not_set(self):
        resp = self.request("/document.txt", query="pipe=header(X-TEST,PASS)")
        self.assertEquals(resp.info()["X-TEST"], "PASS")

    def test_set(self):
        resp = self.request("/document.txt", query="pipe=header(Content-Type,text/html)")
        self.assertEquals(resp.info()["Content-Type"], "text/html")

    def test_multiple(self):
        resp = self.request("/document.txt", query="pipe=header(X-Test,PASS)|header(Content-Type,text/html)")
        self.assertEquals(resp.info()["X-TEST"], "PASS")
        self.assertEquals(resp.info()["Content-Type"], "text/html")

    def test_multiple_same(self):
        resp = self.request("/document.txt", query="pipe=header(Content-Type,FAIL)|header(Content-Type,text/html)")
        self.assertEquals(resp.info()["Content-Type"], "text/html")

    def test_multiple_append(self):
        resp = self.request("/document.txt", query="pipe=header(X-Test,1)|header(X-Test,2,True)")
        self.assertEquals(resp.info()["X-Test"], "1, 2")

    def test_override_content_length(self):
        resp = self.request("/document.txt", query="pipe=header(Content-Length,882)")
        self.assertEquals(resp.info()["Content-Length"], "882")

class TestSlice(TestUsingServer):
    def test_both_bounds(self):
        resp = self.request("/document.txt", query="pipe=slice(1,10)")
        expected = open(os.path.join(doc_root, "document.txt"), "rb").read()
        self.assertEquals(resp.info()["Content-Length"], "9")
        self.assertEquals(resp.read(), expected[1:10])

    def test_no_upper(self):
        resp = self.request("/document.txt", query="pipe=slice(1)")
        expected = open(os.path.join(doc_root, "document.txt"), "rb").read()
        self.assertEquals(resp.info()["Content-Length"], str(len(expected) - 1))
        self.assertEquals(resp.read(), expected[1:])

    def test_no_lower(self):
        resp = self.request("/document.txt", query="pipe=slice(null,10)")
        expected = open(os.path.join(doc_root, "document.txt"), "rb").read()
        self.assertEquals(resp.info()["Content-Length"], "10")
        self.assertEquals(resp.read(), expected[:10])

class TestSub(TestUsingServer):
    def test_sub_config(self):
        resp = self.request("/sub.txt", query="pipe=sub")
        expected = "localhost localhost %i" % self.server.port
        self.assertEquals(resp.info()["Content-Length"], str(len(expected)))
        self.assertEquals(resp.read(), expected)

    def test_sub_headers(self):
        resp = self.request("/sub_headers.txt", query="pipe=sub", headers={"X-Test": "PASS"})
        expected = "PASS"
        self.assertEquals(resp.info()["Content-Length"], "4")
        self.assertEquals(resp.read(), expected)

    def test_sub_params(self):
        resp = self.request("/sub_params.txt", query="test=PASS&pipe=sub")
        expected = "PASS"
        self.assertEquals(resp.read(), expected)
        self.assertEquals(resp.info()["Content-Length"], "4")

class TestTrickle(TestUsingServer):
    def test_trickle(self):
        #Actually testing that the response trickles in is not that easy
        t0 = time.time()
        resp = self.request("/document.txt", query="pipe=trickle(1:d2:5:d1:r2)")
        t1 = time.time()
        expected = open(os.path.join(doc_root, "document.txt"), "rb").read()
        self.assertEquals(resp.info()["Content-Length"], str(len(expected)))
        self.assertEquals(resp.read(), expected)
        self.assertGreaterEqual(t1-t0, 6)

class TestGzip(TestUsingServer):
    def test_gzip(self):
        raw_content = open(os.path.join(doc_root, "document.txt"), "rb").read()
        out = StringIO()
        with gzip_module.GzipFile(fileobj=out, mode="w") as f:
            f.write(raw_content)
        compressed_content = out.getvalue()
        resp = self.request("/document.txt", query="pipe=gzip")
        actual_content = resp.read()
        self.assertEquals("gzip", resp.info()["Content-Encoding"])
        self.assertEquals(resp.info()["Content-Length"], str(len(compressed_content)))

if __name__ == '__main__':
    unittest.main()
