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
        self.assertEqual(len(results), 201)
        self.assertGreater(max(c[0] for c in results), 990)
        stops = proposal(self.road(), stations, [0,0], 50)
        self.assertIsNotNone(stops)
        self.assertTrue(any(s.longitude > 5 for s in stops))

    def pruning_case(self):
        stations = [self.make_station(1, 99, 4.0), self.make_station(2, 103, 2.0)]
        stations += [self.make_station(i + 3, 140 + i * 2.8, 3.0) for i in range(160)]
        return stations

    def test_only_reachable_station_survives_with_many_candidates(self):
        road, stations = self.road(600), self.pruning_case()
        self.assertGreater(len(stations), 150)
        for mode in ('progress', 'cost'):
            stops = proposal(road, stations, [0, 0], 10, mode=mode)
            self.assertIsNotNone(stops)
            self.assertEqual(stops[0].source_id, '1' if mode == 'cost' else '2')

    def test_plan_feasible_with_many_candidates(self):
        stations = self.pruning_case()
        def routing(points, alternatives=False):
            if alternatives:
                return [self.road(600)]
            legs = [(abs(b[1]-a[1]) + abs(b[0]-a[0]))*100 for a,b in zip(points,points[1:])]
            return [{**self.road(sum(legs)), 'legs_miles': legs, 'duration_seconds': sum(legs)*60}]
        with patch('planner.planning.route', side_effect=routing):
            result = plan([0,0],[0,6],10,stations)
        self.assertIsNotNone(result['recommended']['purchase_cost_usd'])

    def test_longer_cheaper_detour_plan_is_verified_first(self):
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
        self.assertEqual([stop['station_id'] for stop in result['baseline']['stops']], ['2', '4'])
        self.assertGreater(result['baseline']['road']['distance_miles'], 1000)
        self.assertEqual(result['recommended'], result['baseline'])
        self.assertEqual(result['alternatives'], [])

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
        baseline = result['baseline']
        self.assertTrue(baseline['verified'])
        self.assertEqual([stop['station_id'] for stop in baseline['stops']], ['1', '2'])
        self.assertAlmostEqual(baseline['stops'][0]['gallons'], 3.1)
        self.assertAlmostEqual(baseline['stops'][1]['gallons'], 7.1)
        self.assertEqual(baseline['purchase_cost_usd'], 29.7)
        self.assertEqual(result['recommended'], baseline)
        self.assertEqual([item['purchase_cost_usd'] > baseline['purchase_cost_usd'] for item in result['alternatives'] if item['verified']], [True])
        self.assertEqual(result['comparison']['savings_usd'], 0.0)

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
        self.assertEqual(result['alternatives'], [])
        self.assertLess(estimated_cost(baseline, [stations[1], stations[2]], stations, 50, [0, 0]), result['baseline']['purchase_cost_usd'])

    def alternative_run(self, proposals, routes, costs=None, fuel=5):
        stations = [self.make_station(i, 30, 3) for i in (1, 2, 3)]
        roads = [self.road(60), {**self.road(60), 'duration_seconds': 7200}]
        by_id = {s.pk: s for s in stations}
        outcomes = [None if p is None else [by_id[i] for i in p] for p in proposals]
        costs = costs or [index + 1 for index, p in enumerate(proposals[:4]) if p is not None]
        with patch('planner.planning.proposal', side_effect=outcomes), patch('planner.planning.estimated_cost', side_effect=costs), patch('planner.planning.route', side_effect=[roads, *routes]) as routing:
            result = plan([0, 0], [0, 1], fuel, stations)
        return result, routing

    def test_second_distinct_proposal_is_verified_after_first_fails(self):
        failed = {**self.road(60), 'legs_miles': [1000, 10]}
        verified = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[1], None, [2], [3], None], [[failed], [verified]])
        self.assertEqual(routing.call_count, 3)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['baseline']['verified'])
        self.assertTrue(result['alternatives'][0]['verified'])
        self.assertEqual(result['recommended'], result['alternatives'][0])
        self.assertEqual(result['recommended']['stops'][0]['station_id'], '2')
        self.assertEqual(result['comparison']['status'], 'baseline_unavailable')

    def test_duplicate_stop_sequence_is_not_reverified(self):
        failed = {**self.road(60), 'legs_miles': [1000, 10]}
        verified = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[1], None, [1], [3], None], [[failed], [verified]])
        self.assertEqual(routing.call_count, 3)
        self.assertEqual(len(result['alternatives']), 1)
        self.assertEqual(result['recommended']['stops'][0]['station_id'], '3')

    def test_proposal_attempts_respect_routing_budget(self):
        failed = {**self.road(60), 'legs_miles': [1000, 10]}
        result, routing = self.alternative_run([[1], None, [2], [3], None], [[failed], [failed]])
        self.assertEqual(routing.call_count, 3)
        self.assertIsNone(result['recommended'])
        self.assertEqual(result['alternatives'][-1]['reason'], 'VERIFICATION_BUDGET_EXHAUSTED')

    def test_comparison_provider_failure_keeps_verified_recommendation(self):
        from planner.providers import ProviderError
        verified = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[2], None, [1], None], [[verified], ProviderError('unavailable')], costs=[2, 1])
        self.assertEqual(routing.call_count, 3)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['baseline']['reason'], 'VERIFICATION_PROVIDER_FAILURE')
        self.assertEqual(result['recommended'], result['alternatives'][0])
        self.assertEqual(result['recommended']['stops'][0]['station_id'], '1')

    def test_verified_fastest_road_outcome_is_baseline_after_failed_unrepaired_attempt(self):
        failed = {**self.road(60), 'legs_miles': [1000, 10]}
        verified = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[1], [2], None, None, None], [[failed], [verified]], costs=[1, 2])
        self.assertEqual(routing.call_count, 3)
        self.assertTrue(result['baseline']['verified'])
        self.assertEqual(result['baseline']['stops'][0]['station_id'], '2')
        self.assertEqual(result['recommended'], result['baseline'])
        self.assertFalse(result['alternatives'][0]['verified'])
        self.assertNotEqual(result['comparison']['status'], 'baseline_unavailable')

    def test_untried_baseline_reports_provider_failure_from_slower_road(self):
        from planner.providers import ProviderError
        result, routing = self.alternative_run([[1], None, [2], None], [ProviderError('unavailable')], costs=[2, 1])
        self.assertEqual(routing.call_count, 2)
        self.assertEqual(result['baseline']['reason'], 'VERIFICATION_PROVIDER_FAILURE')
        self.assertEqual(result['alternatives'][0]['reason'], 'VERIFICATION_PROVIDER_FAILURE')
        self.assertIsNone(result['recommended'])

    def test_zero_stop_alternative_is_evaluated_when_baseline_has_no_proposal(self):
        fastest = self.road(600)
        slower = {**self.road(490), 'duration_seconds': 600 * 60 + 1}
        with patch('planner.planning.route', side_effect=[[fastest, slower]]) as routing:
            result = plan([0, 0], [0, 6], 50, [])
        self.assertEqual(routing.call_count, 1)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['baseline']['verified'])
        self.assertEqual(result['recommended']['road']['distance_miles'], 490)
        self.assertEqual(result['recommended']['purchase_cost_usd'], 0)
        self.assertEqual(result['fuel_stops'], [])

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

    def routed_trip(self, roads, stations, finish_lon, extra=None, fuel=50):
        extra = extra or {}
        calls = []
        def routing(points, alternatives=False):
            calls.append(points)
            if alternatives:
                return roads
            legs = [(abs(b[1] - a[1]) + abs(b[0] - a[0])) * 100 + extra.get(round(b[1] * 100), 0) for a, b in zip(points, points[1:])]
            return [{**self.road(sum(legs)), 'legs_miles': legs, 'duration_seconds': sum(legs) * 60}]
        with patch('planner.planning.route', side_effect=routing):
            result = plan([0, 0], [0, finish_lon], fuel, stations)
        return result, calls

    def test_slack_stop_beyond_range_is_not_tried_before_cheaper_in_range_proposal(self):
        stations = [self.make_station(1, 505, 3.5), self.make_station(2, 470, 3.2), self.make_station(3, 940, 3.2)]
        result, calls = self.routed_trip([self.road(1000)], stations, 10, extra={505: 10})
        self.assertLessEqual(len(calls), 3)
        self.assertEqual(calls[1], [[0, 0], [0, 4.7], [0, 9.4], [0, 10]])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([stop['station_id'] for stop in result['recommended']['stops']], ['2', '3'])
        self.assertTrue(all(leg <= 500 for leg in result['recommended']['road']['legs_miles']))

    def cheaper_on_second_road(self):
        expensive, cheap = self.make_station(1, 300, 5), self.make_station(2, 300, 2)
        cheap.latitude = 0.5
        fast = self.road(600)
        slow = {'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [3, 0.5], [6, 0]]}, 'distance_miles': 700, 'duration_seconds': 600 * 60 + 600, 'legs_miles': [700]}
        return [expensive, cheap], [fast, slow]

    def test_cheapest_proposal_is_verified_first_then_fastest_road_for_comparison(self):
        stations, roads = self.cheaper_on_second_road()
        result, calls = self.routed_trip(roads, stations, 6)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1], [[0, 0], [0.5, 3], [0, 6]])
        self.assertEqual(calls[2], [[0, 0], [0, 3], [0, 6]])
        self.assertEqual(result['comparison']['status'], 'compared')
        self.assertGreater(result['comparison']['savings_usd'], 0)
        self.assertEqual(result['baseline']['road']['distance_miles'], 600)
        self.assertEqual(result['recommended'], result['alternatives'][0])
        self.assertEqual(result['recommended']['stops'][0]['station_id'], '2')

    def test_fastest_road_verified_first_still_verifies_remaining_proposal_within_budget(self):
        stations, roads = self.cheaper_on_second_road()
        stations[1].price = 6
        result, calls = self.routed_trip(roads, stations, 6)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['recommended'], result['baseline'])
        self.assertEqual(len(result['alternatives']), 1)
        self.assertEqual(result['comparison']['status'], 'compared')
        self.assertEqual(result['comparison']['savings_usd'], 0)

    def test_second_proposal_is_verified_and_recommended_when_baseline_actual_cost_is_higher(self):
        pricey = {**self.road(80), 'legs_miles': [30, 50]}
        cheap = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[1], None, [2], None], [[pricey], [cheap]], costs=[1, 2])
        self.assertEqual(routing.call_count, 3)
        self.assertEqual(result['baseline']['stops'][0]['station_id'], '1')
        self.assertEqual(result['recommended'], result['alternatives'][0])
        self.assertEqual(result['recommended']['stops'][0]['station_id'], '2')
        self.assertEqual(result['comparison']['status'], 'compared')
        self.assertGreater(result['comparison']['savings_usd'], 0)

    def test_routing_calls_never_exceed_three_with_many_proposals(self):
        pricey = {**self.road(80), 'legs_miles': [30, 50]}
        cheap = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[1], None, [2], [3]], [[pricey], [cheap]], costs=[1, 2, 3])
        self.assertEqual(routing.call_count, 3)
        self.assertEqual(result['recommended']['stops'][0]['station_id'], '2')

    def test_zero_purchase_verified_plan_stops_further_verification(self):
        free = {**self.road(60), 'legs_miles': [30, 30]}
        result, routing = self.alternative_run([[1], None, [2], None], [[free]], costs=[1, 2], fuel=50)
        self.assertEqual(routing.call_count, 2)
        self.assertEqual(result['recommended']['purchase_cost_usd'], 0)
        self.assertEqual(result['alternatives'], [])

    def test_range_margin_is_dropped_when_only_full_range_is_feasible(self):
        stations = [self.make_station(1, 490, 3), self.make_station(2, 980, 3)]
        result, calls = self.routed_trip([self.road(1000)], stations, 10)
        self.assertLessEqual(len(calls), 3)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([stop['station_id'] for stop in result['recommended']['stops']], ['1', '2'])
        for mode in ('cost', 'progress'):
            self.assertEqual([s.source_id for s in proposal(self.road(1000), stations, [0, 0], 50, mode=mode)], ['1', '2'])

    def test_range_margin_is_preferred_when_feasible(self):
        stations = [self.make_station(1, 480, 3), self.make_station(2, 470, 3), self.make_station(3, 940, 3)]
        for mode in ('cost', 'progress'):
            stops = proposal(self.road(1000), stations, [0, 0], 50, mode=mode)
            self.assertEqual([s.source_id for s in stops][:1], ['2'])

    def test_first_failed_leg_is_repaired_with_replacement_stop(self):
        result, calls = self.long_trip(1100, [(470, 2), (450, 3), (940, 3), (900, 3)], {470: 35})
        self.assertLessEqual(len(calls), 3)
        self.assertIsNotNone(result['recommended'])
        self.assertTrue(result['baseline']['verified'])
        self.assertEqual([stop['station_id'] for stop in result['baseline']['stops']], ['2', '4'])
        legs = result['baseline']['road']['legs_miles']
        self.assertLessEqual(legs[0], 500)
        self.assertTrue(all(leg <= 500 for leg in legs))

    def test_later_failed_leg_keeps_prefix_and_is_repaired(self):
        result, calls = self.long_trip(1600, [(495, 3), (990, 2), (1480, 3), (960, 3), (1450, 3)], {990: 15})
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
