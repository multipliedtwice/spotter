from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from planner.management.commands.resolve_osm import address_keys, match_node


class OsmEvidenceTests(SimpleTestCase):
    def test_address_index_uses_typed_road_markers(self):
        self.assertTrue(address_keys('I-85 EXIT 152') & address_keys('I-40/85 EXIT 152'))
        self.assertFalse(address_keys('I-70 EXIT 209') & address_keys('I-70 MILE209'))
        self.assertFalse(address_keys('US-60 EXIT 10') & address_keys('HWY-60 EXIT 10'))
        self.assertTrue(address_keys('I-40 EXIT 280 & I-55 EXIT 4') & address_keys('I-40 EXIT 280'))
        self.assertFalse(address_keys('I-40 EXIT 280 & I-55 EXIT 4') & address_keys('I-40 EXIT 4'))

    def test_requires_source_identity_and_independent_address(self):
        station = SimpleNamespace(pk=1, source_id='7', address='123 MAIN ST', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': 'PILOT #42'}])
        index = defaultdict(list)
        for key in address_keys(station.address):
            index[(station.city, station.state, key)].append(station)
        boundary = {'type': 'Polygon', 'coordinates': [[[-78, 38], [-76, 38], [-76, 40], [-78, 40], [-78, 38]]]}
        tags = {'amenity': 'fuel', 'name': 'Pilot', 'ref': '42', 'addr:housenumber': '123', 'addr:street': 'Main St', 'addr:city': 'Washington', 'addr:state': 'DC'}
        matches = match_node(tags, 38.9, -77.0, 123, index, boundary)
        self.assertEqual(matches[0][1]['source'], 'https://www.openstreetmap.org/node/123')
        for change in ({'ref': '99'}, {'addr:street': 'Other St'}, {'addr:city': ''}, {'amenity': 'parking'}):
            self.assertEqual(match_node({**tags, **change}, 38.9, -77.0, 123, index, boundary), [])
        self.assertEqual(match_node(tags, 0, 0, 123, index, boundary), [])
        with patch('planner.management.commands.resolve_osm.in_us', return_value=True) as check:
            self.assertEqual(match_node({**tags, 'ref': '99'}, 38.9, -77.0, 123, index, boundary), [])
            check.assert_not_called()
            match_node(tags, 38.9, -77.0, 123, index, boundary)
            check.assert_called_once()



class OsmCommandTests(TestCase):
    def test_pbf_matches_and_reports_ambiguous_and_missing_groups(self):
        import csv
        import io
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from django.core.management import call_command
        from planner.models import Station

        def station(source_id, number, ref):
            Station.objects.create(source_id=source_id, name=f'PILOT #{ref}', address=f'{number} MAIN ST', city='WASHINGTON', state='DC', rows=[{'Truckstop Name': f'PILOT #{ref}'}], price=3, price_min=3, price_max=3)

        station('1', 123, 42)
        station('2', 124, 43)
        station('3', 125, 44)

        class Tags(dict):
            def __iter__(self):
                return iter(SimpleNamespace(k=k, v=v) for k, v in self.items())

        def node(identifier, number, ref):
            tags = Tags({'amenity': 'fuel', 'name': 'Pilot', 'ref': str(ref), 'addr:housenumber': str(number), 'addr:street': 'Main St', 'addr:city': 'Washington', 'addr:state': 'DC'})
            return SimpleNamespace(id=identifier, tags=tags, location=SimpleNamespace(lat=38.9, lon=-77.0, valid=lambda: True))

        class Handler:
            pass

        def apply(reader, tag_filter, handler):
            for item in (node(1, 123, 42), node(2, 124, 43), node(3, 124, 43)):
                handler.node(item)

        node_type = object()
        thread_pool = MagicMock()
        reader = MagicMock()
        tag_filter = MagicMock()
        fake_osmium = SimpleNamespace(SimpleHandler=Handler, io=SimpleNamespace(ThreadPool=thread_pool, Reader=reader), osm=SimpleNamespace(osm_entity_bits=SimpleNamespace(NODE=node_type)), filter=SimpleNamespace(TagFilter=tag_filter), apply=MagicMock(side_effect=apply))

        boundary = {'type': 'Polygon', 'coordinates': [[[-78, 38], [-76, 38], [-76, 40], [-78, 40], [-78, 38]]]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pbf = root / 'input.pbf'
            pbf.touch()
            output, unresolved = root / 'evidence' / 'results.csv', root / 'unresolved' / 'results.csv'
            stdout = io.StringIO()
            with patch.dict(sys.modules, {'osmium': fake_osmium}), patch('planner.management.commands.resolve_osm.load_boundary', return_value=boundary):
                call_command('resolve_osm', pbf=str(pbf), output=str(output), unresolved=str(unresolved), stdout=stdout)
            thread_pool.assert_called_once_with(1, 2)
            reader.assert_called_once_with(str(pbf), node_type, thread_pool=thread_pool.return_value)
            tag_filter.assert_called_once_with(('amenity', 'fuel'))
            fake_osmium.apply.assert_called_once()
            self.assertIs(fake_osmium.apply.call_args.args[0], reader.return_value.__enter__.return_value)
            self.assertIs(fake_osmium.apply.call_args.args[1], tag_filter.return_value)
            with output.open(newline='') as stream:
                evidence = list(csv.DictReader(stream))
            with unresolved.open(newline='') as stream:
                missing = list(csv.DictReader(stream))
            self.assertEqual([(row['station_id'], row['source']) for row in evidence], [('1', 'https://www.openstreetmap.org/node/1')])
            self.assertEqual([(row['station_id'], row['reason']) for row in missing], [('2', 'ambiguous_match'), ('3', 'no_matching_fuel_node')])
            self.assertIn('Evidence rows: 1. Unresolved groups: 2.', stdout.getvalue())
