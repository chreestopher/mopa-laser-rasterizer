#!/usr/bin/env python3
"""Fail production promotion unless the current release email is approved and complete."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from release_announcement_email import load_announcement, render_announcement


ROOT = Path(__file__).resolve().parents[1]
ANNOUNCEMENT = ROOT / "docs" / "releases" / "current-announcement.json"
CHANGELOG = ROOT / "docs" / "changelog.json"
PLACEHOLDER_MARKERS = (
    "[mailing address", "replace with", "placeholder", "todo", "tbd",
)


def validate() -> list[str]:
    errors: list[str] = []
    try:
        announcement = load_announcement(ANNOUNCEMENT)
        render_announcement(announcement)
    except Exception as error:
        return [str(error)]
    changelog = json.loads(CHANGELOG.read_text(encoding="utf-8"))
    releases = changelog.get("releases") or []
    if not releases:
        errors.append("the public changelog has no release entry")
        return errors
    latest = releases[0]
    for email_key, changelog_key in (
        ("release_id", "id"), ("release_version", "version"), ("release_date", "date"),
    ):
        if announcement[email_key] != latest.get(changelog_key):
            errors.append(f"announcement {email_key} does not match the newest changelog release")
    if announcement["status"] != "approved":
        errors.append("announcement status must be approved")
    if announcement.get("test_email_approved") is not True:
        errors.append("the owner must approve the rendered test email")
    if len(announcement["highlights"]) < 3:
        errors.append("announcement must include at least three release highlights")
    maintained_text = " ".join(
        str(announcement.get(key) or "")
        for key in ("subject", "preheader", "heading", "intro", "closing", "postal_address")
    ).casefold()
    for marker in PLACEHOLDER_MARKERS:
        if marker in maintained_text:
            errors.append(f"announcement still contains placeholder marker: {marker}")
    if announcement["cta_url"] != "https://mopa-laser-rasterizer.com/changelog":
        errors.append("announcement CTA must point to the production changelog")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Release announcement is not ready for production:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    announcement = load_announcement(ANNOUNCEMENT)
    rendered = render_announcement(announcement)
    print(f"Release announcement ready: {rendered.campaign_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
