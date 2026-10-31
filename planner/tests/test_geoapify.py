import csv
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from planner.models import Station

class ResolverTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'data/us_boundary.geojson').write_text(json.dumps({'type':'Polygon','coordinates':[[[-125,24],[-66,24],[-66,50],[-125,50],[-125,24]]]}))
        self.station = Station.objects.create(source_id='12', name='PILOT TRAVEL CENTER #12', address='10 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name':'PILOT TRAVEL CENTER #12'}], price=3, price_min=3, price_max=3)
        self.payload = {'results':[{'name':'PILOT #12','housenumber':'10','street':'MAIN ST','city':'TOWN','state_code':'TX','country_code':'us','lat':40,'lon':-100,'place_id':'abc','result_type':'amenity'}]}

    def run_resolver(self, output, max_requests=1, credit_budget=1):
        with override_settings(BASE_DIR=self.root):
            call_command('resolve_geoapify', cache=str(self.root/'cache.json'), output=str(self.root/output), max_requests=max_requests, credit_budget=credit_budget, stdout=io.StringIO())

    @patch('planner.management.commands.resolve_geoapify.urllib.request.urlopen')
    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':'private-api-key'}, clear=False)
    def test_cache_resume_and_no_key_in_assets(self, urlopen):
        urlopen.return_value = io.BytesIO(json.dumps(self.payload).encode())
        self.run_resolver('first.csv')
        self.run_resolver('second.csv', max_requests=0, credit_budget=0)
        self.assertEqual(urlopen.call_count, 1)
        with (self.root/'second.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['matched_name'], 'PILOT #12')
        self.assertEqual(rows[0]['source_row_ids'], '12:1')
        self.assertNotIn('private-api-key', (self.root/'cache.json').read_text())
        self.assertNotIn('private-api-key', (self.root/'second.csv').read_text())

    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':''}, clear=False)
    def test_missing_key(self):
        with self.assertRaisesMessage(CommandError, 'GEOAPIFY_API_KEY'):
            self.run_resolver('result.csv')

    @patch('planner.management.commands.resolve_geoapify.urllib.request.urlopen')
    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':'private-api-key'}, clear=False)
    def test_brand_or_city_without_address_is_unresolved(self, urlopen):
        self.payload['results'] = [
            {'name':'PILOT','housenumber':'10','street':'MAIN ST','city':'TOWN','state_code':'TX','country_code':'us','lat':40,'lon':-100,'result_type':'amenity'},
            {'name':'PILOT #12','city':'TOWN','state_code':'TX','country_code':'us','lat':40,'lon':-100,'result_type':'city'},
        ]
        urlopen.return_value = io.BytesIO(json.dumps(self.payload).encode())
        self.run_resolver('result.csv')
        with (self.root/'result.csv').open() as stream:
            self.assertEqual(list(csv.DictReader(stream)), [])

    @patch('planner.management.commands.resolve_geoapify.urllib.request.urlopen')
    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':'private-api-key'}, clear=False)
    def test_budget_retains_pending_groups(self, urlopen):
        Station.objects.create(source_id='13', name='OTHER #13', address='11 MAIN ST', city='TOWN', state='TX', rows=[{'Truckstop Name':'OTHER #13'}], price=3, price_min=3, price_max=3)
        urlopen.return_value = io.BytesIO(json.dumps(self.payload).encode())
        with override_settings(BASE_DIR=self.root):
            out = io.StringIO()
            call_command('resolve_geoapify', cache=str(self.root/'cache.json'), output=str(self.root/'result.csv'), max_requests=1, credit_budget=1, stdout=out)
        self.assertIn('Groups awaiting request: 1', out.getvalue())
        self.assertEqual(urlopen.call_count, 1)

    @patch('planner.management.commands.resolve_geoapify.urllib.request.urlopen')
    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':'private-api-key'}, clear=False)
    def test_external_ref_and_datasource(self, urlopen):
        self.payload['results'][0].update(name='PILOT TRAVEL CENTER', ref='12', datasource={'sourcename':'openstreetmap', 'license':'ODbL', 'attribution':'OpenStreetMap contributors', 'url':'https://openstreetmap.org/way/123?apiKey=private-api-key'})
        urlopen.return_value = io.BytesIO(json.dumps(self.payload).encode())
        self.run_resolver('ref.csv')
        with (self.root/'ref.csv').open() as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row['matched_name'], 'PILOT TRAVEL CENTER #12')
        self.assertEqual(row['place_id'], 'abc')
        self.assertEqual(row['datasource_license'], 'ODbL')
        self.assertEqual(row['datasource_url'], 'https://openstreetmap.org/way/123')
        self.assertNotIn('private-api-key', (self.root/'cache.json').read_text())

    @patch('planner.management.commands.resolve_geoapify.time.sleep')
    @patch('planner.management.commands.resolve_geoapify.urllib.request.urlopen')
    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':'private-api-key'}, clear=False)
    def test_fallback_query_with_original_sample_format(self, urlopen, sleep):
        import urllib.parse
        first = {'results':[{'name':'PILOT TRAVEL CENTER', 'city':'TOWN', 'state_code':'TX', 'country_code':'us', 'lat':40, 'lon':-100, 'result_type':'city'}]}
        self.payload['results'][0].update(name='PILOT TRAVEL CENTER', other_names={'ref':'12'})
        urlopen.side_effect = [io.BytesIO(json.dumps(first).encode()), io.BytesIO(json.dumps(self.payload).encode())]
        sample = self.root/'sample.csv'
        sample.write_text('OPIS Truckstop ID,Address,City,State\n12,10 MAIN ST,TOWN,TX\n')
        with override_settings(BASE_DIR=self.root):
            call_command('resolve_geoapify', sample=str(sample), cache=str(self.root/'cache.json'), output=str(self.root/'result.csv'), max_requests=2, credit_budget=2, stdout=io.StringIO())
        self.assertEqual(urlopen.call_count, 2)
        fallback = urllib.parse.parse_qs(urllib.parse.urlsplit(urlopen.call_args_list[1].args[0].full_url).query)['text'][0]
        self.assertNotIn('10 MAIN ST', fallback)
        with (self.root/'result.csv').open() as stream:
            self.assertEqual(next(csv.DictReader(stream))['matched_name'], 'PILOT TRAVEL CENTER #12')

    @patch.dict(os.environ, {'GEOAPIFY_API_KEY':'private-api-key'}, clear=False)
    def test_null_boundary_is_command_error(self):
        (self.root/'data/us_boundary.geojson').write_text(json.dumps({'type':'Feature','geometry':None}))
        with self.assertRaisesMessage(CommandError, 'boundary'):
            self.run_resolver('result.csv')
