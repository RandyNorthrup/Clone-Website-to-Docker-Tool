import os, sys, json, tempfile, shutil, hashlib, unittest

# Ensure Qt import side-effects are minimized (GUI not needed). If cw2dt later supports CW2DT_NO_QT this would help.
os.environ.setdefault('CW2DT_NO_QT', '1')

# Add parent directory to sys.path to import cw2dt
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cw2dt import parse_verification_summary, run_verification  # type: ignore

class TestParseVerificationSummary(unittest.TestCase):
    def test_valid_line(self):
        txt = "noise\n[verify] OK=5 Missing=1 Mismatched=2 Total=8\nend"
        stats = parse_verification_summary(txt)
        self.assertEqual(stats, {'ok':5,'missing':1,'mismatched':2,'total':8})

    def test_empty(self):
        stats = parse_verification_summary("")
        self.assertEqual(stats, {'ok':None,'missing':None,'mismatched':None,'total':None})

    def test_partial_noise(self):
        txt = "Some unrelated output\nStill nothing here"
        stats = parse_verification_summary(txt)
        self.assertEqual(stats, {'ok':None,'missing':None,'mismatched':None,'total':None})

class TestRunVerification(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='cw2dt_tests_')
        self.project_dir = os.path.join(self.tempdir, 'proj')
        os.makedirs(self.project_dir, exist_ok=True)
        # Create sample files
        self.files = {
            'index.html': b'<html>Index</html>',
            'about.html': b'<html>About</html>',
            '_api/data.json': b'{"v": 1}'
        }
        checksums = {}
        for rel, data in self.files.items():
            full = os.path.join(self.project_dir, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'wb') as f:
                f.write(data)
            checksums[rel] = hashlib.sha256(data).hexdigest()
        self.manifest_path = os.path.join(self.project_dir, 'clone_manifest.json')
        manifest = {
            'url': 'https://example.com',
            'docker_name': 'site',
            'output_folder': self.project_dir,
            'checksums_sha256': checksums
        }
        with open(self.manifest_path, 'w', encoding='utf-8') as mf:
            json.dump(manifest, mf, indent=2)

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_pass_fast(self):
        passed, stats = run_verification(self.manifest_path, fast=True, docker_name='site', project_dir=self.project_dir, readme=False)
        self.assertTrue(passed)
        self.assertEqual(stats['missing'], 0)
        self.assertEqual(stats['mismatched'], 0)
        self.assertEqual(stats['ok'], 3)
        self.assertEqual(stats['total'], 3)

    def test_fail_mismatch(self):
        # Corrupt a file
        with open(os.path.join(self.project_dir, 'about.html'), 'wb') as f:
            f.write(b'<html>Corrupted</html>')
        passed, stats = run_verification(self.manifest_path, fast=True, docker_name='site', project_dir=self.project_dir, readme=False)
        self.assertFalse(passed)
        self.assertEqual(stats['total'], 3)
        self.assertGreaterEqual(stats['mismatched'] or 0, 1)

    def test_missing_fast(self):
        os.remove(os.path.join(self.project_dir, 'about.html'))
        passed, stats = run_verification(self.manifest_path, fast=True, docker_name='site', project_dir=self.project_dir, readme=False)
        self.assertFalse(passed)
        self.assertEqual(stats['total'], 3)
        self.assertGreaterEqual(stats['missing'] or 0, 1)

if __name__ == '__main__':
    unittest.main()
