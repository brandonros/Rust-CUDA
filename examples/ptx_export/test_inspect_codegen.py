import unittest
from inspect_codegen import ptx_summary, sass_summary


class InventoryTests(unittest.TestCase):
    def test_ptx_prototypes_nested_calls_and_self_select(self):
        source = '''
.extern .func (.param .b64 retval) prototype(.param .b64 arg);
.visible .func (.param .b64 retval) preserved(.param .b64 arg) {
 .reg .b64 %rd<3>;
 { .param .b64 slot; }
 selp.b64 %rd1, %rd2, %rd1, %p1;
 @%p1 bra DONE;
DONE:
 ret;
}
.visible .entry direct() {
 selp.b32 %r1, %r2, %r3, %p1;
 ret;
}
'''
        result = ptx_summary(source)
        self.assertEqual(set(result), {'preserved', 'direct'})
        self.assertEqual(len(result['preserved']['self_false_selects']), 1)
        self.assertEqual(result['direct']['self_false_selects'], [])
        self.assertEqual(result['preserved']['opcode_histogram']['bra'], 1)

    def test_sass_counts_instructions_not_encoding_continuations(self):
        result = sass_summary('''Function : preserved
 /*0000*/ @!P0 LDG.E R2, [R4]; /* 0x123 */
 /*0010*/ SEL R3, R2, R1, P0;
 /* 0x000000 */
Function : direct
 /*0000*/ EXIT;
''')
        self.assertEqual(result['preserved'], {'LDG.E': 1, 'SEL': 1})
        self.assertEqual(result['direct'], {'EXIT': 1})


if __name__ == '__main__':
    unittest.main()
