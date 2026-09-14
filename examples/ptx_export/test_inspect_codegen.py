import unittest
from inspect_codegen import ptx_summary, sass_summary, sass_symbols


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

    def test_helper_extents_exclude_adjacent_functions(self):
        source = """
 .size kernel,(END - kernel)
kernel:
 /*0000*/ CALL.REL helper;
 .size $kernel$first,($kernel$second - $kernel$first)
$kernel$first:
 /*0010*/ @P0 SEL R1, R2, R3, P0;
LOCAL:
 /*0020*/ RET.REL.NODEC;
 .size $kernel$second,(END - $kernel$second)
$kernel$second:
 /*0030*/ LDG.E R2, [R4];
 /*0040*/ NOP;
END:
"""
        result = sass_symbols(source)
        self.assertEqual(result['$kernel$first']['opcode_histogram'], {'SEL': 1, 'RET.REL.NODEC': 1})
        self.assertEqual(result['$kernel$second']['non_nop_instructions'], 1)
        self.assertEqual(result['kernel']['non_nop_instructions'], 4)
        self.assertEqual(result['kernel']['scope'], 'entry_including_helpers')

    def test_missing_symbol_end_is_an_error(self):
        with self.assertRaises(ValueError):
            sass_symbols('.size helper,(MISSING - helper)\nhelper:\n /*0000*/ RET;\n')


if __name__ == '__main__':
    unittest.main()
