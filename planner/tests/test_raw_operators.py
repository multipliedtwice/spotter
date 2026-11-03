import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import valid_operator_record
from planner.raw_operator_evidence import RACETRAC_SOURCE, ROYAL_SOURCE, RUTTERS_SOURCE, SEVENFLEET_SOURCE, SUNSTOP_SOURCE, THORNTONS_SOURCE, TOOT_SOURCE

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'GA'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-85, 32], [-83, 32], [-83, 34], [-85, 34], [-85, 32]]]}}
RACE = {'StoreNumber': 101, 'StoreName': 'Town', 'StoreAddress1': '123 Main St', 'StoreAddress2': None, 'StoreCity': 'Town', 'StoreState': 'Georgia', 'StoreLatitude': 33.0, 'StoreLongitude': -84.0, 'Brand': 'RaceTrac', 'StoreUrl': '/locations/georgia/town/town'}
RUTTERS = {'post_title': 'Rutter’s #101', 'store_meta': {'store_number': '101', 'address': '123 Main St', 'city': 'Town', 'state': 'GA', 'latitude': '33.0', 'longitude': '-84.0'}}
THORNTONS = {'name': 'Thorntons. #101', 'address': '123 Main St', 'city': 'Town', 'state': 'GA', 'data-latitude': '33.0', 'data-longitude': '-84.0'}
SUNSTOP = {'id': 1, 'store': 'SunStop #101', 'address': '123 Main St', 'address2': '', 'city': 'Town', 'state': 'GA', 'zip': '30000', 'country': 'United States', 'lat': '33.0', 'lng': '-84.0', 'url': '', 'permalink': 'https://sunstopstores.com/stores/sunstop-101/'}
TOOT = {'title': "Toot'n Totum #101", 'address': ['123 Main St', 'Town, GA 30000'], 'data-latitude': '33.0', 'data-longitude': '-84.0', 'source_url': 'https://www.tootntotum.com/locations/tootntotum-101'}
ROYAL = {'storeNumber': '0101', 'address': {'line1': '123 Main St', 'line2': '', 'city': 'Town', 'state': 'GA', 'zip': '30000', 'full': '123 Main St, Town, GA 30000'}, 'coordinates': {'lat': 33.0, 'lng': -84.0}}
SEVENFLEET = {'network': '7FLEET', 'brand': 'Sunoco', 'site_name': 'Stripes-101', 'address': '123 Main St', 'city': 'Town', 'state': 'GA', 'zip': '30000', 'marker_title': 'Stripes-101', 'latitude': '33.0', 'longitude': '-84.0', 'locator_url': SEVENFLEET_SOURCE}


class RawOperatorTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='RACETRAC #101', address='I-40 EXIT 99', city='TOWN', state='GA', rows=[{'Truckstop Name': 'RACETRAC #101'}], price=3, price_min=3, price_max=3)

    def valid(self, source, raw, **context):
        return valid_operator_record(self.station, {'store': {'source': source, 'record': raw}, 'identity_only': True, **context}, [33.0, -84.0], BOUNDARY)

    def test_racetrac_strict_raw_facts_and_brand(self):
        self.assertTrue(self.valid(RACETRAC_SOURCE, RACE))
        for change in ({'StoreNumber': True}, {'StoreNumber': 102}, {'Brand': 'RaceWay'}, {'StoreCity': 'Other'}, {'StoreState': 'Florida'}, {'StoreLatitude': float('nan')}, {'StoreUrl': 'https://example.com/store'}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.valid(RACETRAC_SOURCE, {**RACE, **change}))
        self.assertFalse(self.valid('https://example.com', RACE))
        self.station.rows = [{'Truckstop Name': 'RACEWAY #101'}]
        self.assertTrue(self.valid(RACETRAC_SOURCE, {**RACE, 'Brand': 'RaceWay'}))
        self.assertFalse(self.valid(RACETRAC_SOURCE, RACE))

    def test_rutters_and_thorntons_raw_strings(self):
        self.station.rows = [{'Truckstop Name': 'RUTTERS #101'}]
        self.assertTrue(self.valid(RUTTERS_SOURCE, RUTTERS))
        for change in ({'store_number': '102'}, {'latitude': 'nan'}, {'latitude': True}, {'city': 'Other'}):
            self.assertFalse(self.valid(RUTTERS_SOURCE, {**RUTTERS, 'store_meta': {**RUTTERS['store_meta'], **change}}))
        self.station.rows = [{'Truckstop Name': 'THORNTONS #101'}]
        self.assertTrue(self.valid(THORNTONS_SOURCE, THORNTONS))
        for change in ({'name': 'Other #101'}, {'name': 'Thorntons #102'}, {'data-latitude': 'nan'}, {'data-latitude': True}, {'state': 'FL'}, {'extra': 'x'}):
            self.assertFalse(self.valid(THORNTONS_SOURCE, {**THORNTONS, **change}))
        self.assertFalse(self.valid(THORNTONS_SOURCE, THORNTONS, junction={}))

    def test_strong_street_precedes_identity_fallback(self):
        self.station.address = '123 MAIN ST'
        for source, raw, name in ((RACETRAC_SOURCE, RACE, 'RACETRAC #101'), (RUTTERS_SOURCE, RUTTERS, 'RUTTERS #101'), (THORNTONS_SOURCE, THORNTONS, 'THORNTONS #101')):
            self.station.rows = [{'Truckstop Name': name}]
            with self.subTest(source=source):
                self.assertTrue(valid_operator_record(self.station, {'store': {'source': source, 'record': raw}}, [33.0, -84.0], BOUNDARY))

    def test_sunstop_toot_and_royal_strict_identity(self):
        cases = ((SUNSTOP_SOURCE, SUNSTOP, 'SUNSTOP #101'), (TOOT_SOURCE, TOOT, 'TOOT N TOTUM #101'), (ROYAL_SOURCE, ROYAL, 'ROYAL FARMS #101'))
        for source, raw, name in cases:
            self.station.rows = [{'Truckstop Name': name}]
            with self.subTest(source=source):
                self.assertTrue(self.valid(source, raw))
                self.assertFalse(self.valid('https://example.com', raw))
                self.assertFalse(self.valid(source, {**raw, 'extra': True}))
                self.station.rows = [{'Truckstop Name': 'OTHER #101'}]
                self.assertFalse(self.valid(source, raw))
        self.station.rows = [{'Truckstop Name': 'SUNSTOP #101'}]
        self.assertFalse(self.valid(SUNSTOP_SOURCE, {**SUNSTOP, 'permalink': 'https://sunstopstores.com/stores/sunstop-102/'}))
        self.station.rows = [{'Truckstop Name': 'TOOT N TOTUM #101'}]
        self.assertFalse(self.valid(TOOT_SOURCE, {**TOOT, 'address': ['123 Main St', 'Different']}))
        self.station.rows = [{'Truckstop Name': 'TOOT N TOTUM #44'}]
        padded = {**TOOT, 'title': "Toot'n Totum #044", 'source_url': 'https://www.tootntotum.com/locations/tootntotum-044'}
        self.assertTrue(self.valid(TOOT_SOURCE, padded))
        self.assertFalse(self.valid(TOOT_SOURCE, {**padded, 'source_url': 'https://www.tootntotum.com/locations/tootntotum-045'}))
        self.station.rows = [{'Truckstop Name': 'ROYAL FARMS #101'}]
        self.assertFalse(self.valid(ROYAL_SOURCE, {**ROYAL, 'coordinates': {'lat': True, 'lng': -84.0}}))

    def test_sevenfleet_retailer_identity_and_raw_marker(self):
        self.station.rows = [{'Truckstop Name': 'STRIPES 7FLEET #101'}]
        self.assertTrue(self.valid(SEVENFLEET_SOURCE, SEVENFLEET))
        self.assertTrue(self.valid(SEVENFLEET_SOURCE, {**SEVENFLEET, 'brand': ''}))
        for change in ({'brand': None}, {'site_name': 'Stripes-102'}, {'marker_title': 'Stripes-102'}, {'site_name': 'Sunoco-101'}, {'network': 'OTHER'}, {'locator_url': 'https://example.com'}, {'city': 'Other'}, {'state': 'FL'}, {'zip': 'bad'}, {'latitude': 'nan'}, {'latitude': True}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.valid(SEVENFLEET_SOURCE, {**SEVENFLEET, **change}))
        self.station.rows = [{'Truckstop Name': 'SPEEDWAY #8039'}]
        self.assertFalse(self.valid(SEVENFLEET_SOURCE, {**SEVENFLEET, 'site_name': 'Speedway-43877', 'marker_title': 'Speedway-43877'}))
        self.station.rows = [{'Truckstop Name': '7-Eleven/7FLEET #40496'}]
        eleven = {**SEVENFLEET, 'site_name': '7-Eleven-40496', 'marker_title': '7-Eleven-40496'}
        self.assertTrue(self.valid(SEVENFLEET_SOURCE, eleven))

    def test_resolvers_import_raw_and_reject_duplicate_points(self):
        cases = (('resolve_racetrac', RACETRAC_SOURCE, RACE, 'RACETRAC #101', 'RaceTrac'), ('resolve_rutters', RUTTERS_SOURCE, RUTTERS, 'RUTTERS #101', 'Rutter’s #101'), ('resolve_thorntons', THORNTONS_SOURCE, THORNTONS, 'THORNTONS #101', 'Thorntons. #101'), ('resolve_sunstop', SUNSTOP_SOURCE, SUNSTOP, 'SUNSTOP #101', 'SunStop #101'), ('resolve_tootntotum', TOOT_SOURCE, TOOT, 'TOOT N TOTUM #101', "Toot'n Totum #101"), ('resolve_royalfarms', ROYAL_SOURCE, ROYAL, 'ROYAL FARMS #101', 'Royal Farms'), ('resolve_sevenfleet', SEVENFLEET_SOURCE, SEVENFLEET, 'STRIPES 7FLEET #101', 'Stripes'))
        for command, source_url, raw, source_name, display_name in cases:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                self.station.name = source_name
                self.station.rows = [{'Truckstop Name': source_name}]
                self.station.save(update_fields=['name', 'rows'])
                root = Path(directory)
                (root / 'data').mkdir()
                (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
                source, output = root / 'stores.json', root / 'evidence.csv'
                source.write_text(json.dumps({'source': source_url, 'stores': [raw]}))
                with override_settings(BASE_DIR=root):
                    call_command(command, input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                    with output.open(newline='') as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]['matched_name'], display_name)
                    self.assertTrue(json.loads(rows[0]['operator_evidence'])['identity_only'])
                    call_command('load_data', 'evidence', str(output), verbosity=0)
                    self.station.refresh_from_db()
                    self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                    self.assertEqual(self.station.evidence['matched_address'], '123 Main St')
                    self.assertEqual(self.station.evidence['operator_evidence']['store']['record'], raw)
                    rows[0]['longitude'] = '-84.1'
                    with output.open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerows(rows)
                    call_command('load_data', 'evidence', str(output), verbosity=0)
                    self.station.refresh_from_db()
                    self.assertIsNone(self.station.latitude)
                    source.write_text(json.dumps({'source': source_url, 'stores': [raw, raw]}))
                    call_command(command, input=str(source), output=str(root / 'duplicate.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                    with (root / 'duplicate.csv').open(newline='') as stream:
                        self.assertEqual(list(csv.DictReader(stream)), [])


PUMP_SOURCE = 'https://pumpandpantry.com/wp-json/pump-pantry/v1/locations'
PUMP_BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'NE'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-99, 40], [-98, 40], [-98, 42], [-99, 42], [-99, 40]]]}}
PUMP = {'id': 737, 'store_name': 'Pump &amp; Pantry #1', 'post_title': 'Pump &amp; Pantry #1', 'store_title': 'CORNER STORE', 'title': 'Pump &amp; Pantry #1', 'address': '3507 East Bismark Road, Grand Island, NE, USA', 'post_code': '68801', 'location': {'address': '3507 East Bismark Road, Grand Island, NE, USA', 'lat': 40.9156305, 'lng': -98.3021826, 'zoom': 15, 'place_id': 'example', 'name': '3507 E Bismark Rd', 'street_number': '3507', 'street_name': 'East Bismark Road', 'street_name_short': 'E Bismark Rd', 'city': 'Grand Island', 'state': 'Nebraska', 'state_short': 'NE', 'post_code': '68801', 'country': 'United States', 'country_short': 'US'}, 'permalink': 'https://pumpandpantry.com/store/pump-pantry-1/'}


class PumpPantryTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='PUMP & PANTRY #1', address='US-30', city='GRAND ISLAND', state='NE', rows=[{'Truckstop Name': 'PUMP & PANTRY #1'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=PUMP, source=PUMP_SOURCE):
        return valid_operator_record(self.station, {'store': {'source': source, 'record': raw}, 'identity_only': True}, [40.9156305, -98.3021826], PUMP_BOUNDARY)

    def test_published_raw_identity_and_schema(self):
        self.assertTrue(self.valid())
        self.assertTrue(self.valid({**PUMP, 'store_title': ''}))
        self.assertFalse(self.valid({**PUMP, 'store_title': None}))
        for change in ({'id': True}, {'permalink': 'https://example.com/store/pump-pantry-1/'}, {'store_name': 'Pump &amp; Pantry #2'}, {'address': 'Other'}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.valid({**PUMP, **change}))
        for change in ({'lat': True}, {'lat': float('nan')}, {'city': 'Other'}, {'state_short': 'IA'}, {'country_short': 'CA'}):
            self.assertFalse(self.valid({**PUMP, 'location': {**PUMP['location'], **change}}))
        self.assertFalse(self.valid(source='https://example.com'))
        self.station.rows = [{'Truckstop Name': 'OTHER #1'}]
        self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'PUMP & PANTRY #2'}]
        self.assertFalse(self.valid())

    def test_resolver_import_retains_raw_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [PUMP_BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': PUMP_SOURCE, 'stores': [PUMP]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_pump_pantry', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], PUMP['location']['name'])
                self.assertEqual(self.station.evidence['operator_evidence']['store']['record'], PUMP)
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                rows[0]['longitude'] = '-98.4'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps({'source': PUMP_SOURCE, 'stores': [PUMP, PUMP]}))
                call_command('resolve_pump_pantry', input=str(source), output=str(root / 'duplicate.csv'), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with (root / 'duplicate.csv').open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])


