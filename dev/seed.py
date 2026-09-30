#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Configure a local test Stash (see dev/README.md). Standard library only.

    python3 dev/seed.py 9931 setup     first-run setup, scan, generate, sample metadata
    python3 dev/seed.py 9931 auth on   require login (user "dev", password "dev-password")
    python3 dev/seed.py 9931 auth off  remove the login again
    python3 dev/seed.py 9931 status    show version, setup state and whether login is on
    python3 dev/seed.py 9933 demo      the screenshot instance: setup + scan + friendly metadata (dev/demo_media.py first)
"""

import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USERNAME, PASSWORD = "dev", "dev-password"


class Stash:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.http = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def gql(self, query, **variables):
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(
            self.base + "/graphql", body, {"Content-Type": "application/json"}
        )
        try:
            result = json.load(self.http.open(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 401 and self.login():
                return self.gql(query, **variables)
            raise
        if result.get("errors"):
            raise RuntimeError(json.dumps(result["errors"], indent=2))
        return result["data"]

    def login(self):
        """Log in with the dev credentials; returns False if login isn't possible."""
        form = urllib.parse.urlencode(
            {"username": USERNAME, "password": PASSWORD, "returnURL": "/"}
        ).encode()
        try:
            self.http.open(self.base + "/login", form, timeout=10)
        except urllib.error.HTTPError:
            return False
        return True

    def wait_until_up(self):
        for _ in range(60):
            try:
                return self.gql("{ systemStatus { status appSchema } version { version hash } }")
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(2)
        sys.exit(f"Stash at {self.base} did not respond within 2 minutes")

    def wait_for_job(self, job_id, label):
        while True:
            job = self.gql("query($id: ID!) { findJob(input: {id: $id}) { status progress error } }", id=job_id)["findJob"]
            if job is None or job["status"] in ("FINISHED", "CANCELLED", "FAILED"):
                print(f"  {label}: {job['status'] if job else 'FINISHED'}")
                if job and job["error"]:
                    print(f"  error: {job['error']}")
                return
            time.sleep(1)


def setup(stash):
    status = stash.wait_until_up()["systemStatus"]["status"]
    if status == "SETUP":
        stash.gql(
            """mutation($input: SetupInput!) { setup(input: $input) }""",
            input={
                "configLocation": "/root/.stash/config.yml",
                "stashes": [{"path": "/data", "excludeVideo": False, "excludeImage": False}],
                "databaseFile": "",
                "generatedLocation": "/generated",
                "cacheLocation": "/cache",
                "storeBlobsInDatabase": False,
                "blobsLocation": "/blobs",
            },
        )
        print("  first-run setup done")
        stash.wait_until_up()
    else:
        print(f"  setup already done (status {status})")

    job = stash.gql(
        """mutation { metadataScan(input: {
             scanGenerateCovers: true, scanGeneratePreviews: true, scanGenerateSprites: true,
             scanGenerateThumbnails: true }) }"""
    )["metadataScan"]
    stash.wait_for_job(job, "scan")

    seed_metadata(stash)
    scene_ids = [s["id"] for s in stash.gql("{ findScenes(filter: {per_page: -1}) { scenes { id } } }")["findScenes"]["scenes"]]

    job = stash.gql(
        # By scene: Stash v0.31.1 doesn't create a scene's marker folder when generating by marker id.
        """mutation($scenes: [ID!]) { metadataGenerate(input: {
             markers: true, markerImagePreviews: true, markerScreenshots: true, sceneIDs: $scenes,
             transcodes: true }) }""",
        scenes=scene_ids,
    )["metadataGenerate"]
    stash.wait_for_job(job, "generate markers and transcodes")


def find_or_create(stash, kind, name):
    found = stash.gql(
        f"""query($name: String!) {{ find{kind}s(filter: {{q: $name, per_page: 50}}) {{
              {kind.lower()}s {{ id name }} }} }}""",
        name=name,
    )[f"find{kind}s"][f"{kind.lower()}s"]
    for item in found:
        if item["name"] == name:
            return item["id"]
    return stash.gql(
        f"mutation($name: String!) {{ {kind.lower()}Create(input: {{name: $name}}) {{ id }} }}",
        name=name,
    )[f"{kind.lower()}Create"]["id"]


