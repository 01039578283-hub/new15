"""A newer generation must use its own baseline, never silently skip checks."""
import unittest

from refresh_branch_hierarchy import audit_script


class AuditCheckpointTests(unittest.TestCase):
    def test_elementary_extension_uses_its_own_checkpoint(self):
        self.assertEqual(audit_script(['고2', '초6', '중3', '중1', '초5', '고1', '중2']),
                         'audit_branch_elementary_pages.py')

    def test_incomplete_or_unreviewed_elementary_extension_fails(self):
        prior = ['중1', '중2', '중3', '고1', '고2']
        for grades in (prior + ['초5'], prior + ['초6'], prior + ['초4', '초5', '초6']):
            with self.subTest(grades=grades), self.assertRaises(ValueError):
                audit_script(grades)

    def test_middle_extension_uses_its_own_checkpoint(self):
        self.assertEqual(audit_script(['고2', '중3', '중1', '고1', '중2']),
                         'audit_branch_middle_pages.py')

    def test_incomplete_middle_extension_does_not_skip_checks(self):
        for grades in (['고1', '고2', '중1'], ['고1', '고2', '중1', '중2']):
            with self.subTest(grades=grades), self.assertRaises(ValueError):
                audit_script(grades)

    def test_current_combined_grades_use_high1_checkpoint(self):
        self.assertEqual(audit_script(['고2', '고1']), 'audit_branch_high1_pages.py')

    def test_earlier_grade_checkpoint_retained(self):
        self.assertEqual(audit_script(['고2']), 'audit_branch_high2_pages.py')

    def test_no_grade_inventory_uses_center_checkpoint(self):
        self.assertEqual(audit_script([]), 'audit_branch_pages.py')

    def test_unreviewed_grade_inventory_fails_closed(self):
        for grades in (['고1'], ['고1', '고2', '고3'], ['중1']):
            with self.subTest(grades=grades), self.assertRaises(ValueError):
                audit_script(grades)


if __name__ == '__main__':
    unittest.main()
