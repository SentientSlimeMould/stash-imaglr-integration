# SPDX-License-Identifier: AGPL-3.0-only
"""GraphQL documents (static checks) and the stash.api functions against a stubbed StashClient.gql."""

import re
import unittest
from unittest import mock

from imaglr_integration.stash import api, queries
from imaglr_integration.stash.client import StashClient, StashError
from imaglr_integration.stash.models import Marker, Tag

from .test_stash_models import sample_image, sample_marker


def _documents():
    for name in dir(queries):
        value = getattr(queries, name)
        if name.isupper() and isinstance(value, str) and re.search(r"\b(query|mutation)\b", value):
            yield name, value


class DocumentTest(unittest.TestCase):
    """Every declared variable must be used and vice versa (Stash answers 422 otherwise)."""

    def test_all_declared_variables_are_used(self):
        problems = []
        for name, doc in _documents():
            head, body = doc[: doc.index("{")], doc[doc.index("{") :]
            for var in re.findall(r"\$(\w+)\s*:", head):
                if not re.search(r"\$" + var + r"\b", body):
                    problems.append(f"{name}: ${var} declared but unused")
        self.assertEqual(problems, [])

    def test_all_used_variables_are_declared(self):
        problems = []
        for name, doc in _documents():
            declared = set(re.findall(r"\$(\w+)\s*:", doc[: doc.index("{")]))
            used = set(re.findall(r"\$(\w+)", doc[doc.index("{") :]))
            problems.extend(f"{name}: ${var} used but not declared" for var in used - declared)
        self.assertEqual(problems, [])

    def test_documents_have_balanced_braces(self):
        for name, doc in _documents():
            self.assertEqual(doc.count("{"), doc.count("}"), name)


class FakeStash:
    """Stands in for StashClient.gql: maps an operation name (e.g. 'Version') to data or a callable."""

    def __init__(self, **responses):
        self.responses = responses
        self.calls = []

    def __call__(self, query, variables=None):
        op = query.split("{", 1)[0].split()[1].split("(")[0]
        self.calls.append((op, variables or {}))
        if op not in self.responses:
            raise AssertionError(f"unstubbed operation {op}")
        data = self.responses[op]
        return data(variables or {}) if callable(data) else data


def client_with(fake):
    client = StashClient({"SessionCookie": {"Name": "session", "Value": "c"}})
    client._api_key_checked = True
    client.gql = fake
    return client


def tags_response(*tags):
    return {"findTags": {"tags": list(tags)}}


class TagTest(unittest.TestCase):
    def test_existing_tag_is_reused_whatever_its_case(self):
        fake = FakeStash(FindTagExact=tags_response({"id": "7", "name": "Imaglr", "aliases": []}))
        self.assertEqual(api.ensure_tag(client_with(fake), "imaglr"), Tag("7", "Imaglr"))
        self.assertEqual([c[0] for c in fake.calls], ["FindTagExact"])

    def test_like_wildcard_matches_are_ignored(self):
        # Stash's EQUALS is LIKE: "imaglr_drafted" also matches "imaglrXdrafted".
        fake = FakeStash(FindTagExact=tags_response({"id": "3", "name": "imaglrXdrafted"}))
        self.assertIsNone(api.find_tag_exact(client_with(fake), "imaglr_drafted"))

    def test_name_match_beats_alias_match(self):
        fake = FakeStash(
            FindTagExact=tags_response(
                {"id": "2", "name": "Workflow", "aliases": ["IMAGLR"]}, {"id": "1", "name": "imaglr", "aliases": []}
            )
        )
        self.assertEqual(api.find_tag_exact(client_with(fake), "Imaglr").id, "1")

    def test_alias_match_counts(self):
        fake = FakeStash(FindTagExact=tags_response({"id": "2", "name": "Workflow Done", "aliases": ["IMAGLR-Drafted"]}))
        self.assertEqual(api.ensure_tag(client_with(fake), "imaglr-drafted").id, "2")

    def test_missing_tag_is_created(self):
        fake = FakeStash(FindTagExact=tags_response(), TagCreate=lambda v: {"tagCreate": {"id": "99", "name": v["name"]}})
        with mock.patch.object(api.log, "info") as info:
            self.assertEqual(api.ensure_tag(client_with(fake), "imaglr"), Tag("99", "imaglr"))
        info.assert_called_once()
        self.assertEqual(fake.calls[-1], ("TagCreate", {"name": "imaglr"}))

    def test_create_race_finds_the_other_tag(self):
        found = iter([tags_response(), tags_response({"id": "5", "name": "imaglr"})])

        def create(_):
            raise StashError("tag with name 'imaglr' already exists")

        fake = FakeStash(FindTagExact=lambda v: next(found), TagCreate=create)
        self.assertEqual(api.ensure_tag(client_with(fake), "imaglr").id, "5")

    def test_create_failure_is_raised(self):
        def create(_):
            raise StashError("boom")

        fake = FakeStash(FindTagExact=tags_response(), TagCreate=create)
        with self.assertRaises(StashError):
            api.ensure_tag(client_with(fake), "imaglr")

    def test_autocomplete(self):
        fake = FakeStash(FindTagsByName=tags_response({"id": "1", "name": "Sunset"}))
        self.assertEqual(api.find_tags(client_with(fake), "sun"), [Tag("1", "Sunset")])


