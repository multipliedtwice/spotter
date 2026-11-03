import csv
import os
import tempfile
from django.core.management import call_command
from django.test import TestCase
from planner.models import City, Station

class ImportTests(TestCase):
    def test_spaced_exit_suffix_is_narrow(self):
        from planner.road import road_marker_keys
        self.assertEqual(road_marker_keys('I-94 EXIT 15 B'), {('I', '94', 'exit', '15B')})
        self.assertEqual(road_marker_keys('I-94 EXIT 15 A, US-6'), {('I', '94', 'exit', '15A')})
        for address in ('I-94 EXIT 15 E', 'I-94 EXIT 15 N', 'I-94 EXIT 15 B WEST', 'I-94 MM 15 B'):
            with self.subTest(address=address):
                self.assertNotIn(('I', '94', 'exit', '15B'), road_marker_keys(address) or set())

    def test_road_markers_do_not_broadcast_to_other_clauses_or_later_roads(self):
        from planner.management.commands.load_data import station_match
        from planner.road import road_marker_keys
        names = {'LOVES #766'}
        for published in ('I-80 EXIT 12, US-6', 'I-80 EXIT 12 (US-6)', 'I-80 EXIT 12 & US-6'):
            with self.subTest(published=published):
                self.assertFalse(station_match(names, 'US-6 EXIT 12', "Love's #766", published))
                self.assertTrue(station_match(names, 'I-80 EXIT 12', "Love's #766", published))
        self.assertTrue(station_match(names, 'I-90 EXIT 15B', "Love's #766", 'I-94/90 EXIT 15B'))
        self.assertTrue(station_match(names, 'I-85 EXIT 152', "Love's #766", 'I-40/85 EXIT 152'))
        self.assertFalse(station_match(names, 'I-80 EXIT 13', "Love's #766", 'I-80 EXIT 12 US-6 EXIT 13'))
        self.assertTrue(station_match(names, 'I-80 EXIT 12', "Love's #766", 'I-80 EXIT 12 US-6 EXIT 13'))
        self.assertFalse(station_match(names, 'I-80 MM 12', "Love's #766", 'I-80 EXIT 12'))
        self.assertEqual(road_marker_keys('I-80 EXIT 12/13'), {('I', '80', 'exit', '12'), ('I', '80', 'exit', '13')})

    def test_explicit_us_route_decorators_preserve_type(self):
        from planner.road import road_marker_keys
        from planner.osm_evidence import typed_roads
        for text in ('US HWY 41 EXIT 12', 'U.S. HIGHWAY 41 EXIT 12', 'US ROUTE 41 EXIT 12'):
            with self.subTest(text=text):
                self.assertEqual(road_marker_keys(text), {('US', '41', 'exit', '12')})
                self.assertEqual(typed_roads(text), {('US', '41')})
        self.assertNotIn(('US', '41'), typed_roads('HWY 41'))

    def test_compound_county_and_farm_roads_cannot_be_dropped(self):
        from planner.management.commands.load_data import station_match
        from planner.osm_evidence import typed_roads
        names = {'PILOT #42'}
        cases = (
            ('I-80/US-6 EXIT 93 & CR-P28', 'I-80 EXIT 93', 'I-80 EXIT 93 & US-6 & County Road P28'),
            ('I-94/US-52 EXIT 135 & CR 173', 'I-94 EXIT 135', 'I-94 EXIT 135 & US-52 & County Road 173'),
            ('I-20 EXIT 370 & FM 919', 'I-20 EXIT 370', 'I-20 EXIT 370 & Farm to Market 919'),
            ('I-20 EXIT 370 & CR-H20', 'I-20 EXIT 370', 'I-20 EXIT 370 & County Road H20'),
            ('I-20 EXIT 370 & CR-L26', 'I-20 EXIT 370', 'I-20 EXIT 370 & CR-L26'),
        )
        for source, partial, full in cases:
            with self.subTest(source=source):
                self.assertFalse(station_match(names, source, 'PILOT #42', partial))
                self.assertTrue(station_match(names, source, 'PILOT #42', full))
        self.assertNotIn(('US', '41'), typed_roads('HWY 41'))
        self.assertFalse(station_match(names, 'I-20 EXIT 370 & US-41 ALT', 'PILOT #42', 'I-20 EXIT 370 & US-41'))

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

    def test_evidence_identity_and_all_source_roads_required(self):
        from planner.management.commands.load_data import station_match
        self.assertFalse(station_match({'PILOT TRAVEL CENTER #1243'}, 'I-44, EXIT 283 & US-69', 'PILOT #1243', 'I-44 EXIT 283'))
        self.assertTrue(station_match({'PILOT TRAVEL CENTER #1243'}, 'I-44, EXIT 283 & US-69', 'PILOT #1243', 'I-44 EXIT 283 & US-69'))
        self.assertFalse(station_match({'PILOT #1243'}, 'I-94 EXIT 344 & SR-31', 'PILOT #1243', 'I-94 EXIT 344', 'WI'))
        self.assertTrue(station_match({'PILOT #1243'}, 'I-94 EXIT 344 & SR-31', 'PILOT #1243', 'I-94 EXIT 344 & WI-31', 'WI'))
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
                self.assertFalse(station_match({'LOVES #766'}, source, "Love's #766", matched))
        from planner.road import road_marker_keys
        paired = [
            ('I-40, EXIT 280 & I-55, EXIT 4', 'I-40 EXIT 280', 'INTERSTATE 40 EXIT 280 & INTERSTATE 55 EXIT 4', 'I-40 EXIT 4 & I-55 EXIT 280', {('I', '40', 'exit', '280'), ('I', '55', 'exit', '4')}),
            ('I-295, EXIT 56 & I-95, EXIT 7', 'I-295 EXIT 56', 'INTERSTATE 295 EXIT 56 & INTERSTATE 95 EXIT 7', 'I-295 EXIT 7 & I-95 EXIT 56', {('I', '295', 'exit', '56'), ('I', '95', 'exit', '7')}),
            ('I-81 EXIT 52B OR I-76 EXIT 226', 'I-81 EXIT 52B', 'INTERSTATE 81 EXIT 52B OR INTERSTATE 76 EXIT 226', 'I-81 EXIT 226 OR I-76 EXIT 52B', {('I', '81', 'exit', '52B'), ('I', '76', 'exit', '226')}),
        ]
        for source, partial, complete, wrong, markers in paired:
            with self.subTest(source=source):
                self.assertFalse(station_match({'LOVES #766'}, source, "Love's #766", partial))
                self.assertTrue(station_match({'LOVES #766'}, source, "Love's #766", complete))
                self.assertFalse(station_match({'LOVES #766'}, source, "Love's #766", wrong))
                self.assertEqual(road_marker_keys(source), markers)
        self.assertFalse(station_match({'LOVES #766'}, paired[0][0], "Love's #766", 'I-55 EXIT 280'))
        self.assertFalse(station_match({'LOVES #766'}, paired[0][0], "Love's #766", 'I-40 EXIT 280 & I-55 EXIT 999'))
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
