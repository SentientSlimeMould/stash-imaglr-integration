# SPDX-License-Identifier: AGPL-3.0-only
import os
import re
import unittest

from imaglr_integration import settings

YML = os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "imaglrIntegration", "imaglrIntegration.yml")


class SettingsTest(unittest.TestCase):
    def test_unsaved_settings_use_defaults(self):
        self.assertEqual(settings.parse(None), settings.Settings())
        self.assertEqual(settings.parse({"queueTag": "  ", "defaultClipSeconds": None}), settings.Settings())

    def test_saved_values_are_converted(self):
        s = settings.parse({"queueTag": " to-post ", "keepTagCase": True, "defaultClipSeconds": 8, "preparedRetentionDays": 3})
        self.assertEqual((s.queue_tag, s.keep_tag_case, s.default_clip_seconds, s.prepared_retention_days),
                         ("to-post", True, 8.0, 3))

    def test_nonsense_numbers_fall_back(self):
        s = settings.parse({"defaultClipSeconds": 0, "preparedRetentionDays": "abc"})
        self.assertEqual((s.default_clip_seconds, s.prepared_retention_days), (15.0, 14))

    def test_yaml_declares_exactly_the_known_settings(self):
        with open(YML, encoding="utf-8") as f:
            text = f.read()
        declared = re.findall(r"^  (\w+):$", text.split("\nsettings:\n", 1)[1], re.M)
        self.assertEqual(sorted(declared), sorted(settings._FIELDS))


if __name__ == "__main__":
    unittest.main()
