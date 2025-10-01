import os, sys, tempfile, shutil, json, hashlib, unittest, time
os.environ.setdefault('CW2DT_NO_QT','1')
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
	sys.path.insert(0, BASE_DIR)

from cw2dt_core import compute_checksums, _snapshot_file_hashes, _compute_diff  # type: ignore

class TestChecksumsAndDiff(unittest.TestCase):
	def setUp(self):
		self.tempdir = tempfile.mkdtemp(prefix='cw2dt_chk_')
		# Create initial files
		self.files_v1 = {
			'index.html': b'<html>A</html>',
			'about.html': b'<html>About</html>',
			'_api/data.json': b'{"a":1}',
			'styles.css': b'body{color:#000}',
		}
		for rel, data in self.files_v1.items():
			path = os.path.join(self.tempdir, rel)
			os.makedirs(os.path.dirname(path), exist_ok=True)
			with open(path,'wb') as f: f.write(data)

	def tearDown(self):
		shutil.rmtree(self.tempdir, ignore_errors=True)

	def test_compute_checksums_basic_and_extra(self):
		checks = compute_checksums(self.tempdir, extra_extensions=['css'])
		# index/about + _api/data.json + styles.css = 4 entries
		self.assertEqual(len(checks), 4)
		for rel in ['index.html','about.html','_api/data.json','styles.css']:
			self.assertIn(rel, checks)

	def test_diff_modified_added_removed(self):
		# Snapshot v1
		snap1 = {'files': _snapshot_file_hashes(self.tempdir, extra_ext=['css'])}
		# Modify about, remove styles, add contact
		with open(os.path.join(self.tempdir, 'about.html'),'wb') as f: f.write(b'<html>About NEW</html>')
		os.remove(os.path.join(self.tempdir, 'styles.css'))
		with open(os.path.join(self.tempdir, 'contact.html'),'wb') as f: f.write(b'<html>Contact</html>')
		snap2 = {'files': _snapshot_file_hashes(self.tempdir, extra_ext=['css'])}
		diff = _compute_diff(snap1, snap2)
		self.assertIn('contact.html', diff['added'])
		self.assertIn('styles.css', diff['removed'])
		modified_paths = [m['path'] for m in diff['modified']]
		self.assertIn('about.html', modified_paths)

if __name__ == '__main__':
	unittest.main()
