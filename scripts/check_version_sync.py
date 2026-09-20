#!/usr/bin/env python3
"""
Pre-release version synchronization and tag validation check.
- Enforces packages/ico-cache-py (pyproject.toml) and packages/ico-cache-js (package.json) versions match exactly.
- Enforces that git tag matching vX.Y.Z matches the version in both files.
- Fails if the version being released already exists as an earlier git tag.
"""
import argparse
import json
import os
import re
import subprocess
import sys


def check_version_sync(target_tag: str = None) -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    pyproject_path = os.path.join(repo_root, "packages/ico-cache-py/pyproject.toml")
    package_json_path = os.path.join(repo_root, "packages/ico-cache-js/package.json")

    with open(pyproject_path, "r", encoding="utf-8") as f:
        py_match = re.search(r'version\s*=\s*"(.*?)"', f.read())
    if not py_match:
        sys.exit("ERROR: Could not locate version in packages/ico-cache-py/pyproject.toml")
    py_version = py_match.group(1).strip()

    with open(package_json_path, "r", encoding="utf-8") as f:
        js_data = json.load(f)
    js_version = js_data.get("version", "").strip()

    if py_version != js_version:
        sys.exit(
            f"ERROR: Version mismatch! ico-cache-py={py_version} vs ico-cache-js={js_version}. "
            "Both packages must have identical versions before release."
        )

    print(f"✓ Package versions match: {py_version}")

    tag = target_tag or os.environ.get("RELEASE_TAG") or os.environ.get("GITHUB_REF_NAME")
    if tag:
        tag_version = tag.lstrip("v")
        if tag_version != py_version:
            sys.exit(
                f"ERROR: Tag '{tag}' does not match package version '{py_version}'! "
                f"Expected tag 'v{py_version}'."
            )
        print(f"✓ Release tag '{tag}' matches package version 'v{py_version}'.")

        try:
            out = subprocess.check_output(
                ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            # If tag exists but points to an earlier commit than HEAD
            if out and out != head:
                sys.exit(f"ERROR: Version tag '{tag}' already exists on previous commit {out[:8]}! Cannot re-release.")
        except subprocess.CalledProcessError:
            # Tag does not exist yet; safe to proceed
            pass

    return py_version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify package version synchronization")
    parser.add_argument("--tag", default=None, help="Optional release tag to validate (e.g. v0.1.0)")
    args = parser.parse_args()
    check_version_sync(args.tag)
