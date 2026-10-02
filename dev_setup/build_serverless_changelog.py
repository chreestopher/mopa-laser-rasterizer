#!/usr/bin/env python3
"""Render the cumulative release changelog as a static serverless page."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "docs" / "changelog.json"
DEFAULT_TEMPLATE = REPO_ROOT / "templates" / "changelog.html"
RELEASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def load_releases(source_path: Path) -> list[dict]:
    """Load and validate release data without silently discarding history."""
    try:
        document = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid changelog JSON: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("changelog schema_version must be 1")
    releases = document.get("releases")
    if not isinstance(releases, list) or not releases:
        raise ValueError("changelog releases must be a non-empty list")

    normalized = []
    seen_ids: set[str] = set()
    seen_versions: set[str] = set()
    previous_date: date | None = None
    for index, raw_release in enumerate(releases):
        field = f"releases[{index}]"
        if not isinstance(raw_release, dict):
            raise ValueError(f"{field} must be an object")
        release_id = _required_text(raw_release.get("id"), f"{field}.id")
        if not RELEASE_ID.fullmatch(release_id):
            raise ValueError(f"{field}.id must be a lowercase, URL-safe slug")
        version = _required_text(raw_release.get("version"), f"{field}.version")
        try:
            released_on = date.fromisoformat(_required_text(raw_release.get("date"), f"{field}.date"))
        except ValueError as error:
            raise ValueError(f"{field}.date must use YYYY-MM-DD") from error
        if release_id in seen_ids or version in seen_versions:
            raise ValueError(f"{field} duplicates a release id or version")
        if previous_date is not None and released_on > previous_date:
            raise ValueError("releases must be newest-first; prepend new releases")

        groups = raw_release.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"{field}.groups must be a non-empty list")
        normalized_groups = []
        for group_index, raw_group in enumerate(groups):
            group_field = f"{field}.groups[{group_index}]"
            if not isinstance(raw_group, dict):
                raise ValueError(f"{group_field} must be an object")
            items = raw_group.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError(f"{group_field}.items must be a non-empty list")
            normalized_groups.append({
                "title": _required_text(raw_group.get("title"), f"{group_field}.title"),
                "items": [_required_text(item, f"{group_field}.items") for item in items],
            })

        links = raw_release.get("links", [])
        if not isinstance(links, list):
            raise ValueError(f"{field}.links must be a list")
        normalized_links = []
        for link_index, raw_link in enumerate(links):
            link_field = f"{field}.links[{link_index}]"
            if not isinstance(raw_link, dict):
                raise ValueError(f"{link_field} must be an object")
            href = _required_text(raw_link.get("href"), f"{link_field}.href")
            parsed = urlparse(href)
            if not (href.startswith("/") or (parsed.scheme == "https" and parsed.netloc)):
                raise ValueError(f"{link_field}.href must be a root-relative or HTTPS URL")
            normalized_links.append({
                "label": _required_text(raw_link.get("label"), f"{link_field}.label"),
                "href": href,
                "external": parsed.scheme == "https",
            })

        normalized.append({
            "id": release_id,
            "version": version,
            "date": released_on.isoformat(),
            "display_date": (
                f"{MONTH_NAMES[released_on.month - 1]} {released_on.day}, {released_on.year}"
            ),
            "title": _required_text(raw_release.get("title"), f"{field}.title"),
            "summary": _required_text(raw_release.get("summary"), f"{field}.summary"),
            "groups": normalized_groups,
            "links": normalized_links,
        })
        seen_ids.add(release_id)
        seen_versions.add(version)
        previous_date = released_on
    return normalized


def render_changelog(source_path: Path, template_path: Path, public_url: str) -> str:
    releases = load_releases(source_path)
    environment = Environment(
        loader=FileSystemLoader(template_path.parent),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    template = environment.get_template(template_path.name)
    base_url = public_url.rstrip("/") + "/"
    return template.render(
        releases=releases,
        canonical=urljoin(base_url, "changelog"),
        release_count=len(releases),
    )


def main(arguments: list[str]) -> int:
    if len(arguments) not in (2, 4):
        print(
            "usage: build_serverless_changelog.py OUTPUT PUBLIC_URL "
            "[SOURCE_JSON TEMPLATE_HTML]",
            file=sys.stderr,
        )
        return 2
    output_path = Path(arguments[0])
    public_url = arguments[1]
    source_path = Path(arguments[2]) if len(arguments) == 4 else DEFAULT_SOURCE
    template_path = Path(arguments[3]) if len(arguments) == 4 else DEFAULT_TEMPLATE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_changelog(source_path, template_path, public_url), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
