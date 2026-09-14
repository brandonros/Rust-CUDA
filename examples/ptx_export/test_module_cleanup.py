import unittest
from check_module_cleanup import canonical


class ModuleComparisonTests(unittest.TestCase):
    def test_comments_do_not_change_ir(self):
        self.assertEqual(canonical('; ModuleID = one\nbb: ; preds = %a, %b\n ret void\n'),
                         canonical('; ModuleID = two\nbb: ; preds = %b, %a\n ret void\n'))

    def test_strings_and_semantic_differences_are_preserved(self):
        line = '@"semi;colon" = constant [2 x i8] c";x" ; comment'
        self.assertEqual(canonical(line), '@"semi;colon" = constant [2 x i8] c";x"')
        self.assertNotEqual(canonical('ret i32 1 ; first'), canonical('ret i32 2 ; second'))
        self.assertNotEqual(canonical('@s = constant [1 x i8] c";"'),
                            canonical('@s = constant [1 x i8] c":"'))

    def test_phi_order_preserves_value_block_associations(self):
        a = '%0 = phi i64 [ 3, %1 ], [ 5, %2 ]'
        b = '%0 = phi i64 [ 5, %2 ], [ 3, %1 ]'
        wrong = '%0 = phi i64 [ 5, %1 ], [ 3, %2 ]'
        self.assertEqual(canonical(a), canonical(b))
        self.assertNotEqual(canonical(a), canonical(wrong))
        self.assertEqual(canonical('%0 = phi [2 x i8] [ [i8 1, i8 2], %1 ], [ zeroinitializer, %2 ]'),
                         canonical('%0 = phi [2 x i8] [ zeroinitializer, %2 ], [ [i8 1, i8 2], %1 ]'))


if __name__ == '__main__':
    unittest.main()
