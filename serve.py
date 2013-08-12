#!/usr/bin/env python
import server
import handlers

routes = [("GET", ".*\.asis", handlers.as_is_handler),
          ("GET", "/.*", handlers.file_handler),
          ]

router = server.Router("/home/jgraham/develop/web-platform-tests/", routes)
httpd = server.WebTestHttpd(router)
httpd.start()
