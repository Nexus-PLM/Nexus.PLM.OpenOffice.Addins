# -*- coding: utf-8 -*-
"""The shipped Python must run on Python 2.7, because that is what Apache OpenOffice bundles.

This is the constraint that makes this repo different from every other one in the estate, and it
is invisible: modern Python is a syntax error inside OpenOffice, and the failure arrives as an
extension that installs cleanly and then does nothing — no toolbar, no menu, nothing logged where
anyone looks. So it is held here rather than discovered there.

**Measured** (Apache OpenOffice 4.1.16, its own `program\\python.exe`): Python **2.7.18**, 32-bit.
Three things had to change when the LibreOffice add-in was ported, and those three are what these
tests hold:

  1. an encoding declaration on every file — they all carry non-ASCII, and Python 2 refuses a
     source file with no ``coding:`` line, at import, with a SyntaxError naming a line that looks
     innocent;
  2. ``urllib.request``/``urllib.error``/``urllib.parse`` are Python 3 spellings — Python 2 has
     ``urllib2`` and ``urllib``;
  3. ``raise X(...) from error`` is Python 3 syntax.

The textual checks run everywhere, including CI, where no Python 2 exists. The real import check
runs only where OpenOffice is installed and **skips** otherwise — a green tick for an assurance
nobody has is worse than no test, which is the rule the .NET round-trip test already follows.

    python -m unittest discover -s tests/python
"""

import io
import os
import re
import subprocess
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SHIPPED = os.path.join(ROOT, "extension", "python")

#: Where Apache OpenOffice keeps the Python it runs extensions with, when it is installed.
OPENOFFICE_PYTHONS = (
    r"C:\Program Files (x86)\OpenOffice 4\program\python.exe",
    r"C:\Program Files\OpenOffice 4\program\python.exe",
)


def shipped_files():
    """Every .py this extension actually ships — the ones OpenOffice will import."""
    found = []
    for folder, _dirs, files in os.walk(SHIPPED):
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(folder, name))
    return found


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def without_strings_and_comments(source):
    """Source with string literals and comments blanked, so a rule about CODE is not tripped by
    a docstring that happens to describe the thing being forbidden — these very files do."""
    source = re.sub(r'"""".*?"""|\'\'\'.*?\'\'\'', '""', source, flags=re.DOTALL)
    source = re.sub(r'""".*?"""', '""', source, flags=re.DOTALL)
    source = re.sub(r"'''.*?'''", "''", source, flags=re.DOTALL)
    source = re.sub(r"#[^\n]*", "", source)
    return source


class EveryShippedFileDeclaresItsEncoding(unittest.TestCase):
    def test_all_of_them(self):
        # PEP 263: the declaration must be on line 1, or line 2 after a shebang. Anywhere else and
        # Python 2 does not see it.
        missing = []
        for path in shipped_files():
            head = read(path).split("\n")[:2]
            if not any(re.search(r"coding[:=]\s*([-\w.]+)", line) for line in head):
                missing.append(os.path.basename(path))
        self.assertEqual(
            [], missing,
            "Python 2 refuses a file with non-ASCII and no encoding line, at import")

    def test_there_are_files_to_check(self):
        # The walk finding nothing would make every test above pass while proving nothing.
        self.assertGreater(len(shipped_files()), 5)


