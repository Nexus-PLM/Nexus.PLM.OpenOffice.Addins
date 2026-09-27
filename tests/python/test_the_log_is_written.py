# -*- coding: utf-8 -*-
"""Every log line reaches the file, including the ones built only from literals.

`io.open` in text mode accepts ONLY unicode, on both Pythons. On 3 every `str` already is one; on
2.7 a plain `str` is bytes, and writing one raises TypeError. Every `_log` here sits inside a bare
`except`, so that TypeError was swallowed and the line simply never appeared.

What made it baffling rather than obvious is which lines survived. ``"%s" % something_unicode``
produces unicode, and the service's answers arrive as unicode because that is what Python 2's
``json`` returns — so a line built from a service value logged perfectly:

    Reload: opened 'C:\\Nexus\\Staging\\LTD-00000010-ODT.odt' as f38b633d-…, wrote 7 field(s)

while every line built from literals — "started", "done", and every failure — vanished:

    ConnectionStatus: started        <- never once appeared, in any session

A log that works for some lines and not others looks like a log that is working. It sent a long
hunt through the extension cache, the script provider and the deployed copy, when the whole cause
was the type of the argument.

    python -m unittest discover -s tests/python
"""

import io
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "extension", "python", "pythonpath"))

from nexusplm import _compat  # noqa: E402

SHIPPED = os.path.join(ROOT, "extension", "python")

#: The three modules that keep a log of their own.
LOGGERS = ("nexus_commands.py", "nexusplm_controllers.py", "nexusplm_sidebar.py")


def read(name):
    with io.open(os.path.join(SHIPPED, name), encoding="utf-8") as handle:
        return handle.read()


class CoercingToText(unittest.TestCase):
    def test_a_plain_str_becomes_text(self):
        got = _compat.as_text("ConnectionStatus: started")
        self.assertEqual(got, u"ConnectionStatus: started")
        self.assertIsInstance(got, type(u""))

    def test_text_is_left_alone(self):
        self.assertEqual(_compat.as_text(u"already text"), u"already text")

    def test_bytes_are_decoded_not_repr_d(self):
        # str(b"x") on Python 3 gives "b'x'", which would put b'...' in the log.
        self.assertEqual(_compat.as_text(b"bytes here"), u"bytes here")

    def test_undecodable_bytes_do_not_raise(self):
        # A path from the office can be anything; a log line must never be the thing that fails.
        self.assertIsInstance(_compat.as_text(b"\xff\xfe not utf-8"), type(u""))

    def test_something_that_is_not_a_string_at_all(self):
        self.assertEqual(_compat.as_text(7), u"7")


class EveryLogWritesText(unittest.TestCase):
    """Held on the source, because the failure is invisible at runtime: the line just is not there."""

    def test_every_logger_coerces_before_writing(self):
        for name in LOGGERS:
            source = read(name)
            writes = re.findall(r"handle\.write\(([^\n]*)\)", source)
            self.assertTrue(writes, "%s has no log write at all" % name)
            for call in writes:
                self.assertIn("as_text(", call,
                              "%s writes a value that may not be text: %s" % (name, call))

    def test_no_logger_writes_a_bare_str_literal_newline(self):
        # `+ "\\n"` is a str on 2.7 and poisons the whole concatenation even when the message
        # itself is unicode.
        for name in LOGGERS:
            source = read(name)
            for call in re.findall(r"handle\.write\(([^\n]*)\)", source):
                self.assertNotRegex(
                    call, r'(?<!u)"\\n"',
                    "%s appends a str newline; use u\"...\" - %s" % (name, call))

    def test_every_logger_imports_the_helper(self):
        for name in LOGGERS:
            self.assertIn("from nexusplm import _compat", read(name), name)


if __name__ == "__main__":
    unittest.main()