QUEUE, DONE = Tag("10", "imaglr"), Tag("11", "imaglr-drafted")


class MarkerTest(unittest.TestCase):
    def test_queue_primary_becomes_done_primary(self):
        m = Marker.parse(sample_marker())
        self.assertEqual(api.swapped_marker_tags(m, QUEUE, DONE), ("11", ["20", "21"]))

    def test_queue_secondary_is_replaced_by_done_secondary(self):
        m = Marker.parse(sample_marker(primary_tag={"id": "20", "name": "Slow Motion"}, tags=[{"id": "10", "name": "imaglr"}]))
        self.assertEqual(api.swapped_marker_tags(m, QUEUE, DONE), ("20", ["11"]))

    def test_swap_is_idempotent(self):
        m = Marker.parse(sample_marker(primary_tag={"id": "11", "name": "imaglr-drafted"}, tags=[{"id": "10", "name": "imaglr"}]))
        self.assertEqual(api.swapped_marker_tags(m, QUEUE, DONE), ("11", []))

    def test_swap_keeps_in_and_out_points(self):
        fake = FakeStash(MarkerUpdate={"sceneMarkerUpdate": {"id": "501"}})
        api.marker_swap_tags(client_with(fake), Marker.parse(sample_marker()), QUEUE, DONE)
        self.assertEqual(
            fake.calls,
            [("MarkerUpdate", {"id": "501", "seconds": 10.0, "end_seconds": 22.5, "primary_tag_id": "11", "tag_ids": ["20", "21"]})],
        )

    def test_remove_secondary_queue_tag(self):
        fake = FakeStash(MarkerUpdate={"sceneMarkerUpdate": {"id": "501"}})
        m = Marker.parse(sample_marker(primary_tag={"id": "20", "name": "Slow Motion"}, tags=[{"id": "10", "name": "imaglr"}, {"id": "21", "name": "x"}]))
        self.assertTrue(api.marker_remove_tag(client_with(fake), m, QUEUE))
        self.assertEqual(fake.calls[0][1]["primary_tag_id"], "20")
        self.assertEqual(fake.calls[0][1]["tag_ids"], ["21"])

    def test_remove_primary_queue_tag_promotes_next_tag(self):
        fake = FakeStash(MarkerUpdate={"sceneMarkerUpdate": {"id": "501"}})
        self.assertTrue(api.marker_remove_tag(client_with(fake), Marker.parse(sample_marker()), QUEUE))
        self.assertEqual(fake.calls[0][1]["primary_tag_id"], "20")
        self.assertEqual(fake.calls[0][1]["tag_ids"], ["21"])

    def test_remove_only_tag_refuses(self):
        fake = FakeStash(MarkerUpdate={"sceneMarkerUpdate": {"id": "501"}})
        self.assertFalse(api.marker_remove_tag(client_with(fake), Marker.parse(sample_marker(tags=[])), QUEUE))
        self.assertEqual(fake.calls, [])

    def test_in_out_write_back_keeps_tags(self):
        fake = FakeStash(MarkerUpdate={"sceneMarkerUpdate": {"id": "501"}})
        api.marker_update(client_with(fake), Marker.parse(sample_marker()), seconds=12.0, end_seconds=18.0)
        self.assertEqual(
            fake.calls[0][1], {"id": "501", "seconds": 12.0, "end_seconds": 18.0, "primary_tag_id": "10", "tag_ids": ["20", "21"]}
        )

    def test_find_marker_missing_is_none(self):
        # Stash errors ("scene marker with id 9 not found") instead of returning an empty list.
        def missing(v):
            raise StashError(f"scene marker with id {v['id']} not found")

        self.assertIsNone(api.find_marker(client_with(FakeStash(MarkerById=missing)), "9"))

    def test_find_marker_other_errors_are_raised(self):
        def down(_):
            raise StashError("Cannot reach Stash")

        with self.assertRaises(StashError):
            api.find_marker(client_with(FakeStash(MarkerById=down)), "9")

    def test_queued_markers_pages_until_count(self):
        def page(v):
            start = (v["page"] - 1) * v["perPage"]
            ids = range(start, min(start + v["perPage"], 150))
            return {"findSceneMarkers": {"count": 150, "scene_markers": [sample_marker(id=str(i)) for i in ids]}}

        fake = FakeStash(QueuedMarkers=page)
        self.assertEqual(len(api.queued_markers(client_with(fake), "10")), 150)
        self.assertEqual([c[1]["page"] for c in fake.calls], [1, 2])
        self.assertEqual(len(api.queued_markers(client_with(fake), "10", limit=120)), 120)


