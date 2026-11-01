import math
from typing import NamedTuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from planner.core import MPG, SIMPLIFY_TOLERANCE, TANK, distance, in_us, key, optimize, load_boundary, simplify
from planner.models import City, RoutePlan, Station
from planner.locations import STATE_NAMES, strip_country
from planner.providers import census, route, route_settings, ProviderError, RouteCoverageError, AddressError

OPTIONS = {
    'tank': TANK,
    'mpg': MPG,
    'repair_limit': 1,
    'range_margins_miles': [25.0, 0.0],
    'comparison': 'cost-duration-distance-v1',
    'strategy': 'progress-cost-v12',
    'simplify_tolerance': SIMPLIFY_TOLERANCE,
    'response': 'start-fuel-cost-basis-v2',
}

def corridor_miles():
    value = settings.FUEL_CORRIDOR_MILES
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ProviderError('Fuel corridor must be positive and finite')
    return value


def planning_settings():
    return {**OPTIONS, 'corridor_miles': corridor_miles(), 'routing': route_settings()}

CITY_CANDIDATE_LIMIT = 20


class Candidate(NamedTuple):
    position: float
    detour: float
    station: Station

class InputError(Exception):
    def __init__(self, code, message, **details):
        self.code, self.message, self.details = code, message, details


def resolve_locations(values):
    result = [None, None]
    addresses, slots = [], []
    for index, value in enumerate(values):
        if isinstance(value, dict) and 'station_id' in value:
            stations = list(Station.objects.filter(source_id=str(value['station_id']), latitude__isnull=False, longitude__isnull=False))
            if len(stations) != 1:
                raise InputError('UNRESOLVABLE_LOCATION', 'Station ID must identify one verified station.')
            result[index] = [stations[0].latitude, stations[0].longitude]
        elif isinstance(value, dict) and set(value) == {'latitude', 'longitude'}:
            try:
                lat, lon = float(value['latitude']), float(value['longitude'])
                is_bool = isinstance(value['latitude'], bool) or isinstance(value['longitude'], bool)
                is_finite = math.isfinite(lat) and math.isfinite(lon)
                if is_bool or not is_finite or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ValueError()
                result[index] = [lat, lon]
            except (TypeError, ValueError, OverflowError):
                raise InputError('INVALID_LOCATION', 'Invalid coordinates.')
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            parts = strip_country([x.strip() for x in text.split(',')])
            cities = City.objects.filter(name__iexact=parts[0])
            state_code = STATE_NAMES.get(parts[1].upper(), parts[1].upper()) if len(parts) == 2 else ''
            if len(parts) == 2 and state_code in set(STATE_NAMES.values()):
                cities = cities.filter(state__iexact=state_code)
            elif len(parts) != 1:
                cities = City.objects.none()
            ordered = cities.order_by('name', 'state', 'latitude', 'longitude', 'pk')
            matches = list(ordered.values('name', 'state', 'latitude', 'longitude')[:CITY_CANDIDATE_LIMIT + 1])
            if len(matches) > 1:
                listed = [
                    {**match, 'location': {'latitude': match['latitude'], 'longitude': match['longitude']}}
                    for match in matches[:CITY_CANDIDATE_LIMIT]
                ]
                raise InputError(
                    'AMBIGUOUS_LOCATION',
                    'Retry with a candidate location; narrow by state if truncated.',
                    candidates=listed,
                    truncated=len(matches) > CITY_CANDIDATE_LIMIT,
                )
            if matches:
                result[index] = [matches[0]['latitude'], matches[0]['longitude']]
            elif len(parts) == 1 or (len(parts) == 2 and state_code in set(STATE_NAMES.values()) and not any(c.isdigit() for c in parts[0])):
                raise InputError('UNRESOLVABLE_LOCATION', 'City was not found in the local gazetteer.')
            else:
                addresses.append(text)
                slots.append(index)
        else:
            raise InputError('INVALID_LOCATION', 'Use coordinates, a city, a street address, or a station ID.')
    if addresses:
        try:
            resolved = census(addresses)
        except AddressError as exc:
            raise InputError('INVALID_LOCATION', str(exc)) from exc
        for slot, point in zip(slots, resolved):
            if point is None:
                raise InputError('UNRESOLVABLE_LOCATION', 'Street address was not matched by Census.')
            result[slot] = point
    try:
        boundary = load_boundary(Path(settings.BASE_DIR) / 'data/us_boundary.geojson')
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProviderError('US boundary dataset is unavailable or invalid') from exc
    if not all(in_us(point, boundary) for point in result):
        raise InputError('OUTSIDE_USA', 'Both locations must be inside the USA.')
    return result


