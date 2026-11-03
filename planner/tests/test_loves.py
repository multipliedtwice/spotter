import csv
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from planner.management.commands.resolve_loves import match_store
from planner.models import Station

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'IL'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-91, 40], [-89, 40], [-89, 42], [-91, 42], [-91, 40]]]}}
STORE = {'number': 766, 'latitude': 41.410645, 'longitude': -90.016349, 'address1': '5 South State Street', 'city': 'Atkinson', 'state': 'IL', 'highway': 'I-80', 'exitNumber': '27/State St', 'isLoveStore': True, 'isCountryStore': False}


class LovesResolverTests(TestCase):
    def station(self, source_id='135', name='LOVES TRAVEL STOP #766'):
        return Station.objects.create(source_id=source_id, name=name, address='I-80, EXIT 27', city='ATKINSON', state='IL', rows=[{'Truckstop Name': name}], price=3, price_min=3, price_max=3)

    def test_requires_independent_location_identity_and_state(self):
        station = self.station()
        result = match_store(station, STORE, BOUNDARY)
        self.assertEqual(result['matched_name'], "Love's #766")
        self.assertEqual(result['matched_address'], 'I-80 EXIT 27/State St')
        self.assertEqual(result['place_id'], '766')
        for change in ({'exitNumber': '28'}, {'state': 'IA'}, {'city': 'Other'}, {'number': 767}, {'longitude': -120}, {'isLoveStore': False}, {'latitude': float('nan')}):
            self.assertIsNone(match_store(station, {**STORE, **change}, BOUNDARY))
        station.rows = [{'Truckstop Name': 'LOVES TRAVEL STOP'}]
        self.assertIsNone(match_store(station, STORE, BOUNDARY))

    def test_padded_store_number_and_country_store_import(self):
        station = self.station(name='LOVES TRAVEL STOP #046')
        store = {**STORE, 'number': 46}
        self.assertIsNotNone(match_store(station, store, BOUNDARY))
        station.rows = [{'Truckstop Name': 'LOVES COUNTRY STORE #046'}]
        self.assertIsNotNone(match_store(station, store, BOUNDARY))
        station.rows.append({'Truckstop Name': 'LOVES #047'})
        self.assertIsNone(match_store(station, store, BOUNDARY))
        station.rows = [{'Truckstop Name': 'PILOT #046'}]
        self.assertIsNone(match_store(station, store, BOUNDARY))
        station.rows = [{'Truckstop Name': 'LOVES OTHER BUSINESS #046'}]
        self.assertIsNone(match_store(station, store, BOUNDARY))
        station.rows = [{'Truckstop Name': 'LOVES COUNTRY STORE #046'}]
        station.save(update_fields=['rows'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            station.refresh_from_db()
            self.assertEqual(station.latitude, STORE['latitude'])
            self.assertEqual(station.rows[0]['Truckstop Name'], 'LOVES COUNTRY STORE #046')

    def test_explicit_operator_road_formats_and_city_spacing(self):
        station = self.station()
        cases = [
            ('I-85 EXIT 152', 'I-40/85', '152/Trollingwood Rd'),
            ('I-27 EXIT 116', 'I-27', '115 NB/116 SB'),
            ('I-70 MM 209', 'I-70', 'Mile209'),
        ]
        for address, highway, marker in cases:
            station.address = address
            station.city = 'MC CALLA'
            store = {**STORE, 'city': 'McCalla', 'highway': highway, 'exitNumber': marker}
            with self.subTest(address=address):
                result = match_store(station, store, BOUNDARY)
                self.assertIsNotNone(result)
                self.assertIn(marker, result['matched_address'])
        station.address = 'I-85 EXIT 152'
        self.assertIsNone(match_store(station, {**STORE, 'city': 'McCalla', 'highway': 'I-40/85', 'exitNumber': '152 NB/153 SB'}, BOUNDARY))

    def test_ambiguous_operator_records_remain_unresolved(self):
        self.station()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, unresolved = root / 'source.json', root / 'out' / 'evidence.csv', root / 'out' / 'unresolved.csv'
            source.write_text(json.dumps({'stores': [STORE, STORE]}))
            boundary = {'type': 'FeatureCollection', 'features': [BOUNDARY]}
            stdout = io.StringIO()
            with patch('planner.management.commands.resolve_loves.load_boundary', return_value=boundary):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(unresolved), stdout=stdout)
            with output.open(newline='') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])
            with unresolved.open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['reason'], 'ambiguous_match')
            self.assertIn('Evidence rows: 0. Unresolved groups: 1.', stdout.getvalue())

    def test_street_abbreviations_resolve_and_import(self):
        station = self.station()
        station.address = '5 S STATE ST'
        station.city = 'MC CALLA'
        station.save(update_fields=['address', 'city'])
        store = {**STORE, 'city': 'McCalla', 'highway': '', 'exitNumber': ''}
        self.assertIsNone(match_store(station, {**store, 'address1': '5 North State Street'}, BOUNDARY))
        self.assertIsNone(match_store(station, {**store, 'address1': '6 South State Street'}, BOUNDARY))
        self.assertIsNone(match_store(station, {**store, 'number': 767}, BOUNDARY))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            data.mkdir()
            boundary = {'type': 'FeatureCollection', 'features': [BOUNDARY]}
            (data / 'us_boundary.geojson').write_text(json.dumps(boundary))
            source, output, unresolved = root / 'source.json', root / 'evidence.csv', root / 'unresolved.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(unresolved), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            station.refresh_from_db()
            self.assertEqual(station.latitude, STORE['latitude'])
            self.assertEqual(station.longitude, STORE['longitude'])
            self.assertEqual(station.evidence['matched_address'], '5 South State Street')

    def test_route_only_operator_record_is_rechecked_on_import(self):
        station = self.station()
        for source, highway in (('I-35', 'I-35'), ('US-50/400', 'US-50/400'), ('I-2', 'I-2'), ('I-94', 'I-94'), ('US-77', 'US-77')):
            station.address = source
            with self.subTest(source=source):
                self.assertIsNotNone(match_store(station, {**STORE, 'address1': '100 Other Road', 'highway': highway, 'exitNumber': ''}, BOUNDARY))
        station.address = 'US-50/400'
        store = {**STORE, 'address1': '100 Other Road', 'highway': 'US-50/400', 'exitNumber': ''}
        for change in ({'highway': 'US-50'}, {'highway': 'HWY-50/400'}, {'number': 767}, {'city': 'Other'}, {'state': 'IA'}, {'longitude': -120}):
            self.assertIsNone(match_store(station, {**store, **change}, BOUNDARY))
        station.rows.append({'Truckstop Name': 'LOVES #767'})
        self.assertIsNone(match_store(station, store, BOUNDARY))
        station.rows.pop()
        for address in ('US-77 EXIT 1', 'US-77 MM 1', 'US-77 NORTH'):
            station.address = address
            self.assertIsNone(match_store(station, {**STORE, 'address1': '100 US-77', 'highway': 'I-69', 'exitNumber': ''}, BOUNDARY))
        station.address = 'US-77'
        store = {**STORE, 'address1': '100 US-77', 'highway': 'I-69', 'exitNumber': ''}
        self.assertEqual(match_store(station, store, BOUNDARY)['matched_address'], '100 US-77 I-69')
        station.save(update_fields=['address', 'rows'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertEqual(station.latitude, STORE['latitude'])
                self.assertEqual(station.evidence['matched_address'], '100 US-77 I-69')
                rows[0]['longitude'] = '-90.1'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertIsNone(station.latitude)
                source.write_text(json.dumps({'stores': [store, {**store, 'number': '0766'}]}))
                call_command('resolve_loves', input=str(source), output=str(root / 'duplicates.csv'), unresolved=str(root / 'duplicates-missing.csv'), verbosity=0)
                with (root / 'duplicates.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])

    def test_compound_junction_evidence_and_import(self):
        from planner.operator_evidence import LOVES_SOURCE, valid_loves_route_record
        station = self.station()
        station.address = 'I-35 & I-44 EXIT 137'
        station.save(update_fields=['address'])
        store = {**STORE, 'address1': '100 Other Road', 'highway': 'I-35', 'exitNumber': '137'}
        point = [store['latitude'], store['longitude']]
        junction = {'id': 8, 'point': point, 'ref': '137', 'old_ref': '', 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'highway': 'motorway', 'ref': 'I 35;I 44', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}, 'ramps': []}
        context = {'source': LOVES_SOURCE, 'store': store, 'junction': junction}
        self.assertTrue(valid_loves_route_record(station, context, point, BOUNDARY))
        for modified in ({**junction, 'ref': '138'}, {**junction, 'point': [41.5, -90.0]}, {**junction, 'road': {**junction['road'], 'ref': 'I 35'}}, {**junction, 'road': {**junction['road'], 'nodes': [7]}}):
            self.assertFalse(valid_loves_route_record(station, {**context, 'junction': modified}, point, BOUNDARY))
        self.assertFalse(valid_loves_route_record(station, {**context, 'junction': None}, point, BOUNDARY))
        self.assertFalse(valid_loves_route_record(station, {**context, 'extra': True}, point, BOUNDARY))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output, pbf = root / 'stores.json', root / 'evidence.csv', root / 'roads.osm.pbf'
            pbf.touch()
            source.write_text(json.dumps({'stores': [store]}))
            grid = {(int(point[0] * 10), int(point[1] * 10 // 1)): [junction]}
            with override_settings(BASE_DIR=root), patch('planner.management.commands.resolve_loves.read_junctions', return_value=grid):
                call_command('resolve_loves', input=str(source), pbf=str(pbf), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['matched_address'], '100 Other Road I-35 137')
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertEqual(station.latitude, point[0])
                raw = json.loads(rows[0]['operator_evidence'])
                raw['junction']['road']['ref'] = 'I 35'
                rows[0]['operator_evidence'] = json.dumps(raw)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertIsNone(station.latitude)

    def test_explicit_approval_rechecked_and_scope_retained(self):
        from planner.operator_evidence import LOVES_SOURCE, valid_loves_route_record
        station = self.station()
        station.address = 'I-35 & I-44 EXIT 137'
        station.save(update_fields=['address'])
        store = {**STORE, 'address1': '100 Other Road', 'highway': 'I-35', 'exitNumber': '137'}
        point = [store['latitude'], store['longitude']]
        approval = {'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'number': store['number'], 'latitude': point[0], 'longitude': point[1], 'source': LOVES_SOURCE, 'highway': store['highway'], 'exitNumber': store['exitNumber'], 'unverified_source_details': station.address}
        context = {'source': LOVES_SOURCE, 'store': store, 'approved_primary_exit': True}
        self.assertTrue(valid_loves_route_record(station, context, point, BOUNDARY, [approval]))
        self.assertFalse(valid_loves_route_record(station, context, point, BOUNDARY))
        self.assertFalse(valid_loves_route_record(station, {**context, 'approved_primary_exit': False}, point, BOUNDARY, [approval]))
        self.assertFalse(valid_loves_route_record(station, {**context, 'unknown': True}, point, BOUNDARY, [approval]))
        for change in ({'station_id': 'other'}, {'address': 'I-35 EXIT 137'}, {'city': 'Other'}, {'state': 'IA'}, {'number': 767}, {'latitude': 40.5}, {'source': 'https://example.com'}, {'highway': 'I-44'}, {'exitNumber': '138'}, {'unverified_source_details': 'verified'}):
            with self.subTest(change=change):
                self.assertFalse(valid_loves_route_record(station, context, point, BOUNDARY, [{**approval, **change}]))
        self.assertFalse(valid_loves_route_record(station, context, [point[0], point[1] + 0.01], BOUNDARY, [approval]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            (root / 'data/approved_operator_locations.json').write_text(json.dumps({'records': [approval]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertTrue(json.loads(rows[0]['operator_evidence'])['approved_primary_exit'])
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertEqual(station.evidence['verification_scope'], 'operator_identity_and_primary_exit')
                self.assertEqual(station.evidence['unverified_source_address_details'], station.address)
                (root / 'data/approved_operator_locations.json').write_text(json.dumps({'records': []}))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertIsNone(station.latitude)

    def test_identity_only_loves_raw_record(self):
        from planner.operator_evidence import LOVES_SOURCE, valid_loves_route_record
        station = self.station()
        station.address = 'I-80 EXIT 99'
        context = {'source': LOVES_SOURCE, 'store': STORE, 'identity_only': True}
        point = [STORE['latitude'], STORE['longitude']]
        self.assertTrue(valid_loves_route_record(station, context, point, BOUNDARY))
        self.assertFalse(valid_loves_route_record(station, {**context, 'approved_primary_exit': True}, point, BOUNDARY))
        self.assertFalse(valid_loves_route_record(station, {**context, 'store': {**STORE, 'number': 767}}, point, BOUNDARY))
        for variant in ('LOVES TRAVEL STOPS #766', 'LOVES TRAVE STOP #766'):
            station.rows = [{'Truckstop Name': 'LOVES TRAVEL STOP #766'}, {'Truckstop Name': variant}]
            self.assertTrue(valid_loves_route_record(station, context, point, BOUNDARY))
        station.rows = [{'Truckstop Name': 'LOVES OTHER BUSINESS #766'}]
        self.assertFalse(valid_loves_route_record(station, context, point, BOUNDARY))
        station.rows = [{'Truckstop Name': 'LOVES TRAVEL STOP #766'}]
        station.save(update_fields=['address'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            station.refresh_from_db()
            self.assertEqual(station.evidence['matched_address'], STORE['address1'])
            self.assertEqual(station.evidence['verification_scope'], 'operator_identity_only')

    def test_mount_juliet_format_keeps_unknown_road_unverified(self):
        from planner.operator_evidence import LOVES_SOURCE, valid_loves_route_record
        from planner.osm_evidence import evidence_city_key
        station = Station.objects.create(source_id='71055', name='LOVES TRAVEL STOP #793', address='I-840, EXIT 67 & COUCHVILLE PIKE', city='MOUNT JULIET', state='TN', rows=[{'Truckstop Name': 'LOVES TRAVEL STOP #793'}], price=3, price_min=3, price_max=3)
        store = {'number': 793, 'latitude': 36.067289, 'longitude': -86.428406, 'address1': '150 Couchville Industrial Blvd', 'city': 'Mt Juliet', 'state': 'TN', 'highway': 'I-840', 'exitNumber': '67/Couchville Pike', 'preferredName': 'Mt Juliet', 'facilitySubtypeName': 'Travel Stop', 'isLoveStore': True, 'isCountryStore': False}
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'TN'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-87, 35], [-85, 35], [-85, 37], [-87, 37], [-87, 35]]]}}
        point = [store['latitude'], store['longitude']]
        context = {'source': LOVES_SOURCE, 'store': store, 'identity_only': True}
        self.assertEqual(evidence_city_key('Mount Juliet'), evidence_city_key('Mt. Juliet'))
        self.assertNotEqual(evidence_city_key('Mount Vernon'), evidence_city_key('Mt Vernon'))
        self.assertNotEqual(evidence_city_key('Matfield Green'), evidence_city_key('Cassoday'))
        self.assertTrue(valid_loves_route_record(station, context, point, boundary))
        self.assertFalse(valid_loves_route_record(station, {'source': LOVES_SOURCE, 'store': store}, point, boundary))
        for change in ({'number': 794}, {'state': 'KY'}, {'city': 'Mount Vernon'}):
            self.assertFalse(valid_loves_route_record(station, {**context, 'store': {**store, **change}}, point, boundary))
        station.city = 'Mount Vernon'
        self.assertFalse(valid_loves_route_record(station, context, point, boundary))
        station.city = 'MOUNT JULIET'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            station.refresh_from_db()
            self.assertEqual([station.latitude, station.longitude], point)
            self.assertEqual(station.evidence['verification_scope'], 'operator_identity_only')
            self.assertEqual(station.evidence['unverified_source_address_details'], 'I-840, EXIT 67 & COUCHVILLE PIKE')

    def test_approved_named_plaza_requires_exact_raw_scope_and_import(self):
        import csv
        from planner.operator_evidence import LOVES_SOURCE, valid_loves_route_record
        store = {'number': 176, 'latitude': 38.095391, 'longitude': -96.579511, 'address1': 'Mile 97 Kansas Turnpike', 'city': 'Cassoday', 'state': 'KS', 'highway': 'I-35', 'exitNumber': 'Mile 97', 'preferredName': 'Matfield Green Turnpike - SRI', 'facilitySubtypeName': 'Travel Stop', 'isLoveStore': True, 'isCountryStore': False}
        station = Station.objects.create(source_id='293', name='LOVES TRAVEL STOP #176', address='I-35, MILE MARKER 97', city='MATFIELD GREEN', state='KS', rows=[{'Truckstop Name': 'LOVES TRAVEL STOP #176'}], price=3, price_min=3, price_max=3)
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'KS'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-98, 37], [-95, 37], [-95, 39], [-98, 39], [-98, 37]]]}}
        approval = {'kind': 'named_plaza', 'station_id': '293', 'address': station.address, 'city': station.city, 'state': 'KS', 'source': LOVES_SOURCE, 'store': store}
        point = [38.095391, -96.579511]
        context = {'source': LOVES_SOURCE, 'store': store, 'approved_named_plaza': True}
        self.assertTrue(valid_loves_route_record(station, context, point, boundary, [approval]))
        self.assertFalse(valid_loves_route_record(station, context, point, boundary, []))
        for change in ({'preferredName': 'Other'}, {'city': 'Other'}, {'exitNumber': 'Exit 97'}, {'highway': 'I-135'}, {'latitude': 38.0}, {'isCountryStore': True}, {'country': 'CA'}):
            self.assertFalse(valid_loves_route_record(station, {**context, 'store': {**store, **change}}, point, boundary, [approval]))
        for bad in ({**context, 'identity_only': True}, {**context, 'approved_named_plaza': False}, {**context, 'source': 'https://example.com'}, {**context, 'junction': {}}, {**context, 'extra': True}):
            self.assertFalse(valid_loves_route_record(station, bad, point, boundary, [approval]))
        station.source_id = '294'
        self.assertFalse(valid_loves_route_record(station, context, point, boundary, [approval]))
        station.source_id = '293'
        station.address = 'I-35 EXIT 97'
        self.assertFalse(valid_loves_route_record(station, context, point, boundary, [approval]))
        station.address = 'I-35, MILE MARKER 97'
        station.rows.append({'Truckstop Name': 'PILOT #176'})
        self.assertFalse(valid_loves_route_record(station, context, point, boundary, [approval]))
        station.rows.pop()
        station.rows.append({'Truckstop Name': 'SHELL #176'})
        self.assertFalse(valid_loves_route_record(station, context, point, boundary, [approval]))
        station.rows.pop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
            (root / 'data/approved_named_plazas.json').write_text(json.dumps({'records': [approval]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_loves', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertTrue(json.loads(rows[0]['operator_evidence'])['approved_named_plaza'])
                call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertEqual([station.latitude, station.longitude], point)
                self.assertEqual(station.evidence['verification_scope'], 'operator_identity_and_named_plaza')
                self.assertEqual(station.evidence['operator_postal_city'], 'Cassoday')
                self.assertEqual(station.evidence['operator_location_label'], 'Matfield Green Turnpike - SRI')
