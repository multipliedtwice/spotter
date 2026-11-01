import csv
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from planner.osm_evidence import area_point, identity_matches, supported_exit_keys, valid_area, valid_context
from planner.models import City, Station


BOUNDARY = {'type': 'Polygon', 'coordinates': [[[-78, 38], [-76, 38], [-76, 40], [-78, 40], [-78, 38]]]}
FEATURES = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'STUSPS': 'DC'}, 'geometry': BOUNDARY}]}


class OsmValidationTests(SimpleTestCase):
    def setUp(self):
        self.station = SimpleNamespace(address='123 NORTH MAIN STREET', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}])
        self.point = [38.9, -77.0]
        self.context = {'type': 'node', 'id': 5, 'geometry': {'type': 'Point', 'coordinates': [-77.0, 38.9]}, 'tags': {'amenity': 'fuel', 'brand': 'Pilot', 'ref': '42', 'addr:housenumber': '123', 'addr:street': 'N. Main St.'}}

    def check(self, context):
        return valid_context(self.station, context, self.point, BOUNDARY, [[38.9, -77]])

    def test_address_equivalence_and_conflicting_refs(self):
        self.assertTrue(self.check(self.context))
        self.assertFalse(self.check({**self.context, 'tags': {**self.context['tags'], 'ref': '99'}}))
        self.assertFalse(self.check({**self.context, 'tags': {**self.context['tags'], 'addr:street': 'South Main St'}}))
        self.assertFalse(valid_context(self.station, self.context, self.point, BOUNDARY, []))
        self.assertTrue(self.check({**self.context, 'tags': {**self.context['tags'], 'addr:state': 'District of Columbia'}}))
        self.assertFalse(self.check({**self.context, 'tags': {**self.context['tags'], 'addr:state': 'Texas'}}))
        self.assertFalse(self.check({**self.context, 'tags': {**self.context['tags'], 'addr:state': 'Unknown'}}))

    def test_identity_requires_canonical_name(self):
        self.assertFalse(identity_matches(['BIG CABIN TRUCK STOP'], {'name': 'Big Red Fuel'}))
        self.assertTrue(identity_matches(['BIG CABIN TRUCK STOP #42'], {'name': 'Big Cabin', 'ref': '42'}))
        self.assertTrue(identity_matches(["LOVE'S TRAVEL STOP #42"], {'brand': 'Love', 'ref': '42'}))
        self.assertFalse(identity_matches(['PILOT TRAVEL CENTER #42'], {'brand': 'Flying J', 'ref': '42'}))
        self.assertFalse(identity_matches(['BIG CABIN TRUCK STOP #42'], {'name': 'Big Cabin', 'ref': '43'}))
        self.assertTrue(identity_matches(['LOVES TRAVEL STOP #046'], {'brand': "Love's", 'ref': '46'}))
        self.assertTrue(identity_matches(['LOVES #00046A'], {'brand': "Love's", 'ref': '46A'}))
        self.assertFalse(identity_matches(['LOVES #046A'], {'brand': "Love's", 'ref': '46B'}))
        self.assertTrue(identity_matches(['CASEYS #3956'], {'brand': "Casey's General Store", 'ref': '3956'}))
        self.assertTrue(identity_matches(['TA SEYMOUR TRAVEL CENTER'], {'brand': 'TA'}))
        self.assertTrue(identity_matches(['TA BINGHAMTON TRAVELCENTER'], {'brand': 'TA'}))
        self.assertTrue(identity_matches(['TA SAGINAW I 75 TRAVEL CENTER'], {'brand': 'TravelCenters of America'}))
        self.assertFalse(identity_matches(['BIG CABIN TRUCK STOP'], {'name': 'Big Cabin East'}))

    def test_rejects_malformed_context(self):
        for context in (None, [], {'tags': []}, {**self.context, 'tags': 'fuel'}, {**self.context, 'geometry': []}, {**self.context, 'junction': []}):
            self.assertFalse(self.check(context))
        for point in ([True, -77], [38.9, float('nan')], [91, -77]):
            self.assertFalse(valid_context(self.station, self.context, point, BOUNDARY, [[38.9, -77]]))
        junction = {'id': 8, 'ref': '42', 'point': [float('nan'), -77], 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'ref': 'I 40', 'highway': 'motorway', 'nodes': [8], 'url': 'https://www.openstreetmap.org/way/9'}}
        self.assertFalse(self.check({**self.context, 'junction': junction}))

    def test_invalid_area_topology(self):
        outer = [[-77.1, 38.8], [-76.9, 38.8], [-76.9, 39.0], [-77.1, 39.0], [-77.1, 38.8]]
        outside = [[-76.8, 38.8], [-76.7, 38.8], [-76.7, 38.9], [-76.8, 38.9], [-76.8, 38.8]]
        crossing = [[-77.0, 38.85], [-76.8, 38.85], [-76.8, 38.95], [-77.0, 38.95], [-77.0, 38.85]]
        for geometry in ({'type': 'Polygon', 'coordinates': [outer, outside]}, {'type': 'Polygon', 'coordinates': [outer, crossing]}, {'type': 'MultiPolygon', 'coordinates': [[outer], [crossing]]}):
            self.assertFalse(valid_area(geometry, [38.81, -77.09]))

    def test_exit_keys_preserve_road_association(self):
        self.assertEqual(supported_exit_keys('I-44, EXIT 283 & US-69'), {('I', '44', 'exit', '283')})
        self.assertEqual(supported_exit_keys('I-35 & I-44, EXIT 137'), set())
        self.assertEqual(supported_exit_keys('I-40 EXIT 280 & I-55 EXIT 4'), {('I', '40', 'exit', '280'), ('I', '55', 'exit', '4')})
        self.assertEqual(supported_exit_keys('I-40/85 EXIT 152'), set())

    def test_exit_requires_member_road_and_proximity(self):
        self.station.address = 'I-40 EXIT 42'
        context = {**self.context, 'tags': {'amenity': 'fuel', 'brand': 'Pilot', 'ref': '42'}, 'junction': {'id': 8, 'ref': '42', 'point': [38.9, -77.0], 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'ref': 'I 40', 'highway': 'motorway', 'nodes': [7, 8], 'url': 'https://www.openstreetmap.org/way/9'}}}
        self.assertTrue(self.check(context))
        for road in ({**context['junction']['road'], 'ref': 'US 40'}, {**context['junction']['road'], 'nodes': [7]}):
            self.assertFalse(self.check({**context, 'junction': {**context['junction'], 'road': road}}))
        self.station.address = 'I-35 & I-40 EXIT 42'
        self.assertFalse(self.check(context))
        self.station.address = 'I-40 MILE 42'
        self.assertFalse(self.check(context))

    def test_exit_accepts_legacy_old_ref(self):
        self.station.address = 'I-90, EXIT 12'
        junction = {'id': 8, 'ref': '111', 'point': [38.9, -77.0], 'highway': 'motorway_junction', 'url': 'https://www.openstreetmap.org/node/8', 'road': {'id': 9, 'ref': 'I 90', 'highway': 'motorway', 'nodes': [7, 8], 'url': 'https://www.openstreetmap.org/way/9'}}
        context = {**self.context, 'tags': {'amenity': 'fuel', 'brand': 'Pilot', 'ref': '42'}, 'junction': junction}
        self.assertFalse(self.check(context))
        self.assertTrue(self.check({**context, 'junction': {**junction, 'old_ref': '12'}}))
        self.assertTrue(self.check({**context, 'junction': {**junction, 'ref': '12'}}))
        self.assertFalse(self.check({**context, 'junction': {**junction, 'old_ref': '13'}}))
        self.assertFalse(self.check({**context, 'junction': {**junction, 'old_ref': '12 A-B'}}))
        for bad in (12, None, ['12']):
            self.assertFalse(self.check({**context, 'junction': {**junction, 'old_ref': bad}}))

    def test_area_point_respects_holes_and_incomplete_ring(self):
        geometry = {'type': 'Polygon', 'coordinates': [[[-77.1, 38.8], [-76.9, 38.8], [-76.9, 39.0], [-77.1, 39.0], [-77.1, 38.8]], [[-77.05, 38.85], [-76.95, 38.85], [-76.95, 38.95], [-77.05, 38.95], [-77.05, 38.85]]]}
        point = area_point(geometry)
        self.assertIsNotNone(point)
        context = {**self.context, 'type': 'relation', 'geometry': geometry}
        self.assertTrue(valid_context(self.station, context, point, BOUNDARY, [[38.9, -77]]))
        geometry['coordinates'][0].pop()
        self.assertIsNone(area_point(geometry))


