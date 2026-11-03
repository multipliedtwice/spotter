import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from planner.models import Station
from planner.wex_evidence import ENDPOINT, SOURCE, valid_wex_record

BOUNDARY = {'type': 'Feature', 'properties': {'STUSPS': 'IA'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-95, 40], [-92, 40], [-92, 43], [-95, 43], [-95, 40]]]}}
RAW = {'siteId': '1-WEX-TEST', 'name': 'CASEYS #123', 'brand': "CASEY'S GENERAL STORE", 'address': '123 MAIN ST', 'city': 'TOWN', 'state': 'IA', 'zip': '50000', 'location': {'latitude': 41.0, 'longitude': -93.0}}
JUNCTION = {'id': 8, 'ref': '42', 'point': [41.0, -93.0], 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'ref': 'IA 163', 'highway': 'motorway', 'nodes': [7, 8], 'url': 'https://www.openstreetmap.org/way/9'}}


class WexTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(source_id='1', name='CASEYS #123', address='SR-163 EXIT 42', city='TOWN', state='IA', rows=[{'Truckstop Name': 'CASEYS #123'}], price=3, price_min=3, price_max=3)

    def valid(self, raw=RAW, junction=JUNCTION):
        return valid_wex_record(self.station, {'source': SOURCE, 'record': raw, 'junction': junction}, [41.0, -93.0], BOUNDARY)

    def test_state_prefixed_junction_and_identity_are_required(self):
        self.assertTrue(self.valid())
        self.assertFalse(valid_wex_record(self.station, {'source': SOURCE, 'record': RAW}, [41.0, -93.0], BOUNDARY))
        for change in ({'name': 'CASEYS #124'}, {'brand': 'OTHER'}, {'city': 'Other'}, {'state': 'IL'}, {'siteId': ''}, {'location': {'latitude': float('nan'), 'longitude': -93}}, {'extra': True}):
            self.assertFalse(self.valid({**RAW, **change}))
        for ref in ('IL 163', 'IA 163 ALT', 'HWY 163'):
            self.assertFalse(self.valid(junction={**JUNCTION, 'road': {**JUNCTION['road'], 'ref': ref}}))
        self.station.address = 'SR-163 EXIT 42 & CO-R6F'
        self.assertFalse(self.valid())
        self.station.address = 'US-34'
        self.assertFalse(self.valid())
        self.station.address = '123 MAIN STREET'
        self.assertTrue(valid_wex_record(self.station, {'source': SOURCE, 'record': RAW}, [41.0, -93.0], BOUNDARY))
        self.station.address = 'SR-163 EXIT 42'
        self.station.rows.append({'Truckstop Name': 'OTHER #123'})
        self.assertFalse(self.valid())

    def test_numbered_trunk_exit_requires_complete_linked_proof(self):
        from planner.osm_evidence import junction_match
        self.station.address = 'US-30 EXIT 158 & SR-17'
        ramp = {'id': 10, 'highway': 'trunk_link', 'destination:ref': 'IA 17', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/10'}
        road = {**JUNCTION['road'], 'ref': 'US 30', 'highway': 'trunk'}
        junction = {**JUNCTION, 'ref': '158', 'road': road, 'ramps': [ramp]}
        self.assertTrue(self.valid(junction=junction))
        for kind in ('primary', 'residential', 'trunk_link', 'service'):
            self.assertFalse(self.valid(junction={**junction, 'road': {**road, 'highway': kind}}))
        self.assertFalse(self.valid(junction={**junction, 'road': {**road, 'nodes': [7]}}))
        self.assertFalse(self.valid(junction={**junction, 'ref': '159'}))
        self.assertFalse(self.valid(junction={**junction, 'ref': '159', 'old_ref': '158'}))
        self.assertFalse(self.valid(junction={**junction, 'ramps': []}))
        self.assertFalse(self.valid(junction={**junction, 'ramps': [{**ramp, 'destination:ref': 'IL 17'}]}))
        self.assertFalse(self.valid(junction={**junction, 'ramps': [{**ramp, 'highway': 'primary_link'}]}))
        self.assertIsNone(junction_match(self.station, [41.0, -93.0], {**junction, 'point': [41.03, -93.0]}, BOUNDARY, max_distance=5))
        self.station.address = 'US-30 & SR-17'
        self.assertFalse(self.valid(junction=junction))

    def test_resolver_import_and_duplicate_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            asset = {'source': SOURCE, 'endpoint': ENDPOINT, 'records': [RAW]}
            source = root / 'data/source_wex_locations.json'
            source.write_text(json.dumps(asset))
            proof = root / 'junctions.json'
            proof.write_text(json.dumps({'records': [{'siteId': RAW['siteId'], 'junction': JUNCTION}]}))
            output = root / 'evidence.csv'
            with override_settings(BASE_DIR=root):
                call_command('resolve_wex', input=str(source), junctions=str(proof), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], [41.0, -93.0])
                context = json.loads(rows[0]['directory_evidence'])
                context['record']['siteId'] = 'fake'
                rows[0]['directory_evidence'] = json.dumps(context)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                source.write_text(json.dumps({**asset, 'records': [RAW, {**RAW, 'siteId': 'other'}]}))
                duplicate = root / 'duplicate.csv'
                call_command('resolve_wex', input=str(source), junctions=str(proof), output=str(duplicate), unresolved=str(root / 'duplicate-missing.csv'), verbosity=0)
                with duplicate.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                source.write_text(json.dumps({**asset, 'records': [RAW, {**RAW, 'location': {'latitude': 41.1, 'longitude': -93.0}}]}))
                duplicate_id = root / 'duplicate-id.csv'
                call_command('resolve_wex', input=str(source), junctions=str(proof), output=str(duplicate_id), unresolved=str(root / 'duplicate-id-missing.csv'), verbosity=0)
                with duplicate_id.open(newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])

    def test_local_osm_junction_resolver_and_import(self):
        self.station.address = 'SR-163 EXIT 42 & SR-17'
        self.station.save()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source = root / 'data/source_wex_locations.json'
            source.write_text(json.dumps({'source': SOURCE, 'endpoint': ENDPOINT, 'records': [RAW]}))
            for index, (exit_ref, secondary, expected) in enumerate((('42', 'IA 17', True), ('43', 'IA 17', False), ('42', 'IA 18', False), ('42', '', False))):
                road = root / f'roads-{index}.osm'
                ramp = f'<way id="10"><nd ref="8"/><tag k="highway" v="motorway_link"/><tag k="destination:ref" v="{secondary}"/></way>' if secondary else ''
                road.write_text(f'<osm version="0.6"><node id="7" lat="41.001" lon="-93"/><node id="8" lat="41" lon="-93"><tag k="highway" v="motorway_junction"/><tag k="ref" v="{exit_ref}"/></node><way id="9"><nd ref="7"/><nd ref="8"/><tag k="highway" v="motorway"/><tag k="ref" v="IA 163"/></way>{ramp}</osm>')
                output = root / f'evidence-{index}.csv'
                with override_settings(BASE_DIR=root):
                    call_command('resolve_wex', input=str(source), pbf=str(road), output=str(output), unresolved=str(root / f'missing-{index}.csv'), verbosity=0)
                    with output.open(newline='') as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), int(expected))
                    if expected:
                        self.assertEqual(json.loads(rows[0]['directory_evidence'])['junction']['id'], 8)
                        call_command('load_data', 'evidence', str(output), verbosity=0)
                        self.station.refresh_from_db()
                        self.assertEqual([self.station.latitude, self.station.longitude], [41.0, -93.0])

    def test_full_business_name_and_complete_road_proof(self):
        raw = {**RAW, 'name': 'LEES FOOD MART 1122', 'brand': 'PHILLIPS 66'}
        self.station.rows = [{'Truckstop Name': "LEE'S FOOD MART #1122"}]
        self.station.address = 'SR-163 EXIT 42 & SR-17'
        ramp = {'id': 10, 'highway': 'motorway_link', 'destination:ref': 'IA 17', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/10'}
        junction = {**JUNCTION, 'ramps': [ramp]}
        context = {'source': SOURCE, 'record': raw, 'junction': junction}
        point = [41.0, -93.0]
        self.assertTrue(valid_wex_record(self.station, context, point, BOUNDARY))
        for name in ("LEE'S FOOD MART #112", "LEE'S MART #1122", "LEE'S FOOD MART #01122", "LEE'S FÓOD MART #1122", 'PHILLIPS 66'):
            self.station.rows = [{'Truckstop Name': name}]
            self.assertFalse(valid_wex_record(self.station, context, point, BOUNDARY))
        self.station.rows = [{'Truckstop Name': "LEE'S FOOD MART #1122"}, {'Truckstop Name': 'OTHER #1122'}]
        self.assertFalse(valid_wex_record(self.station, context, point, BOUNDARY))
        self.station.rows = [{'Truckstop Name': "LEE'S FOOD MART #1122"}]
        for change in ({'city': 'OTHER'}, {'state': 'IL'}, {'location': {'latitude': 41.1, 'longitude': -93.0}}):
            self.assertFalse(valid_wex_record(self.station, {**context, 'record': {**raw, **change}}, point, BOUNDARY))
        for bad in ({**junction, 'ramps': []}, {**junction, 'ref': '43'}):
            self.assertFalse(valid_wex_record(self.station, {**context, 'junction': bad}, point, BOUNDARY))
        self.station.address = 'HWY 163 EXIT 42'
        self.assertFalse(valid_wex_record(self.station, context, point, BOUNDARY))
        self.station.address = 'SR-163'
        self.assertFalse(valid_wex_record(self.station, {'source': SOURCE, 'record': raw}, point, BOUNDARY))

    def test_full_name_resolver_import_and_catalog_guards(self):
        self.station.rows = [{'Truckstop Name': 'FAS MART #5154'}]
        self.station.address = 'SR-163 EXIT 42'
        self.station.save()
        raw = {**RAW, 'name': 'FAS. MART 5154', 'brand': 'UNBRANDED'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/us_boundary.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [BOUNDARY]}))
            source = root / 'data/source_wex_locations.json'
            asset = {'source': SOURCE, 'endpoint': ENDPOINT, 'records': [raw]}
            source.write_text(json.dumps(asset))
            proof = root / 'junctions.json'
            proof.write_text(json.dumps({'records': [{'siteId': raw['siteId'], 'junction': JUNCTION}]}))
            with override_settings(BASE_DIR=root):
                output = root / 'evidence.csv'
                call_command('resolve_wex', input=str(source), junctions=str(proof), output=str(output), unresolved=str(root / 'missing.csv'), verbosity=0)
                with output.open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertEqual([self.station.latitude, self.station.longitude], [41.0, -93.0])
                context = json.loads(rows[0]['directory_evidence'])
                context['record']['name'] = 'FAS MART 5155'
                rows[0]['directory_evidence'] = json.dumps(context)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output), verbosity=0)
                self.station.refresh_from_db()
                self.assertIsNone(self.station.latitude)
                for index, duplicate in enumerate(({**raw, 'siteId': 'another'}, {**raw, 'location': {'latitude': 41.1, 'longitude': -93.0}})):
                    source.write_text(json.dumps({**asset, 'records': [raw, duplicate]}))
                    duplicate_output = root / f'duplicate-{index}.csv'
                    call_command('resolve_wex', input=str(source), junctions=str(proof), output=str(duplicate_output), unresolved=str(root / f'duplicate-missing-{index}.csv'), verbosity=0)
                    with duplicate_output.open(newline='') as stream:
                        self.assertEqual(list(csv.DictReader(stream)), [])

    def test_nebraska_route_14_connected_intersection(self):
        from copy import deepcopy
        from planner.osm_evidence import complete_source_road_description, state_route_marker_text, typed_roads
        from planner.road import road_marker_keys
        self.assertEqual(typed_roads('N-14', 'NE'), {('SR', '14')})
        for text, state in (('N-14', None), ('N-14', 'IA'), ('N-15', 'NE'), ('N-14 ALT', 'NE'), ('N-14 BUS', 'NE'), ('N-14 BYPASS', 'NE'), ('N-14 SPUR', 'NE'), ('N-14 TRUCK', 'NE')):
            self.assertNotIn(('SR', '14'), typed_roads(text, state))
        self.assertTrue(complete_source_road_description('N-14 EXIT 2', 'NE'))
        self.assertFalse(complete_source_road_description('N-14 EXIT 2', 'IA'))
        self.assertIn(('SR', '14', 'exit', '2'), road_marker_keys(state_route_marker_text('N-14 EXIT 2', 'NE')))
        self.station.rows = [{'Truckstop Name': "CASEY'S #3085"}]
        self.station.address, self.station.city, self.station.state = 'US-34 & SR-14', 'AURORA', 'NE'
        raw = {'siteId': '1-OLXSD4', 'name': 'CASEYS #3085', 'brand': "CASEY'S GENERAL STORE", 'address': '1502 16TH ST', 'city': 'AURORA', 'state': 'NE', 'zip': '68818-1303', 'location': {'latitude': 40.87173, 'longitude': -97.99775}}
        boundary = {'type': 'Feature', 'properties': {'STUSPS': 'NE'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-99, 40], [-97, 40], [-97, 42], [-99, 42], [-99, 40]]]}}
        proof = {'canonical_url': 'https://www.openstreetmap.org/node/134445948',
         'latitude': '40.8725000',
         'longitude': '-97.9977940',
         'node_id': '134445948',
         'node_tags': {'highway': 'traffic_signals'},
         'route_ways': [{'canonical_url': 'https://www.openstreetmap.org/way/554305786',
                         'geometry': [{'id': '134445948',
                                       'lat': '40.8725000',
                                       'lon': '-97.9977940',
                                       'tags': {'highway': 'traffic_signals'}},
                                      {'id': '134504268', 'lat': '40.8729560', 'lon': '-97.9978070', 'tags': {}},
                                      {'id': '134518956', 'lat': '40.8734608', 'lon': '-97.9978307', 'tags': {}}],
                         'id': '554305786',
                         'node_ids': ['134445948', '134504268', '134518956'],
                         'tags': {'hgv': 'designated',
                                  'hgv:national_network': 'yes',
                                  'highway': 'secondary',
                                  'name': '16th Street',
                                  'ref': 'N-14',
                                  'source:hgv:national_network': 'https://www.ecfr.gov/current/title-23/chapter-I/subchapter-G/part-658;https://hepgis-usdot.hub.arcgis.com/apps/usdot::national-network-conventional-combination-trucks-map'}},
                        {'canonical_url': 'https://www.openstreetmap.org/way/118479726',
                         'geometry': [{'id': '134445944', 'lat': '40.8725000', 'lon': '-97.9963650', 'tags': {}},
                                      {'id': '11187729343', 'lat': '40.8725000', 'lon': '-97.9968721', 'tags': {}},
                                      {'id': '134445946', 'lat': '40.8725000', 'lon': '-97.9971870', 'tags': {}},
                                      {'id': '134445948',
                                       'lat': '40.8725000',
                                       'lon': '-97.9977940',
                                       'tags': {'highway': 'traffic_signals'}}],
                         'id': '118479726',
                         'node_ids': ['134445944', '11187729343', '134445946', '134445948'],
                         'tags': {'hgv': 'designated',
                                  'hgv:national_network': 'yes',
                                  'highway': 'primary',
                                  'lanes': '4',
                                  'maxspeed': '35 mph',
                                  'name': 'Q Street',
                                  'ref': 'US 34;I 80 Alt',
                                  'source:hgv:national_network': 'https://www.ecfr.gov/current/title-23/chapter-I/subchapter-G/part-658;https://hepgis-usdot.hub.arcgis.com/apps/usdot::national-network-conventional-combination-trucks-map',
                                  'tiger:cfcc': 'A21',
                                  'tiger:county': 'Hamilton, NE',
                                  'tiger:name_base': 'Q',
                                  'tiger:name_type': 'St'}}]}
        context = {'source': SOURCE, 'record': raw, 'intersection': proof}
        point = [40.87173, -97.99775]
        self.assertTrue(valid_wex_record(self.station, context, point, boundary))
        self.station.address = 'US-34 & I-80'
        self.assertFalse(valid_wex_record(self.station, context, point, boundary))
        self.station.address = 'US-34 & SR-14'
        for ref in ('N-15', 'N-14 ALT', 'N-14 BUS', 'N-14 BYPASS', 'N-14 SPUR', 'N-14 TRUCK'):
            bad = deepcopy(proof)
            bad['route_ways'][0]['tags']['ref'] = ref
            self.assertFalse(valid_wex_record(self.station, {**context, 'intersection': bad}, point, boundary))
