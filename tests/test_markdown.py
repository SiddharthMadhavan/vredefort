import unittest

from citycollapse.markdown_text import markdown_runs


class MarkdownTests(unittest.TestCase):
    def test_analyst_sections_lists_and_emphasis(self):
        runs = list(markdown_runs(
            '## Current situation\n\n'
            '- Speed: **28 km/h**; *no reported delay*.\n'
            '1. **Freshness:** observation age unknown.\n'
            '> Provider **confidence** is not match confidence.\n'))
        visible = ''.join(text for text, _ in runs)
        self.assertIn('Current situation\n', visible)
        self.assertIn('- Speed: 28 km/h; no reported delay.', visible)
        self.assertIn('1. Freshness: observation age unknown.', visible)
        self.assertIn(('Current situation', ('heading2',)), runs)
        self.assertIn(('28 km/h', ('list', 'strong')), runs)
        self.assertIn(('no reported delay', ('list', 'emphasis')), runs)
        self.assertIn(('confidence', ('quote', 'strong')), runs)

    def test_ids_code_and_escaped_markers_are_preserved(self):
        source = ('kml_merged_e_20022_0_1\n'
                  '`**literal**` and \\*literal\\*\n'
                  '```json\n{"road_id": "kml_n_77.6_12.9", "text": "**raw**"}\n```\n')
        runs = list(markdown_runs(source))
        visible = ''.join(text for text, _ in runs)
        self.assertIn('kml_merged_e_20022_0_1', visible)
        self.assertIn('**literal** and *literal*', visible)
        self.assertIn(('**literal**', ('code',)), runs)
        self.assertIn('{"road_id": "kml_n_77.6_12.9", "text": "**raw**"}\n', visible)
        self.assertNotIn('```', visible)

    def test_nested_styles_links_and_rules(self):
        runs = list(markdown_runs(
            '***Both*** and **bold with *emphasis*** and ~~old~~\n'
            '[Source](https://example.com/flow)\n---\n'))
        self.assertIn(('Both', ('strong_emphasis',)), runs)
        self.assertIn(('emphasis', ('strong', 'strong_emphasis')), runs)
        self.assertNotIn('*', ''.join(text for text, _ in runs))
        self.assertIn(('old', ('strike',)), runs)
        self.assertIn(('Source', ('link',)), runs)
        self.assertIn((' (https://example.com/flow)', ('link',)), runs)
        self.assertTrue(any('rule' in tags for _, tags in runs))

    def test_incomplete_stream_is_visible_until_delimiters_arrive(self):
        partial = ''.join(text for text, _ in markdown_runs('Speed **28'))
        self.assertEqual(partial, 'Speed **28')
        finished = list(markdown_runs('Speed **28 km/h**'))
        self.assertIn(('28 km/h', ('strong',)), finished)


if __name__ == '__main__':
    unittest.main()
