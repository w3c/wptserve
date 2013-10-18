Handlers
========

Handlers are functions that have the general signature::

  handler(request, response)

It is expected that the handler will use information from
the request (e.g. the path) either to populate the response
object with the data to send, or to directly write to the
output stream via the ResponseWriter instance associated with
the request. If a handler writes to the output stream then the
server will not attempt additional writes i.e. the choice to write
directly in the handler or not is all-or-nothing.

By default there are three types of handler provided:

Python Handlers
---------------

A python handler executes raw python code (and is therefore unsafe
to run in an untrusted environment). It is expected that
`request.path` points to a file containing python code that provides
a function `main` with the signature::

  main(request, response)

This function may operate in (a combination of) two ways. It can
manipulate the response directly, including writing directly to
the socket. It can also simply return values which are then used to
populate the response. There are three possible sets of values
that may be returned::


  (status, headers, content)
  (headers, content)
  content

Here `status` is either a tuple (status code, message) or simply a
integer status code, `headers` is a list of (field name, value) pairs,
and `content` is a string or an iterable returning strings.

asis Handlers
-------------

This is used to serve files as literal byte streams including the
HTTP status line, headers and body. In the default configuration this
handler is invoked for all files with a .asis extension.

File Handlers
-------------

File handlers are used to serve static files. By default the content
type of these files is set by examining the file extension. However
this can be overridden, or additional headers supplied, by providing a
file with the same name as the file being served but an additional
.headers suffix i.e. test.html has its headers set from
test.html.headers. The format of the .headers file is plaintext, with
each line containing::

  Header-Name: header_value

In addition headers can be set for a whole directory of files (but not
subdirectories), using a file called `__dir__.headers`.