def seed_metadata(stash):
    """Ordinary Stash metadata the tag-suggestion pipeline reads. No workflow tags: the plugin creates those."""
    tag_names = [
        "Sunset", "Beach", "Outdoor", "Portrait",
        "AI_Housekeeping",  # excluded by the default ^AI_ pattern
        "An extremely long descriptive tag name that exceeds the sixty four character limit",
    ]
    tags = {name: find_or_create(stash, "Tag", name) for name in tag_names}
    performer = find_or_create(stash, "Performer", "Test Performer")
    studio = find_or_create(stash, "Studio", "Test Studio")

    scenes = stash.gql("{ findScenes(filter: {per_page: -1}) { scenes { id files { basename } scene_markers { id } } } }")
    marker_ids = []
    for scene in scenes["findScenes"]["scenes"]:
        stash.gql(
            """mutation($id: ID!, $tags: [ID!], $performers: [ID!], $studio: ID) {
                 sceneUpdate(input: {id: $id, tag_ids: $tags, performer_ids: $performers, studio_id: $studio}) { id } }""",
            id=scene["id"], tags=list(tags.values()), performers=[performer], studio=studio,
        )
        if scene["scene_markers"]:
            marker_ids += [m["id"] for m in scene["scene_markers"]]
            continue
        marker = stash.gql(
            """mutation($scene: ID!, $primary: ID!, $tags: [ID!]) {
                 sceneMarkerCreate(input: {title: "Test moment", seconds: 5, end_seconds: 12,
                   scene_id: $scene, primary_tag_id: $primary, tag_ids: $tags}) { id } }""",
            scene=scene["id"], primary=tags["Sunset"], tags=[tags["Beach"]],
        )["sceneMarkerCreate"]
        marker_ids.append(marker["id"])

    images = stash.gql("{ findImages(filter: {per_page: -1}) { images { id } } }")["findImages"]["images"]
    stash.gql(
        """mutation($ids: [ID!], $tags: [ID!], $performers: [ID!], $studio: ID) {
             bulkImageUpdate(input: {ids: $ids, studio_id: $studio,
               tag_ids: {ids: $tags, mode: SET}, performer_ids: {ids: $performers, mode: SET}}) { id } }""",
        ids=[i["id"] for i in images], tags=[tags["Portrait"], tags["Outdoor"]],
        performers=[performer], studio=studio,
    )
    print(f"  metadata: {len(scenes['findScenes']['scenes'])} scenes, {len(marker_ids)} markers, {len(images)} images")
    return marker_ids


