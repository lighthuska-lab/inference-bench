"""Exercise the documented checksum gate without downloads or model execution."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

VALIDATION = Path(__file__).resolve().parents[1] / "validation" / "llama-cpu"
ARCHIVE_DIGEST = "c8094268b6bf62f4998f0e45656fd9f5e2d4afb6b1cd0044d761db64be1dd47d"
MODEL_DIGEST = "2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d"

STUB = """#!/usr/bin/env python3
import os
import pathlib
import sys

events = pathlib.Path(os.environ['BENCH_TEST_EVENTS'])
if pathlib.Path(sys.argv[0]).name == 'curl':
    target = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
    data = b'archive fixture' if target.name == 'llama.tar.gz' else b'model fixture'
    target.write_bytes(data)
else:
    with events.open('a') as stream:
        stream.write('extract\\n')
    directory = pathlib.Path(sys.argv[sys.argv.index('-C') + 1]) / 'llama-b12110'
    directory.mkdir()
    server = directory / 'llama-server'
    server.write_text(
        "#!/bin/sh\\n"
        "printf 'launch\\\\n' >> \\\"$BENCH_TEST_EVENTS\\\"\\n"
    )
    server.chmod(0o755)
"""


@unittest.skipUnless(
    shutil.which("bash") and shutil.which("shasum"), "requires bash and shasum"
)
class ReproductionTests(unittest.TestCase):
    def run_recipe(self, *, bad_archive: bool = False, bad_model: bool = False):
        recipe = (VALIDATION / "README.md").read_text().split("```bash\n", 1)[1]
        recipe = recipe.split("```", 1)[0]
        archive = hashlib.sha256(b"archive fixture").hexdigest()
        model = hashlib.sha256(b"model fixture").hexdigest()
        recipe = recipe.replace(ARCHIVE_DIGEST, "0" * 64 if bad_archive else archive)
        recipe = recipe.replace(MODEL_DIGEST, "0" * 64 if bad_model else model)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for command in ("curl", "tar"):
                target = root / command
                target.write_text(STUB)
                target.chmod(0o755)
            events = root / "events"
            env = os.environ.copy()
            env["PATH"] = str(root) + os.pathsep + env.get("PATH", "")
            env["TMPDIR"] = str(root)
            env["BENCH_TEST_EVENTS"] = str(events)
            result = subprocess.run(
                ["bash"], input=recipe, capture_output=True, text=True, env=env
            )
            actions = events.read_text().splitlines() if events.exists() else []
        return result, actions

    def test_bad_archive_digest_prevents_extraction_and_launch(self):
        result, actions = self.run_recipe(bad_archive=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actions, [])

    def test_bad_model_digest_prevents_extraction_and_launch(self):
        result, actions = self.run_recipe(bad_model=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actions, [])

    def test_valid_digests_allow_extraction_and_launch(self):
        result, actions = self.run_recipe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["extract", "launch"])
