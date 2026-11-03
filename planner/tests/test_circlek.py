import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import CIRCLEK_SOURCE, valid_operator_record
from planner.osm_evidence import valid_context

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'KY'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-88, 37], [-87, 37], [-87, 39], [-88, 39], [-88, 37]]]}}
STORE = {'id': '4700095', 'brand': 'CIRCLEK', 'publicBrand': 'CIRCLEK', 'latitude': 37.883641, 'longitude': -87.563736, 'address': {'street': '3113 Hwy 41 N', 'city': 'Henderson', 'state': 'KY', 'postalCode': '42420-2054', 'country': 'US'}, 'source': f'{CIRCLEK_SOURCE}/4700095'}


class CircleKTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='CIRCLE K #4700095', address='3113 HWY 41 N', city='HENDERSON', state='KY', rows=[{'Truckstop Name': 'CIRCLE K #4700095'}], price=3, price_min=3, price_max=3)

    def check(self, store=STORE):
        return valid_operator_record(self.station, {'store': store}, [STORE['latitude'], STORE['longitude']], BOUNDARY)

    def test_raw_record_identity_and_address(self):
        self.assertTrue(self.check())
        for change in ({'id': '4700096'}, {'source': f'{CIRCLEK_SOURCE}/4700096'}, {'brand': 'OTHER'}, {'publicBrand': 'OTHER'}, {'latitude': float('nan')}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.check({**STORE, **change}))
        for change in ({'city': 'Other'}, {'state': 'IN'}, {'country': 'CA'}, {'street': '3114 Hwy 41 N'}):
            self.assertFalse(self.check({**STORE, 'address': {**STORE['address'], **change}}))
        self.station.address = 'US-41'
        self.assertFalse(self.check())
        self.assertTrue(self.check({**STORE, 'address': {**STORE['address'], 'street': '3113 US Highway 41 N'}}))
        self.station.address = 'US-41/60'
        self.assertFalse(self.check({**STORE, 'address': {**STORE['address'], 'street': '3113 US Highway 41 N'}}))

    def test_identity_only_requires_exact_api_identity(self):
        self.station.address = 'I-69 EXIT 99'
        point = [STORE['latitude'], STORE['longitude']]
        context = {'store': STORE, 'identity_only': True}
        self.assertTrue(valid_operator_record(self.station, context, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': {**STORE, 'id': '4700096'}, 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': STORE, 'identity_only': True, 'roads': []}, point, BOUNDARY))

    def test_junction_proof_requires_membership_and_exit(self):
        self.station.address = 'I-69 EXIT 12'
        junction = {'id': 8, 'point': [37.883641, -87.563736], 'ref': '12', 'old_ref': '', 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'highway': 'motorway', 'ref': 'I 69', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}, 'ramps': []}
        self.assertTrue(valid_operator_record(self.station, {'store': STORE, 'junction': junction}, [STORE['latitude'], STORE['longitude']], BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': STORE, 'junction': {**junction, 'ref': '13'}}, [STORE['latitude'], STORE['longitude']], BOUNDARY))
        distant = {**junction, 'point': [37.923641, -87.563736]}
        self.assertTrue(valid_operator_record(self.station, {'store': STORE, 'junction': distant}, [STORE['latitude'], STORE['longitude']], BOUNDARY))
        context = {'type': 'node', 'id': 1, 'geometry': {'type': 'Point', 'coordinates': [STORE['longitude'], STORE['latitude']]}, 'tags': {'amenity': 'fuel', 'name': 'Circle K', 'ref': '4700095', 'addr:city': 'Henderson'}, 'junction': distant}
        self.assertFalse(valid_context(self.station, context, [STORE['latitude'], STORE['longitude']], BOUNDARY, []))

    def test_named_roads_require_all_valid_nearby_ways(self):
        self.station.address = 'I-69 & US-41'
        def way(identifier, ref, latitude=37.8837):
            return {'id': identifier, 'url': f'https://www.openstreetmap.org/way/{identifier}', 'tags': {'highway': 'primary', 'ref': ref}, 'nodes': [identifier, identifier + 1], 'geometry': [[latitude, -87.57], [latitude, -87.56]]}
        first, second = way(10, 'I 69'), way(20, 'US 41')
        point = [STORE['latitude'], STORE['longitude']]
        def valid(roads):
            return valid_operator_record(self.station, {'store': STORE, 'roads': roads}, point, BOUNDARY)
        self.assertTrue(valid([first, second]))
        self.assertFalse(valid([first]))
        self.assertFalse(valid([first, way(20, 'HWY 41')]))
        self.assertFalse(valid([first, way(20, 'US 41 BUS')]))
        self.assertFalse(valid([first, way(20, 'US 41', 38.0)]))
        self.assertFalse(valid([first, {**second, 'nodes': [20]}]))
        self.assertFalse(valid([first, {**second, 'url': 'https://example.com/way/20'}]))
        self.assertFalse(valid([first, {**second, 'geometry': [[float('nan'), -87.57], [37.8837, -87.56]]}]))
        narrow = {'type': 'Polygon', 'coordinates': [[[-87.57, 37.88], [-87.56, 37.88], [-87.56, 37.88365], [-87.57, 37.88365], [-87.57, 37.88]]]}
        self.assertFalse(valid_operator_record(self.station, {'store': STORE, 'roads': [first, second]}, point, narrow))
        self.station.address = 'I-69 & US-41 ALT'
        self.assertFalse(valid([first, second]))

    def test_road_asset_resolves_and_imports_scope(self):
        self.station.address = 'US-41'
        self.station.save(update_fields=['address'])
        way = {'id': 10, 'url': 'https://www.openstreetmap.org/way/10', 'tags': {'highway': 'primary', 'ref': 'US 41'}, 'nodes': [10, 11], 'geometry': [[37.8837, -87.57], [37.8837, -87.56]]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, roads, output = root / 'stores.json', root / 'roads.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': CIRCLEK_SOURCE, 'stores': [STORE]}))
            roads.write_text(json.dumps({'ways': [way]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_circlek', input=str(source), roads=str(roads), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.latitude, STORE['latitude'])
            self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_and_nearby_named_roads')

    def test_resolver_import_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': CIRCLEK_SOURCE, 'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_circlek', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['matched_name'], 'Circle K')
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.latitude, STORE['latitude'])
                self.assertEqual(self.station.evidence['operator_evidence']['store'], STORE)
                rows[0]['longitude'] = '-87.5'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                Station.objects.create(source_id='2', name='CIRCLE K #4700095', address='3113 HWY 41 N', city='HENDERSON', state='KY', rows=[{'Truckstop Name': 'CIRCLE K #4700095'}], price=3, price_min=3, price_max=3)
                call_command('resolve_circlek', input=str(source), output=str(root / 'duplicate.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with (root / 'duplicate.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