class ImageAndSceneTest(unittest.TestCase):
    def test_image_swap_adds_done_before_removing_queue(self):
        fake = FakeStash(BulkImageAddTags={"bulkImageUpdate": []}, BulkImageRemoveTags={"bulkImageUpdate": []})
        api.image_swap_tags(client_with(fake), "801", QUEUE, DONE)
        self.assertEqual(
            fake.calls,
            [("BulkImageAddTags", {"ids": ["801"], "add": ["11"]}), ("BulkImageRemoveTags", {"ids": ["801"], "remove": ["10"]})],
        )

    def test_find_image(self):
        fake = FakeStash(ImageById=lambda v: {"findImage": sample_image() if v["id"] == "801" else None})
        self.assertEqual(api.find_image(client_with(fake), "801").title, "Photo")
        self.assertIsNone(api.find_image(client_with(fake), "802"))

    def test_scene_search_and_version(self):
        fake = FakeStash(
            FindScenes={"findScenes": {"count": 1, "scenes": [sample_marker()["scene"]]}},
            SceneById={"findScene": None},
            Version={"version": {"version": "v0.31.1"}},
        )
        client = client_with(fake)
        count, scenes = api.find_scenes(client, "seven")
        self.assertEqual((count, scenes[0].id), (1, "7"))
        self.assertIsNone(api.find_scene(client, "8"))
        self.assertEqual(api.version(client), "v0.31.1")


class AuthHeadersTest(unittest.TestCase):
    def test_api_key_is_preferred(self):
        client = StashClient({"SessionCookie": {"Name": "session", "Value": "c"}})
        client._api_key_checked, client._api_key = True, "k"
        self.assertEqual(api.auth_headers(client), {"ApiKey": "k"})

    def test_session_cookie_without_api_key(self):
        client = client_with(FakeStash())
        self.assertEqual(api.auth_headers(client), {"Cookie": "session=c"})

    def test_no_auth(self):
        client = StashClient({})
        client._api_key_checked = True
        self.assertEqual(api.auth_headers(client), {})

    def test_api_key_is_looked_up_first(self):
        client = StashClient({})
        calls = []

        def request(query, variables=None):
            calls.append(query)
            return {"configuration": {"general": {"apiKey": "k"}}}

        client._request = request
        self.assertEqual(api.auth_headers(client), {"ApiKey": "k"})
        self.assertEqual(api.auth_headers(client), {"ApiKey": "k"})
        self.assertEqual(len(calls), 1)  # looked up once, then remembered


if __name__ == "__main__":
    unittest.main()
