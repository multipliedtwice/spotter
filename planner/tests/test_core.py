from itertools import product
from random import Random
from django.test import SimpleTestCase
from planner.core import in_us, optimize

class OptimizerTests(SimpleTestCase):
    def brute(self, legs, prices, fuel, capacity=50):
        states = {fuel: 0}
        for i, leg in enumerate(legs):
            after = {}
            for amount, cost in states.items():
                remaining = amount - leg // 10
                if remaining < 0:
                    continue
                if i == len(prices):
                    after[remaining] = min(after.get(remaining, float('inf')), cost)
                else:
                    for buy in range(capacity - remaining + 1):
                        level = remaining + buy
                        after[level] = min(after.get(level, float('inf')), cost + buy * prices[i])
            states = after
        return min(states.values()) if states else None

    def test_matches_independent_integer_reference(self):
        for legs in product((0, 100, 300, 500), repeat=3):
            for prices in ((2, 3), (3, 2), (2, 2)):
                for start in (0, 10, 50):
                    expected = self.brute(legs, prices, start)
                    actual = optimize(list(legs), list(prices), start)
                    if expected is None:
                        self.assertIsNone(actual, (legs, prices, start))
                    else:
                        self.assertAlmostEqual(actual['purchase_cost_usd'], expected, msg=str((legs, prices, start)))

    def test_bounded_sequences_against_independent_fuel_state_oracle(self):
        random = Random(8675309)
        for case in range(128):
            stops = random.randrange(5)
            demands = [random.randrange(11) for _ in range(stops + 1)]
            cents = [random.randint(100, 500) for _ in range(stops)]
            start = random.randrange(9)
            states = {start: 0}
            for index, demand in enumerate(demands):
                arrivals = {}
                for fuel, cost in states.items():
                    if fuel >= demand:
                        level = fuel - demand
                        arrivals[level] = min(cost, arrivals.get(level, cost))
                if index < stops:
                    states = {}
                    for level, cost in arrivals.items():
                        for purchase in range(9 - level):
                            target = level + purchase
                            total = cost + purchase * cents[index]
                            states[target] = min(total, states.get(target, total))
                else:
                    states = arrivals
            legs = [demand * 62.5 for demand in demands]
            prices = [price / 100 for price in cents]
            result = optimize(legs, prices, start * 6.25)
            with self.subTest(case=case, demands=demands, cents=cents, start=start):
                if not states:
                    self.assertIsNone(result)
                    continue
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result['purchase_cost_usd'], min(states.values()) * 0.0625)
                fuel = start * 6.25
                low_points = [('start', fuel)]
                for index, demand in enumerate(demands):
                    fuel -= demand * 6.25
                    self.assertGreaterEqual(fuel, -1e-8)
                    low_points.append((f'stop_{index + 1}' if index < stops else 'arrival', fuel))
                    if index < stops:
                        purchase = result['purchases'][index]
                        self.assertAlmostEqual(purchase['fuel_before_gallons'], fuel)
                        self.assertGreaterEqual(purchase['gallons'], 0)
                        fuel += purchase['gallons']
                        self.assertLessEqual(fuel, 50 + 1e-8)
                        self.assertAlmostEqual(purchase['fuel_after_gallons'], fuel)
                        self.assertAlmostEqual(purchase['cost_usd'], purchase['gallons'] * prices[index])
                minimum = min(value for _, value in low_points)
                expected_low = [(point, value) for point, value in low_points if abs(value - minimum) < 1e-8]
                self.assertEqual([point['point'] for point in result['lowest_fuel_points']], [point for point, _ in expected_low])
                for actual, (_, expected) in zip(result['lowest_fuel_points'], expected_low):
                    self.assertAlmostEqual(actual['fuel_gallons'], expected)
                self.assertAlmostEqual(result['remaining_gallons'], fuel)
                self.assertAlmostEqual(result['purchased_gallons'], sum(p['gallons'] for p in result['purchases']))
                self.assertAlmostEqual(result['purchase_cost_usd'], sum(p['cost_usd'] for p in result['purchases']))
                self.assertAlmostEqual(result['consumed_gallons'], sum(legs) / 10)
                self.assertAlmostEqual(start * 6.25 + result['purchased_gallons'], fuel + result['consumed_gallons'])

    def test_unrounded_cost_metamorphic_relations(self):
        legs, prices = [0, 100, 100], [3, 2]
        base = optimize(legs, prices, 0)
        scaled = optimize(legs, [price * 4 for price in prices], 0)
        more_fuel = optimize(legs, prices, 5)
        extra_stop = optimize([0, 0, 100, 100], [3, 3, 2], 0)
        self.assertAlmostEqual(scaled['purchase_cost_usd'], 4 * base['purchase_cost_usd'])
        self.assertLessEqual(more_fuel['purchase_cost_usd'], base['purchase_cost_usd'])
        self.assertAlmostEqual(extra_stop['purchase_cost_usd'], base['purchase_cost_usd'])

    def test_invalid_fuel_sequences(self):
        cases = [
            ([-1], [], 0), ([float('nan')], [], 0), ([float('inf')], [], 0),
            ([0, 1], [0], 0), ([0, 1], [-1], 0),
            ([0, 1], [float('nan')], 0), ([0, 1], [float('inf')], 0),
            ([0, 1], [], 0), ([0], [3], 0),
            ([0], [], -0.01), ([0], [], 50.01),
        ]
        for legs, prices, fuel in cases:
            with self.subTest(legs=legs, prices=prices, fuel=fuel):
                with self.assertRaises(ValueError):
                    optimize(legs, prices, fuel)

    def test_partial_and_boundary(self):
        result = optimize([0, 500], [3], 0)
        self.assertEqual(result['purchased_gallons'], 50)
        self.assertEqual(result['remaining_gallons'], 0)
        self.assertIsNotNone(optimize([500], [], 50))
        self.assertIsNone(optimize([500.000001], [], 50))
        self.assertIsNone(optimize([501], [], 50))
        self.assertIsNone(optimize([20, 10], [3], 1))
        self.assertAlmostEqual(optimize([0, 12.5], [3], 0)['purchase_cost_usd'], 3.75)

    def test_polygon_and_hole(self):
        geo = {'type': 'Polygon', 'coordinates': [[[0,0],[5,0],[5,5],[0,5],[0,0]], [[1,1],[2,1],[2,2],[1,2],[1,1]]]}
        self.assertTrue(in_us([3,3], geo))
        self.assertFalse(in_us([1.5,1.5], geo))
        self.assertFalse(in_us([8,8], geo))

    def test_fractional_and_nonfinite(self):
        result = optimize([0, 7.5, 12.5], [4, 2], 0)
        self.assertAlmostEqual(result['purchase_cost_usd'], 5.5)
        for fuel in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                optimize([0], [], fuel)
        with self.assertRaises(ValueError):
            optimize([0, 1], [0], 0)

    def test_invalid_boundary(self):
        from planner.core import validate_boundary
        for geo in (None, {'type':'Feature','geometry':None}, {'type':'FeatureCollection','features':[{'type':'Feature','geometry':None}]}, {'type':'Polygon','coordinates':None}, {'type':'Polygon','coordinates':[[[0,0], [1,1]]] } ):
            with self.assertRaises(ValueError):
                validate_boundary(geo)

class BoundaryCacheTests(SimpleTestCase):
    def test_reuses_unchanged_file_and_reloads_changed_or_invalid_file(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from planner.core import _read_boundary, load_boundary, validate_boundary

        first = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        second = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 0]]]}
        _read_boundary.cache_clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'boundary.json'
            path.write_text(json.dumps(first))
            with patch('planner.core.validate_boundary', wraps=validate_boundary) as validate:
                self.assertEqual(load_boundary(path), first)
                self.assertEqual(load_boundary(path), first)
                self.assertEqual(validate.call_count, 1)
                path.write_text(json.dumps(second))
                self.assertEqual(load_boundary(path), second)
                self.assertEqual(validate.call_count, 2)
                path.write_text('{}')
                with self.assertRaises(ValueError):
                    load_boundary(path)
        _read_boundary.cache_clear()
