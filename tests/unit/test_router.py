import os
import unittest
import urllib2
import json
import time

import wptserve
from wptserve import router

class TestRouteCompiler(unittest.TestCase):
    def test_empty(self):
        regexp = router.compile_path_match("")
        self.assertEquals("^/$", regexp.pattern)
        self.assertTrue(regexp.match("/") is not None)
        self.assertTrue(regexp.match("/foo") is None)

    def test_group(self):
        regexp = router.compile_path_match("{abc}")
        self.assertEquals("^/(?P<abc>[^/]+)$", regexp.pattern)
        m = regexp.match("/foo")
        self.assertTrue(m is not None)
        self.assertEquals(m.groupdict(), {"abc": "foo"})


    def test_star(self):
        regexp = router.compile_path_match("*")
        self.assertEquals("^/(.*)$", regexp.pattern)
        m = regexp.match("/foo/bar")
        self.assertTrue(m is not None)
        self.assertEquals(m.groupdict(), {})
        self.assertEquals(m.groups(), ("foo/bar",))

    def test_literal(self):
        regexp = router.compile_path_match("foo*")
        self.assertEquals("^/foo(.*)$", regexp.pattern)
        m = regexp.match("/foobar/baz")
        self.assertTrue(m is not None)
        self.assertEquals(m.groupdict(), {})
        self.assertEquals(m.groups(), ("bar/baz",))

    def test_mixed(self):
        regexp = router.compile_path_match("{a}/f/*.py")
        self.assertEquals(r"^/(?P<a>[^/]+)/f/(.*)\.py$", regexp.pattern)
        m = regexp.match("/giraf/f/e.py")
        self.assertTrue(m is not None)
        self.assertEquals(m.groupdict(), {"a": "giraf"})
        self.assertEquals(m.groups(), ("giraf", "e",))


    def test_double_star(self):
        with self.assertRaises(ValueError) as cm:
            router.compile_path_match("*/*")

    def test_group_after_star(self):
        with self.assertRaises(ValueError) as cm:
            router.compile_path_match("*/{foo}")

if __name__ == '__main__':
    unittest.main()
