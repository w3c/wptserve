Pipes
======

Pipe are functions that may be used when serving files to alter parts
of the response. These are invoked by adding a pipe= query parameter
taking a | separated list of pipe functions and parameters. The pipe
functions are applied to the response from left to right. For example::

  GET /sample.txt?pipe=slice(1,200)|status(404).

This would serve bytes 1 to 199, inclusive, of foo.txt with the HTTP status
code 404.

:mod:`Interface <pipes>`
-------------------------------------------------

.. automodule:: wptserve.pipes
   :members:
