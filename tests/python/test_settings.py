# SPDX-License-Identifier: AGPL-3.0-only
import os
import re
import unittest

from imaglr_integration import settings

YML = os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "imaglrIntegration", "imaglrIntegration.yml")


class SettingsTest(unittest.TestCase):
    def test_unsaved_settings_use_defaults(self):
        self.assertEqual(settings.parse(None), settings.Settings())
        self.assertEqual(settings.parse({"tagQueue": "  ", "videoDefaultClipSeconds": None}), settings.Settings())

    def test_saved_values_are_converted(self):
        s = settings.parse({"tagQueue": " to-post ", "tagsKeepCapitals": True, "videoDefaultClipSeconds": "8",
                            "workingFilesKeepDays": "3"})
        self.assertEqual((s.queue_tag, s.keep_tag_case, s.default_clip_seconds, s.prepared_retention_days),
                         ("to-post", True, 8.0, 3))

    def test_nonsense_numbers_fall_back(self):
        s = settings.parse({"videoDefaultClipSeconds": "0", "workingFilesKeepDays": "abc"})
        self.assertEqual((s.default_clip_seconds, s.prepared_retention_days), (15.0, 14))

    def test_queue_and_sent_tags_must_differ(self):
        with self.assertRaises(settings.SettingsError):
            settings.parse({"tagQueue": "Post", "tagSent": "post"})
        with self.assertRaises(settings.SettingsError):
            settings.parse({"tagSent": "IMAGLR"})

    def test_yaml_lists_settings_in_display_order(self):
        """Stash shows settings sorted by key, so the keys must sort into the order users should read them."""
        self.assertEqual(list(settings._FIELDS), sorted(settings._FIELDS))

    def test_yaml_declares_exactly_the_known_settings(self):
        with open(YML, encoding="utf-8") as f:
            text = f.read()
        declared = re.findall(r"^  (\w+):$", text.split("\nsettings:\n", 1)[1], re.M)
        self.assertEqual(declared, sorted(declared))
        self.assertEqual(sorted(declared), sorted(settings._FIELDS))

    def test_yaml_descriptions_are_plain_scalars(self):
        """A description starting with a quote mark is a quoted YAML scalar, and any text after the closing quote
        breaks the whole manifest, so Stash can't load the plugin at all."""
        with open(YML, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*(?:description|displayName):\s*(.*)$", line)
                if m:
                    self.assertFalse(m.group(1).startswith(('"', "'")), line.strip())


if __name__ == "__main__":
    unittest.main()


class ClipDefaultsTest(unittest.TestCase):
    def test_codec_and_picture_size_defaults(self):
        from imaglr_integration import settings as s
        self.assertEqual((s.parse({}).clips_hevc, s.parse({}).clip_max_edge), (False, None))
        self.assertTrue(s.parse({"videoClipsAsHevc": True}).clips_hevc)
        self.assertEqual(s.parse({"videoClipSize": "720"}).clip_max_edge, 1280)
        self.assertEqual(s.parse({"videoClipSize": " 480p "}).clip_max_edge, 854)
        self.assertIsNone(s.parse({"videoClipSize": "1080"}).clip_max_edge)
        self.assertIsNone(s.parse({"videoClipSize": "huge"}).clip_max_edge)
