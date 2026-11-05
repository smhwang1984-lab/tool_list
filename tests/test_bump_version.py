# -*- coding: utf-8 -*-
"""v2.2.9 버전 번호 규칙(각 자리 10이 되면 윗자리로) 테스트."""
import unittest

import bump_version as bv


class VersionRuleTests(unittest.TestCase):
    def test_next_version_rolls_over_at_ten(self):
        self.assertEqual(bv.next_version('2.2.8'), '2.2.9')
        self.assertEqual(bv.next_version('2.2.9'), '2.3.0')
        self.assertEqual(bv.next_version('2.9.9'), '3.0.0')
        self.assertEqual(bv.next_version('1.5.10'), '1.6.0')  # 옛 두 자리 PATCH도 규칙대로 정리

    def test_valid_versions(self):
        self.assertTrue(bv.is_valid_version('2.3.0'))
        self.assertFalse(bv.is_valid_version('2.2.10'))
        self.assertFalse(bv.is_valid_version('2.2'))

    def test_repository_files_agree(self):
        found = bv.current_versions()
        self.assertEqual(len(set(found.values())), 1, found)
        self.assertTrue(bv.is_valid_version(found['NC_Tool_List.py']))


if __name__ == '__main__':
    unittest.main()
