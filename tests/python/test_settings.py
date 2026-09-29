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


if __name__ == "__main__":
    unittest.main()
