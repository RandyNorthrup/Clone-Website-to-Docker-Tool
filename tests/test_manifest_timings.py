import os, sys, tempfile, json, shutil, unittest, hashlib
os.environ.setdefault('CW2DT_NO_QT','1')
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cw2dt_core import compute_checksums  # type: ignore

class TestManifestRelated(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='cw2dt_manifest_')
        # simulate files prerender + api capture scenario
        os.makedirs(os.path.join(self.tempdir, '_api'), exist_ok=True)
        with open(os.path.join(self.tempdir, 'index.html'),'w',encoding='utf-8') as f: f.write('<html>Hi</html>')
        with open(os.path.join(self.tempdir, '_api','data.json'),'w',encoding='utf-8') as f: f.write('{"x":1}')

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_checksums_include_api(self):
        checks = compute_checksums(self.tempdir)
        self.assertIn('index.html', checks)
        self.assertIn('_api/data.json', checks)

if __name__ == '__main__':
    unittest.main()
