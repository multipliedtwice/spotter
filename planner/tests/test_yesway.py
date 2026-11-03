import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import YESWAY_SOURCE, valid_operator_record

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'TX'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-102, 32], [-100, 32], [-100, 34], [-102, 34], [-102, 32]]]}}
STORE = {'number': '247', 'name': "Allsup's #247", 'address': '123 Main Street', 'city': 'Town', 'state': 'TX', 'country': 'US', 'latitude': 33.0, 'longitude': -101.0, 'coming_soon': False, 'amenities': [], 'fuel_cards': [], 'source': YESWAY_SOURCE}
NATIVE = {'id': 1, 'store': 'Allsup&#8217;s Store # 247', 'acf': {'business_name': "Allsup's", 'internal_store_code': '100247', 'address_line_1': '123 Main Street', 'address_line_2': '', 'city': 'Town', 'state': 'TX', 'country': 'US', 'postal_code': '12345', 'latitude': '33.0', 'longitude': '-101.0', 'coming_soon': False, 'amenities': [], 'fuel_card': []}}


def native(raw=NATIVE):
    return {'source': YESWAY_SOURCE, 'record': raw}


class YeswayTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='ALLSUPS #247', address='123 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name': 'ALLSUPS #247'}], price=3, price_min=3, price_max=3)

    def test_record_requires_exact_store_and_published_status(self):
        def valid(store):
            return valid_operator_record(self.station, {'store': store}, [33.0, -101.0], BOUNDARY)
        self.assertTrue(valid(STORE))
        self.assertTrue(valid({**STORE, 'coming_soon': None, 'fuel_cards': None}))
        for change in ({'coming_soon': True}, {'coming_soon': 0}, {'country': 'CA'}, {'name': 'Yesway #247'}, {'name': "Allsup's #248"}, {'number': ''}, {'source': 'https://example.com'}, {'longitude': float('nan')}, {'amenities': None}, {'fuel_cards': 'none'}):
            with self.subTest(change=change):
                self.assertFalse(valid({**STORE, **change}))

    def test_allsups_convenience_store_exact_variant(self):
        self.station.rows = [{'Truckstop Name': "ALLSUP'S CONVENIENCE STORE #247"}]
        self.assertTrue(valid_operator_record(self.station, {'store': STORE}, [33.0, -101.0], BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': {**STORE, 'name': "Allsup's #248"}}, [33.0, -101.0], BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': {**STORE, 'name': 'Yesway #247'}}, [33.0, -101.0], BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'ALLSUPS CONVENIENCE #247'}]
        self.assertTrue(valid_operator_record(self.station, {'store': native(), 'identity_only': True}, [33.0, -101.0], BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'ALLSUPS MARKETPLACE #247'}]
        self.assertFalse(valid_operator_record(self.station, {'store': native(), 'identity_only': True}, [33.0, -101.0], BOUNDARY))
        self.station.rows = [{'Truckstop Name': "ALLSUP'S CONVENIENCE STORE #247"}]
        self.station.address = 'US-77'
        self.assertFalse(valid_operator_record(self.station, {'store': STORE}, [33.0, -101.0], BOUNDARY))

    def test_numbered_identity_only(self):
        self.station.address = 'I-40 EXIT 99'
        point = [33.0, -101.0]
        self.assertTrue(valid_operator_record(self.station, {'store': native(), 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': native({**NATIVE, 'acf': {**NATIVE['acf'], 'coming_soon': True}}), 'identity_only': True}, point, BOUNDARY))

    def test_native_displayed_number_is_not_internal_code(self):
        self.station.address = 'I-40 EXIT 99'
        self.station.rows = [{'Truckstop Name': 'ALLSUPS #2159'}]
        raw = {**NATIVE, 'store': 'Allsup&#8217;s Store # 2159', 'acf': {**NATIVE['acf'], 'internal_store_code': '102159'}}
        point = [33.0, -101.0]
        self.assertTrue(valid_operator_record(self.station, {'store': native(raw), 'identity_only': True}, point, BOUNDARY))
        without_optional = {**raw, 'acf': {key: value for key, value in raw['acf'].items() if key not in ('coming_soon', 'fuel_card')}}
        self.assertTrue(valid_operator_record(self.station, {'store': native(without_optional), 'identity_only': True}, point, BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'ALLSUPS #102159'}]
        self.assertFalse(valid_operator_record(self.station, {'store': native(raw), 'identity_only': True}, point, BOUNDARY))
        self.station.rows = [{'Truckstop Name': 'ALLSUPS #2159'}]
        for label in ('Yesway Wine & Spirits', 'Allsup&#8217;s Store # 2159 &#8211; Temp Closed', 'Allsup&#8217;s Store # 2160'):
            self.assertFalse(valid_operator_record(self.station, {'store': native({**raw, 'store': label}), 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': native({**raw, 'acf': {**raw['acf'], 'business_name': 'Yesway'}}), 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': native({**raw, 'acf': {**raw['acf'], 'latitude': 'nan'}}), 'identity_only': True}, point, BOUNDARY))
        self.assertFalse(valid_operator_record(self.station, {'store': native({**raw, 'acf': {**raw['acf'], 'internal_store_code': 102159}}), 'identity_only': True}, point, BOUNDARY))

    def test_resolve_import_and_namespaced_ownership(self):
        self.station.rows = [{'Truckstop Name': 'ALLSUPS CONVENIENCE #247'}]
        self.station.address = 'I-40 EXIT 99'
        self.station.save(update_fields=['rows', 'address'])
        kwik = {'number': '247', 'name': 'KWIK TRIP #247', 'address': '123 Main Street', 'city': 'Town', 'state': 'TX', 'latitude': 33.0, 'longitude': -101.0, 'sells_gas': True, 'sells_diesel': False, 'source': 'https://www.kwiktrip.com/Maps-Downloads/Store-List'}
        Station.objects.create(source_id='2', name='KWIK TRIP #247', address='123 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name': 'KWIK TRIP #247'}], price=3, price_min=3, price_max=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            yes, kwik_path = root / 'yes.json', root / 'kwik.json'
            unknown = {**NATIVE, 'acf': {**NATIVE['acf'], 'coming_soon': None, 'fuel_card': None}}
            yes.write_text(json.dumps({'source': YESWAY_SOURCE, 'stores': [unknown]}))
            kwik_path.write_text(json.dumps({'source': kwik['source'], 'stores': [kwik]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_yesway', input=str(yes), output=str(root / 'yes.csv'), unresolved=str(root / 'yes-missing.csv'), verbosity=0)
                call_command('resolve_kwiktrip', input=str(kwik_path), output=str(root / 'kwik.csv'), unresolved=str(root / 'kwik-missing.csv'), verbosity=0)
                with (root / 'yes.csv').open(newline='') as stream:
                    yes_rows = list(csv.DictReader(stream))
                with (root / 'kwik.csv').open(newline='') as stream:
                    kwik_rows = list(csv.DictReader(stream))
                self.assertEqual((len(yes_rows), len(kwik_rows)), (1, 1))
                with (root / 'merged.csv').open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=yes_rows[0].keys())
                    writer.writeheader()
                    writer.writerows(yes_rows + kwik_rows)
                call_command('load_data', 'evidence', str(root / 'merged.csv'), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual(self.station.latitude, 33.0)
                self.assertEqual(self.station.evidence['matched_address'], STORE['address'])
                self.assertEqual(self.station.evidence['unverified_source_address_details'], 'I-40 EXIT 99')
                self.assertEqual(self.station.evidence['verification_scope'], 'operator_identity_only')
                self.assertIsNone(self.station.evidence['operator_evidence']['store']['record']['acf']['coming_soon'])
                self.assertIsNone(self.station.evidence['operator_evidence']['store']['record']['acf']['fuel_card'])
                self.assertEqual(Station.objects.get(source_id='2').latitude, 33.0)
                yes_rows[0]['longitude'] = '-101.1'
                with (root / 'merged.csv').open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=yes_rows[0].keys())
                    writer.writeheader()
                    writer.writerows(yes_rows)
                call_command('load_data', 'evidence', str(root / 'merged.csv'), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
