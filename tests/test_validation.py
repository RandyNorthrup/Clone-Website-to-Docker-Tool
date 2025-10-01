import os, sys, unittest

os.environ.setdefault('CW2DT_NO_QT', '1')
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cw2dt_core import validate_required_fields  # type: ignore

class TestValidateRequiredFields(unittest.TestCase):
    def test_all_ok_without_build(self):
        errs = validate_required_fields('https://example.com', '/tmp/out', '127.0.0.1', False, '')
        self.assertEqual(errs, [])

    def test_missing_url_and_dest(self):
        errs = validate_required_fields('', '', '127.0.0.1', False, '')
        self.assertIn('Website URL required', errs)
        self.assertIn('Destination Folder required', errs)

    def test_invalid_ip(self):
        errs = validate_required_fields('https://e.com', '/tmp', '', False, '')
        self.assertIn('Bind IP invalid', errs)

    def test_build_requires_docker_name(self):
        errs = validate_required_fields('https://e.com', '/tmp', '0.0.0.0', True, '')
        self.assertIn('Docker image name required when building', errs)

if __name__ == '__main__':
    unittest.main()
