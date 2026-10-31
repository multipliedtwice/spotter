import contextlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase
from scripts.osrm_native import main


class NativeOsrmTests(SimpleTestCase):
    def test_custom_directory_prepares_and_serves_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, graph = root / 'source.pbf', root / 'card' / 'graph'
            source.write_bytes(b'sample')
            graph.parent.mkdir()
            main(['prepare', '--input', str(source), '--data-dir', str(graph)])
            self.assertEqual((graph / 'region.osm.pbf').read_bytes(), b'sample')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['prepare', '--input', str(source), '--data-dir', str(graph)])
            self.assertEqual((graph / 'region.osm.pbf').read_bytes(), b'sample')
            for suffix in ('.ebg', '.partition', '.cell_metrics'):
                (graph / f'region.osrm{suffix}').touch()
            with patch('scripts.osrm_native.shutil.which', return_value='/bin/osrm-routed'), patch('scripts.osrm_native.os.execv') as execute:
                main(['serve', '--data-dir', str(graph)])
            args = execute.call_args.args[1]
            self.assertIn(str(graph / 'region.osrm'), args)
            self.assertIn('--mmap', args)
            self.assertEqual(args[args.index('--port') + 1], '5050')

    def test_custom_directory_requires_existing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'source.pbf'
            source.write_bytes(b'sample')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['prepare', '--input', str(source), '--data-dir', str(root / 'missing' / 'graph')])
            self.assertFalse((root / 'missing').exists())

    def test_prepare_hard_link_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, graph = root / 'source.pbf', root / 'graph'
            source.write_bytes(b'sample')
            main(['prepare', '--input', str(source), '--data-dir', str(graph), '--link-input'])
            linked = graph / 'region.osm.pbf'
            self.assertEqual(source.stat().st_ino, linked.stat().st_ino)
            self.assertEqual(source.stat().st_dev, linked.stat().st_dev)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['prepare', '--input', str(source), '--data-dir', str(graph), '--link-input'])
            linked.unlink()
            self.assertEqual(source.read_bytes(), b'sample')

    def test_link_input_rejected_outside_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['partition', '--data-dir', str(root / 'graph'), '--link-input'])

    def test_profile_rejected_for_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'source.pbf'
            source.write_bytes(b'sample')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['prepare', '--input', str(source), '--profile', str(root / 'car.lua'), '--data-dir', str(root / 'graph')])
            self.assertFalse((root / 'graph').exists())
