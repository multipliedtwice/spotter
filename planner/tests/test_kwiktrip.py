import csv
import json
import math
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.core import distance as distance_miles
from planner.management.commands.resolve_kwiktrip import nearby_junctions
from planner.kwiktrip_evidence import SOURCE, valid_operator_record
from planner.models import Station

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'WI'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-92, 43], [-88, 43], [-88, 46], [-92, 46], [-92, 43]]]}}
STORE = {'number': '247', 'name': 'KWIK TRIP #247', 'address': '123 Main Street', 'city': 'Town', 'state': 'WI', 'latitude': 44.0, 'longitude': -90.0, 'sells_gas': True, 'sells_diesel': False, 'source': SOURCE}
JUNCTION = {'id': 8, 'point': [44.0, -90.0], 'ref': '42', 'old_ref': '', 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'highway': 'motorway', 'ref': 'I 90', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}, 'ramps': []}


class KwikTripTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='KWIK TRIP #247', address='123 MAIN ST', city='TOWN', state='WI', rows=[{'Truckstop Name': 'KWIK TRIP #247'}], price=3, price_min=3, price_max=3)

    def valid(self, store=STORE, junction=None):
        context = {'store': store}
        if junction is not None:
            context['junction'] = junction
        return valid_operator_record(self.station, context, [44.0, -90.0], BOUNDARY)

    def test_nearby_junction_distance_limits(self):
        point = [44.0, -90.0]
        near = {'point': [44.01, -90.0]}
        middle = {'point': [44.04, -90.0]}
        far = {'point': [44.1, -90.0]}
        grid = {(440, -900): [near, middle], (441, -900): [far]}
        self.assertEqual(list(nearby_junctions(grid, point, max_distance=1)), [near])
        self.assertEqual(list(nearby_junctions(grid, point)), [near, middle])
        boundary = distance_miles(point, middle['point'])
        self.assertEqual(list(nearby_junctions(grid, point, max_distance=boundary)), [near, middle])
        self.assertEqual(list(nearby_junctions(grid, point, max_distance=math.nextafter(boundary, 0))), [near])
        distant = {'point': [44.31, -90.0]}
        self.assertEqual(list(nearby_junctions({(443, -900): [distant]}, point, max_distance=25)), [distant])

    def test_street_identity_and_junction_proof(self):
        self.assertTrue(self.valid())
        for change in ({'name': 'KWIK STAR #247'}, {'name': 'KWIK TRIP #248'}, {'number': '248'}, {'address': '124 Main Street'}, {'state': 'IA'}, {'source': 'https://example.com'}, {'latitude': float('nan')}, {'sells_gas': False}, {'sells_gas': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.valid({**STORE, **change}))
        self.station.rows.append({'Truckstop Name': 'KWIK TRIP #248'})
        self.assertFalse(self.valid())
        self.station.rows.pop()
        self.station.address = 'I-90 EXIT 42'
        self.assertFalse(self.valid())
        self.assertTrue(self.valid(junction=JUNCTION))
        self.assertFalse(self.valid(junction={**JUNCTION, 'ref': '43'}))
        self.assertFalse(self.valid(junction={**JUNCTION, 'road': {**JUNCTION['road'], 'ref': 'I 90W'}}))
        self.assertFalse(self.valid(junction={**JUNCTION, 'road': {**JUNCTION['road'], 'nodes': [7]}}))

    def test_resolver_import_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, out, unresolved = root / 'stores.json', root / 'evidence.csv', root / 'missing.csv'
            source.write_text(json.dumps({'source': SOURCE, 'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_kwiktrip', input=str(source), output=str(out), unresolved=str(unresolved), verbosity=0)
                with out.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertNotIn('identity_only', json.loads(rows[0]['operator_evidence']))
                call_command('load_data', 'evidence', str(out), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.latitude, 44.0)
                for change in ({'source': 'https://example.com'}, {'longitude': '-90.1'}):
                    with out.open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerow({**rows[0], **change})
                    call_command('load_data', 'evidence', str(out), verbosity=0)
                    self.station.refresh_from_db()
                    self.assertIsNone(self.station.latitude)
                Station.objects.create(source_id='2', name='KWIK TRIP #247', address='123 MAIN ST', city='TOWN', state='WI', rows=[{'Truckstop Name': 'KWIK TRIP #247'}], price=3, price_min=3, price_max=3)
                call_command('resolve_kwiktrip', input=str(source), output=str(root / 'other.csv'), unresolved=str(root / 'ambiguous.csv'), verbosity=0)
                with (root / 'other.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                with (root / 'ambiguous.csv').open(newline='') as stream:
                    self.assertEqual([row['reason'] for row in csv.DictReader(stream)], ['ambiguous_match', 'ambiguous_match'])

    def test_road_extract_resolves_and_imports_operator_point(self):
        self.station.address = 'I-90 EXIT 42'
        self.station.save(update_fields=['address'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, roads, out, unresolved = root / 'stores.json', root / 'roads.osm', root / 'evidence.csv', root / 'missing.csv'
            source.write_text(json.dumps({'source': SOURCE, 'stores': [STORE]}))
            roads.write_text('<osm version="0.6"><node id="8" lat="44" lon="-90"><tag k="highway" v="motorway_junction"/><tag k="ref" v="42"/></node><way id="9"><nd ref="8"/><tag k="highway" v="motorway"/><tag k="ref" v="I 90"/></way></osm>')
            with override_settings(BASE_DIR=root):
                call_command('resolve_kwiktrip', input=str(source), pbf=str(roads), output=str(out), unresolved=str(unresolved), verbosity=0)
                call_command('load_data', 'evidence', str(out), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.longitude, -90.0)
            self.assertEqual(self.station.evidence['operator_evidence']['junction']['id'], 8)

    def test_identity_only_fallback_and_import(self):
        self.station.address = 'I-90 EXIT 99'
        self.station.save(update_fields=['address'])
        point = [44.0, -90.0]
        context = {'store': STORE, 'identity_only': True}
        self.assertTrue(valid_operator_record(self.station, context, point, BOUNDARY))
        self.station.city = 'MC CALLA'
        self.assertTrue(valid_operator_record(self.station, {'store': {**STORE, 'city': 'McCalla'}, 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': {**STORE, 'city': 'Other'}, 'identity_only': True}, point, BOUNDARY))
        self.station.city = 'TOWN'
        for change in ({'number': '248'}, {'name': 'KWIK STAR #247'}, {'city': 'Other'}, {'state': 'IA'}, {'source': 'https://example.com'}, {'sells_gas': False}, {'latitude': float('nan')}):
            with self.subTest(change=change):
                self.assertFalse(valid_operator_record(self.station, {'store': {**STORE, **change}, 'identity_only': True}, point, BOUNDARY))
        for change in ({'identity_only': False}, {'identity_only': 1}, {'junction': JUNCTION}, {'roads': []}, {'approved_primary_exit': True}):
            self.assertFalse(valid_operator_record(self.station, {**context, **change}, point, BOUNDARY))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': SOURCE, 'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_kwiktrip', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertTrue(json.loads(rows[0]['operator_evidence'])['identity_only'])
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], STORE['address'])
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], self.station.address)
                context = json.loads(rows[0]['operator_evidence'])
                context['store']['number'] = '248'
                rows[0]['operator_evidence'] = json.dumps(context)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
