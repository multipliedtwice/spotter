import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.ambest_evidence import SOURCE, valid_ambest_record
from planner.models import Station

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'IA'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-95, 42], [-93, 42], [-93, 44], [-95, 44], [-95, 42]]]}}
RAW = {'id': 11086, 'internal_id': None, 'name': 'Chrome Truck Stop', 'directory_address': 'US Hwy 18/US Hwy 169', 'city': 'Algona', 'state_in_sort': None, 'state': 'IA', 'zip': '50511', 'lat': '43.0839', 'long': '-94.235399'}
POINT = [43.0839, -94.235399]


def way(identifier, ref, other):
    return {'id': str(identifier), 'canonical_url': f'https://www.openstreetmap.org/way/{identifier}', 'tags': {'highway': 'primary', 'ref': ref}, 'node_ids': ['100', str(other)], 'geometry': [{'id': '100', 'lat': '43.0827926', 'lon': '-94.2362238', 'tags': {}}, {'id': str(other), 'lat': '43.0828', 'lon': '-94.237', 'tags': {}}]}


PROOF = {'node_id': '100', 'canonical_url': 'https://www.openstreetmap.org/node/100', 'latitude': '43.0827926', 'longitude': '-94.2362238', 'node_tags': {}, 'route_ways': [way(11, 'US 18', 101), way(12, 'US 169', 102)]}


class AmbestTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='3460', name='CHROME TRUCK STOP', address='US-18 & US-169', city='ALGONA', state='IA', rows=[{'Truckstop Name': 'CHROME TRUCK STOP'}], price=3, price_min=3, price_max=3)

    def check(self, raw=RAW, proof=PROOF):
        return valid_ambest_record(self.station, {'source': SOURCE, 'record': raw, 'intersection': proof}, POINT, BOUNDARY)

    def test_connected_intersection_requires_all_source_facts(self):
        self.assertTrue(self.check())
        self.assertFalse(valid_ambest_record(self.station, {'source': SOURCE, 'record': RAW}, POINT, BOUNDARY))
        for replacement in ({'node_id': '101'}, {'latitude': '43.09'}, {'canonical_url': 'https://example.com/node/100'}, {'route_ways': [PROOF['route_ways'][0], way(12, 'US 170', 102)]}, {'route_ways': [PROOF['route_ways'][0], way(12, 'US 169 ALT', 102)]}, {'route_ways': [PROOF['route_ways'][0], way(11, 'US 169', 102)]}):
            self.assertFalse(self.check(proof={**PROOF, **replacement}))
        self.assertFalse(self.check(raw={**RAW, 'lat': '43.09'}))
        self.assertFalse(self.check(raw={**RAW, 'lat': 'nan'}))
        self.assertFalse(self.check(raw={**RAW, 'city': 'Other'}))
        self.assertFalse(self.check(raw={**RAW, 'state': 'IL'}))
        self.assertFalse(self.check(raw={**RAW, 'name': 'Other Truck Stop'}))
        self.assertFalse(self.check(raw={**RAW, 'name': 'Chrome Truck Stops'}))
        self.assertFalse(self.check(raw={**RAW, 'name': 'Chrome Truck Stop #3460'}))
        self.assertFalse(self.check(raw={**RAW, 'id': True}))
        self.station.address = 'US-18 & US-169 BUS'
        self.assertFalse(self.check())
        self.station.address = 'US-18'
        self.assertFalse(self.check())

    def test_exit_and_street_need_full_business_identity(self):
        self.station.address = 'I-40 EXIT 12'
        raw = {**RAW, 'directory_address': 'I-40 Exit 12'}
        self.assertTrue(valid_ambest_record(self.station, {'source': SOURCE, 'record': raw}, POINT, BOUNDARY))
        self.assertFalse(valid_ambest_record(self.station, {'source': SOURCE, 'record': {**raw, 'directory_address': 'I-40 Exit 13'}}, POINT, BOUNDARY))
        self.station.rows.append({'Truckstop Name': 'OTHER #1'})
        self.assertFalse(valid_ambest_record(self.station, {'source': SOURCE, 'record': raw}, POINT, BOUNDARY))

    def test_truckstop_spacing_only_and_resolver_import(self):
        from planner.ambest_evidence import name_key
        self.assertEqual(name_key("Grady's Truck Stop"), name_key('GRADYS TRUCKSTOP'))
        self.assertNotEqual(name_key('CHROMETRUCKSTOP'), name_key('CHROME TRUCKSTOP'))
        self.station.source_id, self.station.name = '4372', 'GRADYS TRUCKSTOP'
        self.station.address, self.station.city, self.station.state = 'I-16, EXIT 111', 'PULASKI', 'GA'
        self.station.rows = [{'Truckstop Name': 'GRADYS TRUCKSTOP'}]
        self.station.save()
        raw = {'id': 11184, 'internal_id': None, 'name': "Grady's Truck Stop", 'directory_address': 'I-16 Exit 111', 'city': 'Pulaski', 'state_in_sort': None, 'state': 'GA', 'zip': '30439', 'lat': '32.33606', 'long': '-81.952879'}
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'GA'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-83, 31], [-81, 31], [-81, 33], [-83, 33], [-83, 31]]]}}
        self.assertTrue(valid_ambest_record(self.station, {'source': SOURCE, 'record': raw}, [32.33606, -81.952879], boundary))
        self.assertFalse(valid_ambest_record(self.station, {'source': SOURCE, 'record': {**raw, 'name': "Grady's Truck Stop #1"}}, [32.33606, -81.952879], boundary))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
            source, output = root / 'data/source_ambest_locations.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': SOURCE, 'records': [raw]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_ambest', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual([self.station.latitude, self.station.longitude], [32.33606, -81.952879])

    def test_resolve_import_and_native_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            asset = {'source': SOURCE, 'records': [RAW]}
            source = root / 'data/source_ambest_locations.json'
            source.write_text(json.dumps(asset))
            proof = root / 'proof.json'
            proof.write_text(json.dumps({'records': [PROOF]}))
            output = root / 'evidence.csv'
            with override_settings(BASE_DIR=root):
                call_command('resolve_ambest', input=str(source), intersections=str(proof), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], POINT)
                context = json.loads(rows[0]['directory_evidence'])
                context['record']['id'] = 1
                rows[0]['directory_evidence'] = json.dumps(context)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)

    def test_rejects_wrong_source_number_and_disconnected_proofs(self):
        self.station.rows = [{'Truckstop Name': 'CHROME TRUCK STOP #5'}]
        self.assertFalse(self.check())
        self.station.rows = [{'Truckstop Name': 'CHROME TRUCK STOP'}]
        disconnected = way(12, 'US 169', 102)
        disconnected['node_ids'][0] = '200'
        disconnected['geometry'][0]['id'] = '200'
        self.assertFalse(self.check(proof={**PROOF, 'route_ways': [PROOF['route_ways'][0], disconnected]}))
        self.assertFalse(self.check(proof={**PROOF, 'route_ways': [PROOF['route_ways'][0], way(12, 'SR 169', 102)]}))
        self.assertFalse(self.check(proof={**PROOF, 'latitude': '40.0'}))
        self.assertFalse(self.check(proof={**PROOF, 'latitude': '45.0'}))
        self.assertFalse(valid_ambest_record(self.station, {'source': 'https://example.com', 'record': RAW, 'intersection': PROOF}, POINT, BOUNDARY))
        self.assertFalse(valid_ambest_record(self.station, {'source': SOURCE, 'record': RAW, 'identity_only': True}, POINT, BOUNDARY))
        self.assertFalse(valid_ambest_record(self.station, {'source': SOURCE, 'record': RAW, 'intersection': PROOF}, [43.084, -94.235399], BOUNDARY))

    def test_duplicate_native_points_ids_and_source_owners_are_held(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, proof = root / 'stores.json', root / 'proof.json'
            proof.write_text(json.dumps({'records': [PROOF]}))
            with override_settings(BASE_DIR=root):
                for index, records in enumerate(([RAW, {**RAW, 'id': 42, 'name': 'Another Business'}], [RAW, {**RAW, 'lat': '43.08'}])):
                    source.write_text(json.dumps({'source': SOURCE, 'records': records}))
                    output = root / f'evidence-{index}.csv'
                    call_command('resolve_ambest', input=str(source), intersections=str(proof), output=str(output), unresolved=str(root / f'missing-{index}.csv'), verbosity=0)
                    with output.open(newline='') as stream:
                        self.assertEqual(list(csv.DictReader(stream)), [])
                Station.objects.create(source_id='other', name='CHROME TRUCK STOP', address=self.station.address, city=self.station.city, state=self.station.state, rows=self.station.rows, price=4, price_min=4, price_max=4)
                source.write_text(json.dumps({'source': SOURCE, 'records': [RAW]}))
                output = root / 'owners.csv'
                call_command('resolve_ambest', input=str(source), intersections=str(proof), output=str(output), unresolved=str(root / 'owners-missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
