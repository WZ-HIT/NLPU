"""The image leak audit may exclude only byte-identical frozen baseline files."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import subprocess
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

from batch.image_recipes import BASELINE_NATIVE_AUDIT_SHA256, sha256_file


BENCH = Path(__file__).resolve().parents[2]
AUDIT = BENCH / "batch/images/3f3cb885eddf34fc6fd76a1acbeff601cbc6f506/record-deployment.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("sdd_image_audit_v2", AUDIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BaselineNativeContentTest(unittest.TestCase):
    def test_audit_script_is_pinned(self):
        self.assertEqual(sha256_file(AUDIT), BASELINE_NATIVE_AUDIT_SHA256)

    def test_exact_baseline_file_only(self):
        module = load_audit()
        original = b"public test with synthetic sensitive snippet\n"
        pinned = {"tests/example.py": {"size_bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()}}
        patterns = {"synthetic_gold": b"synthetic sensitive snippet"}

        def scan(files):
            def fake_run(*args, **kwargs):
                if args[:2] == ("docker", "create"):
                    return subprocess.CompletedProcess(args, 0, stdout=b"fake-container\n", stderr=b"")
                if args[:2] == ("docker", "export"):
                    destination = Path(args[args.index("--output") + 1])
                    with tarfile.open(destination, "w") as archive:
                        for name, data in files.items():
                            entry = tarfile.TarInfo(name)
                            entry.size = len(data)
                            archive.addfile(entry, io.BytesIO(data))
                return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

            with patch.object(module, "run", side_effect=fake_run):
                return module.scan_image_filesystem("fake-image", patterns, pinned)

        self.assertEqual(scan({"workspace/tests/example.py": original})["status"], "PASS")
        self.assertEqual(scan({"workspace/tests/example.py": original + b"changed\n"})["status"], "FAIL")
        self.assertEqual(scan({"workspace/other.py": original})["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
