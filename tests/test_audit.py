import copy
import unittest
from unittest.mock import patch

from maternity_copilot.core import catalog, decode_json
from maternity_copilot.audit import browse


class CatalogBoundaryTests(unittest.TestCase):
    def test_browse_filters_paginate_without_similarity_claims(self):
        page = browse({"stage": "pregnancy", "topic": "appointments"})
        self.assertEqual([row["id"] for row in page["resources"]], ["appointments-guide"])
        first, second = browse(limit=6), browse(offset=6, limit=6)
        self.assertEqual(first["next_offset"], 6)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(len({row["id"] for row in first["resources"] + second["resources"]}), 12)
        self.assertEqual(browse({"topic": "appointments", "focus": "support"})["total"], 0)
        for filters in ({"name": "person"}, {"stage": ["pregnancy"]}):
            with self.assertRaises(ValueError):
                browse(filters)

    def test_local_json_is_unambiguous_and_finite(self):
        for text in ('{"version":1,"version":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                decode_json(text)
        self.assertEqual(decode_json('{"x":1}'), {"x": 1})

    def test_catalog_does_not_export_undocumented_fields(self):
        original = catalog()
        for change in ({"notes": "unreviewed"}, {"id": "Name@example.com"}, {"id": "UPPER"}):
            rows = copy.deepcopy(original)
            rows[0].update(change)
            with patch("maternity_copilot.core.json.loads", return_value=rows):
                with self.assertRaises(ValueError):
                    catalog()
