import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import operator_store_key, valid_operator_record

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'OK'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-96, 35], [-95, 35], [-95, 36], [-96, 36], [-96, 35]]]}}
STORE = {'number': '259', 'name': 'Pilot Travel Center #259', 'address': '3000 N 32nd St', 'highway': 'US-69 & Harris Rd', 'city': 'Muskogee', 'state': 'OK', 'latitude': 35.7844509, 'longitude': -95.4016042, 'source': 'https://locations.pilotflyingj.com/us/ok/muskogee/3000-n-32nd-st'}


class OperatorTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='66894', name='PILOT TRAVEL CENTERS #259', address='US-69', city='MUSKOGEE', state='OK', rows=[{'Truckstop Name': 'PILOT TRAVEL CENTERS #259'}], price=3, price_min=3, price_max=3)

    def check(self, store=STORE, point=None):
        return valid_operator_record(self.station, {'store': store}, point or [STORE['latitude'], STORE['longitude']], BOUNDARY)

    def test_exact_operator_and_full_typed_route(self):
        self.assertTrue(self.check())
        for change in ({'name': 'Pilot Travel Center'}, {'name': 'Pilot #260'}, {'name': 'Flying J #259'}, {'number': '260'}, {'highway': 'HWY-69'}, {'highway': 'US-69W'}, {'source': 'https://example.com/us/ok/muskogee/site'}, {'longitude': -95.5}, {'city': 'Other'}):
            with self.subTest(change=change):
                self.assertFalse(self.check({**STORE, **change}))
        self.station.rows = [{'Truckstop Name': 'PILOT TRAVEL CENTERS'}]
        self.assertFalse(self.check())
        self.station.rows = [{'Truckstop Name': 'PILOT #259'}, {'Truckstop Name': 'PILOT #260'}]
        self.assertFalse(self.check())
        self.station.rows = [{'Truckstop Name': 'PILOT #259'}]
        for address in ('US-69 EXIT 1', 'US-69 OR US-70', 'US-69 NORTH', 'US-69 MM 2', 'US-69 & US-70'):
            self.station.address = address
            with self.subTest(address=address):
                self.assertFalse(self.check())
        self.station.address = 'US-69 & US-70'
        self.assertTrue(self.check({**STORE, 'highway': 'US-69 & US-70'}))

    def test_resolve_and_import_rechecks_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, out, unresolved = root / 'source.json', root / 'evidence.csv', root / 'missing.csv'
            source.write_text(json.dumps({'stores': [STORE]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_pilot', input=str(source), output=str(out), unresolved=str(unresolved), verbosity=0)
                with out.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(out), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.latitude, STORE['latitude'])
                rows[0]['longitude'] = '-95.5'
                with out.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(out), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)

    def test_spaced_exit_suffix_matches_operator_exit(self):
        self.station.rows = [{'Truckstop Name': 'FLYING J TRAVEL PLAZA #650'}]
        self.station.address = 'I-94, EXIT 15 B'
        self.station.city, self.station.state = 'LAKE STATION', 'IN'
        store = {'number': '650', 'name': 'Flying J Travel Center #650', 'address': '1401 Ripley St',
                 'highway': 'I-94/90, Exit 15B', 'city': 'Lake Station', 'state': 'IN',
                 'latitude': 41.5864333, 'longitude': -87.2395347,
                 'source': 'https://locations.pilotflyingj.com/us/in/lake-station/1401-ripley-st'}
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'IN'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-88, 41], [-87, 41], [-87, 42], [-88, 42], [-88, 41]]]}}
        point = [store['latitude'], store['longitude']]
        def check(highway):
            return valid_operator_record(self.station, {'store': {**store, 'highway': highway}}, point, boundary)
        self.assertTrue(check(store['highway']))
        for highway in ('I-94 EXIT 15A', 'I-94 EXIT 15', 'I-94 EXIT 15E', 'I-94 MM 15B'):
            with self.subTest(highway=highway):
                self.assertFalse(check(highway))

    def test_shared_route_tokens_require_all_routes(self):
        self.station.address = 'US-69/75'
        self.assertTrue(self.check({**STORE, 'highway': 'US-69/75'}))
        self.assertFalse(self.check({**STORE, 'highway': 'US-69'}))
        self.assertFalse(self.check({**STORE, 'highway': 'HWY-69/75'}))
        self.station.address = 'US-69/75 OR US-70'
        self.assertFalse(self.check({**STORE, 'highway': 'US-69/75'}))

    def test_published_exit_requires_every_intersection_road(self):
        self.station.address = 'I-94 EXIT 12 & US-6'
        self.assertFalse(self.check({**STORE, 'highway': 'I-94 EXIT 12'}))
        self.assertTrue(self.check({**STORE, 'highway': 'I-94 EXIT 12 & US-6'}))
        self.station.address = 'I-80/US-6 EXIT 93 & CR-P28'
        self.assertFalse(self.check({**STORE, 'highway': 'I-80 EXIT 93'}))
        self.assertTrue(self.check({**STORE, 'highway': 'I-80 EXIT 93 & US-6 & County Road P28'}))

    def test_city_punctuation_and_spacing(self):
        for source, target in (('SAINT CLOUD', 'St. Cloud'), ('MC CALLA', 'McCalla'), ('DEFOREST', 'De Forest')):
            self.station.city = source
            with self.subTest(source=source):
                self.assertTrue(self.check({**STORE, 'city': target}))
                self.assertFalse(self.check({**STORE, 'city': 'Other'}))

    def test_new_operator_brands_and_domains(self):
        self.station.rows = [{'Truckstop Name': 'MAVERIK #259'}]
        self.station.address = '3000 N 32ND ST'
        store = {**STORE, 'name': 'Maverik #259', 'source': 'https://locations.maverik.com/ok/muskogee/3000-n-32nd-st'}
        self.assertTrue(self.check(store))
        self.assertFalse(self.check({**store, 'source': 'https://locations.quiktrip.com/ok/muskogee/3000-n-32nd-st'}))
        self.assertFalse(self.check({**store, 'source': 'https://locations.maverik.com/tx/muskogee/3000-n-32nd-st'}))
        self.assertFalse(self.check({**store, 'name': 'Maverik #260'}))
        self.station.rows = [{'Truckstop Name': 'QUIKTRIP #259'}]
        self.assertTrue(self.check({**store, 'name': 'QuikTrip #259', 'source': 'https://locations.quiktrip.com/ok/muskogee/3000-n-32nd-st'}))

    def test_unparsed_road_requires_identity_only_disclosure(self):
        self.station.address = 'I-35 EXIT 89 & CO-R6F'
        store = {**STORE, 'highway': 'I-35 EXIT 89'}
        self.assertFalse(self.check(store))
        self.assertTrue(valid_operator_record(self.station, {'store': store, 'identity_only': True}, [store['latitude'], store['longitude']], BOUNDARY))

    def test_maverik_country_store_exact_variant(self):
        self.station.rows = [{'Truckstop Name': 'MAVERIK COUNTRY STORE #259'}]
        store = {**STORE, 'name': 'Maverik #259', 'source': 'https://locations.maverik.com/ok/muskogee/3000-n-32nd-st'}
        self.assertTrue(self.check(store))
        self.assertFalse(self.check({**store, 'name': 'Maverik #260'}))
        self.assertFalse(self.check({**store, 'name': 'Kum & Go #259'}))
        self.assertFalse(self.check({**store, 'highway': 'US-70'}))

    def test_pilot_dealer_matches_same_family_only(self):
        self.station.address = 'US-69'
        dealer = {**STORE, 'name': 'Pilot Dealer #259'}
        self.station.rows = [{'Truckstop Name': 'PILOT DEALER #259'}]
        self.assertTrue(self.check(dealer))
        self.assertTrue(self.check(STORE))
        self.station.rows = [{'Truckstop Name': 'PILOT #259'}]
        self.assertTrue(self.check(dealer))
        self.station.rows = [{'Truckstop Name': 'PILOT EXPRESS #259'}]
        self.assertFalse(self.check(dealer))
        self.station.rows = [{'Truckstop Name': 'FLYING J #259'}]
        self.assertTrue(self.check({**STORE, 'name': 'Flying J Dealer #259'}))
        self.assertFalse(self.check(dealer))
        self.station.rows = [{'Truckstop Name': 'PILOT #259'}, {'Truckstop Name': 'ONE9 #259'}]
        self.assertFalse(self.check(dealer))
        self.station.rows = [{'Truckstop Name': 'PILOT #260'}]
        self.assertFalse(self.check(dealer))

    def test_flying_j_literal_operator_descriptors(self):
        store = {**STORE, 'name': 'Flying J #259'}
        for name in ('Flying J Travel Plaza #259', 'Flying J TravelPlaza #259', 'FLYING J FUEL STOP #259'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertTrue(self.check(store))
        for name in ('Flying J Licensed #259', 'Pilot Express #259', 'One9 #259'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(self.check(store))

    def test_pilot_location_dotted_slugs_are_anchored(self):
        urls = (
            'https://locations.pilotflyingj.com/us/az/ehrenberg/i-10-exit-1-frontage-road-n.',
            'https://locations.pilotflyingj.com/us/ut/tooele/1605-east-saddleback-blvd.',
            'https://locations.pilotflyingj.com/us/tx/buda/10700-u.s.-hwy-183-n.',
            'https://locations.pilotflyingj.com/us/nm/santa-rosa/2464-u.s.-route-66',
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(operator_store_key({**STORE, 'source': url}), ('PILOT', '259'))
        for url in ('https://example.com/us/ok/muskogee/3000-n-32nd-st', 'https://locations.pilotflyingj.com/us/ok/muskogee/..', 'https://locations.pilotflyingj.com/us/ok/muskogee/.', 'https://locations.pilotflyingj.com/us/ok/muskogee/name?ref=1'):
            self.assertIsNone(operator_store_key({**STORE, 'source': url}))

    def test_maverik_dotted_slugs_resolve_and_import(self):
        urls = ('https://locations.maverik.com/nm/albuquerque/1915-menaul-blvd.-ne', 'https://locations.maverik.com/ia/ames/2108-isaac-newton-dr.')
        store = {'number': '638', 'name': 'Maverik #638', 'address': '1915 Menaul Blvd NE', 'highway': '', 'city': 'Albuquerque', 'state': 'NM', 'latitude': 35.1, 'longitude': -106.6, 'source': urls[0]}
        for url in urls:
            self.assertEqual(operator_store_key({**store, 'source': url}), ('MAVERIK', '638'))
        for url in ('https://example.com/nm/albuquerque/name', 'https://locations.maverik.com/nm/albuquerque/..', 'https://locations.maverik.com/nm/albuquerque/.', 'https://locations.maverik.com/nm/albuquerque/name?x=1', 'https://locations.maverik.com/nm/albuquerque/name/extra'):
            self.assertIsNone(operator_store_key({**store, 'source': url}))
        self.station.name = 'MAVERIK #638'
        self.station.rows = [{'Truckstop Name': self.station.name}]
        self.station.city, self.station.state, self.station.address = 'ALBUQUERQUE', 'NM', 'I-40 EXIT 99'
        self.station.save(update_fields=['name', 'rows', 'city', 'state', 'address'])
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'NM'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-107, 35], [-106, 35], [-106, 36], [-107, 36], [-107, 35]]]}}
        self.assertFalse(valid_operator_record(self.station, {'store': {**store, 'source': urls[1]}, 'identity_only': True}, [35.1, -106.6], boundary))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_operator', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.latitude, 35.1)
            self.assertEqual(self.station.evidence['matched_address'], store['address'])

    def test_pilot_express_requires_distinct_exact_brand(self):
        self.station.address = 'I-95 EXIT 14'
        self.station.rows = [{'Truckstop Name': 'PILOT EXPRESS #259'}]
        express = {**STORE, 'name': 'Pilot Express #259'}
        point = [STORE['latitude'], STORE['longitude']]
        self.assertTrue(valid_operator_record(self.station, {'store': express, 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': STORE, 'identity_only': True}, point, BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'PILOT #259'}]
        self.assertFalse(valid_operator_record(self.station, {'store': express, 'identity_only': True}, point, BOUNDARY))

    def test_pilot_and_maverik_identity_only(self):
        self.station.address = 'I-94 EXIT 99'
        point = [STORE['latitude'], STORE['longitude']]
        self.assertTrue(valid_operator_record(self.station, {'store': STORE, 'identity_only': True}, point, BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'MAVERIK #259'}]
        maverik = {**STORE, 'name': 'Maverik #259', 'source': 'https://locations.maverik.com/ok/muskogee/3000-n-32nd-st'}
        self.assertTrue(valid_operator_record(self.station, {'store': maverik, 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': {**maverik, 'name': 'QuikTrip #259'}, 'identity_only': True}, point, BOUNDARY))

    def test_generic_operator_resolver_and_import(self):
        self.station.name = 'MAVERIK #259'
        self.station.rows = [{'Truckstop Name': self.station.name}]
        self.station.address = '3000 N 32ND ST'
        self.station.save(update_fields=['name', 'rows', 'address'])
        store = {**STORE, 'name': 'Maverik #259', 'source': 'https://locations.maverik.com/ok/muskogee/3000-n-32nd-st'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'source.json', root / 'evidence.csv'
            source.write_text(json.dumps({'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_operator', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                call_command('load_data', 'evidence', str(output), verbosity=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.latitude, store['latitude'])

    def test_pilot_resolver_rejects_cross_provider_and_normalized_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source = root / 'stores.json'
            other = {**STORE, 'name': 'Maverik #259', 'source': 'https://locations.maverik.com/ok/muskogee/3000-n-32nd-st'}
            self.station.address = '3000 N 32ND ST'
            self.station.name = 'MAVERIK #259'
            self.station.rows = [{'Truckstop Name': self.station.name}]
            self.station.save(update_fields=['address', 'name', 'rows'])
            with override_settings(BASE_DIR=root):
                source.write_text(json.dumps({'stores': [other]}))
                call_command('resolve_pilot', input=str(source), output=str(root / 'other.csv'), unresolved=str(root / 'other-missing.csv'), verbosity=0)
                with (root / 'other.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                self.station.name = 'PILOT #259'
                self.station.rows = [{'Truckstop Name': self.station.name}]
                self.station.save(update_fields=['name', 'rows'])
                source.write_text(json.dumps({'stores': [STORE, {**STORE, 'number': '0259', 'name': 'Pilot Travel Center #0259'}]}))
                call_command('resolve_pilot', input=str(source), output=str(root / 'duplicate.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with (root / 'duplicate.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])


class SharedOperatorApprovalTests(TestCase):
    def test_exact_two_barron_owners_only(self):
        from types import SimpleNamespace
        from planner.shared_operator_approval import approved_shared_operator
        owners = [SimpleNamespace(source_id=i, address='US 8', city='Barron', state='WI', rows=[{'Truckstop Name': 'KWIK TRIP #748'}]) for i in ('72812', '73096')]
        store = {'source': 'https://www.kwiktrip.com/Maps-Downloads/Store-List', 'number': '748', 'name': 'KWIK TRIP #748', 'address': '1456 E LA SALLE AVE', 'city': 'BARRON', 'state': 'WI', 'latitude': 45.40061, 'longitude': -91.83492, 'sells_gas': True, 'sells_diesel': True}
        approvals = [{'owners': [{'station_id': o.source_id, 'address': o.address, 'city': o.city, 'state': o.state} for o in owners], 'store': store}]
        self.assertTrue(approved_shared_operator(owners, store, approvals))
        self.assertFalse(approved_shared_operator(owners[:1], store, approvals))
        self.assertFalse(approved_shared_operator(owners + [owners[0]], store, approvals))
        self.assertFalse(approved_shared_operator(owners, {**store, 'latitude': 45.4}, approvals))
        self.assertFalse(approved_shared_operator(owners, {**store, 'source': 'https://example.com'}, approvals))
        self.assertFalse(approved_shared_operator(owners, store, []))
        owners[0].address = 'US 9'
        self.assertFalse(approved_shared_operator(owners, store, approvals))

    def test_barron_resolver_and_import_preserves_distinct_prices(self):
        from planner.shared_operator_approval import approved_shared_operator
        store = {'source': 'https://www.kwiktrip.com/Maps-Downloads/Store-List', 'number': '748', 'name': 'KWIK TRIP #748', 'address': '1456 E LA SALLE AVE', 'city': 'BARRON', 'state': 'WI', 'latitude': 45.40061, 'longitude': -91.83492, 'sells_gas': True, 'sells_diesel': True}
        owners = [Station.objects.create(source_id=i, name='KWIK TRIP #748', address='US 8', city='BARRON', state='WI', rows=[{'Truckstop Name': 'KWIK TRIP #748'}], price=price, price_min=price, price_max=price) for i, price in (('72812', 3.664), ('73096', 3.64733333))]
        approvals = [{'owners': [{'station_id': o.source_id, 'address': o.address, 'city': o.city, 'state': o.state} for o in owners], 'store': store}]
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'WI'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-93, 44], [-90, 44], [-90, 47], [-93, 47], [-93, 44]]]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
            (root / 'data/approved_shared_operator_locations.json').write_text(json.dumps({'records': approvals}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': store['source'], 'stores': [store]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_kwiktrip', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 2)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                for owner in owners:
                    owner.refresh_from_db()
                    self.assertEqual([owner.latitude, owner.longitude], [45.40061, -91.83492])
                self.assertEqual([o.price for o in owners], [3.664, 3.64733333])
                self.assertFalse(approved_shared_operator(owners + [owners[0]], store, approvals))
