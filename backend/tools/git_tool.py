import subprocess
import os

class GitTool:
    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)

    def _run_git(self, args: list):
        """Helper to run git commands and return result."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise Exception(f"Git command failed: {e.stderr}")

    def ensure_clean_workspace(self):
        """Checks if there are uncommitted changes."""
        status = self._run_git(["status", "--porcelain"])
        if status:
            raise Exception("Workspace is not clean. Please commit or stash changes first.")
        return True

    def prepare_fix_branch(self, issue_name: str):
        """Creates and switches to a new ai-fix/ branch."""
        # Sanitize issue name for branch
        clean_name = "".join(c if c.isalnum() else "-" for c in issue_name).lower()[:30]
        branch_name = f"ai-fix/{clean_name}"
        
        # Try to delete if exists or just create
        try:
            self._run_git(["checkout", "-b", branch_name])
        except Exception:
            self._run_git(["checkout", branch_name])
            
        return branch_name

    def commit_and_tag(self, message: str, files: list[str] | None = None):
        """Commits changes — only stages specified files, or all if None."""
        if files:
            for f in files:
                self._run_git(["add", f])
        else:
            self._run_git(["add", "."])
        self._run_git(["commit", "-m", f"[AI-HEAL] {message}"])
        return True

    def rollback(self, branch_name: str, base_branch: str = "main"):
        """Rollback changes by switching back and deleting the failed branch."""
        try:
            self._run_git(["checkout", base_branch])
            self._run_git(["branch", "-D", branch_name])
        except Exception as e:
            print(f"Rollback failed: {e}")