TEXBEST_SOURCE = 'https://www.texbeststores.com/locations/'
TEXBEST_BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'TX'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-100, 28], [-97, 28], [-97, 31], [-100, 31], [-100, 28]]]}}
TEXBEST = {'name': 'Tex-Best #504', 'address': '14650 Interstate 35 South, Von Ormy, Texas 78073, United States', 'lat': 29.3, 'lng': -98.5, 'coming_soon': False}


class TexBestTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='TEX BEST #504', address='I-35 EXIT 99', city='VON ORMY', state='TX', rows=[{'Truckstop Name': 'TEX BEST #504'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=TEXBEST, source=TEXBEST_SOURCE):
        return valid_operator_record(self.station, {'store': {'source': source, 'record': raw}, 'identity_only': True}, [29.3, -98.5], TEXBEST_BOUNDARY)

    def test_exact_raw_identity_and_unambiguous_address(self):
        self.assertTrue(self.valid())
        for change in ({'name': 'Tex-Best #505'}, {'name': 'Other #504'}, {'coming_soon': True}, {'coming_soon': 0}, {'lat': True}, {'lat': float('nan')}, {'address': 'Tex Best Travel Center, 18701 Interstate 35 Kyle, TX 78640 USA'}, {'address': '14650 Interstate 35 South, Other, TX 78073, United States'}, {'extra': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.valid({**TEXBEST, **change}))
        self.assertFalse(self.valid(source='https://example.com'))
        self.assertFalse(valid_operator_record(self.station, {'store': {'source': TEXBEST_SOURCE, 'record': TEXBEST}, 'identity_only': True}, [29.3, -98.5], {'type': 'Polygon', 'coordinates': [[[-96, 28], [-95, 28], [-95, 29], [-96, 29], [-96, 28]]]}))
        self.station.rows = [{'Truckstop Name': 'OTHER #504'}]
        self.assertFalse(self.valid())

    def test_resolver_and_import_recheck_raw_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [TEXBEST_BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': TEXBEST_SOURCE, 'stores': [TEXBEST]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_texbest', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], '14650 Interstate 35 South')
                self.assertEqual(self.station.evidence['operator_evidence']['store']['record'], TEXBEST)
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                raw = json.loads(rows[0]['operator_evidence'])
                raw['store']['record']['coming_soon'] = True
                rows[0]['operator_evidence'] = json.dumps(raw)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)


ASAP_SOURCE = 'https://asapenergyinc.com/locations/'
ASAP_BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'OK'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-100, 35], [-98, 35], [-98, 36], [-100, 36], [-100, 35]]]}}
ASAP = {'locator_pin': {'data-title': 'ASAP General Store 104', 'data-lat': '35.533867640099', 'data-lng': '-98.6594581604', 'address': ''}, 'detail_card': {'href': '/store104', 'title': 'ASAP General Store 104', 'address_lines': ['801 S Airport Road', 'Weatherford, OK 73096']}}


class ASAPTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='ASAP GENERAL STORE #104', address='I-40 EXIT 84', city='WEATHERFORD', state='OK', rows=[{'Truckstop Name': 'ASAP GENERAL STORE #104'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=ASAP):
        return valid_operator_record(self.station, {'store': {'source': ASAP_SOURCE, 'record': raw}, 'identity_only': True}, [35.533867640099, -98.6594581604], ASAP_BOUNDARY)

    def test_pin_card_same_number_and_address_required(self):
        self.assertTrue(self.valid())
        self.assertFalse(self.valid({'locator_pin': ASAP['locator_pin']}))
        for change in ({'href': '/store105'}, {'title': 'ASAP General Store 105'}, {'address_lines': ['801 S Airport Road', 'Other, OK 73096']}):
            self.assertFalse(self.valid({**ASAP, 'detail_card': {**ASAP['detail_card'], **change}}))
        for change in ({'data-title': 'ASAP General Store 105'}, {'data-lat': 'nan'}, {'data-lat': True}):
            self.assertFalse(self.valid({**ASAP, 'locator_pin': {**ASAP['locator_pin'], **change}}))
        self.assertFalse(self.valid({**ASAP, 'status': 'open'}))
        self.station.rows = [{'Truckstop Name': 'OTHER #104'}]
        self.assertFalse(self.valid())

    def test_native_address_lines_and_fragments(self):
        self.station.city = 'MADILL'
        self.station.rows = [{'Truckstop Name': 'ASAP GENERAL STORE #332'}]
        lines = ['1109 S 1st Street', 'Madill, OK 73446']
        pin = {**ASAP['locator_pin'], 'data-title': 'ASAP General Store 332', 'address': '1109 S 1st Street Madill, OK 73446', 'address_lines': lines}
        card = {'href': '/store332', 'title': pin['data-title'], 'address_lines': lines}
        self.assertTrue(self.valid({'locator_pin': pin, 'detail_card': card}))
        self.assertFalse(self.valid({'locator_pin': pin, 'detail_card': {**card, 'href': '/store333'}}))
        self.assertFalse(self.valid({'locator_pin': {**pin, 'address': 'Other address'}, 'detail_card': card}))
        self.station.city = 'HINTON'
        self.station.rows = [{'Truckstop Name': 'ASAP GENERAL STORE #322'}]
        fragments = [{'tag': 'span', 'text': '736 N. Broadway\u00a0'}, {'tag': 'text', 'text': 'Hinton'}, {'tag': 'span', 'text': ', OK 73047'}, {'tag': 'text', 'text': ', USA'}]
        pin = {**ASAP['locator_pin'], 'data-title': 'ASAP General Store 322', 'address': '736 N. Broadway Hinton, OK 73047, USA', 'address_fragments': fragments}
        self.assertTrue(self.valid({'locator_pin': pin}))
        self.assertFalse(self.valid({'locator_pin': {**pin, 'address_fragments': list(reversed(fragments))}}))
        self.assertFalse(self.valid({'locator_pin': pin, 'detail_card': {'href': '/store303', 'title': pin['data-title'], 'address_lines': []}}))

    def test_resolver_import_retains_raw_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [ASAP_BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': ASAP_SOURCE, 'stores': [ASAP]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_asap', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], '801 S Airport Road')
                self.assertEqual(self.station.evidence['operator_evidence']['store']['record'], ASAP)
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                rows[0]['longitude'] = '-98.6'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)


HUCKS_SOURCE = 'https://hucks.com/locations/'
HUCKS_BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'IL'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-90, 40], [-88, 40], [-88, 41], [-90, 41], [-90, 40]]]}}
HUCKS = {'location_title': 'Location #0186', 'address_lines': ['701 West Cleveland', 'Heyworth, IL 61745'], 'map_record': {'data-id': 'published-marker', 'data-latitude': '40.312511', 'data-longitude': '-88.985321'}}


class HucksTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='HUCKS FOOD & FUEL #186', address='I-55 EXIT 99', city='HEYWORTH', state='IL', rows=[{'Truckstop Name': 'HUCKS FOOD & FUEL #186'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=HUCKS, source=HUCKS_SOURCE):
        return valid_operator_record(self.station, {'store': {'source': source, 'record': raw}, 'identity_only': True}, [40.312511, -88.985321], HUCKS_BOUNDARY)

    def test_exact_published_identity_and_raw_fields(self):
        self.assertTrue(self.valid())
        for source_name in ('HUCKS FOOD AND FUEL #186', 'HUCKS MARKET #186', 'HUCKS TRAVEL CENTER #186', 'HUCKS TRAVEL CENTER #0186'):
            self.station.rows = [{'Truckstop Name': source_name}]
            self.assertTrue(self.valid())
        for source_name in ('HUCKS OTHER #186', 'HUCKS FOOD & FUEL #186 DBA PILOT #1294', 'PILOT #186', 'HUCKS #187'):
            self.station.rows = [{'Truckstop Name': source_name}]
            self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'HUCKS FOOD & FUEL #186'}]
        for raw in ({**HUCKS, 'location_title': 'Location #187'}, {**HUCKS, 'address_lines': ['701 West Cleveland', 'Other, IL 61745']}, {**HUCKS, 'address_lines': ['701 West Cleveland', 'Heyworth, IN 61745']}, {**HUCKS, 'map_record': {**HUCKS['map_record'], 'data-latitude': 'nan'}}, {**HUCKS, 'extra': 1}):
            self.assertFalse(self.valid(raw))
        self.assertFalse(self.valid(source='https://example.com'))

    def test_resolver_import_preserves_raw_and_discloses_source_address(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [HUCKS_BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': HUCKS_SOURCE, 'stores': [HUCKS]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_hucks', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['matched_name'], "Huck's")
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['operator_evidence']['store']['record'], HUCKS)
                self.assertEqual(self.station.evidence['matched_address'], '701 West Cleveland')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], self.station.address)
                rows[0]['longitude'] = '-88.8'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)


class JetFoodTests(TestCase):
    def setUp(self):
        from planner.raw_operator_evidence import JETFOOD_SOURCE
        self.source = JETFOOD_SOURCE
        self.raw = {'location_list_record': {'data-loc-id': '7218', 'published_address': 'Store #04: 10550 U.S. 1, Wadley, GA'}, 'map_marker': {'data-loc-id': '7218', 'data-lat': '33.0', 'data-lng': '-84.0'}}
        self.station = Station.objects.create(source_id='1', name='JET FOOD STORES #4', address='I-40 EXIT 99', city='WADLEY', state='GA', rows=[{'Truckstop Name': 'JET FOOD STORES #4'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=None):
        return valid_operator_record(self.station, {'store': {'source': self.source, 'record': raw or self.raw}, 'identity_only': True}, [33.0, -84.0], BOUNDARY)

    def test_published_address_formats_and_identity(self):
        from planner.raw_operator_evidence import published_postal_address
        for text, expected in (
            ('10550 U.S. 1, Wadley, GA', ('10550 U.S. 1', 'Wadley', 'GA')),
            ('706 North Main Street Wrens, Georgia 30833', ('706 North Main Street', 'Wrens', 'GA')),
            ('2897 Us Hwy 441 s Douglas GA', ('2897 Us Hwy 441 s', 'Douglas', 'GA')),
            ('18701 Interstate 35 Kyle, TX 78640, USA', ('18701 Interstate 35', 'Kyle', 'TX')),
            ('14650 Interstate 35 South, Von Ormy, Texas 78073, United States', ('14650 Interstate 35 South', 'Von Ormy', 'TX')),
        ):
            with self.subTest(text=text):
                self.assertEqual(published_postal_address(text), expected)
        for text in ('123 Road Unknown GA', '123 Main Street, Town, GA, Canada', 'I-75 EXIT 1, Town, GA', '123 Main St, Town', '706 North Main Street Lake St Wrens, Georgia 30833'):
            self.assertIsNone(published_postal_address(text))
        self.assertTrue(self.valid())
        self.station.rows = [{'Truckstop Name': 'JET FOOD STORE #04'}]
        self.assertTrue(self.valid())
        for name in ('JET FOOD STORES #5', 'OTHER #4', 'JET FOOD STORES #4 SHELL #7'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'JET FOOD STORES #4'}]
        self.assertFalse(self.valid({**self.raw, 'map_marker': {**self.raw['map_marker'], 'data-loc-id': 'wrong'}}))
        self.assertFalse(self.valid({**self.raw, 'map_marker': {**self.raw['map_marker'], 'data-lat': 'nan'}}))
        self.station.city = 'Other'
        self.assertFalse(self.valid())

    def test_resolver_import_rechecks_native_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': self.source, 'stores': [self.raw]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_jetfood', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], '10550 U.S. 1')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], 'I-40 EXIT 99')
                context = json.loads(rows[0]['operator_evidence'])
                context['store']['record']['map_marker']['data-loc-id'] = 'other'
                self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))


class Good2GoTests(TestCase):
    def setUp(self):
        from planner.raw_operator_evidence import GOOD2GO_SOURCE
        self.source = GOOD2GO_SOURCE
        self.raw = {'infoTitle': 'Good 2 Go #212', 'position': '1801 US Hwy 310, Lovell, WY 82431', 'infoAddress': '1801 US Hwy 310, Lovell, WY 82431', 'coordinates': '44.8376301, -108.4190535'}
        self.boundary = {'type': 'Feature', 'properties': {'STUSPS': 'WY'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-110, 43], [-107, 43], [-107, 46], [-110, 46], [-110, 43]]]}}
        self.station = Station.objects.create(source_id='1', name='GOOD 2 GO #212', address='I-90 EXIT 1', city='LOVELL', state='WY', rows=[{'Truckstop Name': 'GOOD 2 GO #212'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=None, source=None):
        return valid_operator_record(self.station, {'store': {'source': source or self.source, 'record': raw or self.raw}, 'identity_only': True}, [44.8376301, -108.4190535], self.boundary)

    def test_exact_native_identity_address_and_point(self):
        self.assertTrue(self.valid())
        self.station.rows = [{'Truckstop Name': 'GOOD2GO #0212'}]
        self.assertTrue(self.valid())
        for name in ('GOOD 2 GO #213', 'ONE9 #212', 'GOOD 2 GO #212 ONE9 #1432'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'GOOD 2 GO #212'}]
        for change in ({'infoTitle': 'Good 2 Go #213'}, {'infoAddress': '1802 US Hwy 310, Lovell, WY 82431'}, {'position': '1801 US Hwy 310 Lovell WY 82431'}, {'coordinates': 'nan, -108.4190535'}, {'coordinates': '40, -108.4190535'}, {'extra': 'x'}):
            self.assertFalse(self.valid({**self.raw, **change}))
        self.assertFalse(self.valid(source='https://example.com/locations/'))
        self.station.city = 'Other'
        self.assertFalse(self.valid())
        self.station.city, self.station.state = 'Lovell', 'ID'
        self.assertFalse(self.valid())

    def test_resolver_import_and_tampered_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [self.boundary]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': self.source, 'stores': [self.raw]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_good2go', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], '1801 US Hwy 310')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], 'I-90 EXIT 1')
                context = json.loads(rows[0]['operator_evidence'])
                context['store']['record']['coordinates'] = '44.8, -108.4'
                self.assertFalse(valid_operator_record(self.station, context, [44.8376301, -108.4190535], self.boundary))
                source.write_text(json.dumps({'source': self.source, 'stores': [self.raw, {**self.raw, 'infoTitle': 'Good 2 Go #213'}]}))
                duplicate = root / 'duplicate.csv'
                call_command('resolve_good2go', input=str(source), output=str(duplicate), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with duplicate.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])


