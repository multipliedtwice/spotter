import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.operator_evidence import LOVES_SOURCE, valid_loves_route_record, valid_operator_record
from planner.osm_evidence import evidence_city_key


class PrimaryCityFormatTests(TestCase):
    def test_scoped_city_keys(self):
        for full, short, state in (('Fort Bridger', 'Ft. Bridger', 'WY'), ('North Little Rock', 'N. Little Rock', 'AR')):
            self.assertEqual(evidence_city_key(full, state), evidence_city_key(short, state))
            self.assertNotEqual(evidence_city_key(full), evidence_city_key(short))
            self.assertNotEqual(evidence_city_key(full, 'TN'), evidence_city_key(short, 'TN'))
        self.assertNotEqual(evidence_city_key('Fort Collins', 'WY'), evidence_city_key('Ft Collins', 'WY'))
        self.assertNotEqual(evidence_city_key('North Conway', 'AR'), evidence_city_key('N Conway', 'AR'))

    def test_numbered_primary_resolve_import_and_disclosure(self):
        cases = [
            ('resolve_ta', '3592', 'TA BRIDGER TRAVEL CENTER #188', 'I-80 EXIT 30 & CR-202', 'FORT BRIDGER', 'WY',
             {'number': '0188', 'name': 'TA Ft. Bridger #0188', 'address': 'I-80 at Bigelow Road, Exit 30', 'city': 'Ft. Bridger', 'state': 'WY', 'latitude': 41.3144, 'longitude': -110.5095, 'highway': 'A TA Petro truckstop at I-80, Exit 30', 'source': 'https://www.ta-petro.com/location/wy/ta-ft-bridger/'},
             [[[-111, 41], [-110, 41], [-110, 42], [-111, 42], [-111, 41]]]),
            ('resolve_loves', '52601', 'LOVES TRAVEL STOP #236', 'I-40 EXIT 161 & SR-391', 'NORTH LITTLE ROCK', 'AR',
             {'number': 236, 'latitude': 34.786217, 'longitude': -92.125573, 'address1': '11801 I-40 Fwy', 'city': 'N Little Rock', 'state': 'AR', 'highway': 'I-40', 'exitNumber': '161', 'preferredName': 'N. Little Rock', 'facilitySubtypeName': 'Travel Stop', 'isLoveStore': True, 'isCountryStore': False},
             [[[-93, 34], [-91, 34], [-91, 36], [-93, 36], [-93, 34]]]),
        ]
        for command, source_id, name, address, city, state, store, coordinates in cases:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                station = Station.objects.create(source_id=source_id, name=name, address=address, city=city, state=state, rows=[{'Truckstop Name': name}], price=3, price_min=3, price_max=3)
                boundary = {'type': 'Feature', 'properties': {'STUSPS': state}, 'geometry': {'type': 'Polygon', 'coordinates': coordinates}}
                point = [store['latitude'], store['longitude']]
                context = {'store': store, 'identity_only': True}
                validator = valid_operator_record
                if command == 'resolve_loves':
                    context['source'] = LOVES_SOURCE
                    validator = valid_loves_route_record
                self.assertTrue(validator(station, context, point, boundary))
                for change in ({'city': 'Other'}, {'state': 'TN'}, {'number': '999'}):
                    self.assertFalse(validator(station, {**context, 'store': {**store, **change}}, point, boundary))
                root = Path(directory)
                (root / 'data').mkdir()
                (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [boundary]}))
                source, output = root / 'stores.json', root / 'evidence.csv'
                source.write_text(json.dumps({'stores': [store]}))
                with override_settings(BASE_DIR=root):
                    call_command(command, input=str(source), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                    with output.open(newline='') as stream:
                        self.assertEqual(len(list(csv.DictReader(stream))), 1)
                    call_command('load_data', 'evidence', str(output), verbosity=0)
                station.refresh_from_db()
                self.assertEqual([station.latitude, station.longitude], point)
                self.assertEqual(station.evidence['verification_scope'], 'operator_identity_only')
                self.assertEqual(station.evidence['unverified_source_address_details'], address)
                station.delete()
