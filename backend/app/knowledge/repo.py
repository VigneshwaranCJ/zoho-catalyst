"""Per-organization Git repository holding the published OKF bundle.

* `main` = what customers' answers are based on. Only APPROVED knowledge is ever
  committed, so Git history == publication history (who approved what, when).
* Drafts live in the database until approved (no branches, no merge conflicts).
* We use pygit2 (libgit2) so no `git` program is needed in the container.
* Commit authors use `<user-id>@users.csp.invalid`, not real emails, so the
  repository contains no personal data.

Callers must serialize writes per organization (we hold a PostgreSQL advisory
lock while publishing, see services/knowledge_publish.py).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pygit2

from app.core.config import get_settings

BRANCH = "refs/heads/main"
_SAFE_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9._-]*)*\.md$")


class RepoError(Exception):
    pass


def check_bundle_path(path: str) -> str:
    """Only lowercase, slash-separated `.md` paths inside the bundle."""
    if not _SAFE_PATH_RE.fullmatch(path) or ".." in PurePosixPath(path).parts:
        raise RepoError(f"Unsafe knowledge path: {path!r}")
    return path


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    message: str
    author: str
    at: datetime


class KnowledgeRepo:
    def __init__(self, organization_id: uuid.UUID, root: Path | None = None) -> None:
        base = (root or get_settings().knowledge_repos_dir).resolve()
        self.path = base / str(organization_id)
        self._repo: pygit2.Repository | None = None

    @property
    def repo(self) -> pygit2.Repository:
        if self._repo is None:
            if (self.path / ".git").exists():
                self._repo = pygit2.Repository(str(self.path))
            else:
                self.path.mkdir(parents=True, exist_ok=True)
                self._repo = pygit2.init_repository(str(self.path), initial_head="main")
        return self._repo

    def head_sha(self) -> str | None:
        try:
            return str(self.repo.revparse_single(BRANCH).id)
        except KeyError:
            return None

    def _tree(self, ref: str = BRANCH) -> pygit2.Tree | None:
        try:
            commit = self.repo.revparse_single(ref)
        except KeyError:
            return None
        return commit.peel(pygit2.Tree)

    def read(self, path: str, ref: str = BRANCH) -> str | None:
        tree = self._tree(ref)
        if tree is None:
            return None
        try:
            blob = self.repo[tree[check_bundle_path(path)].id]
        except KeyError:
            return None
        if not isinstance(blob, pygit2.Blob):
            return None
        return blob.data.decode("utf-8")

    def read_all(self, ref: str = BRANCH) -> dict[str, str]:
        tree = self._tree(ref)
        files: dict[str, str] = {}
        if tree is None:
            return files

        def walk(t: pygit2.Tree, prefix: str) -> None:
            for entry in t:
                name = f"{prefix}{entry.name}"
                obj = self.repo[entry.id]
                if isinstance(obj, pygit2.Tree):
                    walk(obj, f"{name}/")
                elif name.endswith(".md"):
                    files[name] = obj.data.decode("utf-8")  # type: ignore[attr-defined]

        walk(tree, "")
        return files

    def commit(
        self,
        changes: dict[str, str | None],
        *,
        message: str,
        author_id: str,
        author_name: str,
    ) -> str:
        """Apply {path: new content | None (delete)} as ONE commit on main."""
        if not changes:
            raise RepoError("Nothing to commit")
        repo = self.repo
        index = repo.index
        index.read()
        for path, content in changes.items():
            check_bundle_path(path)
            target = self.path / path
            if content is None:
                if target.exists():
                    target.unlink()
                try:
                    index.remove(path)
                except (KeyError, OSError):
                    pass
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
                index.add(path)
        index.write()
        tree_id = index.write_tree()
        now = int(datetime.now(UTC).timestamp())
        author = pygit2.Signature(author_name, f"{author_id}@users.csp.invalid", now, 0)
        committer = pygit2.Signature("CSP Knowledge Publisher", "publisher@csp.invalid", now, 0)
        parents = [] if self.head_sha() is None else [repo.revparse_single(BRANCH).id]
        commit_id = repo.create_commit(BRANCH, author, committer, message, tree_id, parents)
        return str(commit_id)

    def history(self, path: str | None = None, limit: int = 100) -> list[CommitInfo]:
        """Commits on main, newest first; with `path`, only commits that changed it."""
        if self.head_sha() is None:
            return []
        result: list[CommitInfo] = []
        # Topological order = newest first even when commits share a timestamp.
        walker = self.repo.walk(
            self.repo.revparse_single(BRANCH).id,
            pygit2.enums.SortMode.TOPOLOGICAL | pygit2.enums.SortMode.TIME,
        )
        for commit in walker:
            if path is not None:
                before = self._blob_id(commit.parents[0].tree, path) if commit.parents else None
                after = self._blob_id(commit.tree, path)
                if before == after:
                    continue
            result.append(
                CommitInfo(
                    sha=str(commit.id),
                    message=commit.message.strip(),
                    author=commit.author.name,
                    at=datetime.fromtimestamp(commit.author.time, UTC),
                )
            )
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _blob_id(tree: pygit2.Tree, path: str) -> str | None:
        try:
            return str(tree[path].id)
        except KeyError:
            return None
