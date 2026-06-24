from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RepoType(Enum):
    GREENFIELD = "greenfield"
    ACTIVE = "active"
    BROKEN = "broken"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class AuthMethod(Enum):
    NONE = "none"
    GITHUB_TOKEN = "github_token"
    GITLAB_TOKEN = "gitlab_token"
    BITBUCKET_TOKEN = "bitbucket_token"
    SSH_KEY = "ssh_key"


@dataclass
class RepoAuth:
    method: AuthMethod
    token: str | None = None
    ssh_key_path: str | None = None
    username: str | None = None


@dataclass
class RepoClassification:
    repo_type: RepoType
    primary_language: str
    secondary_languages: list[str]
    frameworks: list[str]
    has_tests: bool
    has_ci: bool
    has_docs: bool
    has_docker: bool
    entry_points: list[str]
    package_manager: str | None
    test_runner: str | None
    last_commit_days_ago: int | None
    open_issues_hint: list[str]
    confidence: float


@dataclass
class RepoContext:
    """Everything the agent loop needs about a repo before Turn 1."""
    url: str | None
    local_path: str
    classification: RepoClassification
    file_tree: str
    key_files: dict[str, str]
    git_log_summary: str
    test_results: dict | None
    build_errors: list[str]
    readme_content: str | None
    estimated_complexity: str

    def to_dict(self) -> dict:
        """JSON-serializable representation."""
        c = self.classification
        return {
            "url": self.url,
            "local_path": self.local_path,
            "classification": {
                "repo_type": c.repo_type.value,
                "primary_language": c.primary_language,
                "secondary_languages": c.secondary_languages,
                "frameworks": c.frameworks,
                "has_tests": c.has_tests,
                "has_ci": c.has_ci,
                "has_docs": c.has_docs,
                "has_docker": c.has_docker,
                "entry_points": c.entry_points,
                "package_manager": c.package_manager,
                "test_runner": c.test_runner,
                "last_commit_days_ago": c.last_commit_days_ago,
                "open_issues_hint": c.open_issues_hint,
                "confidence": c.confidence,
            },
            "file_tree": self.file_tree,
            "key_files": self.key_files,
            "git_log_summary": self.git_log_summary,
            "test_results": self.test_results,
            "build_errors": self.build_errors,
            "readme_content": self.readme_content,
            "estimated_complexity": self.estimated_complexity,
        }