class NoPython3OnlySyntax(unittest.TestCase):
    """Each of these is a SyntaxError inside OpenOffice, so none may reach the shipped code."""

    def offenders(self, pattern, why):
        bad = []
        for path in shipped_files():
            code = without_strings_and_comments(read(path))
            for number, line in enumerate(code.split("\n"), start=1):
                if re.search(pattern, line):
                    bad.append("%s:%d" % (os.path.basename(path), number))
        self.assertEqual([], bad, why)

    def test_no_f_strings(self):
        self.offenders(r"""\bf["']""", "an f-string is a SyntaxError on Python 2.7")

    def test_no_exception_chaining(self):
        self.offenders(r"\braise\b.*\bfrom\b|^\s*\)\s+from\s+\w+",
                       "`raise ... from` is Python 3 only; Python 2 has no chaining")

    def test_no_walrus(self):
        self.offenders(r"[^:=!<>]:=[^=]", "the walrus operator is Python 3.8+")

    def test_no_nonlocal(self):
        self.offenders(r"^\s*nonlocal\b", "`nonlocal` is Python 3 only")

    def test_no_annotated_signatures(self):
        self.offenders(r"^\s*def \w+\([^)]*\)\s*->", "return annotations are Python 3 only")

    def test_no_yield_from(self):
        self.offenders(r"\byield\s+from\b", "`yield from` is Python 3 only")


class TheUrllibDifferencesLiveInOnePlace(unittest.TestCase):
    """`_compat.py` is the only module allowed to know that the two Pythons differ.

    The first attempt at this port shimmed `client.py` alone and missed `document.py`, which
    imports `urllib.parse` too. Nothing caught it: the tests run on Python 3, where both spellings
    work, and it surfaced only when OpenOffice tried to register the extension - as
    `ImportError: No module named parse`, with nothing naming the file. Hence a rule about every
    shipped file, not about the one that was noticed.
    """

    def setUp(self):
        self.compat = read(os.path.join(SHIPPED, "pythonpath", "nexusplm", "_compat.py"))

    def test_the_shim_tries_python3_first_then_falls_back(self):
        self.assertIn("from urllib.request import", self.compat)
        self.assertIn("except ImportError:", self.compat)
        self.assertIn("from urllib2 import", self.compat)

    def test_it_carries_the_method_python2_would_otherwise_drop(self):
        # urllib2.Request has no `method`, so a PUT built with one is silently a GET - the service
        # would see a read and look like it had ignored the write.
        self.assertIn("def get_method(self)", self.compat)
        self.assertIn("def make_request(", self.compat)

    def test_it_makes_the_response_usable_with_with(self):
        # Python 2's urlopen result is not a context manager; `with urlopen(...)` is a TypeError
        # at the first call rather than at import.
        self.assertIn("contextlib.closing", self.compat)

    def test_no_other_shipped_file_spells_the_python3_names(self):
        offenders = []
        for path in shipped_files():
            if os.path.basename(path) == "_compat.py":
                continue
            code = without_strings_and_comments(read(path))
            for spelling in ("urllib.request.", "urllib.error.", "urllib.parse.",
                             "import urllib.request", "import urllib.error", "import urllib.parse"):
                if spelling in code:
                    offenders.append("%s: %s" % (os.path.basename(path), spelling))
        self.assertEqual([], offenders, "go through nexusplm._compat instead")


