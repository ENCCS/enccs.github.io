#!/usr/bin/env python3
"""Check the lesson cards in content/lessons for the mistakes that break the library.

  python3 scripts/check_cards.py           # card text and taxonomy
  python3 scripts/check_cards.py --links   # also open every link (slower)

Exits with 1 when a card needs fixing. Draft cards are checked too, but only for
problems that would matter once they are published. Only the standard library is used.
"""

import argparse
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "content" / "lessons"
LEVELS = {"difficulty": {"beginner", "intermediate", "advanced"}, "maturity": {"alpha", "beta", "stable"}}


def front_matter(path):
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+\n(.*)", path.read_text(), re.S)
    if not m:
        return None, ""
    return tomllib.loads(m.group(1)), m.group(2)


def opens(url):
    req = urllib.request.Request(url, headers={"User-Agent": "enccs-lesson-library-check"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--links", action="store_true", help="also check that every link opens")
    args = ap.parse_args()

    config = tomllib.loads((ROOT / "zola.toml").read_text())
    categories = set(config["extra"]["badge_colors"]["category"])
    problems, urls = [], {}

    for path in sorted(LESSONS.glob("*.md")):
        if path.name == "_index.md":
            continue
        name = path.stem
        fm, body = front_matter(path)
        if fm is None:
            problems.append(f"{name}: no +++ front matter")
            continue
        title, desc = fm.get("title", "").strip(), fm.get("description", "").strip()
        tax, url = fm.get("taxonomies", {}), fm.get("extra", {}).get("external_url", "")
        if not title:
            problems.append(f"{name}: no title")
        if not desc:
            problems.append(f"{name}: empty description")
        elif desc.lower() == title.lower():
            problems.append(f"{name}: description only repeats the title")
        for cat in tax.get("category", []):
            if cat not in categories:
                hint = " (use underscores)" if cat.replace("-", "_") in categories else ""
                problems.append(f"{name}: category {cat!r} is not in zola.toml{hint}")
        if not tax.get("category"):
            problems.append(f"{name}: no category")
        for kind, allowed in LEVELS.items():
            values = tax.get(kind, [])
            if not values:
                problems.append(f"{name}: no {kind}")
            for v in values:
                if v not in allowed:
                    problems.append(f"{name}: {kind} {v!r} is not one of {sorted(allowed)}")
        if not url:
            problems.append(f"{name}: no external_url")
        else:
            key = url.rstrip("/").lower()
            if key in urls:
                problems.append(f"{name}: same external_url as {urls[key]}")
            urls[key] = name
        for link in re.findall(r"\[lesson page\]\(([^)]*)\)", body):
            if link != url:
                problems.append(f"{name}: 'lesson page' link {link} differs from external_url {url}")
        if args.links:
            for link in sorted(set([url] + re.findall(r"\]\((https?://[^)\s]+)\)", body))):
                status = opens(link)
                if status != 200:
                    problems.append(f"{name}: {link} answered {status or 'nothing'}")

    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s) in {len(list(LESSONS.glob('*.md'))) - 1} card(s)", file=sys.stderr)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
