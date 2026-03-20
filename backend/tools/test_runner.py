from __future__ import annotations

import subprocess
import os
from pathlib import Path


class TestRunner:
    def __init__(self, workspace: str = "."):
        self.workspace = os.path.abspath(workspace)

    def run_pytest(self, test_file_path: str):
        """
        Executes pytest on a specific file and captures output.
        Returns (success, output)
        """
        if test_file_path.startswith("-"):
            return False, f"Invalid test path (looks like a flag): {test_file_path}"
        resolved = Path(test_file_path).resolve()
        if not str(resolved).startswith(str(Path(self.workspace).resolve())):
            return False, f"Test path outside workspace: {test_file_path}"
        try:
            result = subprocess.run(
                ["pytest", str(resolved), "-v", "--tb=short"],
                cwd=self.workspace,
                capture_output=True,
                text=True,
            )
            success = result.returncode == 0
            output = result.stdout + "\n" + result.stderr
            return success, output
        except Exception as e:
            return False, str(e)
