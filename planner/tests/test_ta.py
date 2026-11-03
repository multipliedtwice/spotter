import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import valid_operator_record

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'TN'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-85, 35], [-83, 35], [-83, 37], [-85, 37], [-85, 35]]]}}
STORE = {'number': '0333', 'name': 'TA Knoxville East #0333', 'address': '123 Main Street', 'city': 'Knoxville', 'state': 'TN', 'latitude': 36.0, 'longitude': -84.0, 'highway': 'A TA Petro truckstop at I-40, Exit 12', 'source': 'https://www.ta-petro.com/location/tn/ta-knoxville-east/'}


class TAOperatorTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='TA KNOXVILLE EAST TRAVEL CENTER #333', address='I-40 EXIT 12', city='KNOXVILLE', state='TN', rows=[{'Truckstop Name': 'TA KNOXVILLE EAST TRAVEL CENTER #333'}], price=3, price_min=3, price_max=3)

    def valid(self, store=STORE, **context):
        return valid_operator_record(self.station, {'store': store, **context}, [36.0, -84.0], BOUNDARY)

    def test_numbered_source_and_conflicts(self):
        self.assertTrue(self.valid())
        for change in ({'number': '334'}, {'name': 'TA Knoxville East #334'}, {'name': 'Petro Knoxville East #333'}, {'city': 'Other'}, {'state': 'KY'}, {'source': 'https://example.com/location/tn/site/'}, {'source': 'https://www.ta-petro.com/location/ky/site/'}, {'latitude': float('nan')}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.valid({**STORE, **change}))
        self.station.rows = [{'Truckstop Name': 'TA KNOXVILLE EAST #334'}]
        self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'PETRO SERVE USA #333'}]
        self.assertFalse(self.valid())

    def test_unnumbered_full_branch_and_independent_proof(self):
        self.station.rows = [{'Truckstop Name': 'TA KNOXVILLE EAST TRAVEL CENTER'}]
        self.assertTrue(self.valid())
        for name in ('TA', 'TA KNOXVILLE', 'TA KNOXVILLE WEST', 'TA EXPRESS KNOXVILLE EAST', 'PETRO KNOXVILLE EAST'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'TA KNOXVILLE EAST TRAVEL CENTER'}]
        self.station.address = 'I-40'
        self.assertFalse(self.valid())
        self.station.address = '123 MAIN ST'
        self.assertTrue(self.valid())
        self.station.address = 'I-40 EXIT 12 & US-25'
        self.assertFalse(self.valid())
        junction = {'id': 8, 'point': [36.0, -84.0], 'ref': '12', 'old_ref': '', 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'highway': 'motorway', 'ref': 'I 40;US 25', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}, 'ramps': []}
        self.assertTrue(self.valid(junction=junction))
        self.assertFalse(self.valid(junction={**junction, 'road': {**junction['road'], 'ref': 'I 40'}}))

    def test_published_exit_requires_full_intersection(self):
        self.station.address = 'I-40 EXIT 12 & US-25'
        self.assertFalse(self.valid())
        self.assertTrue(self.valid({**STORE, 'highway': 'I-40 EXIT 12 & US-25'}))

    def test_identity_only_requires_numbered_source(self):
        self.station.address = 'I-40 EXIT 99'
        self.assertTrue(self.valid(identity_only=True))
        self.station.rows = [{'Truckstop Name': 'TA KNOXVILLE EAST TRAVEL CENTER'}]
        self.assertFalse(self.valid(identity_only=True))

    def test_unnumbered_resolve_import_and_ownership(self):
        self.station.rows = [{'Truckstop Name': 'TA KNOXVILLE EAST TRAVEL CENTER'}]
        self.station.save(update_fields=['rows'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_ta', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.latitude, 36.0)
                raw = json.loads(rows[0]['operator_evidence'])
                raw['store']['number'] = '334'
                rows[0]['operator_evidence'] = json.dumps(raw)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                Station.objects.create(source_id='2', name='TA KNOXVILLE EAST', address='I-40 EXIT 12', city='KNOXVILLE', state='TN', rows=[{'Truckstop Name': 'TA KNOXVILLE EAST'}], price=3, price_min=3, price_max=3)
                call_command('resolve_ta', input=str(source), output=str(root / 'duplicate.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with (root / 'duplicate.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])

    def test_malformed_operator_row_does_not_block_valid_row(self):
        other = Station.objects.create(source_id='2', name='TA #334', address='I-40 EXIT 13', city='KNOXVILLE', state='TN', rows=[{'Truckstop Name': 'TA #334'}], price=3, price_min=3, price_max=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_ta', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                malformed = {**rows[0], 'station_id': other.source_id, 'address': other.address, 'operator_evidence': json.dumps({'store': []})}
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows([rows[0], malformed])
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                other.refresh_from_db()
                self.assertEqual(self.station.latitude, 36.0)
                self.assertIsNone(other.latitude)