class SpinxTests(TestCase):
    def setUp(self):
        from planner.raw_operator_evidence import SPINX_SOURCE
        self.source = SPINX_SOURCE
        self.raw = {'data-post-id': '7190', 'title': 'Spinx #179 ›', 'address': '2901 North Pleasantburg Dr, Greenville, SC 29609', 'map_record': {'id': 7190, 'latLang': {'lat': 34.8862156, 'lng': -82.3918975}}}
        self.boundary = {'type': 'Feature', 'properties': {'STUSPS': 'SC'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-84, 33], [-81, 33], [-81, 36], [-84, 36], [-84, 33]]]}}
        self.station = Station.objects.create(source_id='1', name='SPINX 179', address='I-85 EXIT 1', city='GREENVILLE', state='SC', rows=[{'Truckstop Name': 'SPINX 179'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=None, source=None):
        return valid_operator_record(self.station, {'store': {'source': source or self.source, 'record': raw or self.raw}, 'identity_only': True}, [34.8862156, -82.3918975], self.boundary)

    def test_strict_published_identity_and_marker(self):
        from planner.raw_operator_evidence import spinx_source_numbers
        self.assertEqual(spinx_source_numbers('Spinx 317'), {'317'})
        self.assertEqual(spinx_source_numbers('Spinx317'), set())
        self.assertTrue(self.valid())
        self.station.rows = [{'Truckstop Name': 'SPINX #179 (DISCOUNT AVAILABLE)'}]
        self.assertTrue(self.valid())
        self.station.rows = [{'Truckstop Name': 'SPINX #0179'}]
        self.assertTrue(self.valid())
        for name in ('SPINX179', 'SPINX 179 HIGHWAY 1', 'SPINX 180', 'SPINX #180', 'OTHER #179', 'SPINX #179 (OTHER)', 'SPINX #179 PILOT #4'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'SPINX #179'}]
        for change in ({'title': 'Spinx #180 ›'}, {'title': 'Spinx #179'}, {'address': '2901 Main St, Other, SC 29609'}, {'address': '2901 Main St, Greenville, GA 29609'}, {'data-post-id': '7191'}, {'map_record': {'id': 7190, 'latLang': {'lat': True, 'lng': -82.3918975}}}, {'extra': 1}):
            self.assertFalse(self.valid({**self.raw, **change}))
        self.assertFalse(self.valid(source='https://example.com/locations/'))
        self.station.city = 'Other'
        self.assertFalse(self.valid())
        self.station.city, self.station.state = 'Greenville', 'GA'
        self.assertFalse(self.valid())

    def test_resolver_import_tamper_and_duplicate_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [self.boundary]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': self.source, 'stores': [self.raw]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_spinx', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], '2901 North Pleasantburg Dr')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], 'I-85 EXIT 1')
                context = json.loads(rows[0]['operator_evidence'])
                context['store']['record']['map_record']['id'] = 7191
                self.assertFalse(valid_operator_record(self.station, context, [34.8862156, -82.3918975], self.boundary))
                source.write_text(json.dumps({'source': self.source, 'stores': [self.raw, {**self.raw, 'title': 'Spinx #180 ›'}]}))
                duplicate = root / 'duplicate.csv'
                call_command('resolve_spinx', input=str(source), output=str(duplicate), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with duplicate.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])


