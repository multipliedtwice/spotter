import json
import re
from unittest.mock import patch
from django.test import TestCase
from planner.models import City, RoutePlan, Station
from planner.planning import plan
from planner.providers import ProviderError

ROAD = {'geometry': {'type':'LineString', 'coordinates':[[-100, 40], [-99,40]]}, 'distance_miles': 60, 'duration_seconds': 3600, 'legs_miles': [60]}
BOUNDARY = {'type':'Polygon', 'coordinates': [[[-125,24],[-66,24],[-66,50],[-125,50],[-125,24]]]}

LEGACY_ROAD = {**ROAD, 'geometry': {'type':'LineString', 'coordinates':[[-100, 40], [-99.5, 40.2], [-99,40]]}}

def legacy_result(recommended):
    candidate = {'verified': True, 'road': LEGACY_ROAD, 'stops': [{'station_id': '1', 'latitude': 40, 'longitude': -99.5}]}
    return {'status': 'ok' if recommended else 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE', 'baseline_original_road': LEGACY_ROAD, 'baseline': candidate, 'alternatives': [], 'recommended': candidate if recommended else None}

class ViewsTests(TestCase):
    def map_plan(self, result):
        stored = RoutePlan.objects.create(result=result)
        response = self.client.get(f'/map/{stored.pk}')
        self.assertEqual(response.status_code, 200)
        return json.loads(re.search(r'<script id="plan" type="application/json">(.*?)</script>', response.content.decode(), re.S).group(1)), stored

    def test_legacy_map_is_normalized_on_read(self):
        plan_data, stored = self.map_plan(legacy_result(True))
        gid = plan_data['baseline_original_road']['geometry_id']
        self.assertEqual(list(plan_data['geometries']), [gid])
        self.assertEqual(plan_data['geometries'][gid]['coordinates'], LEGACY_ROAD['geometry']['coordinates'])
        for road in (plan_data['baseline']['road'], plan_data['recommended']['road']):
            self.assertEqual(road['geometry_id'], gid)
            self.assertNotIn('geometry', road)
        self.assertEqual(len(plan_data['recommended']['stops']), 1)
        stored.refresh_from_db()
        self.assertIn('geometry', stored.result['baseline']['road'])
        self.assertNotIn('geometries', stored.result)

    def test_legacy_map_without_recommendation(self):
        plan_data, _ = self.map_plan(legacy_result(False))
        self.assertIsNone(plan_data['recommended'])
        self.assertEqual(len(plan_data['geometries']), 1)

    def test_new_format_map_is_unchanged(self):
        result = {'status': 'ok', 'baseline_original_road': {'geometry_id': 'g'}, 'baseline': {'road': {'geometry_id': 'g'}}, 'alternatives': [], 'recommended': None, 'geometries': {'g': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}}}
        plan_data, _ = self.map_plan(result)
        self.assertEqual(plan_data, result)

    def post(self, body):
        return self.client.post('/api/routes', json.dumps(body), content_type='application/json')

    def test_validation(self):
        self.assertEqual(self.post({'start': 'a'}).status_code, 400)
        self.assertEqual(self.post({'start':'a','finish':'b','start_fuel_gallons':51}).json()['code'], 'INVALID_FUEL')

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_no_purchase_cache_and_map(self, routing, boundary):
        body = {'start':{'latitude':40,'longitude':-100}, 'finish':{'latitude':40,'longitude':-99}, 'start_fuel_gallons': 10}
        response = self.post(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['recommended']['purchase_cost_usd'], 0)
        self.assertEqual(response.json()['start_fuel_gallons'], 10)
        self.assertIn('cost_basis', response.json())
        self.assertIsNone(response.json()['comparison']['savings_usd'])
        self.assertEqual(self.post(body).json()['plan_id'], response.json()['plan_id'])
        self.assertEqual(routing.call_count, 1)
        map_response = self.client.get(response.json()['map_url'])
        self.assertEqual(map_response.status_code, 200)
        self.assertEqual(map_response['Referrer-Policy'], 'strict-origin-when-cross-origin')
        self.assertEqual(routing.call_count, 1)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_omitted_fuel_defaults_to_full_tank_and_extra_keys_are_ignored(self, routing, boundary):
        body = {'start':{'latitude':40,'longitude':-100}, 'finish':{'latitude':40,'longitude':-99}, 'extra': 1}
        response = self.post(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['recommended']['purchase_cost_usd'], 0)
        self.assertEqual(response.json()['start_fuel_gallons'], 50)
        self.assertIn('Starting fuel is valued at $0', response.json()['cost_basis'])
        explicit = self.post({**body, 'start_fuel_gallons': 50})
        self.assertEqual(explicit.json()['plan_id'], response.json()['plan_id'])
        self.assertEqual(routing.call_count, 1)
        self.assertEqual(self.post({'start': 'a'}).json()['code'], 'INVALID_REQUEST')
        self.assertEqual(self.post([]).json()['code'], 'INVALID_REQUEST')

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_response_contains_each_distinct_geometry_once(self, routing, boundary):
        body = {'start':{'latitude':40,'longitude':-100}, 'finish':{'latitude':40,'longitude':-99}, 'start_fuel_gallons': 10}
        data = self.post(body).json()
        self.assertNotIn('geometry', data['baseline']['road'])
        self.assertEqual(len(data['geometries']), 1)
        ids = {data['baseline_original_road']['geometry_id'], data['baseline']['road']['geometry_id'], data['recommended']['road']['geometry_id']}
        self.assertEqual(ids, set(data['geometries']))
        self.assertEqual(data['recommended'], data['baseline'])

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_missing_coverage(self, routing, boundary):
        response = self.post({'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':1})
        self.assertEqual(response.status_code, 422)
        baseline = response.json()['baseline']
        self.assertIsNone(baseline['purchase_cost_usd'])
        self.assertIsNone(baseline['purchased_gallons'])
        self.assertIsNone(baseline['remaining_gallons'])
        self.assertEqual(baseline['consumed_gallons'], 6)
        self.assertIsNone(response.json()['recommended'])
        self.assertIn('search bounds', response.json()['message'])
        self.assertEqual(self.client.get(response.json()['map_url']).status_code, 200)

    def test_bad_json_and_nonfinite_coordinates(self):
        self.assertEqual(self.client.post('/api/routes', '{', content_type='application/json').status_code, 400)
        response = self.post({'start':{'latitude':float('nan'),'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':10})
        self.assertEqual(response.json()['code'], 'INVALID_LOCATION')
        response = self.post({'start':'1 Main, Boston','finish':'Dallas, TX','start_fuel_gallons':10})
        self.assertEqual(response.status_code, 400)

    def test_oversized_numbers_are_rejected(self):
        head = '{"start":{"latitude":40,"longitude":-100},"finish":{"latitude":40,"longitude":-99}'
        cases = [
            (head + ',"start_fuel_gallons":1' + '0' * 400 + '}', 'INVALID_FUEL'),
            ('{"start":{"latitude":1' + '0' * 400 + ',"longitude":-100},"finish":{"latitude":40,"longitude":-99}}', 'INVALID_LOCATION'),
            ('1' * 5000, 'INVALID_REQUEST'),
        ]
        for body, code in cases:
            response = self.client.post('/api/routes', body, content_type='application/json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['code'], code)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    def test_flat_fields_list_purchase_stops_only(self, boundary):
        Station.objects.create(source_id='1', name='EXAMPLE #1', address='10 MAIN', city='TOWN', state='TX', rows=[], price=3, price_min=3, price_max=3, latitude=40, longitude=-99.5, evidence={'source':'test'})
        def routing(points, alternatives=False):
            return [ROAD] if alternatives else [{**ROAD, 'legs_miles': [30, 30]}]
        with patch('planner.planning.route', side_effect=routing):
            response = self.post({'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':5})
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['distance_miles'], data['recommended']['road']['distance_miles'])
        self.assertEqual(data['purchase_cost_usd'], data['recommended']['purchase_cost_usd'])
        purchases = [stop for stop in data['recommended']['stops'] if stop['purchase']]
        self.assertTrue(purchases)
        self.assertEqual([stop['station_id'] for stop in data['fuel_stops']], [stop['station_id'] for stop in purchases])
        self.assertTrue(all(stop['gallons'] > 0 for stop in data['fuel_stops']))
        self.assertNotIn('summary', data)
        self.assertTrue(data['map_url'])

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_flat_fields_are_null_without_recommendation(self, routing, boundary):
        response = self.post({'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':1})
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertIsNone(data['purchase_cost_usd'])
        self.assertIsNone(data['fuel_stops'])
        self.assertEqual(data['distance_miles'], ROAD['distance_miles'])

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    def test_zero_and_outside(self, boundary):
        body = {'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':0}
        self.assertEqual(self.post(body).json()['code'], 'ZERO_FUEL_ORIGIN_NOT_STATION')
        body['start']['latitude'] = 55
        self.assertEqual(self.post(body).json()['code'], 'OUTSIDE_USA')

    def test_ambiguous_city(self):
        City.objects.create(name='Springfield', state='IL', latitude=40, longitude=-100)
        City.objects.create(name='Springfield', state='MO', latitude=40, longitude=-99)
        response = self.post({'start':'Springfield','finish':'Springfield','start_fuel_gallons':5})
        self.assertEqual(response.json()['code'], 'AMBIGUOUS_LOCATION')
        self.assertEqual(len(response.json()['candidates']), 2)
        self.assertFalse(response.json()['truncated'])

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', side_effect=ProviderError('unavailable'))
    def test_provider_failure(self, routing, boundary):
        response = self.post({'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':10})
        self.assertEqual(response.status_code, 503)

class PlanningTests(TestCase):
    def station(self, source_id, lat=40, lon=-99.5):
        return Station.objects.create(source_id=source_id, name='EXAMPLE #1', address='10 MAIN', city='TOWN', state='TX', rows=[], price=3, price_min=3, price_max=3, latitude=lat, longitude=lon, evidence={'source':'test'})

    @patch('planner.planning.proposal')
    @patch('planner.planning.route')
    def test_two_verifications_share_three_call_budget(self, routing, propose):
        station = self.station('1')
        verified = {**ROAD, 'legs_miles':[30,30]}
        other = self.station('2', lon=-99.4)
        routing.side_effect = [[ROAD, ROAD, ROAD], [verified], [verified]]
        propose.side_effect = [[station], [station], [other], [other], [other], [other]]
        result = plan([40,-100], [40,-99], 5, [station])
        self.assertEqual(routing.call_count, 3)
        self.assertTrue(result['baseline']['verified'])
        self.assertTrue(result['alternatives'][0]['verified'])
        self.assertEqual(result['comparison']['status'], 'compared')

    @patch('planner.planning.proposal')
    @patch('planner.planning.route')
    def test_unavailable_baseline_and_feasible_alternative(self, routing, propose):
        station = self.station('1')
        verified = {**ROAD, 'legs_miles':[30,30]}
        routing.side_effect = [[ROAD, ROAD], [verified]]
        propose.side_effect = [None, None, [station], [station]]
        result = plan([40,-100], [40,-99], 5, [station])
        self.assertFalse(result['baseline']['verified'])
        self.assertTrue(result['recommended']['verified'])
        self.assertIsNone(result['comparison']['savings_usd'])

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_plan_cache_invalidates_evidence_price_and_settings(self, routing, boundary):
        from django.test import override_settings
        station = self.station('1')
        station.latitude = None; station.longitude = None; station.save()
        body = {'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':10}
        first = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()['plan_id']
        station.price = 4; station.save()
        second = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()['plan_id']
        station.evidence = {'source':'changed'}; station.save()
        third = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()['plan_id']
        with override_settings(FUEL_CORRIDOR_MILES=4):
            fourth = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()['plan_id']
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=500):
            fifth = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()['plan_id']
        self.assertEqual(len({first, second, third, fourth, fifth}), 5)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_city_full_state(self, routing, boundary):
        City.objects.create(name='Chicago', state='IL', latitude=40, longitude=-100)
        City.objects.create(name='Dallas', state='TX', latitude=40, longitude=-99)
        response = self.client.post('/api/routes', json.dumps({'start':'Chicago, Illinois','finish':'Dallas, Texas','start_fuel_gallons':10}), content_type='application/json')
        self.assertEqual(response.status_code, 200)

    @patch('planner.planning.proposal')
    @patch('planner.planning.route')
    def test_repair_consumes_remaining_budget(self, routing, propose):
        first = self.station('1')
        second = self.station('2', lon=-99.4)
        bad = {**ROAD, 'legs_miles':[510, 10], 'distance_miles':520}
        good = {**ROAD, 'legs_miles':[30, 30]}
        routing.side_effect = [[ROAD, ROAD], [bad], [good]]
        propose.side_effect = [[first], [second], [first], [first, second], [first, second]]
        result = plan([40,-100], [40,-99], 50, [first, second])
        self.assertEqual(routing.call_count, 3)
        self.assertTrue(result['baseline']['verified'])
        self.assertEqual(result['alternatives'][0]['reason'], 'VERIFICATION_BUDGET_EXHAUSTED')
        self.assertIn('VERIFICATION_BUDGET_EXHAUSTED', result['reasons'])

    @patch('planner.planning.proposal')
    @patch('planner.planning.route')
    def test_waypoint_provider_failure(self, routing, propose):
        first = self.station('1')
        routing.side_effect = [[ROAD], ProviderError('failed')]
        propose.side_effect = [[first], None, [first]]
        result = plan([40,-100], [40,-99], 1, [first])
        self.assertEqual(result['status'], 'PROVIDER_FAILURE')
        self.assertEqual(result['baseline']['reason'], 'VERIFICATION_PROVIDER_FAILURE')

    @patch('planner.planning.load_boundary', side_effect=ValueError('Invalid boundary'))
    def test_null_boundary_is_provider_error(self, boundary):
        body = {'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':10}
        response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'PROVIDER_FAILURE')

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route')
    def test_initial_road_coverage_is_422(self, routing, boundary):
        from planner.providers import RouteCoverageError
        routing.side_effect = RouteCoverageError('No drivable route found in loaded road data')
        body = {'start':{'latitude':40,'longitude':-100},'finish':{'latitude':40,'longitude':-99},'start_fuel_gallons':10}
        response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['code'], 'ROUTING_COVERAGE_UNAVAILABLE')
        self.assertEqual(response.json()['message'], 'No drivable route found in loaded road data')

    @patch('planner.planning.proposal')
    @patch('planner.planning.route')
    def test_waypoint_coverage_retains_road(self, routing, propose):
        from planner.providers import RouteCoverageError
        station = self.station('1')
        routing.side_effect = [[ROAD], RouteCoverageError('No drivable route found in loaded road data')]
        propose.side_effect = [[station], None, [station]]
        result = plan([40,-100], [40,-99], 1, [station])
        self.assertEqual(result['status'], 'ROUTING_COVERAGE_UNAVAILABLE')
        self.assertEqual(result['code'], 'ROUTING_COVERAGE_UNAVAILABLE')
        self.assertEqual(result['baseline']['road'], {**{k: v for k, v in ROAD.items() if k != 'geometry'}, 'geometry_id': result['baseline']['road']['geometry_id']})
        self.assertEqual(result['geometries'][result['baseline']['road']['geometry_id']]['coordinates'], ROAD['geometry']['coordinates'])
        self.assertIsNone(result['baseline']['purchase_cost_usd'])

    @patch('planner.planning.proposal')
    @patch('planner.planning.route')
    def test_waypoint_coverage_allows_verified_alternative(self, routing, propose):
        from planner.providers import RouteCoverageError
        station = self.station('1')
        verified = {**ROAD, 'legs_miles':[30,30]}
        other = self.station('2', lon=-99.4)
        routing.side_effect = [[ROAD, ROAD], RouteCoverageError('No drivable route found in loaded road data'), [verified]]
        propose.side_effect = [[station], None, [other], [other], [other]]
        result = plan([40,-100], [40,-99], 5, [station])
        self.assertEqual(result['baseline']['reason'], 'ROUTING_COVERAGE_UNAVAILABLE')
        self.assertTrue(result['recommended']['verified'])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(routing.call_count, 3)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_ambiguous_same_state_city_can_retry_candidate_coordinates(self, routing, boundary):
        City.objects.create(name='Burbank', state='TX', latitude=40, longitude=-100)
        City.objects.create(name='Burbank', state='TX', latitude=40, longitude=-99)
        body = {'start': 'Burbank, TX', 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 10}
        response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.json()['code'], 'AMBIGUOUS_LOCATION')
        candidates = response.json()['candidates']
        self.assertEqual(len(candidates), 2)
        self.assertFalse(response.json()['truncated'])
        self.assertNotEqual(candidates[0]['location'], candidates[1]['location'])
        body['start'] = candidates[0]['location']
        self.assertEqual(self.client.post('/api/routes', json.dumps(body), content_type='application/json').status_code, 200)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.views.key', return_value='cache-test')
    @patch('planner.views.plan')
    def test_degraded_plan_is_saved_for_map_but_not_reused_even_as_legacy_cache(self, planning, cache_key, boundary):
        from planner.models import RoutePlan
        verified = {'verified': True, 'road': ROAD, 'purchase_cost_usd': 0}
        degraded = {'status': 'ok', 'baseline': verified, 'alternatives': [{'verified': False, 'reason': 'VERIFICATION_PROVIDER_FAILURE'}], 'recommended': verified}
        recovered = {'status': 'ok', 'baseline': verified, 'alternatives': [], 'recommended': verified}
        planning.side_effect = [degraded, recovered]
        body = {'start': {'latitude': 40, 'longitude': -100}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 10}
        first = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()
        self.assertEqual(RoutePlan.objects.get(pk=first['plan_id']).cache_key, '')
        self.assertEqual(self.client.get(first['map_url']).status_code, 200)
        RoutePlan.objects.filter(pk=first['plan_id']).update(cache_key='cache-test')
        second = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()
        third = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()
        self.assertNotEqual(first['plan_id'], second['plan_id'])
        self.assertEqual(second['plan_id'], third['plan_id'])
        self.assertEqual(planning.call_count, 2)

    def test_city_candidates_are_bounded_and_marked_truncated(self):
        City.objects.bulk_create([City(name='Springfield', state='TX', latitude=30 + index / 100, longitude=-100) for index in range(22)])
        body = {'start': 'Springfield', 'finish': 'Springfield', 'start_fuel_gallons': 5}
        response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.json()['code'], 'AMBIGUOUS_LOCATION')
        self.assertTrue(response.json()['truncated'])
        candidates = response.json()['candidates']
        self.assertEqual(len(candidates), 20)
        self.assertEqual([entry['latitude'] for entry in candidates], sorted(entry['latitude'] for entry in candidates))

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.providers.request')
    def test_zero_fuel_near_origin_canonicalizes_before_routing(self, request, boundary):
        from urllib.parse import parse_qs, urlsplit
        from django.test import override_settings
        station = self.station('1', lat=40, lon=-100)
        def respond(url, timeout):
            points = urlsplit(url).path.rsplit('/', 1)[1].split(';')
            legs = [{'distance': 1000}] if len(points) == 2 else [{'distance': 0}, {'distance': 1000}]
            return json.dumps({'code': 'Ok', 'routes': [{'geometry': {'type': 'LineString', 'coordinates': [[-100, 40], [-99, 40]]}, 'distance': 1000, 'duration': 90, 'legs': legs}]})
        request.side_effect = respond
        body = {'start': {'latitude': station.latitude + 1e-9, 'longitude': station.longitude}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 0}
        with override_settings(OSRM_BASE_URL='http://127.0.0.1:5050', OSRM_ENDPOINT_RADIUS_METERS=1000, OSRM_STOP_RADIUS_METERS=100):
            response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.call_count, 2)
        urls = [call.args[0] for call in request.call_args_list]
        initial = urlsplit(urls[0]).path.rsplit('/', 1)[1].split(';')
        routed = urlsplit(urls[1]).path.rsplit('/', 1)[1].split(';')
        self.assertEqual(initial[0], '-100.0,40.0')
        self.assertEqual(routed[0], initial[0])
        self.assertEqual(routed[1], initial[0])
        self.assertEqual(parse_qs(urlsplit(urls[1]).query)['radiuses'], ['100;100;1000'])
        self.assertEqual(response.json()['recommended']['road']['legs_miles'][0], 0)
        self.assertEqual(response.json()['recommended']['stops'][0]['fuel_before_gallons'], 0)
        body['start']['latitude'] = station.latitude + 1e-6
        with patch('planner.providers.request') as unused:
            outside = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(outside.json()['code'], 'ZERO_FUEL_ORIGIN_NOT_STATION')
        unused.assert_not_called()

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.views.distance', return_value=0.0000005)
    def test_equal_distance_distinct_zero_fuel_origins_require_selection(self, distance, boundary):
        self.station('1', lat=40, lon=-100)
        self.station('2', lat=40.000000001, lon=-100)
        body = {'start': {'latitude': 40, 'longitude': -100}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 0}
        response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.json()['code'], 'AMBIGUOUS_ZERO_FUEL_ORIGIN')
        self.assertEqual(len(response.json()['candidates']), 2)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.providers.request')
    def test_zero_fuel_exact_origin_does_not_select_cheaper_nearby_station(self, request, boundary):
        from urllib.parse import parse_qs, urlsplit
        from django.test import override_settings
        origin = self.station('1', lat=40, lon=-100)
        cheaper = self.station('2', lat=40.000000001, lon=-100)
        cheaper.price = cheaper.price_min = cheaper.price_max = 1
        cheaper.save()
        def respond(url, timeout):
            points = urlsplit(url).path.rsplit('/', 1)[1].split(';')
            legs = [{'distance': 1000}] if len(points) == 2 else [{'distance': 0}, {'distance': 1000}]
            return json.dumps({'code': 'Ok', 'routes': [{'geometry': {'type': 'LineString', 'coordinates': [[-100, 40], [-99, 40]]}, 'distance': 1000, 'duration': 90, 'legs': legs}]})
        request.side_effect = respond
        body = {'start': {'latitude': origin.latitude, 'longitude': origin.longitude}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 0}
        with override_settings(OSRM_BASE_URL='http://127.0.0.1:5050', OSRM_ENDPOINT_RADIUS_METERS=1000, OSRM_STOP_RADIUS_METERS=100):
            response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        first = result['recommended']['stops'][0]
        self.assertEqual(first['station_id'], origin.source_id)
        self.assertEqual([first['latitude'], first['longitude']], [origin.latitude, origin.longitude])
        for candidate in [result['baseline'], *result['alternatives']]:
            if candidate['verified'] and candidate['stops']:
                self.assertEqual(candidate['stops'][0]['station_id'], origin.source_id)
                self.assertEqual([candidate['stops'][0]['latitude'], candidate['stops'][0]['longitude']], [origin.latitude, origin.longitude])
        self.assertLessEqual(request.call_count, 3)
        verification = urlsplit(request.call_args_list[1].args[0])
        points = verification.path.rsplit('/', 1)[1].split(';')
        self.assertEqual(points[0], points[1])
        self.assertEqual(parse_qs(verification.query)['radiuses'], ['100;100;1000'])

    def test_station_digest_reuses_data_and_invalidates_for_orm_mutations(self):
        from datetime import timedelta
        from django.db import transaction
        from django.utils import timezone
        from planner.core import key, station_dataset_digest
        from planner.models import CacheEntry, STATION_DATASET_CACHE_KEY
        station = self.station('1')
        with patch('planner.core.key', wraps=key) as hash_data:
            first = station_dataset_digest()
            self.assertEqual(station_dataset_digest(), first)
            City.objects.create(name='OTHER', state='TX', latitude=40, longitude=-100)
            self.assertEqual(station_dataset_digest(), first)
            self.assertEqual(hash_data.call_count, 1)
            station.price = 4
            station.save()
            second = station_dataset_digest()
            self.assertNotEqual(second, first)
            self.assertEqual(hash_data.call_count, 2)
            Station.objects.filter(pk=station.pk).update(evidence={'source': 'updated'})
            third = station_dataset_digest()
            self.assertNotEqual(third, second)
            station.refresh_from_db()
            station.name = 'CHANGED #1'
            Station.objects.bulk_update([station], ['name'], 1)
            fourth = station_dataset_digest()
            self.assertNotEqual(fourth, third)
            extra = Station(source_id='2', name='EXAMPLE #2', address='20 MAIN', city='TOWN', state='TX', rows=[], price=3, price_min=3, price_max=3)
            Station.objects.bulk_create([extra], 1)
            fifth = station_dataset_digest()
            self.assertNotEqual(fifth, fourth)
            Station.objects.filter(source_id='2').delete()
            self.assertEqual(station_dataset_digest(), fourth)
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    Station.objects.filter(pk=station.pk).update(price=9)
                    raise RuntimeError('rollback')
            self.assertEqual(station_dataset_digest(), fourth)
            before_expiry = hash_data.call_count
            CacheEntry.objects.filter(pk=STATION_DATASET_CACHE_KEY).update(expires=timezone.now() - timedelta(seconds=1))
            self.assertEqual(station_dataset_digest(), fourth)
            self.assertEqual(hash_data.call_count, before_expiry + 1)
            station.delete()
            self.assertNotEqual(station_dataset_digest(), fourth)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_expired_plan_recomputes_instead_of_reusing_old_result(self, routing, boundary):
        from datetime import timedelta
        from django.utils import timezone
        from planner.models import RoutePlan
        body = {'start': {'latitude': 40, 'longitude': -100}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 10}
        first = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()
        RoutePlan.objects.filter(pk=first['plan_id']).update(created=timezone.now() - timedelta(hours=25))
        second = self.client.post('/api/routes', json.dumps(body), content_type='application/json').json()
        self.assertNotEqual(first['plan_id'], second['plan_id'])
        self.assertEqual(routing.call_count, 2)

    @patch('planner.planning.load_boundary', return_value=BOUNDARY)
    @patch('planner.planning.route', return_value=[ROAD])
    def test_repeated_requests_do_not_rehash_station_dataset(self, routing, boundary):
        from planner.core import key
        self.station('1')
        body = {'start': {'latitude': 40, 'longitude': -100}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 10}
        with patch('planner.core.key', wraps=key) as hash_data:
            first = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
            second = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json()['plan_id'], first.json()['plan_id'])
        self.assertEqual(hash_data.call_count, 1)
        self.assertEqual(routing.call_count, 1)

    @patch('planner.views.plan')
    @patch('planner.views.resolve_locations')
    def test_station_id_is_refreshed_from_same_snapshot_as_dataset(self, resolve, planning):
        station = self.station('1', lat=40, lon=-99.5)
        resolve.side_effect = [[[40, -100], [40, -99]], [[40, -99.5], [40, -99.5]]]
        verified = {'verified': True, 'road': ROAD, 'purchase_cost_usd': 0}
        planning.return_value = {'status': 'ok', 'baseline': verified, 'alternatives': [], 'recommended': verified}
        body = {'start': {'station_id': station.source_id}, 'finish': {'latitude': 40, 'longitude': -99}, 'start_fuel_gallons': 10}
        response = self.client.post('/api/routes', json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(planning.call_args.args[0], [40, -99.5])
        self.assertEqual([planning.call_args.args[3][0].latitude, planning.call_args.args[3][0].longitude], [40, -99.5])
