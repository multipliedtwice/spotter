import io
import json
import urllib.error
from unittest.mock import patch
from django.test import TestCase, override_settings
from planner.models import CacheEntry
from planner.providers import AddressError, ProviderError, address_fields, census, parse_routes, route

class Response(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

class ProviderTests(TestCase):
    def test_address_formats(self):
        self.assertEqual(address_fields('1 Main St, Boston, MA 02108'), ['1 Main St','Boston','MA','02108'])
        self.assertEqual(address_fields('1 Main St, Boston, MA, 02108, USA'), ['1 Main St','Boston','MA','02108'])
        with self.assertRaises(AddressError):
            address_fields('1 Main St, Boston')

    @patch('planner.providers.urllib.request.urlopen')
    def test_batch_single_call_and_parse(self, urlopen):
        urlopen.return_value = Response(b'0,"1 MAIN, BOSTON, MA",Match,Exact,"1 MAIN, BOSTON, MA","-71.1,42.3"\n1,"2 MAIN, DALLAS, TX",No_Match\n')
        self.assertEqual(census(['1 Main, Boston, MA 02108', '2 Main, Dallas, TX']), [[42.3,-71.1], None])
        self.assertEqual(urlopen.call_count, 1)
        body = urlopen.call_args.args[0].data.decode()
        self.assertIn('0,1 Main,Boston,MA,02108', body)
        self.assertIn('1,2 Main,Dallas,TX,', body)
        self.assertEqual(census(['1 Main, Boston, MA 02108', '2 Main, Dallas, TX']), [[42.3,-71.1], None])
        self.assertEqual(urlopen.call_count, 1)

    @patch('planner.providers.urllib.request.urlopen')
    def test_bad_census_is_provider_error(self, urlopen):
        for payload in (b'', b'9,foo,No_Match\n', b'0,foo,Match,Exact,foo,"nan,42"\n', b'0,foo,No_Match\n0,foo,No_Match\n'):
            CacheEntry.objects.all().delete()
            urlopen.return_value = Response(payload)
            with self.assertRaises(ProviderError):
                census(['1 Main, Boston, MA'])

    def test_invalid_route_responses(self):
        base = {'code':'Ok','routes':[{'geometry':{'type':'LineString','coordinates':[[-100,40],[-99,40]]},'distance':1000,'duration':90,'legs':[{'distance':1000}]}]}
        self.assertEqual(len(parse_routes(base, 2)), 1)
        for bad in [None, {}, {'code':'Ok','routes':[]}, {'code':'Ok','routes':[{**base['routes'][0], 'distance':float('nan')}]}, {'code':'Ok','routes':[{**base['routes'][0], 'legs':[]}]}, {'code':'Ok','routes':[{**base['routes'][0], 'geometry':{'type':'LineString','coordinates':[[999,40],[0,0]]}}]}]:
            with self.assertRaises(ProviderError):
                parse_routes(bad, 2)

    @patch('planner.providers.time.sleep')
    @patch('planner.providers.request')
    def test_route_cache_includes_provider(self, request, sleep):
        response = {'code':'Ok','routes':[{'geometry':{'type':'LineString','coordinates':[[-100,40],[-99,40]]},'distance':1000,'duration':90,'legs':[{'distance':1000}]}]}
        request.return_value = json.dumps(response)
        points = [[40,-100],[40,-99]]
        route(points); route(points)
        self.assertEqual(request.call_count, 1)
        with override_settings(OSRM_BASE_URL='https://example.test', OSRM_PROFILE='car'):
            route(points)
        self.assertEqual(request.call_count, 2)

    @patch('planner.providers.time.sleep')
    @patch('planner.providers.time.monotonic', return_value=100.1)
    @patch('planner.providers._last_route_request', 100.0)
    @patch('planner.providers.request')
    def test_public_rate_limit_not_applied_to_local(self, request, monotonic, sleep):
        response = {'code':'Ok','routes':[{'geometry':{'type':'LineString','coordinates':[[-100,40],[-99,40]]},'distance':1000,'duration':90,'legs':[{'distance':1000}]}]}
        request.return_value = json.dumps(response)
        with override_settings(OSRM_BASE_URL='http://127.0.0.1:5050'):
            route([[40,-100],[40,-99]])
        sleep.assert_not_called()
        with override_settings(OSRM_BASE_URL='https://router.project-osrm.org'):
            route([[40,-100],[40,-99]])
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.9)

    @patch('planner.providers.request')
    def test_route_cache_tracks_dataset_version(self, request):
        response = {'code':'Ok','routes':[{'geometry':{'type':'LineString','coordinates':[[-100,40],[-99,40]]},'distance':1000,'duration':90,'legs':[{'distance':1000}]}]}
        request.return_value = json.dumps(response)
        with override_settings(OSRM_BASE_URL='http://127.0.0.1:5050', OSRM_DATASET_VERSION='a'):
            route([[40,-100],[40,-99]])
            route([[40,-100],[40,-99]])
        with override_settings(OSRM_BASE_URL='http://127.0.0.1:5050', OSRM_DATASET_VERSION='b'):
            route([[40,-100],[40,-99]])
        self.assertEqual(request.call_count, 2)

    def test_routing_coverage_codes_are_distinct_from_provider_errors(self):
        from planner.providers import RouteCoverageError
        for code in ('NoRoute', 'NoSegment'):
            with self.assertRaisesMessage(RouteCoverageError, 'No drivable route found in loaded road data'):
                parse_routes({'code': code}, 2)
        with self.assertRaises(ProviderError) as error:
            parse_routes({'code': 'Unknown'}, 2)
        self.assertNotIsInstance(error.exception, RouteCoverageError)

    @patch('planner.providers.urllib.request.urlopen')
    def test_http_error_coverage_is_not_provider_failure(self, urlopen):
        from planner.providers import RouteCoverageError
        for code in ('NoRoute', 'NoSegment'):
            urlopen.side_effect = urllib.error.HTTPError('http://localhost', 400, 'Bad Request', {}, io.BytesIO(json.dumps({'code': code}).encode()))
            with self.assertRaises(RouteCoverageError):
                route([[38.9, -77.0], [38.8, -77.1]])
        urlopen.side_effect = urllib.error.HTTPError('http://localhost', 500, 'Server Error', {}, io.BytesIO(b'{"code":"NoRoute"}'))
        with self.assertRaises(ProviderError) as error:
            route([[38.9, -77.0], [38.8, -77.1]])
        self.assertNotIsInstance(error.exception, RouteCoverageError)

    @patch('planner.providers.request')
    def test_snap_radii_for_endpoints_and_stops_and_cache_invalidation(self, request):
        from urllib.parse import parse_qs, urlsplit
        def respond(url, timeout):
            count = len(urlsplit(url).path.rsplit('/', 1)[1].split(';'))
            return json.dumps({'code':'Ok','routes':[{'geometry':{'type':'LineString','coordinates':[[-77,38],[-77,39]]}, 'distance':1000, 'duration':90, 'legs':[{'distance':1000 / (count - 1)} for _ in range(count - 1)]}]})
        request.side_effect = respond
        endpoints = [[38,-77],[39,-77]]
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=1000, OSRM_STOP_RADIUS_METERS=100):
            route(endpoints)
            route([endpoints[0], [38.3,-77], [38.6,-77], endpoints[1]])
            self.assertEqual(parse_qs(urlsplit(request.call_args_list[0].args[0]).query)['radiuses'], ['1000;1000'])
            self.assertEqual(parse_qs(urlsplit(request.call_args_list[1].args[0]).query)['radiuses'], ['1000;100;100;1000'])
            route(endpoints)
            self.assertEqual(request.call_count, 2)
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=500, OSRM_STOP_RADIUS_METERS=100):
            route(endpoints)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(parse_qs(urlsplit(request.call_args.args[0]).query)['radiuses'], ['500;500'])
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=1000, OSRM_STOP_RADIUS_METERS=50):
            route([endpoints[0], [38.3,-77], [38.6,-77], endpoints[1]])
        self.assertEqual(request.call_count, 4)
        self.assertEqual(parse_qs(urlsplit(request.call_args.args[0]).query)['radiuses'], ['1000;50;50;1000'])
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=float('inf')):
            with self.assertRaises(ProviderError):
                route(endpoints)

    @patch('planner.providers.request')
    def test_coincident_endpoint_uses_tighter_radius(self, request):
        from urllib.parse import parse_qs, urlsplit
        from planner.providers import route_settings
        request.return_value = json.dumps({'code': 'Ok', 'routes': [{'geometry': {'type': 'LineString', 'coordinates': [[-77, 38], [-77, 39]]}, 'distance': 1000, 'duration': 90, 'legs': [{'distance': 0}, {'distance': 1000}]}]})
        start, finish = [38, -77], [39, -77]
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=1000, OSRM_STOP_RADIUS_METERS=100):
            self.assertEqual(route_settings()['snap_policy'], 'coincident-group-min-v2')
            route([start, start, finish])
            route([start, finish, finish])
            self.assertEqual(parse_qs(urlsplit(request.call_args_list[0].args[0]).query)['radiuses'], ['100;100;1000'])
            self.assertEqual(parse_qs(urlsplit(request.call_args_list[1].args[0]).query)['radiuses'], ['1000;100;100'])
        with override_settings(OSRM_ENDPOINT_RADIUS_METERS=50, OSRM_STOP_RADIUS_METERS=100):
            route([start, start, finish])
            route([start, finish, finish])
            self.assertEqual(parse_qs(urlsplit(request.call_args_list[2].args[0]).query)['radiuses'], ['50;50;50'])
            self.assertEqual(parse_qs(urlsplit(request.call_args_list[3].args[0]).query)['radiuses'], ['50;50;50'])

    @patch('planner.providers.request')
    def test_route_failure_is_not_cached_and_can_recover(self, request):
        response = {'code':'Ok','routes':[{'geometry':{'type':'LineString','coordinates':[[-100,40],[-99,40]]},'distance':1000,'duration':90,'legs':[{'distance':1000}]}]}
        request.side_effect = [ProviderError('unavailable'), json.dumps(response)]
        points = [[40, -100], [40, -99]]
        with self.assertRaises(ProviderError):
            route(points)
        self.assertEqual(len(route(points)), 1)
        self.assertEqual(len(route(points)), 1)
        self.assertEqual(request.call_count, 2)
