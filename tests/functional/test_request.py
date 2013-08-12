import sys
import os
import unittest
import urllib2
import urlparse

here = os.path.split(__file__)[0]
doc_root = os.path.join(here, "docroot")
sys.path.insert(0, os.path.abspath(os.path.join(here, "..", "..")))
import server

class TestBasicRequest(unittest.TestCase):
    def setUp(self):
        self.server = server.WebTestHttpd(host="localhost", port=0,
                                          use_ssl=False, certificate=None,
                                          doc_root=doc_root)
        self.server.start(False)


    def tearDown(self):
        self.server.stop()

    def get_url(self, path, query=None):
        return urlparse.urlunsplit(("http", "localhost:%i" % self.server.port, path, query, None))

    def test_GET(self):
        print self.get_url("/document.txt")
        resp = urllib2.urlopen(self.get_url("/document.txt"))
        content = resp.read()
        self.assertEquals(200, resp.getcode())
        self.assertEquals("text/plain", resp.info()["Content-Type"])
        self.assertEquals(open(os.path.join(doc_root, "document.txt")).read(), content)

    
