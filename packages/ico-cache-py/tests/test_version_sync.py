import json
import os
import re

def test_matching_package_versions():
    """
    Enforce matching version numbers between ico-cache-py and ico-cache-js so that
    any cross-language cache-format or protocol change forces a coordinated bump on both.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    pyproject_path = os.path.join(repo_root, "packages/ico-cache-py/pyproject.toml")
    package_json_path = os.path.join(repo_root, "packages/ico-cache-js/package.json")

    with open(pyproject_path, "r", encoding="utf-8") as f:
        pyproject_text = f.read()
    match = re.search(r'version\s*=\s*"(.*?)"', pyproject_text)
    assert match is not None, "Could not find version in pyproject.toml"
    py_version = match.group(1)

    with open(package_json_path, "r", encoding="utf-8") as f:
        js_data = json.load(f)
    js_version = js_data.get("version")

    assert py_version == js_version, (
        f"Version mismatch between ico-cache-py ({py_version}) and ico-cache-js ({js_version}). "
        "Cross-language cache updates require matching versions."
    )
