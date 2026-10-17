# SPDX-License-Identifier: AGPL-3.0-only
"""Saving imaglr posts: what a post looks like to the browse view, who it is credited to, where its files go,
what Stash is told, and how imaglr tags match Stash names (pure functions; no Stash, no imaglr)."""

import os
import re
import unittest

from imaglr_integration import saving

RAW = {
    "id": 96040950, "url": "https://imaglr.com/post/96040950", "type": "image",
    "profile": {"name": "someone", "url": "https://imaglr.com/profile/someone", "avatar": "https://cdn03.imaglr.com/a.jpg"},
    "created_at": "2026-09-23T15:55:06+00:00", "body": "<p>caption <b>html</b></p>", "summary": "First line\nsecond line",
    "tags": ["art", {"name": "photography"}, "", 7], "nsfw": True,
    "media": [
        {"url": "https://cdn03.imaglr.com/x.jpg", "thumb": None, "kind": "image", "mime": "image/jpeg", "width": 450, "height": 300},
        {"url": "https://cdn03.imaglr.com/y.mp4", "thumb": "https://cdn03.imaglr.com/y.jpg", "kind": "video", "mime": "video/mp4"},
        {"url": "https://cdn03.imaglr.com/z.mp3", "kind": "audio", "mime": "audio/mpeg"},
        {"url": "javascript:alert(1)", "kind": "image"},
    ],
    "reposted_from": None, "note_count": {"likes": 53, "reposts": "46", "comments": None}, "liked": False,
}


def reblog():
    raw = dict(RAW, id=111, url="https://imaglr.com/post/111", profile={"name": "reblogger", "url": "https://imaglr.com/profile/reblogger"},
               reposted_from={"id": 96040950, "url": "https://imaglr.com/post/96040950",
                              "profile": {"name": "someone", "url": "https://imaglr.com/profile/someone"}})
    return saving.normalize_post(raw)


class NormaliseTest(unittest.TestCase):
    def test_only_what_the_view_needs_every_field_checked(self):
        post = saving.normalize_post(RAW)
        self.assertEqual(post["id"], "96040950")
        self.assertEqual([m["kind"] for m in post["media"]], ["image", "video"])  # no audio, no unsafe address
        self.assertEqual(post["media"][0]["width"], 450)
        self.assertEqual(post["tags"], ["art", "photography"])
        self.assertEqual(post["notes"], {"likes": 53, "reposts": 46, "comments": 0})
        self.assertEqual(post["creator"]["name"], "someone")
        self.assertIsNone(post["original"])
        self.assertNotIn("body", post)  # imaglr's HTML never reaches the page

    def test_a_reblog_is_credited_to_the_original(self):
        post = reblog()
        self.assertEqual(post["creator"]["name"], "reblogger")
        who = saving.credit(post)
        self.assertEqual((who["id"], who["creator"]["name"], who["url"]), ("96040950", "someone", "https://imaglr.com/post/96040950"))
        self.assertEqual(saving.custom_fields(post), {"imaglr_post_id": "96040950", "imaglr_creator": "someone"})
        self.assertEqual(saving.stash_urls(post), ["https://imaglr.com/post/96040950", "https://imaglr.com/profile/someone"])


class FilesTest(unittest.TestCase):
    def test_files_go_under_the_creator_named_by_post(self):
        post = saving.normalize_post(RAW)
        plan = saving.file_plan(os.path.join("lib", "imaglr"), post)
        self.assertEqual([p for _, p in plan], [os.path.join("lib", "imaglr", "someone", "96040950-1.jpg"),
                                                 os.path.join("lib", "imaglr", "someone", "96040950-2.mp4")])
        single = saving.normalize_post(dict(RAW, media=RAW["media"][:1]))
        self.assertEqual(saving.file_plan("f", single)[0][1], os.path.join("f", "someone", "96040950.jpg"))

    def test_a_reblog_is_filed_under_the_original(self):
        self.assertTrue(saving.file_plan("f", reblog())[0][1].startswith(os.path.join("f", "someone", "96040950")))

    def test_names_are_safe_everywhere(self):
        self.assertEqual(saving.safe_name('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(saving.safe_name(" .. "), "imaglr")
        self.assertEqual(saving.safe_name("../../etc"), "etc")  # never a path step
        self.assertEqual(saving.safe_name(".."), "imaglr")
        self.assertNotIn(os.sep, saving.safe_name("x/y"))

    def test_extension_from_type_then_address_then_kind(self):
        self.assertEqual(saving.extension({"mime": "image/webp", "url": "https://x/a", "kind": "image"}), ".webp")
        self.assertEqual(saving.extension({"mime": None, "url": "https://x/a.JPEG?v=2", "kind": "image"}), ".jpg")
        self.assertEqual(saving.extension({"mime": "", "url": "https://x/a.exe", "kind": "video"}), ".mp4")


class TextTest(unittest.TestCase):
    def test_title_details_date(self):
        post = saving.normalize_post(RAW)
        self.assertEqual(saving.title_text(post), "First line")
        self.assertEqual(saving.details_text(post), "Saved from imaglr. Posted by @someone on 2026-09-23.\n"
                                                    "https://imaglr.com/post/96040950\n\nFirst line\nsecond line")
        self.assertEqual(saving.stash_date(post), "2026-09-23")
        bare = saving.normalize_post(dict(RAW, summary="", created_at="soon"))
        self.assertEqual(saving.title_text(bare), "@someone on imaglr")
        self.assertIsNone(saving.stash_date(bare))
        self.assertEqual(len(saving.title_text(saving.normalize_post(dict(RAW, summary="x" * 500)))), saving.TITLE_MAX)


class MatchTest(unittest.TestCase):
    def test_pattern_escapes_everything_and_ignores_case(self):
        pattern = saving.regex_any(["a.b (x)", "c+d", "naïve"])
        self.assertTrue(pattern.startswith("(?i)^(?:"))
        for name in ("A.B (X)", "c+d", "NAÏVE"):
            self.assertTrue(re.match(pattern, name), name)
        self.assertFalse(re.match(pattern, "aXb (x)"))

    def test_whole_names_or_aliases_only(self):
        candidates = [{"id": "1", "name": "Amber", "aliases": []}, {"id": "2", "name": "Amber Rose", "aliases": ["AR"]},
                      {"id": "3", "name": "Beach", "aliases": ["seaside"]}, {"id": "4", "name": "imaglr", "aliases": []}]
        self.assertEqual(saving.matches(["amber", "SEASIDE", "imaglr"], candidates, {"imaglr", "imaglr-sent"}), ["1", "3"])
        self.assertEqual(saving.matches(["ar"], candidates), ["2"])
        self.assertEqual(saving.matches([], candidates), [])


class LibraryTest(unittest.TestCase):
    def test_folder_must_be_inside_a_library(self):
        libs = [{"path": "/data"}, {"path": "/data/saved"}, {"path": "/media"}]
        self.assertEqual(saving.library_for("/data/saved/imaglr", libs)["path"], "/data/saved")  # the deepest
        self.assertEqual(saving.library_for("/media", libs)["path"], "/media")
        self.assertIsNone(saving.library_for("/database", libs))  # not inside /data, just similar
        self.assertIsNone(saving.library_for("/tmp", libs))
        self.assertIsNone(saving.library_for("/data/../etc", libs))


if __name__ == "__main__":
    unittest.main()