class OsmCommandTests(TestCase):
    def test_node_and_way_evidence_and_forged_import(self):
        Station.objects.create(source_id='1', name='PILOT #42', address='123 MAIN ST', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        xml = '''<osm version="0.6"><node id="1" lat="38.9" lon="-77.0"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/><tag k="addr:housenumber" v="123"/><tag k="addr:street" v="Main Street"/><tag k="phone" v="private"/></node><node id="2" lat="38.899" lon="-77.001"/><node id="3" lat="38.899" lon="-76.999"/><node id="4" lat="38.901" lon="-76.999"/><node id="5" lat="38.901" lon="-77.001"/><way id="10"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="2"/><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/><tag k="addr:housenumber" v="123"/><tag k="addr:street" v="Main Street"/></way></osm>'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, unresolved = root / 'input.osm', root / 'evidence.csv', root / 'unresolved.csv'
            source.write_text(xml)
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES), patch('planner.management.commands.load_data.load_boundary', return_value=FEATURES):
                call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
                with output.open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertNotIn('phone', json.loads(rows[0]['osm_evidence'])['tags'])
                call_command('load_data', 'evidence', str(output))
                self.assertIsNotNone(Station.objects.get(source_id='1').latitude)
                rows[0]['matched_name'] = 'Forged name'
                rows[0]['matched_address'] = 'Forged address'
                rows[0]['place_id'] = '99999'
                rows[0]['datasource_name'] = 'Forged provider'
                rows[0]['datasource_license'] = 'Forged license'
                rows[0]['datasource_attribution'] = 'Forged attribution'
                rows[0]['datasource_url'] = 'https://example.invalid/'
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output))
                evidence = Station.objects.get(source_id='1').evidence
                self.assertEqual(evidence['matched_name'], 'Pilot')
                self.assertEqual(evidence['matched_address'], '123 Main Street')
                self.assertEqual(evidence['place_id'], '1')
                self.assertEqual(evidence['datasource_name'], 'OpenStreetMap')
                self.assertEqual(evidence['datasource_license'], 'ODbL')
                self.assertEqual(evidence['datasource_attribution'], 'OpenStreetMap contributors')
                self.assertEqual(evidence['datasource_url'], 'https://www.openstreetmap.org/copyright')
                context = json.loads(rows[0]['osm_evidence'])
                context['tags']['addr:street'] = 'Other Street'
                rows[0]['osm_evidence'] = json.dumps(context)
                with output.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                call_command('load_data', 'evidence', str(output))
                self.assertIsNone(Station.objects.get(source_id='1').latitude)

    def test_relation_and_distinct_nearby_nodes(self):
        Station.objects.create(source_id='1', name='PILOT #42', address='123 MAIN ST', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        tags = '<tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/><tag k="addr:housenumber" v="123"/><tag k="addr:street" v="Main St"/>'
        shape = '<node id="1" lat="38.899" lon="-77.001"/><node id="2" lat="38.899" lon="-76.999"/><node id="3" lat="38.901" lon="-76.999"/><node id="4" lat="38.901" lon="-77.001"/><way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>'
        relation = f'<relation id="11"><member type="way" ref="10" role="outer"/><tag k="type" v="multipolygon"/>{tags}</relation>'
        nodes = f'<node id="21" lat="38.9" lon="-77">{tags}</node><node id="22" lat="38.91" lon="-77">{tags}</node>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.osm'
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES):
                source.write_text(f'<osm version="0.6">{shape}{relation}</osm>')
                output, unresolved = root / 'relation.csv', root / 'relation-missing.csv'
                call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
                with output.open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/relation/11')
                source.write_text(f'<osm version="0.6">{nodes}</osm>')
                output, unresolved = root / 'nodes.csv', root / 'nodes-missing.csv'
                call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
                with output.open() as stream:
                    self.assertEqual(list(csv.DictReader(stream)), [])
                with unresolved.open() as stream:
                    self.assertEqual(list(csv.DictReader(stream))[0]['reason'], 'ambiguous_match')

    def test_resolver_joins_exit_by_motorway_node_membership(self):
        station = Station.objects.create(source_id='1', name='PILOT #42', address='I-40 EXIT 42', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES):
                cases = (('I 40', 2, 'I-40 EXIT 42', 'motorway', True), ('US 40', 2, 'I-40 EXIT 42', 'motorway', False), ('I 40', 4, 'I-40 EXIT 42', 'motorway', False), ('I 40;US 70', 2, 'I-40 EXIT 42', 'motorway', True), ('I 40;US 70', 2, 'US-40 EXIT 42', 'motorway', False), ('I 40;US 70', 2, 'I-40 EXIT 43', 'motorway', False), ('I 40', 2, 'I-40 EXIT 42', 'motorway_link', False))
                for index, (road_ref, member, address, highway, expected) in enumerate(cases):
                    station.address = address
                    station.save(update_fields=['address'])
                    xml = f'''<osm version="0.6"><node id="1" lat="38.9" lon="-77"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/></node><node id="2" lat="38.9001" lon="-77"><tag k="highway" v="motorway_junction"/><tag k="ref" v="42"/></node><way id="10"><nd ref="999"/><nd ref="{member}"/><nd ref="1000"/><tag k="highway" v="{highway}"/><tag k="ref" v="{road_ref}"/></way></osm>'''
                    source = root / f'input-{index}.osm'
                    output, unresolved = root / f'evidence-{index}.csv', root / f'unresolved-{index}.csv'
                    source.write_text(xml)
                    call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
                    with output.open() as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), int(expected))
                    if expected:
                        context = json.loads(rows[0]['osm_evidence'])
                        self.assertEqual(context['junction']['id'], 2)
                        self.assertEqual(context['junction']['road']['id'], 10)
                        self.assertIn(2, context['junction']['road']['nodes'])

    def test_resolver_matches_legacy_exit_via_old_ref(self):
        station = Station.objects.create(source_id='1', name='PILOT #42', address='I-90, EXIT 12', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES):
                for index, (old_ref, road_ref, expected) in enumerate((('12', 'I 90', True), ('', 'I 90', False), ('12', 'I 91', False))):
                    old = f'<tag k="old_ref" v="{old_ref}"/>' if old_ref else ''
                    xml = f'''<osm version="0.6"><node id="1" lat="38.9" lon="-77"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/></node><node id="2" lat="38.9001" lon="-77"><tag k="highway" v="motorway_junction"/><tag k="ref" v="111"/>{old}</node><way id="10"><nd ref="999"/><nd ref="2"/><nd ref="1000"/><tag k="highway" v="motorway"/><tag k="ref" v="{road_ref}"/></way></osm>'''
                    source = root / f'input-{index}.osm'
                    output, unresolved = root / f'evidence-{index}.csv', root / f'unresolved-{index}.csv'
                    source.write_text(xml)
                    call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
                    with output.open() as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), int(expected))
                    if expected:
                        junction = json.loads(rows[0]['osm_evidence'])['junction']
                        self.assertEqual((junction['ref'], junction['old_ref']), ('111', '12'))

    def test_select_site_objects_preserves_references(self):
        import osmium
        Station.objects.create(source_id='1', name='PILOT #42', address='I-40 EXIT 42', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        xml = '''<osm version="0.6"><node id="1" lat="38.9" lon="-77"><tag k="shop" v="convenience"/><tag k="brand" v="Pilot"/></node><node id="2" lat="38.9" lon="-77"/><way id="10"><nd ref="2"/><nd ref="1"/><tag k="landuse" v="retail"/><tag k="name" v="Pilot"/></way><relation id="20"><member type="way" ref="10" role="outer"/><tag k="highway" v="services"/><tag k="brand" v="Pilot"/></relation></osm>'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source.osm', root / 'selected.osm'
            source.write_text(xml)
            call_command('select_osm_sites', pbf=str(source), output=str(output))
            objects = [(obj.type_str(), obj.id, [n.ref for n in obj.nodes] if obj.is_way() else [m.ref for m in obj.members] if obj.is_relation() else []) for obj in osmium.FileProcessor(str(output))]
            self.assertEqual(objects, [('n', 1, []), ('w', 10, [2, 1]), ('r', 20, [10])])

    def test_business_and_containing_site_matching(self):
        Station.objects.create(source_id='1', name='PILOT #42', address='I-40 EXIT 42', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        junction = '<node id="1" lat="38.9" lon="-77"><tag k="highway" v="motorway_junction"/><tag k="ref" v="42"/></node>'
        road = '<way id="50"><nd ref="1"/><nd ref="999"/><tag k="highway" v="motorway"/><tag k="ref" v="I 40"/></way>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def resolve(index, content):
                source, output = root / f'site-{index}.osm', root / f'site-{index}.csv'
                unresolved = root / f'missing-{index}.csv'
                source.write_text(f'<osm version="0.6">{junction}{content}{road}</osm>')
                call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
                with output.open() as stream:
                    return list(csv.DictReader(stream))
            def shop(ref):
                return f'<node id="2" lat="38.9001" lon="-77"><tag k="shop" v="convenience"/><tag k="brand" v="Pilot"/>{ref}</node>'
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES):
                self.assertEqual(resolve(1, shop('')), [])
                self.assertEqual(resolve(2, shop('<tag k="ref" v="43"/>')), [])
                self.assertEqual(len(resolve(3, shop('<tag k="ref" v="42"/>'))), 1)
                site_nodes = '<node id="3" lat="38.899" lon="-77.001"/><node id="4" lat="38.899" lon="-76.999"/><node id="5" lat="38.901" lon="-76.999"/><node id="6" lat="38.901" lon="-77.001"/>'
                site = '<way id="10"><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/><tag k="landuse" v="retail"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/></way>'
                fuel = '<node id="2" lat="38.9" lon="-77"><tag k="amenity" v="fuel"/></node>'
                rows = resolve(4, fuel + site_nodes + site)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/node/2')
                self.assertEqual(json.loads(rows[0]['osm_evidence'])['site']['id'], 10)
                with patch('planner.management.commands.load_data.load_boundary', return_value=FEATURES):
                    call_command('load_data', 'evidence', str(root / 'site-4.csv'))
                    self.assertEqual(Station.objects.get(source_id='1').latitude, 38.9)
                    context = json.loads(rows[0]['osm_evidence'])
                    context['site']['tags']['ref'] = '43'
                    rows[0]['osm_evidence'] = json.dumps(context)
                    with (root / 'site-4.csv').open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerows(rows)
                    call_command('load_data', 'evidence', str(root / 'site-4.csv'))
                    self.assertIsNone(Station.objects.get(source_id='1').latitude)
                outside = fuel.replace('lat="38.9"', 'lat="38.902"')
                rows = resolve(5, outside + site_nodes + site)
                self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/way/10')
                conflict = fuel.replace('</node>', '<tag k="ref" v="43"/></node>')
                rows = resolve(6, conflict + site_nodes + site)
                self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/way/10')
                unnumbered_site = site.replace('<tag k="ref" v="42"/>', '')
                named_fuel = fuel.replace('</node>', '<tag k="brand" v="Pilot"/></node>')
                rows = resolve(7, named_fuel + site_nodes + unnumbered_site)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/node/2')
                second_fuel = '<node id="7" lat="38.9005" lon="-77"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/></node>'
                rows = resolve(8, named_fuel + site_nodes + second_fuel + unnumbered_site)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/node/2')

    def test_strong_ref_preferred_but_distinct_strong_sites_ambiguous(self):
        Station.objects.create(source_id='1', name='PILOT #42', address='I-40 EXIT 42', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        junction = '<node id="1" lat="38.9" lon="-77"><tag k="highway" v="motorway_junction"/><tag k="ref" v="42"/></node>'
        fuel = '<node id="2" lat="38.9" lon="-77"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/></node>'
        strong = '<node id="3" lat="38.903" lon="-77"><tag k="shop" v="convenience"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/></node>'
        second = '<node id="4" lat="38.906" lon="-77"><tag k="shop" v="convenience"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/></node>'
        road = '<way id="50"><nd ref="1"/><nd ref="999"/><tag k="highway" v="motorway"/><tag k="ref" v="I 40"/></way>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES):
                for index, extra in enumerate(('', second)):
                    source, output = root / f'in-{index}.osm', root / f'out-{index}.csv'
                    source.write_text(f'<osm version="0.6">{junction}{fuel}{strong}{extra}{road}</osm>')
                    call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(root / f'missing-{index}.csv'))
                    with output.open() as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), 1 if index == 0 else 0)
                    if rows:
                        self.assertEqual(rows[0]['source'], 'https://www.openstreetmap.org/node/3')

    def test_unresolved_reasons_distinguish_source_address_and_identity(self):
        for identifier, name, address in (('1', 'PILOT #42', 'I-40'), ('2', 'SPEEDWAY #21', 'I-40 EXIT 42')):
            Station.objects.create(source_id=identifier, name=name, address=address, city='WASHINGTON', state='DC', rows=[{'Truckstop Name': name}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='DC', latitude=38.9, longitude=-77)
        xml = '<osm version="0.6"><node id="1" lat="38.9" lon="-77"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/></node></osm>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, unresolved = root / 'source.osm', root / 'output.csv', root / 'unresolved.csv'
            source.write_text(xml)
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=FEATURES):
                call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(unresolved))
            with unresolved.open() as stream:
                reasons = {row['station_id']: row['reason'] for row in csv.DictReader(stream)}
            self.assertEqual(reasons, {'1': 'unsupported_source_address', '2': 'no_matching_osm_identity'})

    def test_intersection_requires_same_junction_road_and_ramp_evidence(self):
        station = Station.objects.create(source_id='1', name='PILOT #42', address='I-40 & SR-13', city='WASHINGTON', state='TN', rows=[{'Truckstop Name': 'PILOT #42'}], price=3, price_min=3, price_max=3)
        City.objects.create(name='WASHINGTON', state='TN', latitude=38.9, longitude=-77)
        boundary = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'STUSPS': 'TN'}, 'geometry': BOUNDARY}]}
        cases = (
            ('I-35 & I-44 EXIT 137', 'I 44', '137', '', '', False),
            ('I-35 & I-44 EXIT 137', 'I 35;I 44', '137', '', '', True),
            ('I-40 & SR-13', 'I 40', '', 'TN 13', 'motorway_link', True),
            ('I-40 & SR-13', 'I 40', '', 'KY 13', 'motorway_link', False),
            ('I-40 & US-13', 'I 40', '', 'TN 13', 'motorway_link', False),
            ('I-40 & SR-13', 'I 40', '', 'TN 13', 'trunk_link', False),
            ('I-40 & SR-13 EXIT 8', 'I 40', '9', 'TN 13', 'motorway_link', False),
            ('I-40 OR SR-13', 'I 40', '', 'TN 13', 'motorway_link', False),
            ('I-40 & SR-13 MILE 8', 'I 40', '', 'TN 13', 'motorway_link', False),
            ('I-40', 'I 40', '', 'TN 13', 'motorway_link', False),
            ('I-40 & SR-13', 'I 40', '', 'TN 13', 'detached', False),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('planner.management.commands.resolve_osm.load_boundary', return_value=boundary):
                for index, (address, main_ref, junction_ref, destination, ramp_type, expected) in enumerate(cases):
                    station.address = address
                    station.save(update_fields=['address'])
                    ref_tag = f'<tag k="ref" v="{junction_ref}"/>' if junction_ref else ''
                    ramp_node = 99 if ramp_type == 'detached' else 2
                    highway = 'motorway_link' if ramp_type == 'detached' else ramp_type
                    ramp = f'<way id="51"><nd ref="{ramp_node}"/><nd ref="1001"/><tag k="highway" v="{highway}"/><tag k="destination:ref" v="{destination}"/></way>' if ramp_type else ''
                    xml = f'''<osm version="0.6"><node id="1" lat="38.9" lon="-77"><tag k="amenity" v="fuel"/><tag k="brand" v="Pilot"/><tag k="ref" v="42"/></node><node id="2" lat="38.9001" lon="-77"><tag k="highway" v="motorway_junction"/>{ref_tag}</node><way id="50"><nd ref="2"/><nd ref="1000"/><tag k="highway" v="motorway"/><tag k="ref" v="{main_ref}"/></way>{ramp}</osm>'''
                    source, output = root / f'intersection-{index}.osm', root / f'intersection-{index}.csv'
                    source.write_text(xml)
                    call_command('resolve_osm', pbf=str(source), output=str(output), unresolved=str(root / f'unresolved-{index}.csv'))
                    with output.open() as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), int(expected), address)
                    if expected and destination:
                        self.assertEqual(json.loads(rows[0]['osm_evidence'])['junction']['ramps'][0]['destination:ref'], destination)
