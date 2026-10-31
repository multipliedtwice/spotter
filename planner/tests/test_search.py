from unittest.mock import patch
from django.test import SimpleTestCase
from planner.models import Station
from planner.core import simplify
from planner.planning import estimated_cost, evaluate, nearby, plan, proposal

class SearchTests(SimpleTestCase):
    def make_station(self, number, mile, price):
        return Station(id=number, source_id=str(number), name='TEST', address='SYNTHETIC', city='TEST', state='TX', rows=[], price=price, price_min=price, price_max=price, latitude=0, longitude=mile / 100, evidence={'source':'synthetic test'})

    def road(self, length=1000):
        return {'geometry': {'type':'LineString', 'coordinates': [[0,0],[length/100,0]]}, 'distance_miles':length, 'duration_seconds':length*60, 'legs_miles':[length]}

    def test_coverage_is_distributed_over_route(self):
        stations = [self.make_station(i+1, i*5, 3) for i in range(201)]
        results = nearby(self.road(), stations)
        self.assertLessEqual(len(results), 150)
        self.assertGreater(max(c[0] for c in results), 990)
        stops = proposal(self.road(), stations, [0,0], 50)
        self.assertIsNotNone(stops)
        self.assertTrue(any(s.longitude > 5 for s in stops))

    def test_longer_cheaper_verified_alternative(self):
        stations = [self.make_station(1, 490, 5), self.make_station(2, 350, 2), self.make_station(3, 840, 5), self.make_station(4, 700, 2)]
        stations[1].latitude = 0.02
        stations[3].latitude = 0.02
        calls = []
        def routing(points, alternatives=False):
            calls.append(points)
            if alternatives:
                return [self.road()]
            legs = [(abs(b[1]-a[1]) + abs(b[0]-a[0]))*100 for a,b in zip(points,points[1:])]
            road = {**self.road(sum(legs)), 'legs_miles': legs, 'duration_seconds': sum(legs)*60}
            return [road]
        with patch('planner.planning.route', side_effect=routing):
            result = plan([0,0],[0,10],50,stations)
        self.assertLessEqual(len(calls), 3)
        self.assertTrue(result['baseline']['verified'])
        self.assertTrue(result['alternatives'][0]['verified'])
        self.assertGreater(result['alternatives'][0]['road']['distance_miles'], result['baseline']['road']['distance_miles'])
        self.assertLess(result['alternatives'][0]['purchase_cost_usd'], result['baseline']['purchase_cost_usd'])
        self.assertEqual(result['recommended'], result['alternatives'][0])

    def test_nearby_scan_skipped_when_starting_fuel_suffices(self):
        stations = [self.make_station(1, 50, 3)]
        with patch('planner.planning.nearby') as scan, patch('planner.planning.route', side_effect=[[self.road(100)]]):
            result = plan([0, 0], [0, 1], 50, stations)
        self.assertTrue(result['baseline']['verified'])
        scan.assert_not_called()
        loader = patch('planner.planning.nearby')
        with loader as scan:
            self.assertEqual(proposal(self.road(100), stations, [0, 0], 50, candidates_for=lambda road: self.fail('loaded')), [])
        scan.assert_not_called()

    def test_partial_purchase_before_cheaper_station(self):
        origin = self.make_station(1, 0, 5)
        cheaper = self.make_station(2, 30, 2)
        cheaper.latitude = 0.01
        calls = []
        def routing(points, alternatives=False):
            calls.append(points)
            if alternatives:
                return [self.road(100)]
            legs = [(abs(b[1] - a[1]) + abs(b[0] - a[0])) * 100 for a, b in zip(points, points[1:])]
            return [{**self.road(sum(legs)), 'legs_miles': legs}]
        with patch('planner.planning.route', side_effect=routing):
            result = plan([0, 0], [0, 1], 0, [origin, cheaper])
        self.assertLessEqual(len(calls), 3)
        self.assertEqual(result['baseline']['purchase_cost_usd'], 50)
        alternative = result['alternatives'][0]
        self.assertTrue(alternative['verified'])
        self.assertEqual([stop['station_id'] for stop in alternative['stops']], ['1', '2'])
        self.assertAlmostEqual(alternative['stops'][0]['gallons'], 3.1)
        self.assertAlmostEqual(alternative['stops'][1]['gallons'], 7.1)
        self.assertEqual(alternative['purchase_cost_usd'], 29.7)
        self.assertEqual(result['recommended'], alternative)

    def test_origin_station_and_exact_range(self):
        origin = self.make_station(1, 0, 3)
        road = self.road(500)
        self.assertEqual(proposal(road, [origin], [0,0], 0), [origin])
        self.assertEqual(proposal(road, [origin], [0,0], 50), [])

    def test_purchase_total_sums_rounded_stop_charges(self):
        first = self.make_station(1, 0, 2.006)
        second = self.make_station(2, 10, 1.006)
        road = {**self.road(20), 'legs_miles': [0, 10, 10]}
        result = evaluate(road, [first, second], 0)
        self.assertEqual([stop['cost_usd'] for stop in result['stops']], [2.01, 1.01])
        self.assertEqual(result['purchase_cost_usd'], 3.02)
        half_cent = self.make_station(3, 0, 2.005)
        tie_result = evaluate({**self.road(10), 'legs_miles': [0, 10]}, [half_cent], 0)
        self.assertEqual(tie_result['purchase_cost_usd'], 2.01)

    def test_routed_first_leg_detour_cannot_exceed_starting_fuel(self):
        station = self.make_station(1, 90, 3)
        baseline = self.road(200)
        detour = {**self.road(210), 'legs_miles': [110, 100]}
        with patch('planner.planning.route', side_effect=[[baseline], [detour]]) as routing:
            result = plan([0, 0], [0, 2], 10, [station])
        self.assertIsNone(result['recommended'])
        self.assertFalse(result['baseline']['verified'])
        self.assertIsNone(result['baseline']['purchase_cost_usd'])
        self.assertLessEqual(routing.call_count, 3)

    def test_routed_leg_beyond_full_tank_cannot_be_recommended(self):
        stations = [self.make_station(1, 450, 3), self.make_station(2, 900, 3)]
        baseline = self.road(1000)
        detour = {**self.road(1000), 'legs_miles': [450, 510, 40]}
        with patch('planner.planning.route', side_effect=[[baseline], [detour]]) as routing:
            result = plan([0, 0], [0, 10], 50, stations)
        self.assertIsNone(result['recommended'])
        self.assertFalse(result['baseline']['verified'])
        self.assertIsNone(result['baseline']['purchase_cost_usd'])
        self.assertLessEqual(routing.call_count, 3)

    def test_baseline_remains_recommended_when_alternative_provider_fails(self):
        from planner.providers import ProviderError
        origin = self.make_station(1, 0, 5)
        cheaper = self.make_station(2, 30, 2)
        baseline = self.road(100)
        verified = {**baseline, 'legs_miles': [0, 100]}
        with patch('planner.planning.route', side_effect=[[baseline], [verified], ProviderError('unavailable')]) as routing:
            result = plan([0, 0], [0, 1], 0, [origin, cheaper])
        self.assertEqual(routing.call_count, 3)
        self.assertTrue(result['baseline']['verified'])
        self.assertEqual(result['recommended'], result['baseline'])
        self.assertEqual(result['alternatives'][0]['reason'], 'VERIFICATION_PROVIDER_FAILURE')
        self.assertIsNone(result['alternatives'][0]['purchase_cost_usd'])

    def test_cheaper_estimate_is_not_recommended_after_verification_budget(self):
        stations = [self.make_station(1, 490, 8), self.make_station(2, 450, 6), self.make_station(3, 840, 2), self.make_station(4, 900, 5)]
        baseline = self.road(1000)
        failed = {**baseline, 'legs_miles': [510, 400, 90]}
        repaired = {**baseline, 'legs_miles': [490, 350, 160]}
        with patch('planner.planning.route', side_effect=[[baseline], [failed], [repaired]]) as routing:
            result = plan([0, 0], [0, 10], 50, stations)
        self.assertEqual(routing.call_count, 3)
        self.assertTrue(result['baseline']['verified'])
        self.assertEqual(result['recommended'], result['baseline'])
        alternative = result['alternatives'][0]
        self.assertLess(estimated_cost(baseline, [stations[1], stations[2]], stations, 50, [0, 0]), result['baseline']['purchase_cost_usd'])
        self.assertFalse(alternative['verified'])
        self.assertEqual(alternative['reason'], 'VERIFICATION_BUDGET_EXHAUSTED')
        self.assertIsNone(alternative['purchase_cost_usd'])

    def test_zero_fuel_at_origin_requires_zero_length_first_routed_leg(self):
        origin = self.make_station(1, 0, 3)
        baseline = self.road(100)
        detour = {**self.road(101), 'legs_miles': [1, 100]}
        with patch('planner.planning.route', side_effect=[[baseline], [detour]]) as routing:
            result = plan([0, 0], [0, 1], 0, [origin])
        self.assertIsNone(result['recommended'])
        self.assertFalse(result['baseline']['verified'])
        self.assertIsNone(result['baseline']['purchase_cost_usd'])
        self.assertLessEqual(routing.call_count, 3)

    def test_driven_zero_purchase_waypoint_remains_visible_and_low_points_resolve(self):
        first, second = self.make_station(1, 500, 2), self.make_station(2, 510, 3)
        result = evaluate({**self.road(520), 'legs_miles': [500, 10, 10]}, [first, second], 50)
        self.assertEqual([stop['station_id'] for stop in result['stops']], ['1', '2'])
        self.assertEqual([stop['waypoint_index'] for stop in result['stops']], [1, 2])
        self.assertEqual([stop['purchase'] for stop in result['stops']], [True, False])
        self.assertEqual(result['stops'][1]['gallons'], 0)
        self.assertEqual(result['stops'][1]['cost_usd'], 0)
        for point in result['lowest_fuel_points']:
            if point['point'].startswith('stop_'):
                stop = result['stops'][point['waypoint_index'] - 1]
                self.assertEqual(point['station_id'], stop['station_id'])
        self.assertEqual(result['purchase_cost_usd'], sum(stop['cost_usd'] for stop in result['stops']))
        tied = evaluate({**self.road(520), 'legs_miles': [500, 20, 0]}, [first, second], 50)
        self.assertFalse(tied['stops'][1]['purchase'])
        point = next(point for point in tied['lowest_fuel_points'] if point['point'] == 'stop_2')
        self.assertEqual(point['station_id'], tied['stops'][1]['station_id'])
        self.assertEqual(point['waypoint_index'], tied['stops'][1]['waypoint_index'])

    def test_corridor_grid_respects_distance_at_different_latitudes(self):
        from django.test import override_settings
        for latitude, close_lon, far_lon, corridor in ((45, 0.527, 0.57, 15), (45, 0.33, 0.36, 5), (75, 0.90, 1.20, 15)):
            road = {'geometry': {'type': 'LineString', 'coordinates': [[0.24, latitude - 0.05], [0.24, latitude + 0.05]]}, 'distance_miles': 7, 'duration_seconds': 600, 'legs_miles': [7]}
            close, far = self.make_station(1, 0, 3), self.make_station(2, 0, 3)
            close.latitude = far.latitude = latitude
            close.longitude, far.longitude = close_lon, far_lon
            with self.subTest(latitude=latitude, corridor=corridor), override_settings(FUEL_CORRIDOR_MILES=corridor):
                self.assertEqual([item[2].source_id for item in nearby(road, [close, far])], ['1'])

    def test_invalid_corridor_rejected_for_settings_nearby_and_proposal(self):
        from django.test import override_settings
        from planner.planning import planning_settings
        from planner.providers import ProviderError
        for value in (0, -1, float('nan'), float('inf')):
            with self.subTest(value=value), override_settings(FUEL_CORRIDOR_MILES=value):
                for action in (lambda: planning_settings(), lambda: nearby(self.road(100), []), lambda: proposal(self.road(100), [], [0, 0], 50)):
                    with self.assertRaises(ProviderError):
                        action()

    def test_corridor_wraps_across_antimeridian_in_both_directions(self):
        from django.test import override_settings
        for a, b, longitude in ((179.8, -179.8, -179.95), (-179.8, 179.8, 179.95)):
            road = {'geometry': {'type': 'LineString', 'coordinates': [[a, 60], [b, 60]]}, 'distance_miles': 14, 'duration_seconds': 1200, 'legs_miles': [14]}
            close, far = self.make_station(1, 0, 3), self.make_station(2, 0, 3)
            close.latitude, close.longitude = 60.01, longitude
            far.latitude, far.longitude = 61, longitude
            with self.subTest(start=a), override_settings(FUEL_CORRIDOR_MILES=5):
                candidates = nearby(road, [close, far])
                self.assertEqual([item[2].source_id for item in candidates], ['1'])
                self.assertGreater(candidates[0][0], 0)
                self.assertLess(candidates[0][0], 14)

    def test_corridor_finds_station_across_dateline_from_non_crossing_segment(self):
        from django.test import override_settings
        road = {'geometry': {'type': 'LineString', 'coordinates': [[179.95, 60], [179.95, 60.1]]}, 'distance_miles': 7, 'duration_seconds': 600, 'legs_miles': [7]}
        station = self.make_station(1, 0, 3)
        station.latitude, station.longitude = 60.05, -179.98
        with override_settings(FUEL_CORRIDOR_MILES=5):
            self.assertEqual([item[2].source_id for item in nearby(road, [station])], ['1'])

    def long_trip(self, length, placements, extra, fuel=50):
        stations = [self.make_station(number, mile, price) for number, (mile, price) in enumerate(placements, 1)]
        calls = []
        def routing(points, alternatives=False):
            calls.append(points)
            if alternatives:
                return [self.road(length)]
            legs = [abs(b[1] - a[1]) * 100 + extra.get(round(b[1] * 100), 0) for a, b in zip(points, points[1:])]
            return [{**self.road(sum(legs)), 'legs_miles': legs}]
        with patch('planner.planning.route', side_effect=routing):
            result = plan([0, 0], [0, length / 100], fuel, stations)
        return result, calls

    def test_first_failed_leg_is_repaired_with_replacement_stop(self):
        result, calls = self.long_trip(1100, [(505, 3), (470, 3), (990, 3), (960, 3)], {505: 15})
        self.assertLessEqual(len(calls), 3)
        self.assertIsNotNone(result['recommended'])
        self.assertTrue(result['baseline']['verified'])
        self.assertEqual([stop['station_id'] for stop in result['baseline']['stops']], ['2', '4'])
        legs = result['baseline']['road']['legs_miles']
        self.assertLessEqual(legs[0], 500)
        self.assertTrue(all(leg <= 500 for leg in legs))

    def test_later_failed_leg_keeps_prefix_and_is_repaired(self):
        result, calls = self.long_trip(1600, [(495, 3), (990, 3), (1480, 3), (960, 3), (1450, 3)], {990: 15})
        self.assertLessEqual(len(calls), 3)
        self.assertIsNotNone(result['recommended'])
        self.assertEqual([stop['station_id'] for stop in result['baseline']['stops']], ['1', '4', '5'])
        self.assertTrue(all(leg <= 500 for leg in result['baseline']['road']['legs_miles']))

    def test_failed_final_leg_is_repaired_by_insertion(self):
        stations = [self.make_station(1, 495, 3), self.make_station(2, 985, 3), self.make_station(3, 1400, 3)]
        baseline = self.road(1480)
        failed = {**baseline, 'legs_miles': [495, 490, 520]}
        repaired = {**baseline, 'legs_miles': [495, 490, 415, 80]}
        with patch('planner.planning.route', side_effect=[[baseline], [failed], [repaired]]) as routing:
            result = plan([0, 0], [0, 14.8], 50, stations)
        self.assertEqual(routing.call_count, 3)
        self.assertEqual([stop['station_id'] for stop in result['baseline']['stops']], ['1', '2', '3'])
        self.assertTrue(result['baseline']['verified'])

    def test_simplify_reduces_dense_collinear_line_and_keeps_endpoints(self):
        line = [[i / 1000, 0.0] for i in range(1001)]
        simplified = simplify(line)
        self.assertEqual(simplified, [[0.0, 0.0], [1.0, 0.0]])
        bent = [[0, 0], [1, 0.5], [2, 0]]
        self.assertEqual(simplify(bent), bent)
        self.assertEqual(simplify(line[:2]), line[:2])

    def test_simplify_keeps_backtracking(self):
        self.assertEqual(simplify([[-100, 40], [-99, 40], [-99.5, 40]]), [[-100, 40], [-99, 40], [-99.5, 40]])
        self.assertEqual(simplify([[0, 0], [1, 0], [0, 0]]), [[0, 0], [1, 0], [0, 0]])

    def test_simplify_tolerance_is_part_of_plan_cache_identity(self):
        from planner.core import SIMPLIFY_TOLERANCE
        from planner.planning import planning_settings
        self.assertEqual(planning_settings()['simplify_tolerance'], SIMPLIFY_TOLERANCE)
