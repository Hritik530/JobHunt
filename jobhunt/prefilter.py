"""Deterministic filter that runs BEFORE any LLM call.

This is the whole cost story: ~2000 raw jobs -> ~40 candidates for ~0 rupees,
so Claude only ever reads jobs that already passed title + location + freshness.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .fetch import Job

REMOTE_HINTS = ("remote", "anywhere", "work from home", "wfh", "distributed")
NO_EXPERIENCE_REQUIRED = re.compile(
    r"\bno\s+(?:(?:prior|previous|professional)\s+)*experience\s+"
    r"(?:is\s+)?(?:required|necessary)\b|"
    r"\bexperience\s+(?:is\s+)?not\s+required\b", re.I)


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _requires_experience(patterns: list[str], description: str) -> bool:
    description = NO_EXPERIENCE_REQUIRED.sub("", description)
    return _any_match(patterns, description)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(v) if fmt is None else datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def prefilter(jobs: list[Job], cfg: dict) -> list[Job]:
    inc = cfg.get("include_titles") or [r"."]
    exc = cfg.get("exclude_titles") or []
    locs = [l.lower() for l in (cfg.get("locations") or [])]
    remote_locs = [l.lower() for l in (cfg.get("remote_locations") or locs)]
    entry_patterns = cfg.get("entry_level_patterns") or []
    experience_patterns = cfg.get("exclude_experience_patterns") or []
    allow_remote = bool(cfg.get("allow_remote", True))
    max_age = cfg.get("max_age_days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age) if max_age else None

    kept, stats = [], {"title": 0, "seniority": 0, "location": 0,
                       "experience": 0, "age": 0}
    for j in jobs:
        if not _any_match(inc, j.title) or (exc and _any_match(exc, j.title)):
            stats["title"] += 1
            continue

        if entry_patterns and not _any_match(entry_patterns, f"{j.title}\n{j.description}"):
            stats["seniority"] += 1
            continue

        if locs:
            location = j.location.lower()
            is_remote = any(h in location for h in REMOTE_HINTS)
            allowed_locations = remote_locs if is_remote else locs
            if (is_remote and not allow_remote) or not any(
                    place in location for place in allowed_locations):
                stats["location"] += 1
                continue

        if experience_patterns and _requires_experience(experience_patterns, j.description):
            stats["experience"] += 1
            continue

        if cutoff:
            posted = _parse_date(j.posted_at)
            if posted and posted < cutoff:
                stats["age"] += 1
                continue

        kept.append(j)

        print(f"  prefilter: {len(jobs)} -> {len(kept)} "
            f"(dropped title={stats['title']} seniority={stats['seniority']} "
            f"location={stats['location']} "
            f"experience={stats['experience']} stale={stats['age']})")
    return kept
