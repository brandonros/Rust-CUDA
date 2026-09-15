import json
from pathlib import Path
import tempfile
import unittest
from inspect_codegen import INSPECTION_OUTPUTS, reuse_inspection


class InspectionReuseTests(unittest.TestCase):
    def test_identical_inputs_reuse_with_explicit_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            source, dest = self.fixtures(Path(directory))
            self.assertTrue(reuse_inspection(source,dest))
            for name in INSPECTION_OUTPUTS:
                self.assertEqual((source/name).read_bytes(),(dest/name).read_bytes())
            self.assertIn('assembly/disassembly not rerun',json.loads((dest/'reused-inspection.json').read_text())['note'])
            self.assertFalse(reuse_inspection(source,source))

    def test_changed_ptx_tool_or_inspector_never_reuses(self):
        for name in ['rust_kernels.ptx','inspection-producer-sha256.txt','inspection-tools-sha256.json','ptxas-version.txt']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                source,dest=self.fixtures(Path(directory))
                (dest/name).write_text('different')
                self.assertFalse(reuse_inspection(source,dest))
                self.assertFalse((dest/'rust_kernels.cubin').exists())

    @staticmethod
    def fixtures(root):
        source,dest=root/'source',root/'dest';source.mkdir();dest.mkdir()
        for name in ['rust_kernels.ptx','inspection-producer-sha256.txt','inspection-tools-sha256.json',
                     'ptxas-version.txt','nvdisasm-version.txt','cuobjdump-version.txt']:
            for path in [source,dest]:(path/name).write_text(name)
        for name in INSPECTION_OUTPUTS:(source/name).write_text('offline output '+name)
        (source/'inspection-commands.json').write_text('[]')
        return source,dest
