import contextlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase
from scripts.osrm_filter import main


class OsrmFilterTests(SimpleTestCase):
    def test_preserves_tags_references_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, output = root / 'source.pbf', root / 'filtered.pbf'
            source.write_bytes(b'source')
            with patch('scripts.osrm_filter.shutil.which', return_value='/bin/osmium'), patch('scripts.osrm_filter.os.execv') as execute:
                main(['--input', str(source), '--output', str(output)])
            args = execute.call_args.args[1]
            self.assertEqual(args, ['/bin/osmium', 'tags-filter', str(source), 'nw/highway', 'w/route', 'r/type=restriction*', 'r/type=route', 'r/type=maneuver', 'r/type=manoeuvre', 'nw/amenity=fuel', '--output', str(output)])
            self.assertNotIn('--omit-referenced', args)
            self.assertNotIn('--remove-tags', args)
            self.assertEqual(source.read_bytes(), b'source')

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, output = root / 'source.pbf', root / 'filtered.pbf'
            source.write_bytes(b'source')
            output.write_bytes(b'existing')
            with contextlib.redirect_stderr(io.StringIO()), patch('scripts.osrm_filter.os.execv') as execute, self.assertRaises(SystemExit):
                main(['--input', str(source), '--output', str(output)])
            execute.assert_not_called()
            self.assertEqual(output.read_bytes(), b'existing')
