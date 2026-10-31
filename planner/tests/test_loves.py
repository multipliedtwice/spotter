import csv
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
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
