"""Configuration parsing uses temporary dummy keys, never the user's .env."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run import load_environment


class RunnerEnvironmentTests(unittest.TestCase):
    def test_precedence_and_literal_values(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            project = parent / "app"
            project.mkdir()
            (parent / ".env").write_text("OPENAI_API_KEY=workspace-dummy\n")
            with patch.dict(os.environ, {}, clear=True):
                load_environment(project)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "workspace-dummy")
            (project / ".env").write_text('OPENAI_API_KEY="literal-${HOME}-$(echo nope)"\n')
            with patch.dict(os.environ, {}, clear=True):
                load_environment(project)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "literal-${HOME}-$(echo nope)")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "exported-dummy"}, clear=True):
                load_environment(project)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "exported-dummy")

    def test_missing_files_are_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "app"
            project.mkdir()
            with patch.dict(os.environ, {}, clear=True):
                load_environment(project)
                self.assertNotIn("OPENAI_API_KEY", os.environ)