class NoPython3OnlyStandardLibrary(unittest.TestCase):
    """Calls that exist only on Python 3, and that fail in SILENCE here.

    Every one of these sits inside a bare ``except`` in this code base, so on Python 2.7 it raises,
    is swallowed, and the feature simply stops. They were all found by driving the add-in inside
    Apache OpenOffice, not by any test:

      * the three ``_log`` helpers stopped writing, so a command that plainly ran and raised a
        toast left no trace in any log;
      * ``state.py`` could neither read nor write the document-to-item map, which is what every
        item-scoped command keys off - so each of them would have refused with
        "This document is not registered in PLM";
      * ``os.replace`` is the nastiest of them: 2.7 has only ``os.rename``, which on Windows fails
        when the destination exists, so the FIRST save would have worked and every later one
        silently not.
    """

    def offending(self, pattern, why):
        bad = []
        for path in shipped_files():
            if os.path.basename(path) == "_compat.py":
                continue          # _compat is the one place allowed to know the difference
            code = without_strings_and_comments(read(path))
            for number, line in enumerate(code.splitlines(), start=1):
                if re.search(pattern, line):
                    bad.append("%s:%d" % (os.path.basename(path), number))
        self.assertEqual([], bad, why)

    def test_no_exist_ok(self):
        self.offending(r"exist_ok\s*=",
                       "os.makedirs has no exist_ok on 2.7 - use _compat.makedirs")

    def test_no_builtin_open_with_encoding(self):
        # io.open is the same function as Python 3's open and exists on 2.7.
        self.offending(r"(?<![.\w])open\([^)]*encoding\s*=",
                       "the builtin open has no encoding on 2.7 - use io.open")

    def test_no_os_replace(self):
        self.offending(r"os\.replace\(",
                       "os.replace arrived in 3.3 - use _compat.replace")

    def test_no_json_dump_into_a_text_stream(self):
        # json.dump writes str on 2.7, and an io.open text stream accepts only unicode.
        self.offending(r"json\.dump\(",
                       "json.dump into a text stream is a TypeError on 2.7 - use _compat.write_json")

    def test_compat_provides_all_of_them(self):
        compat = read(os.path.join(SHIPPED, "pythonpath", "nexusplm", "_compat.py"))
        for name in ("def makedirs(", "def replace(", "def write_json("):
            self.assertIn(name, compat)


class ItLogsAndRemembersUnderItsOwnName(unittest.TestCase):
    """The copy left both pointing at LibreOffice's files, so the two hosts would have shared
    them: one log interleaving two applications, and one document map each could overwrite."""

    def test_the_log_is_this_hosts_own(self):
        for name in ("nexus_commands.py", "nexusplm_controllers.py", "nexusplm_sidebar.py"):
            source = read(os.path.join(SHIPPED, name))
            self.assertIn("plmopenofficeaddin.log", source, name)
            self.assertNotIn("plmlibreofficeaddin.log", source, name)

    def test_the_document_map_is_this_hosts_own(self):
        source = read(os.path.join(SHIPPED, "pythonpath", "nexusplm", "state.py"))
        self.assertIn("openoffice-documents.json", source)
        self.assertNotIn("libreoffice-documents.json", source)


class TheHostSaysWhatItIs(unittest.TestCase):
    def test_it_calls_itself_openoffice(self):
        # The host name is declared, not inferred: it names the host in the New dialog's template
        # chip and in the service's log, and the service keeps no list of hosts. Left as
        # "LibreOffice" by the copy, every item created here would have claimed the wrong one.
        source = read(os.path.join(SHIPPED, "pythonpath", "nexusplm", "client.py"))
        self.assertIn('HOST_NAME = "OpenOffice"', source)


class OpenOfficesOwnPythonCanImportIt(unittest.TestCase):
    """The real check, where OpenOffice is installed: its interpreter imports every module.

    Skipped rather than failed where it is not, because CI has no Apache OpenOffice and a test
    that cannot run must not look like one that passed.
    """

    def setUp(self):
        self.python = next((p for p in OPENOFFICE_PYTHONS if os.path.exists(p)), None)
        if self.python is None:
            self.skipTest("Apache OpenOffice is not installed on this machine")

    def test_every_module_imports(self):
        pythonpath = os.path.abspath(os.path.join(SHIPPED, "pythonpath"))
        failures = []
        # document.py and the UNO-facing modules need a running office, so only the ones that do
        # not import `uno` are checked here. They are the ones carrying the logic.
        for module in ("odf", "navigator", "panel", "state", "identity", "client"):
            script = (
                "import sys\n"
                "sys.path.insert(0, r'%s')\n"
                "sys.dont_write_bytecode = True\n"
                "__import__('nexusplm.%s')\n" % (pythonpath, module)
            )
            done = subprocess.Popen([self.python, "-c", script],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _out, err = done.communicate()
            if done.returncode != 0:
                failures.append("%s: %s" % (module, err.decode("utf-8", "replace").strip()[-160:]))
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
