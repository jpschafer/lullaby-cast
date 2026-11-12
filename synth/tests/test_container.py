"""Run from synth/:  python -m unittest discover -s tests"""

import logging
import tempfile
import unittest
from pathlib import Path

from lullaby.__main__ import load_mechanism
from lullaby.config import ConfigError
from lullaby.server import render_config
from supervisor import child_line, icecast_line

GOOD = {
    "ICECAST_HOSTNAME": "192.168.1.27",
    "ICECAST_SOURCE_PASSWORD": "abc123",
    "ICECAST_ADMIN_PASSWORD": "def-456",
}


class IcecastConfigTests(unittest.TestCase):
    def test_renders_values_and_defaults(self):
        xml = render_config(GOOD)
        self.assertIn("<hostname>192.168.1.27</hostname>", xml)
        self.assertIn("<source-password>abc123</source-password>", xml)
        self.assertIn("<port>8000</port>", xml)
        self.assertIn("<mount-name>/lullaby.mp3</mount-name>", xml)
        self.assertNotIn("${", xml)

    def test_lists_every_problem(self):
        env = dict(GOOD, ICECAST_HOSTNAME="", ICECAST_SOURCE_PASSWORD="change-me-source",
                   ICECAST_ADMIN_PASSWORD="a<b", ICECAST_PORT="80x0", ICECAST_MOUNT="lullaby.mp3")
        with self.assertRaises(ConfigError) as caught:
            render_config(env)
        message = str(caught.exception)
        for name in ("ICECAST_HOSTNAME", "ICECAST_SOURCE_PASSWORD", "ICECAST_ADMIN_PASSWORD",
                     "ICECAST_PORT", "ICECAST_MOUNT"):
            self.assertIn(name, message)


class LogLineTests(unittest.TestCase):
    def test_icecast_levels(self):
        self.assertEqual(icecast_line("[2026-11-12  21:04:05] EROR source/get_next_buffer oops"),
                         (logging.ERROR, "source/get_next_buffer oops"))
        self.assertEqual(icecast_line("plain text"), (None, "plain text"))

    def test_child_levels(self):
        self.assertEqual(child_line("WARNING lullaby: hm"), (logging.WARNING, "lullaby: hm"))
        self.assertEqual(child_line("  File x"), (None, "  File x"))


class MechanismFileTests(unittest.TestCase):
    def load(self, source):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "mechanism.py")
            path.write_text(source)
            with self.assertLogs("lullaby", level="INFO"):
                return load_mechanism(str(path))

    def test_loads_with_relative_imports(self):
        module = self.load("from .context import NoteEvent\n"
                           "def shape_note(note, ctx):\n    return NoteEvent(0, 60, 1)\n")
        self.assertEqual(module.shape_note(None, None).note, 60)

    def test_broken_file_falls_back(self):
        self.assertIsNone(self.load("def oops(:\n"))

    def test_unset_means_built_in(self):
        self.assertIsNone(load_mechanism(None))


if __name__ == "__main__":
    unittest.main()
