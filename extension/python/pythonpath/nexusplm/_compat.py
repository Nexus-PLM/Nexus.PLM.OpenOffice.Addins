# -*- coding: utf-8 -*-
"""The handful of places Python 2.7 and Python 3 spell the same thing differently.

Apache OpenOffice 4.1 bundles **Python 2.7.18** — measured with its own ``program\\python.exe`` —
so this is the interpreter the add-in actually runs on. The module is written to work under both
anyway: the tests run on whatever Python the developer has, and a module that only worked under
2.7 could not be exercised in CI at all.

Everything that differs is gathered here rather than shimmed where it is used, because the first
attempt at this port shimmed ``client.py`` alone and missed ``document.py`` — which imports
``urllib.parse`` too, and which failed only when OpenOffice tried to register the extension, with
``ImportError: No module named parse`` and nothing pointing at the file.

Three differences, and the last two are the ones that bite quietly:

* the modules moved — ``urlparse`` and the quoting helpers live in one place on 2.7 and another
  on 3, and they did not move to the *same* place;
* ``urllib2.Request`` on 2.7 has **no ``method`` argument**. A request built with one is silently
  a GET, so a PUT or a DELETE would reach the service as a read and look like the service ignoring
  it;
* ``urlopen``'s result on 2.7 is **not a context manager**, so ``with urlopen(...) as response``
  is a TypeError at the moment of the first call, not at import.
"""

try:
    # ── Python 3: what LibreOffice bundles, and what the tests normally run on ───────────────
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote, unquote, urlencode, urlparse
    from urllib.request import Request as _Request
    from urllib.request import urlopen as _urlopen

    PYTHON2 = False

    def make_request(url, data=None, method=None):
        """A request that carries its HTTP method."""
        return _Request(url, data=data, method=method)

except ImportError:
    # ── Python 2.7: what Apache OpenOffice 4.1 bundles ──────────────────────────────────────
    from urllib import quote, unquote, urlencode           # noqa: F401  (same names, other home)
    from urllib2 import HTTPError, URLError                # noqa: F401
    from urllib2 import Request as _Request
    from urllib2 import urlopen as _urlopen
    from urlparse import urlparse                          # noqa: F401

    PYTHON2 = True

    class _RequestWithMethod(_Request):
        """``urllib2.Request`` with the method the caller asked for.

        Python 2 decides the method from whether there is a body — GET without, POST with — and
        offers no way to say otherwise except this. Without it every PUT and DELETE this add-in
        makes would arrive as a GET or a POST.
        """

        def __init__(self, url, data=None, method=None):
            _Request.__init__(self, url, data=data)
            self._method = method

        def get_method(self):
            if self._method:
                return self._method
            return _Request.get_method(self)

    def make_request(url, data=None, method=None):
        """A request that carries its HTTP method."""
        return _RequestWithMethod(url, data=data, method=method)


def urlopen(request, timeout=None):
    """``urlopen`` whose result can always be used with ``with``.

    Python 3's response is a context manager and Python 2's is not, so both are wrapped: the
    behaviour is then identical, and the calling code does not have to know which it got.
    """
    import contextlib
    return contextlib.closing(_urlopen(request, timeout=timeout))
