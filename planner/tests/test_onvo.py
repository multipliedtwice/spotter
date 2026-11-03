import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.onvo_evidence import onvo_key, valid_onvo_record

RAW = {'source_url': 'https://tryonvo.com/location/onvo-harford/', 'page_title': 'Onvo Harford | Truck Stop & Travel Plaza in Harford, PA', 'schema_type': 'GasStation', 'name': 'Onvo – Harford', 'street_address_literal': '5085 State Route 547, Harford, PA 18834, USA', 'address_locality_literal': '', 'address_region_literal': '', 'address_postal_code_literal': '', 'address_country_literal': 'US', 'latitude': 41.790287, 'longitude': -75.6800372, 'map_marker_latitude': '41.790287', 'map_marker_longitude': '-75.6800372', 'literal_route_labels': ['Exit 217 I-81'], 'literal_road_mentions': ['Interstate 81 at Exit 217', 'State Route 547'], 'map_link': 'https://www.google.com/maps/search/?api=1&query=41.790287%2C-75.6800372'}
POINT = [41.790287, -75.6800372]
BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'PA'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-77, 41], [-75, 41], [-75, 43], [-77, 43], [-77, 41]]]}}


class OnvoTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='66116', name='ONVO TRAVEL PLAZA - HARFORD', address='I-81 EXIT 217 & SR-547', city='HARFORD', state='PA', rows=[{'Truckstop Name': 'ONVO TRAVEL PLAZA - HARFORD'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=RAW):
        return valid_onvo_record(self.station, {'source': raw['source_url'], 'record': raw}, POINT, BOUNDARY)

    def test_exact_branch_and_full_road_proof(self):
        from planner.onvo_evidence import branch_key
        self.assertEqual(branch_key('Onvo – Mt. Cobb', native=True), branch_key('ONVO TRAVEL PLAZA - MT COBB'))
        self.assertNotEqual(branch_key('Onvo – Mt. Cobb', native=True), branch_key('ONVO TRAVEL PLAZA - MOUNTAIN COBB'))
        self.assertTrue(self.valid())
        self.assertFalse(self.valid({**RAW, 'literal_route_labels': []}))
        self.assertFalse(self.valid({**RAW, 'literal_route_labels': [None]}))
        self.assertFalse(self.valid({**RAW, 'literal_road_mentions': 'not a list'}))
        for change in ({'name': 'Onvo – Other'}, {'name': 'Onvo Express – Harford'}, {'source_url': 'https://example.com/location/onvo-harford/'}, {'street_address_literal': '5085 State Route 548, Harford, PA 18834, USA'}, {'literal_route_labels': ['Exit 218 I-81']}, {'literal_route_labels': []}, {'latitude': 41.8}, {'address_country_literal': 'CA'}, {'schema_type': 'Restaurant'}):
            self.assertFalse(self.valid({**RAW, **change}))
        self.station.rows = [{'Truckstop Name': 'ONVO EXPRESS'}]
        self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'ONVO TRAVEL PLAZA - HARFORD #2'}]
        self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'ONVO TRAVEL PLAZA - HARFORD'}, {'Truckstop Name': 'ONVO EXPRESS'}]
        self.assertFalse(self.valid())
        self.station.rows = [{'Truckstop Name': 'ONVO TRAVEL PLAZA - HARFORD'}]
        self.station.address = 'I-81 EXIT 217 & SR-548'
        self.assertFalse(self.valid())
        self.station.address = 'I-81 EXIT 218 & SR-547'
        self.assertFalse(self.valid())
        self.station.address = 'I-81 EXIT 217 & SR-547 & CO-R6F'
        self.assertFalse(self.valid())
        self.station.address = 'I-81'
        self.assertFalse(self.valid())
        self.station.address = '5085 STATE ROUTE 547'
        self.assertTrue(self.valid())
        self.station.address = '5086 STATE ROUTE 547'
        self.assertFalse(self.valid())
        self.station.address = 'I-81 EXIT 217 & SR-547'
        self.assertFalse(valid_onvo_record(self.station, {'source': RAW['source_url'], 'record': RAW, 'identity_only': True}, POINT, BOUNDARY))
        self.station.city = 'Other'
        self.assertFalse(self.valid())
        self.station.city, self.station.state = 'HARFORD', 'NY'
        self.assertFalse(self.valid())

    def test_resolver_import_rechecks_catalog_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source, output = root / 'data/source_onvo_locations.json', root / 'evidence.csv'
            source.write_text(json.dumps({'records': [RAW]}))
            with override_settings(BASE_DIR=root):
                call_command('resolve_onvo', input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], POINT)
                self.assertEqual(self.station.evidence['matched_address'], '5085 State Route 547')
                from planner.planning import station_data
                display = station_data(self.station)
                self.assertEqual(display['address'], '5085 State Route 547')
                self.assertEqual(display['source_address'], 'I-81 EXIT 217 & SR-547')
                self.assertEqual(display['verification_scope'], 'operator_branch_and_address')
                context = json.loads(rows[0]['directory_evidence'])
                context['record']['literal_route_labels'] = ['Exit 218 I-81']
                self.assertFalse(valid_onvo_record(self.station, context, POINT, BOUNDARY))
                self.assertIsNone(onvo_key({**context, 'source': 'https://example.com'}))
                source.write_text(json.dumps({'records': [RAW, RAW]}))
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                duplicate = root / 'duplicate.csv'
                call_command('resolve_onvo', input=str(source), output=str(duplicate), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with duplicate.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                source.write_text(json.dumps({'records': [RAW, {**RAW, 'source_url': 'https://tryonvo.com/location/onvo-other/'}]}))
                duplicate_point = root / 'duplicate-point.csv'
                call_command('resolve_onvo', input=str(source), output=str(duplicate_point), unresolved=str(root / 'duplicate-point-missing.csv'), verbosity=0)
                with duplicate_point.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                source.write_text(json.dumps({'records': [RAW]}))
                Station.objects.create(source_id='other', name=self.station.name, address=self.station.address, city=self.station.city, state=self.station.state, rows=self.station.rows, price=4, price_min=4, price_max=4)
                ambiguous = root / 'owners.csv'
                call_command('resolve_onvo', input=str(source), output=str(ambiguous), unresolved=str(root / 'owners-missing.csv'), verbosity=0)
                with ambiguous.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