def demo(stash):
    """The stash-demo instance: first-run setup and scan like `setup`, then metadata that looks good in
    screenshots instead of the test fixtures. Media comes from dev/demo_media.py (public domain, SFW)."""
    status_ = stash.wait_until_up()["systemStatus"]["status"]
    if status_ == "SETUP":
        stash.gql(
            """mutation($input: SetupInput!) { setup(input: $input) }""",
            input={
                "configLocation": "/root/.stash/config.yml",
                "stashes": [{"path": "/data", "excludeVideo": False, "excludeImage": False}],
                "databaseFile": "", "generatedLocation": "/generated", "cacheLocation": "/cache",
                "storeBlobsInDatabase": False, "blobsLocation": "/blobs",
            },
        )
        print("  first-run setup done")
        stash.wait_until_up()
    job = stash.gql(
        """mutation { metadataScan(input: { scanGenerateCovers: true, scanGeneratePreviews: true,
             scanGenerateSprites: true, scanGenerateThumbnails: true }) }"""
    )["metadataScan"]
    stash.wait_for_job(job, "scan")

    tags = {name: find_or_create(stash, "Tag", name) for name in
            ["Vintage", "Advertising", "Travel", "Americana", "Architecture", "Space", "Nebula", "Earth", "Mars", "Retro"]}
    prelinger = find_or_create(stash, "Studio", "Prelinger Archives")
    nasa = find_or_create(stash, "Studio", "NASA")

    film_tags = {
        "Norelco": ["Vintage", "Advertising", "Retro"],
        "Westinghouse": ["Vintage", "Advertising", "Americana"],
        "Midwest": ["Vintage", "Travel", "Americana"],
        "Wheels": ["Vintage", "Travel"],
        "Parade": ["Vintage", "Architecture", "Americana"],
    }
    scenes = stash.gql("{ findScenes(filter: {per_page: -1}) { scenes { id title files { basename duration } scene_markers { id } } } }")["findScenes"]["scenes"]
    markers = 0
    for scene in scenes:
        name = scene["files"][0]["basename"] if scene["files"] else scene["title"] or ""
        chosen = next((v for k, v in film_tags.items() if k.lower() in name.lower()), ["Vintage"])
        # Stash titles the scene after its file; strip the extension so the demo reads nicely
        title = name.rsplit(".", 1)[0]
        stash.gql(
            """mutation($id: ID!, $title: String, $tags: [ID!], $studio: ID) {
                 sceneUpdate(input: {id: $id, title: $title, tag_ids: $tags, studio_id: $studio}) { id } }""",
            id=scene["id"], title=title, tags=[tags[t] for t in chosen], studio=prelinger,
        )
        if scene["scene_markers"]:
            continue
        duration = (scene["files"][0].get("duration") or 60) if scene["files"] else 60
        for start, label in ((min(12, duration / 4), "Opening"), (min(max(30, duration / 2), duration - 10), "Highlight")):
            stash.gql(
                """mutation($scene: ID!, $title: String!, $s: Float!, $e: Float, $primary: ID!) {
                     sceneMarkerCreate(input: {title: $title, seconds: $s, end_seconds: $e, scene_id: $scene,
                       primary_tag_id: $primary, tag_ids: []}) { id } }""",
                scene=scene["id"], title=label, s=float(start), e=float(start + 8), primary=tags[chosen[0]],
            )
            markers += 1

    images = stash.gql("{ findImages(filter: {per_page: -1}) { images { id title files { basename } } } }")["findImages"]["images"]
    for image in images:
        name = (image["files"][0]["basename"] if image["files"] else image["title"] or "").lower()
        chosen = ["Space"] + [t for t in ("Nebula", "Earth", "Mars") if t.lower() in name]
        stash.gql(
            """mutation($id: ID!, $title: String, $tags: [ID!], $studio: ID) {
                 imageUpdate(input: {id: $id, title: $title, tag_ids: $tags, studio_id: $studio}) { id } }""",
            id=image["id"], title=(image["files"][0]["basename"] if image["files"] else "").rsplit(".", 1)[0] or None,
            tags=[tags[t] for t in chosen], studio=nasa,
        )
    print(f"  metadata: {len(scenes)} films, {markers} new markers, {len(images)} images")
    # no "Release Notes" popup in recordings
    stash.gql("mutation { configureUI(input: {lastNoteSeen: 4102444800000}) { lastNoteSeen } }")
    scene_ids = [s["id"] for s in scenes]
    job = stash.gql(
        """mutation($scenes: [ID!]) { metadataGenerate(input: {
             markers: true, markerImagePreviews: true, markerScreenshots: true, sceneIDs: $scenes }) }""",
        scenes=scene_ids,
    )["metadataGenerate"]
    stash.wait_for_job(job, "generate marker previews")


def auth(stash, on):
    stash.wait_until_up()
    creds = {"username": USERNAME, "password": PASSWORD} if on else {"username": "", "password": ""}
    stash.gql(
        "mutation($input: ConfigGeneralInput!) { configureGeneral(input: $input) { username } }",
        input=creds,
    )
    print(f"  login {'required (dev / dev-password)' if on else 'removed'}")


def status(stash):
    info = stash.wait_until_up()
    try:
        urllib.request.urlopen(stash.base + "/graphql?query=%7Bversion%7Bversion%7D%7D", timeout=10)
        login = "no"
    except urllib.error.HTTPError as e:
        login = "yes" if e.code == 401 else f"unknown (HTTP {e.code})"
    print(json.dumps(info, indent=2), f"\n  login required: {login}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    port, command = sys.argv[1], sys.argv[2]
    stash = Stash(port)
    print(f"Stash on port {port}: {command}")
    if command == "setup":
        setup(stash)
    elif command == "demo":
        demo(stash)
    elif command == "auth" and len(sys.argv) == 4 and sys.argv[3] in ("on", "off"):
        auth(stash, sys.argv[3] == "on")
    elif command == "status":
        status(stash)
    else:
        sys.exit(__doc__)
