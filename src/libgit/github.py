"""
GitHub URLs and the GitHub API. No git here: see git.py for local backups.

A URL is either a single repository (`https://github.com/<owner>/<repo>`) or a whole account
(`https://github.com/<owner>/`). Accounts are listed with GitHub's REST API, using only the
standard library.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from defines import APP_NAME, EntryKind

logger = logging.getLogger(__name__)

WEB_URL = "https://github.com"
API_URL = "https://api.github.com"
ACCEPTED_DOMAINS = ("github.com", "www.github.com")
PAGE_SIZE = 100  # GitHub's maximum
REQUEST_TIMEOUT = 15  # seconds

# github.com paths that look like an account but aren't one
_RESERVED_OWNERS = {"orgs", "settings", "marketplace", "explore", "topics", "sponsors", "login", "about"}


class GitHubError(Exception):
    """Listing an account failed."""


@dataclass(frozen=True)
class GitHubTarget:
    """What a GitHub URL points at."""

    kind: EntryKind
    owner: str
    name: str = ""  # Empty for accounts

    @property
    def url(self) -> str:
        """Normalised URL."""
        return github_url(self.owner, self.name)


@dataclass(frozen=True)
class RemoteRepo:
    """One repository as listed by GitHub."""

    name: str
    fork: bool = False
    archived: bool = False
    description: str = ""


def github_url(owner: str, name: str = "") -> str:
    """URL of a repository or of an account when `name` is empty (with a trailing slash)."""
    return f"{WEB_URL}/{owner}/{name}"


def parse_github_url(url: str) -> Optional[GitHubTarget]:
    """Read a GitHub repository or account URL. Returns None when it is neither."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in ACCEPTED_DOMAINS:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts or parts[0].lower() in _RESERVED_OWNERS:
        return None

    owner = parts[0]
    if len(parts) == 1:
        return GitHubTarget(EntryKind.ACCOUNT, owner)

    name = parts[1].removesuffix(".git")
    return GitHubTarget(EntryKind.REPO, owner, name) if name else None


def list_account_repos(owner: str) -> list[RemoteRepo]:
    """
    Every public repository owned by a GitHub user or organisation, sorted by name.
    Raises GitHubError with a readable message on any failure.
    """
    repos: list[RemoteRepo] = []
    page = 1

    while True:
        url = f"{API_URL}/users/{quote(owner)}/repos?type=owner&sort=full_name&per_page={PAGE_SIZE}&page={page}"
        data = _get_json(url, owner)

        for item in data:
            repos.append(
                RemoteRepo(
                    name=item["name"],
                    fork=bool(item.get("fork")),
                    archived=bool(item.get("archived")),
                    description=item.get("description") or "",
                )
            )

        if len(data) < PAGE_SIZE:
            break
        page += 1

    logger.info(f"Listed {len(repos)} repositories for {owner}")
    return sorted(repos, key=lambda r: r.name.lower())


def _get_json(url: str, owner: str) -> list:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": APP_NAME,  # GitHub rejects requests without one
        },
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = json.load(response)
    except HTTPError as e:
        if e.code == 404:
            raise GitHubError(f"GitHub account '{owner}' was not found.") from e
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(e.headers.get("X-RateLimit-Reset", "0"))
            at = time.strftime("%H:%M", time.localtime(reset)) if reset else "later"
            raise GitHubError(f"GitHub's hourly request limit was reached. Try again after {at}.") from e
        raise GitHubError(f"GitHub returned an error (HTTP {e.code}).") from e
    except (URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise GitHubError(f"Couldn't reach GitHub: {reason}") from e
    except ValueError as e:
        raise GitHubError("GitHub sent a response that couldn't be read.") from e

    if not isinstance(data, list):
        raise GitHubError("GitHub sent an unexpected response.")
    return data