class PetesTests(TestCase):
    def setUp(self):
        from planner.raw_operator_evidence import PETES_SOURCE
        self.source = PETES_SOURCE
        self.raw = {'marker_id': '1597', 'marker_title': 'PETES 05', 'latitude': '37.36392944897959', 'longitude': '-95.25848169387756', 'popup_url': 'https://petescorp.com/places/petes-05/', 'popup_title': 'PETES 05', 'postal_address': {'streetAddress': '2431 North 16th Street', 'addressLocality': 'Parsons', 'addressRegion': 'Kansas', 'postalCode': '67357', 'addressCountry': 'United States'}, 'source_listing': self.source, 'popup_endpoint': 'https://petescorp.com/wp-json/geodir/v2/markers/1597', 'popup_map': 'osm'}
        self.point = [37.36392944897959, -95.25848169387756]
        self.boundary = {'type': 'Feature', 'properties': {'STUSPS': 'KS'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-97, 36], [-94, 36], [-94, 39], [-97, 39], [-97, 36]]]}}
        self.station = Station.objects.create(source_id='1', name="PETE'S 5", address='US-59 & US-400', city='PARSONS', state='KS', rows=[{'Truckstop Name': "PETE'S 5"}], price=3, price_min=3, price_max=3)

    def valid(self, raw=None, source=None):
        return valid_operator_record(self.station, {'store': {'source': source or self.source, 'record': raw or self.raw}, 'identity_only': True}, self.point, self.boundary)

    def test_native_binding_identity_and_metadata(self):
        from planner.raw_operator_evidence import petes_source_numbers
        self.assertEqual(petes_source_numbers("PETE'S 49"), {'49'})
        self.assertEqual(petes_source_numbers("PETE'S49"), set())
        self.assertTrue(self.valid())
        self.station.rows = [{'Truckstop Name': "PETE'S #05"}]
        self.assertTrue(self.valid())
        for name in ('PETES05', 'PETES 05 HIGHWAY 1', 'PETES 06', 'PETES #6', 'OTHER #5', 'PETES #5 PILOT #6'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'PETES #5'}]
        for change in ({'marker_id': '1598'}, {'popup_title': 'PETES 06'}, {'popup_endpoint': 'https://petescorp.com/wp-json/geodir/v2/markers/1598'}, {'popup_url': 'https://example.com/places/petes-05/'}, {'popup_map': 'other'}, {'latitude': 'nan'}, {'source_listing': 'https://example.com/'}, {'extra': 1}, {'postal_address': {**self.raw['postal_address'], 'addressLocality': 'Other'}}, {'postal_address': {**self.raw['postal_address'], 'addressRegion': 'Oklahoma'}}):
            self.assertFalse(self.valid({**self.raw, **change}))
        self.assertFalse(self.valid(source='https://example.com/locations/'))
        self.station.city = 'Other'
        self.assertFalse(self.valid())

    def test_published_food_suffix_and_resolver_import(self):
        from planner.raw_operator_evidence import raw_operator_view
        food = {**self.raw, 'marker_title': "PETES 05 SIMPLE SIMON'S & BROASTER CHICKEN", 'popup_title': 'PETES 05 SIMPLE SIMON&#8217;S &#038; BROASTER CHICKEN', 'popup_url': 'https://petescorp.com/places/petes-05-simple-simons-broaster-chicken/'}
        self.assertIsNotNone(raw_operator_view({'source': self.source, 'record': food}))
        self.assertIsNone(raw_operator_view({'source': self.source, 'record': {**food, 'popup_title': 'PETES 05 OTHER'}}))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [self.boundary]}))
            source, output = root / 'stores.json', root / 'evidence.csv'
            source.write_text(json.dumps({'source': self.source, 'stores': [self.raw]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_petes', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.evidence['matched_address'], '2431 North 16th Street')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], 'US-59 & US-400')
                context = json.loads(rows[0]['operator_evidence'])
                context['store']['record']['popup_endpoint'] += '0'
                self.assertFalse(valid_operator_record(self.station, context, self.point, self.boundary))
                source.write_text(json.dumps({'source': self.source, 'stores': [self.raw, self.raw]}))
                duplicate = root / 'duplicate.csv'
                call_command('resolve_petes', input=str(source), output=str(duplicate), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with duplicate.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])


class DuckAndDandyTests(TestCase):
    def test_native_records_and_strict_provider_identity(self):
        from planner.raw_operator_evidence import DANDY_SOURCE, DUCKTHRU_SOURCE, dandy_source_brand, duckthru_source_brand, raw_operator_view
        duck = {'source_page_uri': 'https://duckthru.com/stores/duck-thru-5/', 'published_page_title': 'Duck Thru #05 in Franklin, VA', 'location': {'store': 'Duck Thru #05', 'address': '30001 Smith Ferry Rd', 'address2': '', 'city': 'Franklin', 'state': 'VA', 'zip': '23851', 'country': 'United States', 'lat': '36.612540', 'lng': '-76.929059', 'id': 600, 'mapShortcode': True}}
        dandy = {'id': 6363, 'store': 'North Towanda &#8211; Dandy 5', 'address': '474 Reuter Blvd', 'address2': '', 'city': 'Towanda', 'state': 'PA', 'zip': '18848', 'country': 'United States', 'lat': '41.78726', 'lng': '-76.453648', 'url': 'https://www.godandy.com/north-towanda-dandy-5/'}
        self.assertEqual(raw_operator_view({'source': DUCKTHRU_SOURCE, 'record': duck})['number'], '05')
        self.assertEqual(raw_operator_view({'source': DANDY_SOURCE, 'record': dandy})['number'], '5')
        for country in ('US', 'USA', 'United States'):
            self.assertIsNotNone(raw_operator_view({'source': DUCKTHRU_SOURCE, 'record': {**duck, 'location': {**duck['location'], 'country': country}}}))
            self.assertIsNotNone(raw_operator_view({'source': DANDY_SOURCE, 'record': {**dandy, 'country': country}}))
        for country in ('CA', '', None):
            self.assertIsNone(raw_operator_view({'source': DUCKTHRU_SOURCE, 'record': {**duck, 'location': {**duck['location'], 'country': country}}}))
        self.assertEqual(duckthru_source_brand('DUCK THRU FOOD STORE #05'), 'DUCK THRU')
        self.assertEqual(dandy_source_brand('DANDY MINI MART #5'), 'DANDY')
        self.assertFalse(duckthru_source_brand('DUCK THRU #5 PILOT #3'))
        self.assertFalse(dandy_source_brand('DANDY OTHER #5'))
        for raw, source in (({**duck, 'source_page_uri': 'https://duckthru.com/stores/duck-thru-6/'}, DUCKTHRU_SOURCE), ({**duck, 'location': {**duck['location'], 'mapShortcode': False}}, DUCKTHRU_SOURCE), ({**dandy, 'url': 'https://example.com/'}, DANDY_SOURCE), ({**dandy, 'lat': 'nan'}, DANDY_SOURCE), ({**dandy, 'store': 'Towanda Dandy'}, DANDY_SOURCE)):
            self.assertIsNone(raw_operator_view({'source': source, 'record': raw}))

    def test_duck_and_dandy_resolve_import_and_recheck(self):
        from planner.raw_operator_evidence import DANDY_SOURCE, DUCKTHRU_SOURCE
        cases = [
            ('duckthru', DUCKTHRU_SOURCE, 'DUCK THRU FOOD STORE #5', 'Franklin', 'VA', 36.61254, -76.929059, {'source_page_uri': 'https://duckthru.com/stores/duck-thru-5/', 'published_page_title': 'Duck Thru #05 in Franklin, VA', 'location': {'store': 'Duck Thru #05', 'address': '30001 Smith Ferry Rd', 'address2': '', 'city': 'Franklin', 'state': 'VA', 'zip': '23851', 'country': 'United States', 'lat': '36.612540', 'lng': '-76.929059', 'id': 600, 'mapShortcode': True}}),
            ('dandy', DANDY_SOURCE, 'DANDY MINI MART #5', 'Towanda', 'PA', 41.78726, -76.453648, {'id': 6363, 'store': 'North Towanda &#8211; Dandy 5', 'address': '474 Reuter Blvd', 'address2': '', 'city': 'Towanda', 'state': 'PA', 'zip': '18848', 'country': 'United States', 'lat': '41.78726', 'lng': '-76.453648', 'url': 'https://www.godandy.com/north-towanda-dandy-5/'})]
        for command, source_url, name, city, state, lat, lon, raw in cases:
            with self.subTest(provider=command), tempfile.TemporaryDirectory() as directory:
                Station.objects.all().delete()
                station = Station.objects.create(source_id=command, name=name, address='I-40 EXIT 99', city=city.upper(), state=state, rows=[{'Truckstop Name': name}], price=3, price_min=3, price_max=3)
                boundary = {'type': 'Feature', 'properties': {'STUSPS': state}, 'geometry': {'type': 'Polygon', 'coordinates': [[[lon-1, lat-1], [lon+1, lat-1], [lon+1, lat+1], [lon-1, lat+1], [lon-1, lat-1]]]}}
                root = Path(directory)
                (root / 'data').mkdir()
                (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
                source, output = root / 'stores.json', root / 'evidence.csv'
                source.write_text(json.dumps({'source': source_url, 'stores': [raw]}))
                with override_settings(BASE_DIR=root):
                    call_command('resolve_' + command, input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                    with output.open(newline='') as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), 1)
                    call_command('load_data', 'evidence', str(output), verbosity=0)
                    station.refresh_from_db()
                    self.assertEqual([station.latitude, station.longitude], [lat, lon])
                    self.assertEqual(station.evidence['unverified_source_address_details'], station.address)
                    context = json.loads(rows[0]['operator_evidence'])
                    context['store']['record']['location' if command == 'duckthru' else 'lat'] = {} if command == 'duckthru' else 'nan'
                    self.assertFalse(valid_operator_record(station, context, [lat, lon], boundary))


class ParkersTests(TestCase):
    def setUp(self):
        from planner.raw_operator_evidence import PARKERS_SOURCE
        self.source = PARKERS_SOURCE
        self.raw = {'publisher_label': "Town Parker's ^{#101}", 'detail_page_excerpt': "#101 | Town Parker's | 123 Main St | Town, Georgia 30000", 'page_url': 'https://parkerskitchen.com/locations/parkers-101/', 'directions_href': 'https://maps.google.com/?daddr=33.0+-84.0&saddr=Current+Location', 'point': {'latitude': 33.0, 'longitude': -84.0}}
        self.station = Station.objects.create(source_id='1', name='PARKERS #101', address='I-40 EXIT 99', city='TOWN', state='GA', rows=[{'Truckstop Name': 'PARKERS #101'}], price=3, price_min=3, price_max=3)

    def test_native_binding_and_identity(self):
        from planner.raw_operator_evidence import parkers_source_brand, raw_operator_view
        wrap = lambda raw: {'source': self.source, 'record': raw}
        self.assertIsNotNone(raw_operator_view(wrap(self.raw)))
        self.assertEqual(parkers_source_brand("PARKER'S #101 (DISCOUNT AVAILABLE)"), 'PARKERS')
        for change in ({'publisher_label': "Town Parker's ^{#102}"}, {'detail_page_excerpt': "#102 | Town Parker's | 123 Main St | Town, Georgia 30000"}, {'detail_page_excerpt': "#101 | Other Parker's | 123 Main St | Town, Georgia 30000"}, {'page_url': 'https://parkerskitchen.com/locations/parkers-102/'}, {'directions_href': 'https://maps.google.com/?daddr=123+Main+St'}, {'directions_href': 'https://maps.google.com/?daddr=33+-84&daddr=33+-84'}, {'directions_href': 'https://evil.example/?daddr=33+-84'}, {'point': {'latitude': True, 'longitude': -84.0}}, {'point': {'latitude': 34.0, 'longitude': -84.0}}, {'extra': 1}, {'detail_page_excerpt': "#101 | Town Parker's | 123 Main St | Town, Florida 30000"}):
            with self.subTest(change=change):
                self.assertIsNone(raw_operator_view(wrap({**self.raw, **change})))
        context = {'store': wrap(self.raw), 'identity_only': True}
        self.assertTrue(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': wrap(self.raw)}, [33.0, -84.0], BOUNDARY))
        for name in ('OTHER #101', 'PARKERS', 'PARKERS #102', 'PARKERS FOOD #101'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'PARKERS #101'}]
        self.station.city = 'OTHER'
        self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))
        self.station.city, self.station.state = 'TOWN', 'SC'
        self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))

    def test_port_wentworth_state_bounded_resolve_import(self):
        from django.conf import settings
        from planner.osm_evidence import evidence_city_key
        self.assertEqual(evidence_city_key('Port Wentworth', 'GA'), evidence_city_key('Pt. Wentworth', 'GA'))
        self.assertNotEqual(evidence_city_key('Port Wentworth'), evidence_city_key('Pt. Wentworth'))
        self.assertNotEqual(evidence_city_key('Port Wentworth', 'SC'), evidence_city_key('Pt. Wentworth', 'SC'))
        self.assertNotEqual(evidence_city_key('Port Royal', 'GA'), evidence_city_key('Pt. Royal', 'GA'))
        self.assertNotEqual(evidence_city_key('Mount Vernon', 'MO'), evidence_city_key('Mt. Vernon', 'MO'))
        asset = json.loads((settings.BASE_DIR / 'data/source_parkers_locations.json').read_text())
        raw = next(record for record in asset['stores'] if record['page_url'].endswith('/parkers-16/'))
        self.assertIn('Pt. Wentworth, Georgia 31407', raw['detail_page_excerpt'])
        self.assertEqual(raw['point'], {'latitude': 32.146916, 'longitude': -81.17731})
        self.station.name = 'PARKERS #16 (DISCOUNT AVAILABLE)'
        self.station.rows = [{'Truckstop Name': self.station.name}]
        self.station.city = 'PORT WENTWORTH'
        self.station.address = 'SR-21'
        self.station.save()
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'GA'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-82, 31], [-80, 31], [-80, 33], [-82, 33], [-82, 31]]]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
            source = root / 'data/source_parkers_locations.json'
            source.write_text(json.dumps({'source': self.source, 'stores': [raw]}))
            output = root / 'evidence.csv'
            with override_settings(BASE_DIR=root):
                call_command('resolve_parkers', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertTrue(json.loads(rows[0]['operator_evidence'])['identity_only'])
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], [32.146916, -81.17731])
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], 'SR-21')
                self.assertEqual(self.station.evidence['matched_address'], '6000 Hwy 21')

    def test_resolve_import_catalog_and_disclosure(self):
        from django.core.management.base import CommandError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            asset = {'source': self.source, 'stores': [self.raw]}
            source = root / 'data/source_parkers_locations.json'
            source.write_text(json.dumps(asset))
            output = root / 'evidence.csv'
            with override_settings(BASE_DIR=root):
                call_command('resolve_parkers', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertTrue(json.loads(rows[0]['operator_evidence'])['identity_only'])
                source.write_text(json.dumps({'source': self.source, 'stores': [{**self.raw, 'publisher_label': "Changed Parker's ^{#101}", 'detail_page_excerpt': "#101 | Changed Parker's | 123 Main St | Town, Georgia 30000"}]}))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                for bad in ([self.raw, self.raw], [self.raw, {**self.raw, 'page_url': 'invalid'}], [self.raw, {**self.raw, 'publisher_label': "Other Parker's ^{#102}", 'detail_page_excerpt': "#102 | Other Parker's | 123 Main St | Town, Georgia 30000", 'page_url': 'https://parkerskitchen.com/locations/parkers-102/'}]):
                    source.write_text(json.dumps({'source': self.source, 'stores': bad}))
                    call_command('load_data', 'evidence', str(output), verbosity=0)
                    self.station.refresh_from_db()
                    self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps(asset))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], [33.0, -84.0])
                self.assertEqual(self.station.evidence['unverified_source_address_details'], self.station.address)
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                for duplicate in (self.raw, {**self.raw, 'publisher_label': "Other Parker's ^{#102}", 'detail_page_excerpt': "#102 | Other Parker's | 123 Main St | Town, Georgia 30000", 'page_url': 'https://parkerskitchen.com/locations/parkers-102/'}, {**self.raw, 'page_url': 'invalid'}):
                    source.write_text(json.dumps({'source': self.source, 'stores': [self.raw, duplicate]}))
                    with self.assertRaises(CommandError):
                        call_command('resolve_parkers', input=str(source), output=str(root / 'other.csv'), unresolved=str(root / 'other-missing.csv'), verbosity=0)


