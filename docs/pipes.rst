Pipes
======

Pipe functions to use when serving files to alter the response.
These are invoked by adding a pipe= query parameter taking a
| separated list of pipe functions and parameters. For example
GET /foo?pipe=slice(1,200)|status(404).

:mod:`pipes`
-------------------------------------------------

.. automodule:: pipes
   :members:
