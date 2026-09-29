# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration.tags.caption import caption_to_html


class CaptionTest(unittest.TestCase):
    def test_blank_is_none(self):
        for text in (None, "", "   \n "):
            self.assertIsNone(caption_to_html(text))

    def test_paragraphs_and_breaks(self):
        self.assertEqual(caption_to_html("a\nb\n\nc"), "<p>a<br>b</p><p>c</p>")

    def test_escaping(self):
        self.assertEqual(caption_to_html("<b> & 'x'"), "<p>&lt;b&gt; &amp; 'x'</p>")

    def test_crlf(self):
        self.assertEqual(caption_to_html("a\r\nb\r\n\r\nc"), "<p>a<br>b</p><p>c</p>")


if __name__ == "__main__":
    unittest.main()
