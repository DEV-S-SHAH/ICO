#!/usr/bin/env python3
"""
CHANGELOG enforcement and extraction script.
Checks that CHANGELOG.md has an entry matching the version being tagged (format: ## [X.Y.Z] - YYYY-MM-DD).
Fails the release build if the entry is missing or empty.
Can extract the release notes section for automated GitHub Release population.
"""
import argparse
import os
import re
import sys


def check_changelog(target_version: str = None, extract_notes: bool = False) -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    changelog_path = os.path.join(repo_root, "CHANGELOG.md")

    if not os.path.exists(changelog_path):
        sys.exit("ERROR: CHANGELOG.md does not exist at repo root!")

    version = target_version or os.environ.get("RELEASE_TAG") or os.environ.get("GITHUB_REF_NAME")
    if not version:
        pyproject_path = os.path.join(repo_root, "packages/ico-cache-py/pyproject.toml")
        with open(pyproject_path, "r", encoding="utf-8") as f:
            m = re.search(r'version\s*=\s*"(.*?)"', f.read())
            if m:
                version = m.group(1).strip()
            else:
                sys.exit("ERROR: No version provided and could not detect from pyproject.toml.")

    clean_version = version.lstrip("v")
    pattern = re.compile(
        r"^##\s*\[" + re.escape(clean_version) + r"\]\s*-\s*(\d{4}-\d{2}-\d{2})",
        re.MULTILINE,
    )

    with open(changelog_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = pattern.search(content)
    if not match:
        sys.exit(
            f"ERROR: CHANGELOG.md is missing an entry for version [{clean_version}]!\n"
            f"Expected format: '## [{clean_version}] - YYYY-MM-DD'"
        )

    release_date = match.group(1)
    print(f"✓ Found valid CHANGELOG.md entry for [{clean_version}] dated {release_date}.")

    # Extract release notes section for this version
    start_pos = match.end()
    next_heading = re.search(r"^##\s*\[", content[start_pos:], re.MULTILINE)
    if next_heading:
        section_text = content[start_pos : start_pos + next_heading.start()].strip()
    else:
        section_text = content[start_pos:].strip()

    if not section_text:
        sys.exit(f"ERROR: CHANGELOG.md section for [{clean_version}] is empty!")

    if extract_notes:
        print(section_text)

    return section_text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate CHANGELOG.md entry")
    parser.add_argument("--version", default=None, help="Target version to check (e.g. 0.1.0 or v0.1.0)")
    parser.add_argument("--extract", action="store_true", help="Print the extracted release notes section")
    args = parser.parse_args()
    check_changelog(target_version=args.version, extract_notes=args.extract)
