import csv
import os
import tempfile
from django.core.management import call_command
from django.test import TestCase
from planner.models import City, Station

class ImportTests(TestCase):
    def test_duplicates_and_conflicting_id(self):
        fields = ['OPIS Truckstop ID','Truckstop Name','Address','City','State','Rack ID','Retail Price']
        rows = [['1','Example','10 Main','Town ','TX','1','3'], ['1','Example','10 Main','Town ','TX','1','3'], ['1','Example','10 Main','Town ','TX','1','5'], ['1','Other','20 Main','Town','TX','1','9'], ['2','Canada','1 Road','Town','ON','1','4']]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', newline='', delete=False) as f:
            writer = csv.writer(f); writer.writerow(fields); writer.writerows(rows); path = f.name
        try:
            call_command('load_data', 'stations', path, verbosity=0)
        finally:
            os.unlink(path)
        self.assertEqual(Station.objects.count(), 2)
        station = Station.objects.get(address='10 MAIN')
        self.assertEqual(station.price, 4)
        self.assertEqual(len(station.rows), 3)
        self.assertIsNone(station.latitude)

    def test_gazetteer_derives_common_city_aliases(self):
        rows = [
            ['Nashville-Davidson metropolitan government', 'TN', '36.1', '-86.7'],
            ['Indianapolis city', 'IN', '39.7', '-86.1'],
            ['Louisville/Jefferson County metro government', 'KY', '38.1', '-85.6'],
            ['Louisville', 'KY', '38.2', '-85.7'],
            ['Winston-Salem', 'NC', '36.0', '-80.2'],
            ['Milford city', 'CT', '41.2', '-73.0'],
            ['Milford', 'CT', '41.3', '-73.1'],
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', newline='', delete=False) as f:
            writer = csv.writer(f); writer.writerow(['name', 'state', 'latitude', 'longitude']); writer.writerows(rows); path = f.name
        try:
            call_command('load_data', 'gazetteer', path, verbosity=0)
        finally:
            os.unlink(path)
        names = sorted(City.objects.values_list('name', 'state'))
        self.assertIn(('Nashville', 'TN'), names)
        self.assertIn(('Indianapolis', 'IN'), names)
        self.assertIn(('Nashville-Davidson metropolitan government', 'TN'), names)
        self.assertEqual(City.objects.filter(name__iexact='Louisville', state='KY').count(), 1)
        self.assertEqual(City.objects.filter(name='Milford', state='CT').count(), 1)
        self.assertEqual(City.objects.get(name='Milford', state='CT').latitude, 41.3)
        self.assertFalse(City.objects.filter(name='Winston').exists())
        self.assertEqual(len(names), 9)

    def test_evidence_identity_requires_name_and_location(self):
        from planner.management.commands.load_data import station_match
        self.assertTrue(station_match({'PILOT TRAVEL CENTER #1243'}, 'I-44, EXIT 283 & US-69', 'PILOT #1243', 'I-44 EXIT 283'))
        self.assertFalse(station_match({'PILOT TRAVEL CENTER #1243'}, 'I-44, EXIT 283 & US-69', 'PILOT', 'I-44 EXIT 283'))
        self.assertFalse(station_match({'PILOT TRAVEL CENTER'}, '10 MAIN ST', 'PILOT TRAVEL CENTER', '10 MAIN ST'))
        self.assertTrue(station_match({'LOVES TRAVEL STOP #766'}, 'I-80 EXIT 27', "Love’s #766", 'I-80 EXIT 27'))
        self.assertFalse(station_match({'LOVES TRAVEL STOP'}, 'I-80 EXIT 27', "Love’s #766", 'I-80 EXIT 27'))
        self.assertFalse(station_match({'PILOT TRAVEL CENTER #1243'}, 'I-44, EXIT 283 & US-69', 'PILOT #1243', 'I-40 EXIT 283'))
        self.assertTrue(station_match({'LOVES #766'}, 'I-85 EXIT 152', "Love's #766", 'I-40/85 EXIT 152/Trollingwood Rd'))
        self.assertTrue(station_match({'LOVES #766'}, 'I-27 EXIT 116', "Love's #766", 'I-27 EXIT 115 NB/116 SB'))
        self.assertTrue(station_match({'LOVES #766'}, 'I-70 MM 209', "Love's #766", 'I-70 Mile209'))
        self.assertFalse(station_match({'LOVES #766'}, 'I-70 EXIT 209', "Love's #766", 'I-70 Mile209'))
        self.assertFalse(station_match({'LOVES #766'}, 'US-60 EXIT 10', "Love's #766", 'HWY-60 EXIT 10'))
        self.assertFalse(station_match({'LOVES #766'}, 'I-85 EXIT 152', "Love's #766", 'I-40/85 EXIT 152 NB/153 SB'))
        intersections = [
            ('I-40 & HORIZON, EXIT 79', 'I-40 EXIT 79'),
            ('I-35 & I-44, EXIT 137', 'I-35 EXIT 137'),
            ('I-10 & AIRPORT RD, EXIT 132', 'I-10 EXIT 132'),
            ('I-40 & US-270, EXIT 166', 'I-40 EXIT 166'),
        ]
        for source, matched in intersections:
            with self.subTest(source=source):
                self.assertTrue(station_match({'LOVES #766'}, source, "Love's #766", matched))
        paired = [
            ('I-40, EXIT 280 & I-55, EXIT 4', 'I-40 EXIT 280', 'I-40 EXIT 4'),
            ('I-295, EXIT 56 & I-95, EXIT 7', 'I-295 EXIT 56', 'I-295 EXIT 7'),
            ('I-81 EXIT 52B OR I-76 EXIT 226', 'I-81 EXIT 52B', 'I-81 EXIT 226'),
        ]
        for source, correct, wrong in paired:
            with self.subTest(source=source):
                self.assertTrue(station_match({'LOVES #766'}, source, "Love's #766", correct))
                self.assertFalse(station_match({'LOVES #766'}, source, "Love's #766", wrong))
        self.assertFalse(station_match({'LOVES #766'}, paired[0][0], "Love's #766", 'I-55 EXIT 280'))
        self.assertFalse(station_match({'LOVES #766'}, 'I-40 EXIT 280 OR I-55', "Love's #766", 'I-55 EXIT 280'))



    def test_evidence_replace_and_highway_type(self):
        import json
        from pathlib import Path
        from django.test import override_settings
        station = Station.objects.create(source_id='1', name='PILOT #12', address='I-44 EXIT 283', city='TOWN', state='TX', rows=[{'Truckstop Name':'PILOT #12'}], price=3, price_min=3, price_max=3)
        fields = ['station_id','address','city','state','latitude','longitude','matched_name','matched_address','source']
        row = ['1','I-44 EXIT 283','TOWN','TX','40','-100','PILOT #12','INTERSTATE 44 EXIT 283','https://example.test/poi']
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'data'; data.mkdir()
            (data / 'us_boundary.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','properties':{'STUSPS':'TX'},'geometry':{'type':'Polygon','coordinates':[[[-125,24],[-66,24],[-66,50],[-125,50],[-125,24]]]}}]}))
            path = Path(directory) / 'evidence.csv'
            def write(value):
                with path.open('w', newline='') as stream:
                    writer = csv.writer(stream); writer.writerow(fields); writer.writerow(value)
            with override_settings(BASE_DIR=Path(directory)):
                write(row); call_command('load_data', 'evidence', str(path), verbosity=0)
                station.refresh_from_db(); self.assertEqual(station.latitude, 40)
                row[8] = 'https://www.openstreetmap.org/node/123'
                write(row); call_command('load_data', 'evidence', str(path), verbosity=0)
                station.refresh_from_db(); self.assertEqual(station.latitude, 40)
                row[7] = 'US 44 EXIT 283'
                write(row); call_command('load_data', 'evidence', str(path), verbosity=0)
                station.refresh_from_db(); self.assertIsNone(station.latitude)

    def test_state_boundary_rejects_other_state_and_missing_state_preserves_evidence(self):
        import json
        from pathlib import Path
        from django.core.management.base import CommandError
        from django.test import override_settings
        station = Station.objects.create(source_id='1', name='PILOT #12', address='10 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name': 'PILOT #12'}], price=3, price_min=3, price_max=3, latitude=30.5, longitude=-100.5, evidence={'source': 'old'})
        def feature(state, west, east):
            return {'type': 'Feature', 'properties': {'STUSPS': state}, 'geometry': {'type': 'Polygon', 'coordinates': [[[west, 30], [east, 30], [east, 31], [west, 31], [west, 30]]]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            data.mkdir()
            boundary = data / 'us_boundary.geojson'
            evidence = root / 'evidence.csv'
            fields = ['station_id', 'address', 'city', 'state', 'latitude', 'longitude', 'matched_name', 'matched_address', 'source']
            with evidence.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                writer.writerow(['1', '10 MAIN ST', 'TOWN', 'TX', 30.5, -99.5, 'PILOT #12', '10 MAIN ST', 'https://example.test'])
            boundary.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature('TX', -101, -100), feature('OK', -100, -99)]}))
            with override_settings(BASE_DIR=root):
                call_command('load_data', 'evidence', str(evidence), verbosity=0)
                station.refresh_from_db()
                self.assertIsNone(station.latitude)
                station.latitude, station.longitude, station.evidence = 30.5, -100.5, {'source': 'old'}
                station.save()
                boundary.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature('OK', -100, -99)]}))
                with self.assertRaises(CommandError):
                    call_command('load_data', 'evidence', str(evidence), verbosity=0)
                station.refresh_from_db()
                self.assertEqual(station.evidence, {'source': 'old'})
                self.assertEqual(station.latitude, 30.5)

    def evidence_setup(self, directory, rows):
        import json
        from pathlib import Path
        root = Path(directory)
        (root / 'data').mkdir()
        (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'STUSPS': 'TX'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-125, 24], [-66, 24], [-66, 50], [-125, 50], [-125, 24]]]}}]}))
        path = root / 'evidence.csv'
        with path.open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['station_id', 'address', 'city', 'state', 'latitude', 'longitude', 'matched_name', 'matched_address', 'source'])
            writer.writerows([['1', '10 MAIN ST', 'TOWN', 'TX', lat, lon, 'PILOT #12', '10 MAIN ST', 'https://example.test'] for lat, lon in rows])
        return root, path

    def test_conflicting_duplicate_evidence_rows_rejected(self):
        from django.core.management.base import CommandError
        from django.test import override_settings
        station = Station.objects.create(source_id='1', name='PILOT #12', address='10 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name': 'PILOT #12'}], price=3, price_min=3, price_max=3, latitude=30.5, longitude=-100.5, evidence={'source': 'old'})
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.evidence_setup(directory, [(40, -100), (41, -101)])
            with override_settings(BASE_DIR=root), self.assertRaisesMessage(CommandError, '1|10 MAIN ST|TOWN|TX'):
                call_command('load_data', 'evidence', str(path), verbosity=0)
        station.refresh_from_db()
        self.assertEqual((station.latitude, station.longitude, station.evidence), (30.5, -100.5, {'source': 'old'}))

    def test_identical_duplicate_evidence_rows_import(self):
        from django.test import override_settings
        station = Station.objects.create(source_id='1', name='PILOT #12', address='10 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name': 'PILOT #12'}], price=3, price_min=3, price_max=3)
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.evidence_setup(directory, [(40, -100), ('40.0', '-100.0')])
            with override_settings(BASE_DIR=root):
                call_command('load_data', 'evidence', str(path), verbosity=0)
        station.refresh_from_db()
        self.assertEqual((station.latitude, station.longitude), (40, -100))

    def test_bundled_gazetteer_overrides_are_in_us(self):
        from django.conf import settings
        from planner.core import in_us, load_boundary
        from planner.planning import resolve_locations
        places = {('Boston', 'MA'), ('San Francisco', 'CA'), ('Chignik', 'AK'), ('Klawock', 'AK'), ('Valdez', 'AK'), ('Coronado', 'CA'), ('Manhattan Beach', 'CA'), ('Monterey', 'CA'), ('Santa Monica', 'CA'), ('South San Francisco', 'CA'), ('Niantic', 'CT'), ('Stonington', 'CT'), ('Tokeneke', 'CT'), ('Atlantic Beach', 'FL'), ('Dunedin', 'FL'), ('Neptune Beach', 'FL'), ('Yankeetown', 'FL'), ('Portland', 'ME'), ('Grand Marais', 'MI'), ('Keansburg', 'NJ'), ('Ocracoke', 'NC')}
        boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
        with (settings.BASE_DIR / 'data/gazetteer.csv').open(newline='') as stream:
            rows = [r for r in csv.DictReader(stream) if (r['name'], r['state']) in places]
        self.assertEqual({(r['name'], r['state']) for r in rows}, places)
        self.assertEqual(len(rows), len(places))
        for row in rows:
            self.assertTrue(in_us([float(row['latitude']), float(row['longitude'])], boundary), row['name'])
        City.objects.bulk_create([City(name=r['name'], state=r['state'], latitude=float(r['latitude']), longitude=float(r['longitude'])) for r in rows])
        for name, state in places:
            self.assertEqual(resolve_locations([f'{name}, {state}', 'Boston, MA'])[0], next([float(r['latitude']), float(r['longitude'])] for r in rows if (r['name'], r['state']) == (name, state)))
