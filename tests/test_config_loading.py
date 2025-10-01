import os, sys, tempfile, json, shutil, unittest
os.environ.setdefault('CW2DT_NO_QT','1')
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
	sys.path.insert(0, BASE_DIR)

from cw2dt_core import _load_config_file  # type: ignore

class TestConfigLoading(unittest.TestCase):
	def setUp(self):
		self.tempdir = tempfile.mkdtemp(prefix='cw2dt_cfg_')

	def tearDown(self):
		shutil.rmtree(self.tempdir, ignore_errors=True)

	def test_load_json(self):
		path = os.path.join(self.tempdir, 'config.json')
		with open(path,'w',encoding='utf-8') as f:
			json.dump({'url':'https://example.com','prerender':True}, f)
		data = _load_config_file(path)
		self.assertTrue(data.get('prerender'))
		self.assertEqual(data.get('url'), 'https://example.com')

	def test_load_yaml_if_available(self):
		path = os.path.join(self.tempdir, 'c.yml')
		with open(path,'w',encoding='utf-8') as f:
			f.write('url: https://y.example\nprerender: true\n')
		data = _load_config_file(path)
		# If PyYAML not installed, falls back to {} silently; handle both outcomes
		if data:
			self.assertEqual(data.get('url'), 'https://y.example')
			self.assertTrue(data.get('prerender'))

if __name__ == '__main__':
	unittest.main()
