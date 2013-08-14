import handlers
routes = [("*", ".*\.py", handlers.python_handler),
          ("GET", ".*\.asis", handlers.as_is_handler),
          ("GET", "/.*", handlers.file_handler),
          ]
