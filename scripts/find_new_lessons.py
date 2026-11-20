#!/usr/bin/env python3
"""Find ENCCS lesson sites that are not yet in the Lesson Library.

Lists the public, non-archived repositories of the ENCCS GitHub organisation that
publish a GitHub Pages site, leaves out the ones the library already links to and
the ones in scripts/lesson_ignore.txt, and reads each site's own title and intro.

  python3 scripts/find_new_lessons.py                 # report only
  python3 scripts/find_new_lessons.py --json          # report as JSON
  python3 scripts/find_new_lessons.py --write-drafts  # also write draft cards

Draft cards get `draft = true`, so Zola leaves them out of the site until someone
has checked the text, categories, difficulty and maturity and removed that line.
Only the standard library is used. GITHUB_TOKEN is used when set (higher API limit).
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "content" / "lessons"
IGNORE = ROOT / "scripts" / "lesson_ignore.txt"
UA = "enccs-lesson-library-finder"

# Keyword hints for a first category guess; a person confirms it before publishing.
CATEGORY_HINTS = [
    ("quantum_computing", r"quantum|qas\d|qiskit|hpc-?qc|qpu"),
    ("gpu_programming", r"\bgpu|cuda|\bhip\b|openacc|rocm|sycl|offload"),
    ("ai", r"\bai\b|deep.?learning|machine.?learning|\bnlp\b|\bllm|pytorch|tensorflow|neural"),
    ("electronic_structure_calculations", r"\bdft\b|vasp|quantum espresso|jdftx|siesta|yambo|electronic.structure|veloxchem"),
    ("molecular_dynamics", r"molecular.dynamics|gromacs|lammps|\bmlip|interatomic"),
    ("computational_fluid_dynamics", r"\bcfd\b|openfoam|nek5000|fluid"),
    ("cpu_programming", r"\bmpi\b|openmp|vectori[sz]"),
    ("programming_tools", r"cmake|\bgit\b|testing|containers?|software.install"),
    ("high_level_language_programming", r"python|julia|data.analytics|hpda|pandas"),
    ("basics_of_hpc", r"\bhpc\b|supercomput|lumi|unix|shell|bootcamp"),
]


def get(url, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if accept:
        req.add_header("Accept", accept)
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, "", e.headers
    except (urllib.error.URLError, TimeoutError):
        return 0, "", {}


def org_repos(org):
    repos, page = [], 1
    while True:
        status, body, _ = get(
            f"https://api.github.com/orgs/{org}/repos?type=public&per_page=100&page={page}",
            "application/vnd.github+json",
        )
        if status != 200:
            sys.exit(f"GitHub API answered {status} for the {org} repositories")
        batch = json.loads(body)
        repos += batch
        if len(batch) < 100:
            return repos
        page += 1


def library_slugs():
    """Repository names the library already links to, in lower case."""
    slugs = set()
    for card in LESSONS.glob("*.md"):
        m = re.search(r'external_url\s*=\s*"https://enccs\.github\.io/([^/"]+)', card.read_text())
        if m:
            slugs.add(m.group(1).lower())
    return slugs


def ignored():
    if not IGNORE.exists():
        return set()
    names = set()
    for line in IGNORE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line.lower())
    return names


def text(fragment):
    plain = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())
    # Text copied from other sites must not carry template syntax into the cards
    return re.sub(r"\{[{%#]|[}%#]\}", "", plain)


def read_site(url):
    status, body, _ = get(url)
    info = {"status": status, "title": "", "intro": "", "generator": ""}
    if status != 200:
        return info
    m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    if m:
        # Sphinx titles read "Page - Project documentation"; keep the first part
        info["title"] = re.split(r"\s+(?:&#8212;|—|\|)\s+", text(m.group(1)))[0].strip()
    m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', body, re.I)
    if m:
        info["intro"] = text(m.group(1))
    else:
        main = re.search(r'<(?:main|article|div[^>]+role="main")[\s\S]*', body, re.I)
        for p in re.findall(r"<p[^>]*>([\s\S]*?)</p>", main.group(0) if main else body):
            p = text(p)
            if len(p) > 60:
                info["intro"] = p
                break
    if "sphinx_lesson" in body or "sphinx-lesson" in body:
        info["generator"] = "sphinx-lesson"
    elif "Sphinx" in body:
        info["generator"] = "sphinx"
    elif "jupyter-book" in body or "Jupyter Book" in body:
        info["generator"] = "jupyter-book"
    return info


def guess_categories(*parts):
    hay = " ".join(p for p in parts if p).lower()
    found = [cat for cat, pattern in CATEGORY_HINTS if re.search(pattern, hay)]
    return found[:2] or ["basics_of_hpc"]


def short(sentence_text, limit=300):
    if len(sentence_text) <= limit:
        return sentence_text
    cut = sentence_text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "..."


def toml_string(value):
    return json.dumps(value, ensure_ascii=False)


def write_draft(c):
    path = LESSONS / f"{c['slug']}.md"
    if path.exists():
        return False
    cats = ", ".join(toml_string(x) for x in c["category"])
    path.write_text(
        f"""+++
title = {toml_string(c['title'])}
description = {toml_string(c['description'])}
# Found by scripts/find_new_lessons.py. Check the text against the lesson, set the
# category, difficulty (beginner, intermediate, advanced) and maturity (stable once its
# event has been held, else beta or alpha), then delete the draft line to publish the card.
draft = true

[taxonomies]
difficulty = ["beginner"]
maturity = ["beta"]
category = [{cats}]

[extra]
tags = []
external_url = {toml_string(c['url'])}
+++

## Overview

{c['description']}

## Learn More

Visit the [lesson page]({c['url']}) to access the full content.
"""
    )
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--org", default="ENCCS")
    ap.add_argument("--json", action="store_true", help="print the candidates as JSON")
    ap.add_argument("--write-drafts", action="store_true", help="write draft cards to content/lessons")
    args = ap.parse_args()

    known, skip = library_slugs(), ignored()
    candidates = []
    for r in org_repos(args.org):
        name = r["name"]
        # Forks are kept: several ENCCS lessons start as forks (e.g. of Carpentries lessons)
        if not r.get("has_pages") or r.get("archived"):
            continue
        if name.lower() in known or name.lower() in skip:
            continue
        url = f"https://enccs.github.io/{name}/"
        site = read_site(url)
        title = site["title"] or name.replace("-", " ").replace("_", " ")
        description = short(site["intro"] or (r.get("description") or ""))
        candidates.append({
            "repo": name,
            "slug": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "url": url,
            "site_status": site["status"],
            "generator": site["generator"],
            "last_push": (r.get("pushed_at") or "")[:10],
            "fork": bool(r.get("fork")),
            "repo_description": r.get("description") or "",
            "title": title,
            "description": description,
            "category": guess_categories(name, title, description, r.get("description")),
        })

    if args.json:
        print(json.dumps(candidates, indent=1, ensure_ascii=False))
    else:
        print(f"{len(candidates)} ENCCS Pages site(s) not in the library and not ignored:")
        for c in candidates:
            print(f"- {c['repo']} ({c['site_status']}, {c['generator'] or 'unknown'}, pushed {c['last_push']}{', fork' if c['fork'] else ''}): {c['title']}")
    if args.write_drafts:
        written = [c["slug"] for c in candidates if c["site_status"] == 200 and write_draft(c)]
        print(f"{len(written)} draft card(s) written: {', '.join(written) or 'none'}", file=sys.stderr)


if __name__ == "__main__":
    main()
