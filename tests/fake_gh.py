"""A fake gh CLI for the tests: `gh api` and `gh release create` against a JSON state file.

Not a test module: the tests install it first on PATH as `gh`. The state ($FAKE_GH_STATE) holds
releases, assets (content in files), tag refs, annotated tags, check runs, statuses, workflow
runs, branch rules and branch names (`branches`); every call is appended to $FAKE_GH_LOG as one
JSON line. `--jq` runs the real jq (-r) on the answer. `list_lag` hides newly created releases
from that many list calls (eventual consistency).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_GH_STATE"])
JQ = None


def load() -> dict:
    return json.loads(STATE.read_text())


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state))


def out(value) -> None:
    text = json.dumps(value) + "\n"
    if JQ is not None:
        text = subprocess.run(["jq", "-r", JQ], input=text, capture_output=True, text=True, check=True).stdout
    sys.stdout.write(text)


def fail(message: str, code: int = 1):
    sys.stderr.write(f"gh: {message}\n")
    sys.exit(code)


def api(args: list[str]) -> None:
    global JQ
    method, headers, fields, path, input_file = "GET", [], {}, None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--method", "-X"):
            method, i = args[i + 1], i + 2
        elif a == "-H":
            headers.append(args[i + 1])
            i += 2
        elif a in ("-F", "-f"):
            key, _, value = args[i + 1].partition("=")
            fields[key] = (value == "true") if a == "-F" and value in ("true", "false") else value
            i += 2
        elif a == "--input":
            input_file, i = args[i + 1], i + 2
        elif a == "--jq":
            JQ, i = args[i + 1], i + 2
        elif a in ("--paginate", "--silent"):
            i += 1
        elif a.startswith("-"):
            fail(f"fake gh api: unexpected flag {a}", 2)
        else:
            path, i = a, i + 1
    state = load()
    for key, message in state.get("fail", {}).items():
        if re.fullmatch(key, f"{method} {path}"):
            fail(message)
    route = re.sub(r"^https://uploads\.github\.com/", "", path).lstrip("/")
    route, _, query = route.partition("?")
    repo = state["repo"]
    prefix = f"repos/{repo}/"
    if not route.startswith(prefix):
        fail(f"HTTP 404: {route}")
    route = route[len(prefix):]
    releases = state.setdefault("releases", [])

    def release(rid: str) -> dict:
        for r in releases:
            if str(r["id"]) == rid:
                return r
        fail(f"HTTP 404: release {rid}")

    if method == "GET" and route == "releases":
        lag = state.get("list_lag", 0)
        if lag:
            state["list_lag"] = lag - 1
            save(state)
            out([r for r in releases if not r.get("new")])
        else:
            out(releases)
    elif m := re.fullmatch(r"releases/(\d+)", route):
        r = release(m[1])
        if method == "PATCH":
            r.update(fields)
            if fields.get("draft") is False:
                state.setdefault("refs", []).append(
                    {"ref": f"refs/tags/{r['tag_name']}", "object": {"type": "commit", "sha": r["target_commitish"]}}
                )
                r["html_url"] = f"https://github.com/{repo}/releases/tag/{r['tag_name']}"
            save(state)
        out(r)
    elif (m := re.fullmatch(r"releases/(\d+)/assets", route)) and method == "GET":
        out([{k: v for k, v in a.items() if k != "file"} for a in state.get("assets", {}).get(m[1], [])])
    elif (m := re.fullmatch(r"releases/(\d+)/assets", route)) and method == "POST":
        name = dict(p.split("=", 1) for p in query.split("&"))["name"]
        assets = state.setdefault("assets", {}).setdefault(m[1], [])
        if any(a["name"] == name for a in assets):
            fail("HTTP 422: already_exists")
        aid = state["next_id"] = state.get("next_id", 900) + 1
        content = Path(input_file).read_bytes()
        stored = STATE.parent / f"asset-{aid}"
        stored.write_bytes(content)
        assets.append({"id": aid, "name": name, "file": str(stored), "content_type": headers})
        save(state)
        out({"id": aid, "name": name, "size": len(content)})
    elif m := re.fullmatch(r"releases/assets/(\d+)", route):
        for rid, assets in state.get("assets", {}).items():
            for a in assets:
                if str(a["id"]) == m[1]:
                    if method == "DELETE":
                        assets.remove(a)
                        save(state)
                        return
                    if "Accept: application/octet-stream" not in headers:
                        fail("fake gh api: asset download without the octet-stream Accept", 2)
                    sys.stdout.buffer.write(Path(a["file"]).read_bytes())
                    return
        fail(f"HTTP 404: asset {m[1]}")
    elif m := re.fullmatch(r"git/matching-refs/tags/(.*)", route):
        out([r for r in state.get("refs", []) if r["ref"].startswith(f"refs/tags/{m[1]}")])
    elif m := re.fullmatch(r"git/tags/([0-9a-f]+)", route):
        out(state["tags"][m[1]])
    elif m := re.fullmatch(r"commits/([0-9a-f]+)/check-runs", route):
        runs = state.get("check_runs", {}).get(m[1], [])
        out({"total_count": len(runs), "check_runs": runs})
    elif m := re.fullmatch(r"commits/([0-9a-f]+)/status", route):
        statuses = state.get("statuses", {}).get(m[1], [])
        combined = "pending"
        if statuses:
            states = {s["state"] for s in statuses}
            combined = "failure" if states & {"failure", "error"} else "pending" if "pending" in states else "success"
        out({"state": combined, "total_count": len(statuses), "statuses": statuses})
    elif m := re.fullmatch(r"actions/runs/(\d+)", route):
        runs = state.get("runs", {})
        if m[1] not in runs:
            fail(f"HTTP 404: run {m[1]}")
        out({"id": int(m[1]), "path": runs[m[1]]})
    elif method == "GET" and route == "branches":
        out([{"name": name} for name in state.get("branches", [])])
    elif (m := re.fullmatch(r"branches/(.+)", route)) and method == "GET":
        if m[1] not in state.get("branches", []):
            fail("HTTP 404: Branch not found")
        out({"name": m[1]})
    elif m := re.fullmatch(r"rules/branches/(.+)", route):
        out(state.get("rules", {}).get(m[1], []))
    else:
        fail(f"fake gh api: unexpected call {method} {path}", 2)


def release_create(args: list[str]) -> None:
    tag, files, opts, i = args[0], [], {}, 1
    while i < len(args):
        a = args[i]
        if a in ("--repo", "--target", "--title", "--notes-file", "--notes"):
            opts[a], i = args[i + 1], i + 2
        elif a in ("--draft", "--prerelease"):
            opts[a], i = True, i + 1
        elif a.startswith("-"):
            fail(f"fake gh release create: unexpected flag {a}", 2)
        else:
            files.append(a)
            i += 1
    state = load()
    if opts.get("--repo") != state["repo"]:
        fail("fake gh release create: --repo missing or wrong", 2)
    rid = state["next_id"] = state.get("next_id", 100) + 1
    body = Path(opts["--notes-file"]).read_text() if "--notes-file" in opts else opts.get("--notes", "")
    state.setdefault("releases", []).append(
        {
            "id": rid,
            "tag_name": tag,
            "name": opts.get("--title"),
            "draft": opts.get("--draft", False),
            "prerelease": opts.get("--prerelease", False),
            "target_commitish": opts.get("--target"),
            "body": body,
            "html_url": f"https://github.com/{state['repo']}/releases/tag/untagged-{rid}",
            "upload_url": f"https://uploads.github.com/repos/{state['repo']}/releases/{rid}/assets{{?name,label}}",
            "new": True,
        }
    )
    assets = state.setdefault("assets", {}).setdefault(str(rid), [])
    for f in files:
        aid = state["next_id"] = state["next_id"] + 1
        assets.append({"id": aid, "name": Path(f).name, "file": str(Path(f).resolve())})
    save(state)
    print("some progress line")
    print(f"https://github.com/{state['repo']}/releases/tag/{tag}")


def main() -> None:
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(json.dumps(args) + "\n")
    if not os.environ.get("GH_TOKEN"):
        fail("GH_TOKEN is not set", 4)
    if args[:1] == ["api"]:
        api(args[1:])
    elif args[:2] == ["release", "create"]:
        release_create(args[2:])
    else:
        fail(f"fake gh: unexpected call {args}", 2)


if __name__ == "__main__":
    main()
