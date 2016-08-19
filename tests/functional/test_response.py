import os
import unittest
import urllib2
import json
import time
from types import MethodType
import pytest

import wptserve
from base import TestUsingServer, doc_root

class TestResponse(TestUsingServer):
    def test_head_with_body(self):
        self.head_helper(True)

    def test_head_without_body(self):
        self.head_helper(False)

    def head_helper(self, send_body):
        body_string = "X-Body: body\r\n"

        def dont_end_headers(self):
            if self._response.add_required_headers:
                self.write_default_headers()

            self._headers_complete = True

        @wptserve.handlers.handler
        def handler(request, response):
            response.send_body_for_head_request = send_body

            #Set the content, but don't write it, so that the content-length
            #is calculated properly in write_default_headers().
            response.content = body_string

            response.writer.write_status(*response.status)
            response.writer.write_default_headers()
            response.writer.write_header("X-Test", "TEST")

            #Leave the headers section open so that we can append the body
            #as a header in the positive case.
            response.write_content()

            #Properly end the headers section so that the HTTP response is well-formed
            #for both positive and negative cases.
            response.writer.write("\r\n")
            response.writer.flush()

        route = ("HEAD", "/test/test_head", handler)
        self.server.router.register(*route)
        resp = self.request(route[1], method="HEAD")
        #According to the RFC, Content-Length for head requests should
        #be set to the entity-length that would have been sent if the request's
        #method had been GET instead of HEAD.
        #http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html
        self.assertEquals(str(len(body_string)), resp.info()['content-length'])
        self.assertEquals("TEST", resp.info()['x-test'])
        if send_body:
            self.assertEquals("body", resp.info()['x-body'])
        else:
            self.assertFalse('x-body' in resp.info())


if __name__ == '__main__':
    unittest.main()
