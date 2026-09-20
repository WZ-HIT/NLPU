"""Runtime guard: agent stages may inspect Python packages but may not run tests/installers."""

import importlib.abc
import os
import sys


class _ForbiddenAgentModule(importlib.abc.MetaPathFinder):
    blocked = {"pip", "pytest", "tox", "unittest"}

    def find_spec(self, fullname, path=None, target=None):
        if os.environ.get("SDD_AGENT_NO_TESTS") == "1" and fullname.split(".", 1)[0] in self.blocked:
            raise RuntimeError(f"agent-stage import forbidden by policy: {fullname}")
        return None


sys.meta_path.insert(0, _ForbiddenAgentModule())
