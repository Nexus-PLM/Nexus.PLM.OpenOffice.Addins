# -*- coding: utf-8 -*-
"""Nothing can write the staged file while the office still has it open.

Staged files are named by PART NUMBER, with no revision in the name, so the file a command is
about to rewrite is usually the document already on screen. An office keeps an exclusive lock on
what it has open — its own ``.~lock.<name>#`` sits in the staging folder beside the file — and so
every write to that path fails. Both of the failures that were found by driving the add-in are
this one cause wearing different clothes:

* **Reload** asked the service to download the vault's copy over the staged path while the
  document was still open. The download failed, and the user was told "The document could not be
  downloaded from the vault" — which sounds like a vault fault, and is not one. The vault had the
  file: the log shows it uploaded moments earlier and Reload had resolved the right key.
* **Revise** could not rewrite that path either, so the RewriteError fallback fired on *every*
  revise of an open document. The values still landed, so the outcome was right, but a warning
  that appears every single time is one people learn to ignore.

Word has always closed the document first and opened the replacement afterwards. These hold that
this add-in now does the same.

    python -m unittest discover -s tests/python
"""

import io
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "extension", "python", "pythonpath"))

from nexusplm import document as doc  # noqa: E402

SHIPPED = os.path.join(ROOT, "extension", "python")


def read(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


# ── a stand-in office ────────────────────────────────────────────────────────

class FakeComponent(object):
    def __init__(self, url, modified=False):
        self.URL = url
        self._modified = modified
        self.stored = False
        self.closed = False

    def isModified(self):
        return self._modified

    def store(self):
        self.stored = True
        self._modified = False

    def setModified(self, flag):
        self._modified = flag

    def close(self, _deliver):
        self.closed = True


class FakeEnumeration(object):
    def __init__(self, items):
        self._items = list(items)

    def hasMoreElements(self):
        return bool(self._items)

    def nextElement(self):
        return self._items.pop(0)


class FakeDesktop(object):
    def __init__(self, components):
        self._components = components

    def getComponents(self):
        outer = self

        class Holder(object):
            def createEnumeration(self):
                return FakeEnumeration(outer._components)
        return Holder()


class FakeContext(object):
    """Only ever handed to the patched ``desktop()``, so it carries nothing."""


class ReleasingTheOpenDocument(unittest.TestCase):
    def setUp(self):
        self.real_desktop = doc.desktop
        self.path = r"C:\Nexus\Staging\LTD-00000010-ODT.odt"
        self.url = doc.path_to_url(self.path)

    def tearDown(self):
        doc.desktop = self.real_desktop

    def office_holding(self, *components):
        doc.desktop = lambda _context: FakeDesktop(list(components))

    def test_it_closes_the_document_that_has_that_file(self):
        held = FakeComponent(self.url)
        self.office_holding(held)

        self.assertTrue(doc.release(FakeContext(), self.path))
        self.assertTrue(held.closed)

    def test_it_leaves_every_other_document_alone(self):
        other = FakeComponent(doc.path_to_url(r"C:\Nexus\Staging\SOMETHING-ELSE.odt"))
        self.office_holding(other)

        self.assertFalse(doc.release(FakeContext(), self.path))
        self.assertFalse(other.closed, "a different document must not be closed")

    def test_it_matches_on_the_file_not_the_title(self):
        # Two revisions of one item share a title, and a staged file is named by part number, so
        # the title identifies nothing. The URL is the only thing that does.
        held = FakeComponent(self.url)
        self.office_holding(held)

        doc.release(FakeContext(), self.path.lower())
        self.assertTrue(held.closed, "the same file spelled differently is the same file")

    def test_nothing_open_is_not_a_failure(self):
        self.office_holding()
        self.assertFalse(doc.release(FakeContext(), self.path))

    def test_it_can_save_first_when_the_caller_asks(self):
        # Revise: the service has just taken a copy of this file for the new revision, so the
        # user's edits are worth the extra write before it goes.
        held = FakeComponent(self.url, modified=True)
        self.office_holding(held)

        doc.release(FakeContext(), self.path, save_first=True)

        self.assertTrue(held.stored, "unsaved edits were not saved before closing")
        self.assertTrue(held.closed)

    def test_it_discards_when_the_caller_does_not_ask(self):
        # Reload: the user has already been asked and said the edits may go.
        held = FakeComponent(self.url, modified=True)
        self.office_holding(held)

        doc.release(FakeContext(), self.path)

        self.assertFalse(held.stored, "Reload must not resurrect edits the user discarded")
        self.assertTrue(held.closed)

    def test_an_office_that_cannot_be_asked_is_not_an_error(self):
        def broken(_context):
            raise RuntimeError("no desktop")
        doc.desktop = broken

        self.assertFalse(doc.release(FakeContext(), self.path))


class TheCommandsReleaseBeforeTheFileIsWritten(unittest.TestCase):
    """The order is the whole fix, so it is held on the source: released FIRST, then written."""

    def setUp(self):
        self.source = read(SHIPPED, "nexus_commands.py")

    def body_of(self, name):
        start = self.source.index("def %s(" % name)
        end = self.source.find("\n@_command", start)
        return self.source[start:end if end > 0 else len(self.source)]

    def test_reload_closes_the_document_before_asking_the_service(self):
        body = self.body_of("reload_document")
        release = body.index("doc.release(")
        download = body.index("client.reload_document(")
        self.assertLess(release, download,
                        "the service downloads over this very file; an open file is locked")

    def test_reload_asks_the_user_before_closing_anything(self):
        # A replacement refused after the close would leave them with neither copy.
        body = self.body_of("reload_document")
        self.assertLess(body.index("_message_box("), body.index("doc.release("))

    def test_reload_does_not_save_the_edits_the_user_just_discarded(self):
        body = self.body_of("reload_document")
        call = body[body.index("doc.release("):]
        self.assertNotIn("save_first=True", call.split(")")[0])

    def test_opening_a_staged_file_releases_it_first(self):
        body = self.body_of("_open_with_values")
        release = body.index("doc.release(")
        prepare = body.index("doc.open_staged(")
        self.assertLess(release, prepare,
                        "make_document cannot rewrite a file the office holds open")

    def test_opening_a_staged_file_keeps_the_users_edits(self):
        body = self.body_of("_open_with_values")
        call = body[body.index("doc.release("):]
        self.assertIn("save_first=True", call.split(")")[0],
                      "Revise reaches here with the user's unsaved work on screen")


if __name__ == "__main__":
    unittest.main()
