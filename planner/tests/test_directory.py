import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.directory_evidence import OPIS_SOURCE, valid_directory_record
from planner.models import Station

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'AL'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-88, 32], [-86, 32], [-86, 34], [-88, 34], [-88, 32]]]}}
RECORD = {'source': 'https://www.findfuelstops.com/truck-stop-001199', 'name': 'Pilot Travel Center #4555', 'address': 'I-20/I-59 Ex 77, 3201 Buttermilk Rd', 'city': 'Cottondale', 'state': 'AL', 'country': 'US', 'latitude': 33.178943, 'longitude': -87.447519}


class DirectoryTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='PILOT #4555', address='I-59 EXIT 77', city='COTTONDALE', state='AL', rows=[{'Truckstop Name': 'PILOT #4555'}], price=3, price_min=3, price_max=3)

    def check(self, record):
        return valid_directory_record(self.station, record, [record['latitude'], record['longitude']], BOUNDARY)

    def test_location_and_identity_proof(self):
        self.assertTrue(self.check(RECORD))
        for change in ({'name': 'Pilot #4556'}, {'name': 'Shell #4555'}, {'state': 'TX'}, {'city': 'Other'}, {'longitude': -120}, {'latitude': float('nan')}, {'source': 'https://example.com/truck-stop-001199'}, {'address': 'I-59 Ex 78'}, {'address': 'US-59 Ex 77'}, {'address': 'Cottondale'}):
            with self.subTest(change=change):
                self.assertFalse(self.check({**RECORD, **change}))
        self.station.address = '3201 BUTTERMILK ROAD'
        self.assertTrue(self.check(RECORD))
        self.station.address = '3202 BUTTERMILK ROAD'
        self.assertFalse(self.check(RECORD))
        self.station.address = 'I-20 EXIT 77 & I-59 EXIT 78'
        self.assertFalse(self.check({**RECORD, 'address': 'I-59 Ex 77'}))

    def test_directory_cannot_drop_unparsed_road(self):
        self.station.address = 'I-59 EXIT 77 & CO-R6F'
        self.assertFalse(self.check(RECORD))
        self.assertTrue(self.check({**RECORD, 'address': 'I-59 EXIT 77 & CO-R6F'}))
        self.station.address = 'I-59 EXIT 77 & AL-69'
        self.assertFalse(self.check(RECORD))
        self.assertTrue(self.check({**RECORD, 'address': 'I-59 Ex 77 & AL-69'}))
        self.station.address = 'I-59 EXIT 77 & I-20 EXIT 77'
        self.assertFalse(self.check({**RECORD, 'address': 'I-59 EXIT 77 & I-20'}))
        self.assertTrue(self.check({**RECORD, 'address': 'I-59 EXIT 77 & I-20 EXIT 77'}))

    def test_missing_country_retains_other_evidence_requirements(self):
        self.station.address = '3201 BUTTERMILK ROAD'
        record = {key: value for key, value in RECORD.items() if key != 'country'}
        self.assertTrue(self.check(record))
        for country in ('CA', '', None, 1):
            with self.subTest(country=country):
                self.assertFalse(self.check({**record, 'country': country}))
        self.assertFalse(self.check({key: value for key, value in record.items() if key != 'address'}))
        self.assertFalse(self.check({**record, 'longitude': -120}))

    def test_compound_highway_requires_all_routes(self):
        self.station.address = 'I-59 EXIT 77 & US-69'
        self.assertFalse(self.check({**RECORD, 'address': 'I-59 Ex 77'}))
        self.assertTrue(self.check({**RECORD, 'address': 'I-59 Ex 77 & US-69'}))
        self.station.address = 'I-20 EXIT 77 & I-59 EXIT 78'
        self.assertFalse(self.check({**RECORD, 'address': 'I-20 Ex 77 & I-59 Ex 999'}))
        self.assertTrue(self.check({**RECORD, 'address': 'I-20 Ex 77 & I-59 Ex 78'}))

    def test_directory_junction_requires_full_proof_and_exact_ref(self):
        self.station.address = 'I-20 EXIT 77 & US-69'
        point = [RECORD['latitude'], RECORD['longitude']]
        ramp = {'id': 10, 'highway': 'motorway_link', 'destination:ref': 'US 69', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/10'}
        junction = {'id': 8, 'point': point, 'ref': '77', 'old_ref': '', 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'ref': 'I 20', 'highway': 'motorway', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}, 'ramps': [ramp]}
        def check(record=RECORD, junction_value=junction):
            return valid_directory_record(self.station, {'record': record, 'junction': junction_value}, point, BOUNDARY)
        self.assertTrue(check())
        self.assertFalse(check(junction_value={**junction, 'ref': '78'}))
        self.assertFalse(check(junction_value={**junction, 'point': [33.3, -87.447519]}))
        self.assertFalse(check(junction_value={**junction, 'ramps': [{**ramp, 'destination:ref': 'US 69 Alternate'}]}))
        self.assertFalse(check(junction_value={**junction, 'ramps': []}))
        self.assertFalse(check(junction_value=[]))
        self.assertFalse(check(record={**RECORD, 'name': 'Pilot #4556'}))
        self.assertFalse(check(record={**RECORD, 'name': 'Pilot'}))

    def test_unnumbered_directory_name_still_requires_full_junction(self):
        self.station.address = 'I-20 EXIT 77 & US-69'
        self.station.rows = [{'Truckstop Name': 'BIG CABIN TRUCK STOP'}]
        record = {**RECORD, 'name': 'Big Cabin Truck Stop', 'address': '123 Other St'}
        point = [record['latitude'], record['longitude']]
        ramp = {'id': 10, 'highway': 'motorway_link', 'destination:ref': 'US 69', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/10'}
        junction = {'id': 8, 'point': point, 'ref': '77', 'old_ref': '', 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'ref': 'I 20', 'highway': 'motorway', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}, 'ramps': [ramp]}
        self.assertTrue(valid_directory_record(self.station, {'record': record, 'junction': junction}, point, BOUNDARY))
        self.assertFalse(valid_directory_record(self.station, record, point, BOUNDARY))
        self.assertFalse(valid_directory_record(self.station, {'record': record, 'junction': {**junction, 'ref': '78'}}, point, BOUNDARY))
        self.assertFalse(valid_directory_record(self.station, {'record': record, 'junction': {**junction, 'ramps': []}}, point, BOUNDARY))

    def test_directory_junction_resolver_and_import(self):
        self.station.address = 'I-20 EXIT 77 & US-69'
        self.station.save(update_fields=['address'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, roads, output = root / 'source.json', root / 'roads.osm', root / 'evidence.csv'
            source.write_text(json.dumps({'records': [RECORD]}))
            roads.write_text('<osm version="0.6"><node id="8" lat="33.178943" lon="-87.447519"><tag k="highway" v="motorway_junction"/><tag k="ref" v="77"/></node><node id="11" lat="33.179943" lon="-87.447519"><tag k="highway" v="motorway_junction"/><tag k="ref" v="77"/></node><way id="9"><nd ref="8"/><nd ref="11"/><tag k="highway" v="motorway"/><tag k="ref" v="I 20"/></way><way id="10"><nd ref="8"/><nd ref="11"/><tag k="highway" v="motorway_link"/><tag k="destination:ref" v="US 69"/></way></osm>')
            with override_settings(BASE_DIR=root):
                call_command('resolve_directory', input=str(source), pbf=str(roads), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.latitude, RECORD['latitude'])
            self.assertEqual(self.station.evidence['directory_evidence']['junction']['id'], 8)

    def test_wrong_city_does_not_shadow_correct_directory_record(self):
        wrong = {**RECORD, 'source': 'https://www.findfuelstops.com/truck-stop-001200', 'city': 'Other'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'source.json', root / 'evidence.csv'
            source.write_text(json.dumps({'records': [wrong, RECORD]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_directory', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
            with output.open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['source'], RECORD['source'])

    def test_chain_name_formats_require_matching_brand_and_reference(self):
        for source, target in (('PILOT TRAVEL CENTERS #79', 'Pilot Travel Center #79'),
                               ('FLYING J TRAVEL PLAZA #650', 'Flying J #650'),
                               ('PETRO STOPPING CENTER #348', 'Petro #348')):
            with self.subTest(source=source):
                self.station.rows = [{'Truckstop Name': source}]
                self.assertTrue(self.check({**RECORD, 'name': target}))
                self.assertFalse(self.check({**RECORD, 'name': target + ' #999'}))
                self.assertFalse(self.check({**RECORD, 'name': 'One9 #79'}))
                self.assertFalse(self.check({**RECORD, 'name': 'Town Pump #79'}))

    def test_numbered_city_appended_travel_centers(self):
        for source, target in (('PETRO #306', 'Petro Cottondale #0306'), ('TA #306', 'TA Cottondale #0306'), ('TA EXPRESS #306', 'TA Express Cottondale #0306'), ('QUICK FUEL #306', 'QuickFuel Cottondale #0306'), ('TOOT N TOTUM #306', 'Toot N Totum Cottondale #0306')):
            self.station.rows = [{'Truckstop Name': source}]
            with self.subTest(source=source):
                self.assertTrue(self.check({**RECORD, 'name': target}))
                self.assertFalse(self.check({**RECORD, 'name': target.replace('0306', '0307')}))
                self.assertFalse(self.check({**RECORD, 'name': target.replace('Cottondale', 'Other')}))
                self.assertFalse(self.check({**RECORD, 'name': target, 'city': 'Other'}))
                self.assertFalse(self.check({**RECORD, 'name': target, 'address': 'Different street'}))
                self.assertFalse(self.check({**RECORD, 'name': 'Pilot Cottondale #0306'}))

    def test_city_appended_resolver_and_import(self):
        self.station.name = 'QUICK FUEL #306'
        self.station.rows = [{'Truckstop Name': self.station.name}]
        self.station.save(update_fields=['name', 'rows'])
        record = {**RECORD, 'name': 'QuickFuel Cottondale #0306'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'source.json', root / 'evidence.csv'
            source.write_text(json.dumps({'records': [record]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_directory', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.latitude, record['latitude'])

    def test_quick_fuel_published_city_suffix_requires_exact_brand_and_road(self):
        for number, city, road in (('1702', 'Livonia', 'I-96 EXIT 173'), ('2301', 'Cincinnati', 'I-275 EXIT 44'), ('2304', 'Toledo', 'I-75 EXIT 210')):
            with self.subTest(city=city):
                self.station.rows = [{'Truckstop Name': f'QUICK FUEL #{number}'}]
                self.station.city = city
                self.station.address = road
                record = {**RECORD, 'name': f'Quick Fuel-{city} #{number}', 'city': city, 'address': road}
                self.assertTrue(self.check(record))
                self.assertFalse(self.check({**record, 'name': f'QuickStation-{city} #{number}'}))
                self.assertFalse(self.check({**record, 'name': f'Quick Fuel-{city} #999'}))
                self.assertFalse(self.check({**record, 'name': f'Quick Fuel-Other #{number}'}))
                self.assertFalse(self.check({**record, 'address': 'I-1 EXIT 999'}))

    def test_resolve_import_rechecks_context_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            data.mkdir()
            (data / 'us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output, unresolved = root / 'source.json', root / 'evidence.csv', root / 'unresolved.csv'
            source.write_text(json.dumps({'records': [RECORD]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_directory', input=str(source), output=str(output), unresolved=str(unresolved), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.longitude, RECORD['longitude'])
                for field, value in (('source', 'https://example.com'), ('longitude', '-87.4')):
                    altered = dict(rows[0], **{field: value})
                    with output.open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerow(altered)
                    call_command('load_data', 'evidence', str(output), verbosity=0)
                    self.station.refresh_from_db()
                    self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps({'records': [RECORD, {**RECORD, 'source': 'https://www.findfuelstops.com/truck-stop-001200'}]}))
                call_command('resolve_directory', input=str(source), output=str(root / 'ambiguous.csv'), unresolved=str(root / 'missing.csv'), verbosity=0)
                with (root / 'ambiguous.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                with (root / 'missing.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream))[0]['reason'], 'ambiguous_match')
                source.write_text(json.dumps({'records': [RECORD]}))
                Station.objects.create(source_id='2', name='PILOT #4555', address='I-20 EXIT 77', city='COTTONDALE', state='AL', rows=[{'Truckstop Name': 'PILOT #4555'}], price=3, price_min=3, price_max=3)
                call_command('resolve_directory', input=str(source), output=str(root / 'owned.csv'), unresolved=str(root / 'owners.csv'), verbosity=0)
                with (root / 'owned.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                with (root / 'owners.csv').open(newline='') as stream:
                    self.assertEqual([row['reason'] for row in csv.DictReader(stream)], ['ambiguous_match', 'ambiguous_match'])

    def test_opis_exact_id_address_and_raw_import(self):
        self.station.source_id = '77'
        self.station.save(update_fields=['source_id'])
        record = {'id': '00077', 'name': 'PILOT #42', 'address': '123 Main St', 'address2': self.station.address, 'city': 'Cottondale', 'state': 'AL', 'country': 'USA', 'latitude': 33.178943, 'longitude': -87.447519, 'source': OPIS_SOURCE}
        self.station.rows = [{'Truckstop Name': 'PILOT #42'}]
        self.station.name = 'PILOT #42'
        self.station.save(update_fields=['name', 'rows'])
        point = [record['latitude'], record['longitude']]
        self.assertTrue(valid_directory_record(self.station, record, point, BOUNDARY))
        for change in ({'id': '78'}, {'name': 'PILOT #43'}, {'name': 'SHELL #42'}, {'address2': self.station.address + ' BUS'}, {'city': 'Other'}, {'source': 'https://example.com'}, {'longitude': -90}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(valid_directory_record(self.station, {**record, **change}, point, BOUNDARY))
        other = Station.objects.create(source_id='78', name='PILOT #43', address='I-20 EXIT 78', city='COTTONDALE', state='AL', rows=[{'Truckstop Name': 'PILOT #43'}], price=3, price_min=3, price_max=3)
        second = {**record, 'id': '00078', 'name': 'PILOT #43', 'address2': other.address}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'source.json', root / 'evidence.csv'
            source.write_text(json.dumps({'records': [record, second]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_directory', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 2)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                other.refresh_from_db()
                self.assertEqual((self.station.latitude, other.latitude), (point[0], point[0]))
                self.assertEqual(self.station.evidence['matched_address'], self.station.address)
                rows[0]['longitude'] = '-87.4'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps({'records': [record, {**record, 'id': '77'}]}))
                call_command('resolve_directory', input=str(source), output=str(root / 'duplicate.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with (root / 'duplicate.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