class KentKwikTests(TestCase):
    def setUp(self):
        from planner.raw_operator_evidence import KENTKWIK_MAP, KENTKWIK_SOURCE
        self.source = KENTKWIK_SOURCE
        self.marker = [41, 33.0, -84.0, 'Kent Kwik Location #804', 5]
        self.record = {'marker': self.marker, 'popup': {'request': {'is_grouped': '0', 'map_id': '182317', 'data_id': '182459', 'id': '41', 'lt': '33.0', 'ln': '-84.0'}, 'response_fields': {'response': True, 'description.html.heading': "<h1 class='small title_header'>Kent Kwik Location #804</h1>", 'description.html.address_block': '<p class="p_description" style="z-index:1;">123 Main St <br />\nTown, GA 30000 <br />\nUSA <br /></p>'}}}
        self.asset = {'source': self.source, 'map': KENTKWIK_MAP, 'marker_request': {}, 'markers': [self.marker], 'stores': [self.record]}
        self.station = Station.objects.create(source_id='1', name='KENT KWIK #804', address='I-40 EXIT 99', city='TOWN', state='GA', rows=[{'Truckstop Name': 'KENT KWIK #804'}], price=3, price_min=3, price_max=3)

    def test_binding_and_identity(self):
        from copy import deepcopy
        from planner.raw_operator_evidence import raw_operator_view
        wrap = lambda raw: {'source': self.source, 'record': raw}
        self.assertIsNotNone(raw_operator_view(wrap(self.record)))
        for section, field, value in (('request', 'id', '42'), ('request', 'lt', '34'), ('request', 'map_id', '1'), ('request', 'is_grouped', '1'), ('response_fields', 'response', False), ('response_fields', 'description.html.heading', "<h1 class='small title_header'>Kent Kwik Location #805</h1>"), ('response_fields', 'description.html.address_block', '<p>Town</p>')):
            bad = deepcopy(self.record)
            bad['popup'][section][field] = value
            self.assertIsNone(raw_operator_view(wrap(bad)))
        context = {'store': wrap(self.record), 'identity_only': True}
        self.assertTrue(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': wrap(self.record)}, [33.0, -84.0], BOUNDARY))
        for name in ('RUSTIC CAFE #804', 'KENT KWIK', 'KENT KWIK #805', 'KENT KWIK OTHER #804'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'KENT KWIK #804'}]
        self.station.city = 'OTHER'
        self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))
        self.station.city, self.station.state = 'TOWN', 'SC'
        self.assertFalse(valid_operator_record(self.station, context, [33.0, -84.0], BOUNDARY))

    def test_catalog_local_collisions_and_invalid_markers(self):
        from planner.raw_operator_evidence import validated_kentkwik_records
        markers = [self.marker, [42, 34.0, -84.0, 'Kent Kwik #306', 5], [43, 35.0, -84.0, 'Kent Kwik #306', 5], [44, 33.0, -84.0, 'Rustic Cafe #804', 7]]
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers}), [self.record])
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers + [[45, 36.0, -84.0, 'Kent Kwik #804', 5]]}), [])
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers + [[45, 33.0, -84.0, 'Kent Kwik #805', 5]]}), [])
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers + [[45, 33.0, -84.0, 'Kent Kwik #bad', 5]]}), [])
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers + [[45, 33.0, -84.0, 'Kent Kwik', 5]]}), [])
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers + [[45, 36.0, -84.0, 'Kent Kwik', 5]]}), [self.record])
        self.assertEqual(validated_kentkwik_records({**self.asset, 'markers': markers + [[45, 33.0, -84.0, 'Rustic Cafe', 7]]}), [self.record])
        for bad in ([41, 34.0, -84.0, 'Kent Kwik #805', 5], [45, True, -84.0, 'Kent Kwik #805', 5]):
            with self.assertRaises(ValueError):
                validated_kentkwik_records({**self.asset, 'markers': markers + [bad]})

    def test_bundled_native_catalog(self):
        from django.conf import settings
        from planner.raw_operator_evidence import kentkwik_marker_number, validated_kentkwik_records
        asset = json.loads((settings.BASE_DIR / 'data/source_kentkwik_locations.json').read_text())
        original = json.loads(json.dumps(asset['markers']))
        records = validated_kentkwik_records(asset)
        self.assertEqual(len(asset['markers']), 177)
        self.assertEqual(len(records), 10)
        self.assertEqual({kentkwik_marker_number(record['marker'][3]) for record in records}, {'804', '501', '928', '273', '262', '315', '219', '433', '221', '206'})
        self.assertEqual(asset['markers'], original)
        self.assertTrue(any(isinstance(marker[1], str) for marker in asset['markers']))
        self.assertTrue(all(record['marker'] in asset['markers'] for record in records))

    def test_native_string_points(self):
        from copy import deepcopy
        from planner.raw_operator_evidence import raw_operator_view, validated_kentkwik_records
        record = deepcopy(self.record)
        record['marker'][1:3] = ['33.0', '-84.0']
        asset = {**self.asset, 'markers': [record['marker'], [42, '34.0', '-84.0', 'Kent Kwik', 5]], 'stores': [record]}
        self.assertEqual(raw_operator_view({'source': self.source, 'record': record})['latitude'], 33.0)
        self.assertEqual(validated_kentkwik_records(asset), [record])
        asset['markers'].append([43, '33.0', '-84.0', 'Kent Kwik', 5])
        self.assertEqual(validated_kentkwik_records(asset), [])
        for invalid in ('nan', 'inf', '33x', '', True, float('nan'), float('inf')):
            bad = {**asset, 'markers': [record['marker'], [42, invalid, '-84.0', 'Kent Kwik', 5]]}
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validated_kentkwik_records(bad)

    def test_zero_id_and_plain_number_collision(self):
        from copy import deepcopy
        from planner.raw_operator_evidence import raw_operator_view, validated_kentkwik_records
        record = deepcopy(self.record)
        record['marker'][0] = 0
        record['popup']['request']['id'] = '0'
        self.assertIsNotNone(raw_operator_view({'source': self.source, 'record': record}))
        asset = {**self.asset, 'markers': [record['marker']], 'stores': [record]}
        self.assertEqual(validated_kentkwik_records(asset), [record])
        record['marker'][3] = 'Kent Kwik #615'
        record['popup']['response_fields']['description.html.heading'] = "<h1 class='title_header'>Kent Kwik #615</h1>"
        asset['markers'].append([42, 34.0, -84.0, 'Kent Kwik 615', 5])
        self.assertEqual(validated_kentkwik_records(asset), [])

    def test_resolve_import_and_catalog_recheck(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source = root / 'data/source_kentkwik_locations.json'
            source.write_text(json.dumps(self.asset))
            output = root / 'evidence.csv'
            with override_settings(BASE_DIR=root):
                call_command('resolve_kentkwik', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                source.write_text(json.dumps({**self.asset, 'markers': [self.marker, [42, 34.0, -84.0, 'Kent Kwik #804', 5]]}))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps({**self.asset, 'stores': []}))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps(self.asset))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], [33.0, -84.0])
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                self.assertEqual(self.station.evidence['unverified_source_address_details'], self.station.address)
