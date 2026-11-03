import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import valid_operator_record
from planner.roadranger_evidence import BILLING_SOURCE, LOCATOR_SOURCE

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'IN'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-88, 41], [-87, 41], [-87, 42], [-88, 42], [-88, 41]]]}}
STORE = {'source': LOCATOR_SOURCE, 'billing': {'number': '240', 'address': '2151 Ripley, Lake Station IN', 'city': 'Lake Station', 'state': 'IN', 'zip': None, 'opis': '01590', 'source': BILLING_SOURCE}, 'locator': {'number': None, 'address': '2151 Ripley, Lake Station IN', 'city': 'Lake Station', 'state': 'IN', 'zip': None, 'latitude': 41.578516978978, 'longitude': -87.239649134988, 'source': LOCATOR_SOURCE}}


class RoadRangerTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1590', name='ROAD RANGER #240', address='I-80 EXIT 15', city='LAKE STATION', state='IN', rows=[{'Truckstop Name': 'ROAD RANGER #240'}], price=3, price_min=3, price_max=3)

    def check(self, store=STORE, **extra):
        return valid_operator_record(self.station, {'store': store, 'identity_only': True, **extra}, [STORE['locator']['latitude'], STORE['locator']['longitude']], BOUNDARY)

    def test_raw_pair_and_source_identity(self):
        self.assertTrue(self.check())
        self.station.city = 'LAKESTATION'
        self.assertTrue(self.check())
        self.station.city = 'OTHER CITY'
        self.assertFalse(self.check())
        self.station.city = 'LAKE STATION'
        for change in ({'number': '241'}, {'opis': '01591'}, {'city': 'Other'}, {'state': 'IL'}, {'address': '2152 Ripley, Lake Station IN'}, {'source': 'https://example.com'}, {'zip': '12345'}):
            with self.subTest(change=change):
                self.assertFalse(self.check({**STORE, 'billing': {**STORE['billing'], **change}}))
        for change in ({'latitude': float('nan')}, {'city': 'Other'}, {'address': '2152 Ripley, Lake Station IN'}, {'source': 'https://example.com'}, {'number': '240'}):
            self.assertFalse(self.check({**STORE, 'locator': {**STORE['locator'], **change}}))
        self.assertFalse(self.check(identity_only=False))
        self.assertFalse(self.check(junction={}))
        self.station.rows = [{'Truckstop Name': 'SHELL #240'}]
        self.assertFalse(self.check())
        self.station.rows = [{'Truckstop Name': 'ROAD RANGERS #240'}]
        self.assertTrue(self.check())
        self.station.rows = [{'Truckstop Name': 'ROAD RANGER #241'}]
        self.assertFalse(self.check())

    def test_resolver_import_and_duplicate_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_roadranger', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], STORE['locator']['address'])
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                raw = json.loads(rows[0]['operator_evidence'])
                raw['store']['locator']['longitude'] = -87.3
                rows[0]['operator_evidence'] = json.dumps(raw)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                duplicate = {**STORE, 'billing': {**STORE['billing'], 'number': '241', 'opis': None}}
                source.write_text(json.dumps({'stores': [STORE, duplicate]}))
                call_command('resolve_roadranger', input=str(source), output=str(root / 'duplicates.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with (root / 'duplicates.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                duplicate = {**duplicate, 'locator': {**duplicate['locator'], 'latitude': 41.58}}
                source.write_text(json.dumps({'stores': [STORE, duplicate]}))
                call_command('resolve_roadranger', input=str(source), output=str(root / 'same-address.csv'), unresolved=str(root / 'same-address-missing.csv'), verbosity=0)
                with (root / 'same-address.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