def station_data(s):
    return {
        'station_id': s.source_id,
        'name': s.name,
        'address': s.address,
        'city': s.city,
        'state': s.state,
        'latitude': s.latitude,
        'longitude': s.longitude,
        'price_usd_per_gallon': round(s.price, 6),
        'price_min': round(s.price_min, 6),
        'price_max': round(s.price_max, 6),
        'source_row_count': len(s.rows),
        'evidence': s.evidence,
    }


def nearby(road, stations):
    corridor = corridor_miles()
    coords = road['geometry']['coordinates']
    if len(coords) < 2:
        return []
    segments = []
    length = 0
    for a, b in zip(coords, coords[1:]):
        miles = distance([a[1], a[0]], [b[1], b[0]])
        start_lon = (a[0] + 180) % 360 - 180
        end_lon = start_lon + (b[0] - a[0] + 180) % 360 - 180
        segments.append(([start_lon, a[1]], [end_lon, b[1]], length, miles))
        length += miles
    # Segment grid limits precise projection work to nearby cells.
    grid = {}
    cell = 0.25
    for i, (a, b, _, _) in enumerate(segments):
        lo_x, hi_x = sorted((a[0], b[0])); lo_y, hi_y = sorted((a[1], b[1]))
        for x in range(math.floor(lo_x/cell), math.floor(hi_x/cell)+1):
            for y in range(math.floor(lo_y/cell), math.floor(hi_y/cell)+1):
                grid.setdefault((x, y), []).append(i)
    candidates = []
    for station in stations:
        latitude_delta = min(180.0, math.degrees(corridor / 3958.7613))
        extreme_latitude = min(90.0, abs(station.latitude) + latitude_delta)
        longitude_delta = 180.0 if extreme_latitude >= 90 else min(180.0, latitude_delta / math.cos(math.radians(extreme_latitude)))
        windows = [
            (
                math.floor((station.longitude + shift - longitude_delta) / cell),
                math.floor((station.longitude + shift + longitude_delta) / cell),
            )
            for shift in (-360, 0, 360)
        ]
        y0 = math.floor((station.latitude - latitude_delta) / cell)
        y1 = math.floor((station.latitude + latitude_delta) / cell)
        window_size = sum(x1 - x0 + 1 for x0, x1 in windows) * (y1 - y0 + 1)
        if window_size > len(grid):
            cells = (key for key in grid if y0 <= key[1] <= y1 and any(x0 <= key[0] <= x1 for x0, x1 in windows))
        else:
            cells = ((x, y) for x0, x1 in windows for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
        indices = {index for key in cells for index in grid.get(key, ())}
        best = None
        for i in indices:
            a, b, offset, miles = segments[i]
            scale = math.cos(math.radians(station.latitude))
            dx, dy = (b[0]-a[0])*scale, b[1]-a[1]
            denom = dx*dx + dy*dy
            station_lon = a[0] + (station.longitude - a[0] + 180) % 360 - 180
            t = max(0, min(1, (((station_lon-a[0])*scale)*dx + (station.latitude-a[1])*dy)/denom)) if denom else 0
            point = [a[1]+t*(b[1]-a[1]), a[0]+t*(b[0]-a[0])]
            detour = distance([station.latitude, station.longitude], point)
            if best is None or detour < best[0]:
                best = (detour, offset+t*miles)
        if best and best[0] <= corridor:
            position = (best[1]/length * road['distance_miles']) if length else 0
            candidates.append(Candidate(position, best[0], station))
    candidates.sort(key=lambda item: (item.position, item.station.source_id))
    return candidates


def is_origin(station, start, fuel):
    if fuel == 0:
        return (station.latitude, station.longitude) == tuple(start)
    return distance(start, [station.latitude, station.longitude]) < 1e-6


def proposal_inputs(road, stations, start, fuel, candidates_for=None):
    corridor_miles()
    if road['distance_miles'] <= fuel * MPG + 1e-7:
        return None
    candidates = candidates_for(road) if candidates_for else nearby(road, stations)
    origins = [station for station in stations if is_origin(station, start, fuel)]
    return candidates, origins


def cost_proposal(road, candidates, origins, start, fuel, excluded, margin=0.0):
    origin_ids = {station.pk for station in origins}
    candidates = [
        candidate for candidate in candidates
        if candidate.station.pk not in origin_ids and candidate.station.pk not in excluded
    ]
    if origins:
        station = min(origins, key=lambda item: (item.price, item.source_id))
        candidates.append(Candidate(0.0, 0.0, station))
    candidates.sort(key=lambda item: (item.position, item.station.source_id))
    points = [(0.0, 0.0)] + [(item.position, item.detour) for item in candidates] + [(road['distance_miles'], 0.0)]
    weight = 1.0 if margin else 0.0
    legs = [max(0.0, b[0] - a[0]) + weight * (a[1] + b[1]) for a, b in zip(points, points[1:])]
    result = optimize(legs, [item.station.price for item in candidates], max(0.0, fuel - margin / MPG), (TANK * MPG - margin) / MPG)
    if result is None:
        return None
    chosen = [
        item.station for item, purchase in zip(candidates, result['purchases'])
        if purchase['gallons'] > 1e-8
    ]
    if fuel == 0 and (not chosen or (chosen[0].latitude, chosen[0].longitude) != tuple(start)):
        return None
    return chosen


def progress_proposal(road, candidates, origins, start, fuel, excluded, prefix, reach, margin=0.0):
    slack_per_stop = 0.0 if margin else 2 * corridor_miles()
    included = {candidate.station.pk for candidate in candidates}
    candidates = [
        *candidates,
        *(Candidate(0.0, 0.0, station) for station in origins if station.pk not in included),
    ]
    positions = {candidate.station.pk: candidate.position for candidate in candidates}
    detours = {candidate.station.pk: candidate.detour if margin else 0.0 for candidate in candidates}
    chosen = list(prefix)
    if any(station.pk not in positions for station in chosen):
        return None
    position = positions[chosen[-1].pk] if chosen else 0.0
    here = detours[chosen[-1].pk] if chosen else 0.0
    available = TANK * MPG if chosen else fuel * MPG
    slack = slack_per_stop
    forced = reach is not None
    if forced:
        available, slack = max(0.0, reach), 0.0
    for _ in range(30):
        if not forced and road['distance_miles'] - position + here <= available - margin + 1e-7:
            return chosen
        forced = False

        def reachable_from_here(candidate):
            station = candidate.station
            if station.pk in excluded:
                return False
            at_origin = not chosen and distance(start, [station.latitude, station.longitude]) < 1e-6
            if not (candidate.position > position + 0.01 or at_origin):
                return False
            if candidate.position - position + here + detours[station.pk] > available - margin + slack + 1e-7:
                return False
            return not chosen or station.pk != chosen[-1].pk

        reachable = [candidate for candidate in candidates if reachable_from_here(candidate)]
        if not chosen and fuel == 0:
            reachable = [
                candidate for candidate in reachable
                if (candidate.station.latitude, candidate.station.longitude) == tuple(start)
            ]
        if not reachable:
            return None
        furthest = max(candidate.position for candidate in reachable)
        shortlist = [candidate for candidate in reachable if candidate.position >= furthest - 25]
        pick = max(shortlist, key=lambda c: (c.position, -c.station.price, c.station.source_id))
        chosen.append(pick.station)
        position = pick.position
        here = detours[pick.station.pk]
        available = TANK * MPG
        slack = slack_per_stop
    return None


def proposal(road, stations, start, fuel, excluded=frozenset(), mode='progress', prefix=(), reach=None, candidates_for=None):
    inputs = proposal_inputs(road, stations, start, fuel, candidates_for)
    if inputs is None:
        return []
    candidates, origins = inputs
    for margin in OPTIONS['range_margins_miles']:
        if mode == 'cost':
            stops = cost_proposal(road, candidates, origins, start, fuel, excluded, margin)
        else:
            stops = progress_proposal(road, candidates, origins, start, fuel, excluded, prefix, reach, margin)
        if stops is not None:
            return stops
    return None


def unavailable(road, reason):
    return {
        'verified': False,
        'reason': reason,
        'road': road,
        'consumed_gallons': road['distance_miles'] / MPG,
        'purchased_gallons': None,
        'purchase_cost_usd': None,
        'remaining_gallons': None,
    }


def evaluate(road, stops, fuel):
    prices = [s.price for s in stops]
    result = optimize(road['legs_miles'], prices, fuel)
    if result is None:
        return None
    purchases = result.pop('purchases')
    result['stops'] = []
    total = Decimal('0.00')
    cumulative = 0
    for i, (station, purchase) in enumerate(zip(stops, purchases)):
        cumulative += road['legs_miles'][i]
        charge = (Decimal(str(purchase['gallons'])) * Decimal(str(station.price))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total += charge
        result['stops'].append({
            **station_data(station),
            **purchase,
            'purchase': purchase['gallons'] > 0,
            'waypoint_index': i + 1,
            'cost_usd': float(charge),
            'route_position_miles': cumulative,
        })
    for point in result['lowest_fuel_points']:
        if point['point'].startswith('stop_'):
            index = int(point['point'].removeprefix('stop_'))
            point.update(station_id=stops[index - 1].source_id, waypoint_index=index)
    result['_cost'] = total
    result['purchase_cost_usd'] = float(total)
    return {'verified': True, 'road': road, **result}


def estimated_cost(road, stops, stations, fuel, start, candidates_for=None):
    positions = {station.pk: 0.0 for station in stops if distance(start, [station.latitude, station.longitude]) < 1e-6}
    if any(station.pk not in positions for station in stops):
        candidates = candidates_for(road) if candidates_for else nearby(road, stations)
        positions = {**{candidate.station.pk: candidate.position for candidate in candidates}, **positions}
    if any(station.pk not in positions for station in stops):
        return float('inf')
    points = [0] + [positions[station.pk] for station in stops] + [road['distance_miles']]
    legs = [max(0, b-a) for a, b in zip(points, points[1:])]
    estimated = optimize(legs, [s.price for s in stops], fuel)
    return estimated['purchase_cost_usd'] if estimated else float('inf')


def failed_leg(road, stops, fuel):
    legs = road['legs_miles']
    if len(legs) != len(stops) + 1:
        return None
    limits = [fuel * MPG] + [TANK * MPG] * len(stops)
    return next(((i, leg - limit, limit) for i, (leg, limit) in enumerate(zip(legs, limits)) if leg > limit + 1e-7), None)


def geometry_id(geometry):
    return key(geometry['coordinates'])[:12]


def shaper(geometries):
    def shape(road):
        gid = geometry_id(road['geometry'])
        geometries.setdefault(gid, {'type': 'LineString', 'coordinates': simplify(road['geometry']['coordinates'])})
        return {**{k: v for k, v in road.items() if k != 'geometry'}, 'geometry_id': gid}
    return shape


def compact(result, recommended):
    geometries = {}
    shape = shaper(geometries)
    def candidate(item):
        return {**item, 'road': shape(item['road'])}
    baseline = candidate(result['baseline'])
    alternatives = [candidate(item) for item in result['alternatives']]
    pairs = list(zip([result['baseline'], *result['alternatives']], [baseline, *alternatives]))
    return {
        **result,
        'baseline_original_road': shape(result['baseline_original_road']),
        'baseline': baseline,
        'alternatives': alternatives,
        'recommended': next((new for old, new in pairs if old is recommended), None),
        'geometries': geometries,
    }


def normalize_legacy(result):
    if 'geometries' in result:
        return result
    geometries = {}
    shape = shaper(geometries)
    def candidate(item):
        has_geometry = isinstance(item, dict) and isinstance(item.get('road'), dict) and 'geometry' in item['road']
        return {**item, 'road': shape(item['road'])} if has_geometry else item
    original = result.get('baseline_original_road')
    return {
        **result,
        'baseline_original_road': shape(result['baseline_original_road']) if 'geometry' in result.get('baseline_original_road', {}) else original,
        'baseline': candidate(result.get('baseline')),
        'alternatives': [candidate(item) for item in result.get('alternatives', [])],
        'recommended': candidate(result.get('recommended')),
        'geometries': geometries,
    }


def flat_fields(compacted):
    recommended = compacted['recommended']
    keys = ('station_id', 'name', 'address', 'city', 'state', 'latitude', 'longitude', 'price_usd_per_gallon', 'gallons', 'cost_usd', 'route_position_miles', 'waypoint_index')
    road = (recommended or compacted['baseline'])['road']
    return {
        'distance_miles': road.get('distance_miles'),
        'purchase_cost_usd': recommended['purchase_cost_usd'] if recommended else None,
        'fuel_stops': [{k: stop[k] for k in keys} for stop in recommended['stops'] if stop['purchase']] if recommended else None,
    }


def plan(start, finish, fuel, stations):
    roads = sorted(route([start, finish], alternatives=True), key=lambda r: (r['duration_seconds'], r['distance_miles']))[:3]
    baseline_road = roads[0]
    road_candidates = {}

    def candidates_for(road):
        if id(road) not in road_candidates:
            road_candidates[id(road)] = nearby(road, stations)
        return road_candidates[id(road)]

    attempts = 0

    def verify(road, stops):
        nonlocal attempts
        if stops is None:
            return unavailable(road, 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE')
        if not stops:
            return evaluate(road, [], fuel) or unavailable(road, 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE')
        attempts += 1
        try:
            actual = route([start] + [[s.latitude, s.longitude] for s in stops] + [finish])[0]
        except RouteCoverageError:
            return unavailable(road, 'ROUTING_COVERAGE_UNAVAILABLE')
        except ProviderError:
            return unavailable(road, 'VERIFICATION_PROVIDER_FAILURE')
        return evaluate(actual, stops, fuel) or unavailable(actual, 'VERIFICATION_FAILED_OR_INSUFFICIENT_VERIFIED_PRICE_COVERAGE')

    choices, seen = [], set()
    for index, road in enumerate(roads):
        for mode in ('cost', 'progress'):
            stops = proposal(road, stations, start, fuel, mode=mode, candidates_for=candidates_for)
            sequence = None if stops is None else (index, tuple(s.pk for s in stops))
            if stops is None or sequence in seen:
                continue
            seen.add(sequence)
            cost = estimated_cost(road, stops, stations, fuel, start, candidates_for=candidates_for)
            choices.append((cost, road['duration_seconds'], index, mode, road, stops))
    choices.sort(key=lambda c: c[:4])
    entries, tried, skipped = [], set(), None
    for _, _, index, _, road, stops in choices:
        verified = [(i, outcome) for i, outcome in entries if outcome['verified']]
        if any(outcome['_cost'] == 0 for _, outcome in verified):
            break
        if verified and not any(i == 0 for i, _ in verified) and index != 0:
            continue
        if any(outcome.get('reason') == 'VERIFICATION_PROVIDER_FAILURE' for _, outcome in entries):
            break
        sequence = tuple(s.pk for s in stops)
        if sequence and sequence in tried:
            continue
        if sequence and attempts >= 2:
            skipped = road
            break
        tried.add(sequence)
        outcome = verify(road, stops)
        failure = (
            failed_leg(outcome['road'], stops, fuel)
            if not outcome['verified'] and stops and attempts < 2
            and outcome.get('reason') == 'VERIFICATION_FAILED_OR_INSUFFICIENT_VERIFIED_PRICE_COVERAGE'
            else None
        )
        if failure:
            leg, excess, limit = failure
            repair = proposal(
                road, stations, start, fuel,
                excluded={stops[leg].pk} if leg < len(stops) else set(), prefix=stops[:leg], reach=limit - excess,
                candidates_for=candidates_for,
            )
            repair_sequence = tuple(s.pk for s in repair) if repair else ()
            if repair and repair_sequence not in tried:
                tried.add(repair_sequence)
                outcome = verify(road, repair)
        entries.append((index, outcome))
    road_zero = [position for position, (index, _) in enumerate(entries) if index == 0]
    first = next((position for position in road_zero if entries[position][1]['verified']), road_zero[0] if road_zero else None)
    if first is not None:
        baseline = entries[first][1]
    elif not any(index == 0 for _, _, index, _, _, _ in choices):
        baseline = unavailable(baseline_road, 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE')
    elif any(outcome.get('reason') == 'VERIFICATION_PROVIDER_FAILURE' for _, outcome in entries):
        baseline = unavailable(baseline_road, 'VERIFICATION_PROVIDER_FAILURE')
    else:
        baseline = unavailable(baseline_road, 'VERIFICATION_BUDGET_EXHAUSTED')
    alternatives = [outcome for position, (_, outcome) in enumerate(entries) if position != first]
    if skipped is not None and not any(outcome['verified'] for outcome in alternatives + [baseline]) and baseline['reason'] != 'VERIFICATION_BUDGET_EXHAUSTED':
        alternatives.append(unavailable(skipped, 'VERIFICATION_BUDGET_EXHAUSTED'))
    results = [baseline, *alternatives]
    feasible = [r for r in results if r['verified']]
    recommended = min(feasible, key=lambda r: (r['_cost'], r['road']['duration_seconds'], r['road']['distance_miles'])) if feasible else None
    alternative_verified = any(r['verified'] for r in alternatives)
    if baseline['verified'] and alternative_verified:
        comparison_status = 'compared'
    elif baseline['verified']:
        comparison_status = 'alternative_unavailable'
    else:
        comparison_status = 'baseline_unavailable'
    comparison = {
        'status': comparison_status,
        'savings_usd': None,
        'extra_miles': None,
        'extra_duration_seconds': None,
    }
    if baseline['verified'] and alternative_verified and recommended:
        comparison.update(
            savings_usd=float(baseline['_cost'] - recommended['_cost']),
            extra_miles=recommended['road']['distance_miles'] - baseline['road']['distance_miles'],
            extra_duration_seconds=recommended['road']['duration_seconds'] - baseline['road']['duration_seconds'],
        )
    for candidate in feasible:
        candidate.pop('_cost')
    provider_failed = any(r.get('reason') == 'VERIFICATION_PROVIDER_FAILURE' for r in results)
    routing_unavailable = any(r.get('reason') == 'ROUTING_COVERAGE_UNAVAILABLE' for r in results)
    if recommended:
        status = 'ok'
    elif provider_failed:
        status = 'PROVIDER_FAILURE'
    elif routing_unavailable:
        status = 'ROUTING_COVERAGE_UNAVAILABLE'
    else:
        status = 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE'
    reasons = list(dict.fromkeys(candidate['reason'] for candidate in results if not candidate['verified'] and candidate.get('reason')))
    messages = {
        'ROUTING_COVERAGE_UNAVAILABLE': 'No drivable route found in loaded road data',
        'INSUFFICIENT_VERIFIED_PRICE_COVERAGE': 'No feasible fuel plan found within verified station data and search bounds.',
        'PROVIDER_FAILURE': 'Route verification provider unavailable.',
    }
    compacted = compact({
        'status': status,
        'code': status if status != 'ok' else None,
        'reasons': reasons,
        'message': messages.get(status),
        'baseline_original_road': baseline_road,
        'baseline': baseline,
        'alternatives': alternatives,
        'comparison': comparison,
        'start_fuel_gallons': fuel,
        'cost_basis': 'Fuel purchased during the journey. Starting fuel is valued at $0.',
    }, recommended)
    return {**compacted, **flat_fields(compacted)}
