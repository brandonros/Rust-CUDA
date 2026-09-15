from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import check_workloads
import run_wave2
import workload


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'source'
        kernels = self.source / 'kernels'
        kernels.mkdir(parents=True)
        self.manifest = kernels / 'Cargo.toml'
        self.original = 'cuda_std = { git = "https://github.com/brandonros/Rust-CUDA.git", rev = "2f4fd1d" }\n'
        self.manifest.write_text(self.original)
        (kernels / 'Cargo.lock').write_text('committed lock\n')
        self.git('init', '--quiet')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'fixture')
        self.pin = self.git('rev-parse', 'HEAD').strip()
        self.manifest.write_text('local edits\n')
        (kernels / 'Cargo.lock').write_text('local lock edits\n')
        (kernels / 'untracked').write_text('keep me\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), *args], text=True)

    def assert_source_unchanged(self):
        self.assertEqual(self.manifest.read_text(), 'local edits\n')
        self.assertEqual((self.manifest.parent / 'Cargo.lock').read_text(), 'local lock edits\n')
        self.assertEqual((self.manifest.parent / 'untracked').read_text(), 'keep me\n')

    def test_repeated_preparation_uses_committed_source_and_cleans_up(self):
        with patch.object(workload, 'MINER_COMMIT', self.pin):
            for _ in range(2):
                with workload.prepared_miner(self.source, self.root / 'artifacts') as miner:
                    self.assertIn('path = ', (miner / 'kernels/Cargo.toml').read_text())
                    self.assertFalse((miner / 'kernels/untracked').exists())
                    (miner / 'kernels/Cargo.lock').write_text('resolved lock\n')
                    self.assert_source_unchanged()
                self.assertFalse(miner.exists())
        self.assertEqual((self.root / 'artifacts/Cargo.toml.original').read_text(), self.original)
        self.assert_source_unchanged()

    def test_both_runners_cleanup_after_failure_and_allow_retry(self):
        def fail(*args):
            self.prepared = args[-1]
            self.assertTrue(self.prepared.exists())
            raise RuntimeError('build failed')

        for module in (run_wave2, check_workloads):
            args = ['runner', 'solana', '--out', str(self.root / 'out')] if module is run_wave2 else ['runner', str(self.root / 'out')]
            args += ['--miner', str(self.source)]
            with patch.object(workload, 'MINER_COMMIT', self.pin), patch.object(sys, 'argv', args), patch.object(module, 'compare', side_effect=fail):
                for _ in range(2):
                    with self.assertRaisesRegex(RuntimeError, 'build failed'):
                        module.main()
                    self.assertFalse(self.prepared.exists())
                    self.assert_source_unchanged()

    def test_wrong_revision_is_rejected_without_modifying_source(self):
        with patch.object(workload, 'MINER_COMMIT', '0' * 40):
            with self.assertRaisesRegex(RuntimeError, 'revision differs'):
                with workload.prepared_miner(self.source, self.root / 'artifacts'):
                    self.fail('accepted incorrect revision')
        self.assert_source_unchanged()
