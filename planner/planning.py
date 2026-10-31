import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from planner.core import MPG, SIMPLIFY_TOLERANCE, TANK, distance, in_us, key, optimize, load_boundary, simplify
from planner.models import City, RoutePlan, Station
from planner.locations import STATE_NAMES
from planner.providers import census, route, route_settings, ProviderError, RouteCoverageError, AddressError

OPTIONS = {'tank': TANK, 'mpg': MPG, 'candidate_limit': 150, 'repair_limit': 1, 'comparison': 'cost-duration-distance-v1', 'strategy': 'progress-cost-v8', 'simplify_tolerance': SIMPLIFY_TOLERANCE}

def corridor_miles():
    value = settings.FUEL_CORRIDOR_MILES
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ProviderError('Fuel corridor must be positive and finite')
    return value


def planning_settings():
    return {**OPTIONS, 'corridor_miles': corridor_miles(), 'routing': route_settings()}

CITY_CANDIDATE_LIMIT = 20

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
                if isinstance(value['latitude'], bool) or isinstance(value['longitude'], bool) or not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ValueError()
                result[index] = [lat, lon]
            except (TypeError, ValueError):
                raise InputError('INVALID_LOCATION', 'Invalid coordinates.')
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            parts = [x.strip() for x in text.split(',')]
            cities = City.objects.filter(name__iexact=parts[0])
            state_code = STATE_NAMES.get(parts[1].upper(), parts[1].upper()) if len(parts) == 2 else ''
            if len(parts) == 2 and state_code in set(STATE_NAMES.values()):
                cities = cities.filter(state__iexact=state_code)
            elif len(parts) != 1:
                cities = City.objects.none()
            matches = list(cities.order_by('name', 'state', 'latitude', 'longitude', 'pk').values('name', 'state', 'latitude', 'longitude')[:CITY_CANDIDATE_LIMIT + 1])
            if len(matches) > 1:
                raise InputError('AMBIGUOUS_LOCATION', 'Retry with a candidate location; narrow by state if truncated.', candidates=[{**match, 'location': {'latitude': match['latitude'], 'longitude': match['longitude']}} for match in matches[:CITY_CANDIDATE_LIMIT]], truncated=len(matches) > CITY_CANDIDATE_LIMIT)
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
    return {'station_id': s.source_id, 'name': s.name, 'address': s.address, 'city': s.city, 'state': s.state, 'latitude': s.latitude, 'longitude': s.longitude, 'price_usd_per_gallon': round(s.price, 6), 'price_min': round(s.price_min, 6), 'price_max': round(s.price_max, 6), 'source_row_count': len(s.rows), 'evidence': s.evidence}


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
        windows = [(math.floor((station.longitude + shift - longitude_delta) / cell), math.floor((station.longitude + shift + longitude_delta) / cell)) for shift in (-360, 0, 360)]
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
            candidates.append((position, best[0], station))
    candidates.sort(key=lambda item: (item[0], item[2].source_id))
    limit = OPTIONS['candidate_limit']
    if len(candidates) <= limit:
        return candidates
    buckets = {}
    width = max(road['distance_miles'] / (limit // 2), 0.001)
    for candidate in candidates:
        bucket = min(limit // 2 - 1, int(candidate[0] / width))
        buckets.setdefault(bucket, []).append(candidate)
    selected = []
    for group in buckets.values():
        selected.append(min(group, key=lambda c: (c[2].price, c[0], c[2].source_id)))
        furthest = max(group, key=lambda c: (c[0], c[2].source_id))
        if furthest != selected[-1]:
            selected.append(furthest)
    return sorted(selected, key=lambda c: (c[0], c[2].source_id))


def proposal(road, stations, start, fuel, excluded=frozenset(), mode='progress', prefix=(), reach=None):
    corridor = corridor_miles()
    if road['distance_miles'] <= fuel * MPG + 1e-7:
        return []
    candidates = nearby(road, stations)
    origins = [station for station in stations if ((station.latitude, station.longitude) == tuple(start) if fuel == 0 else distance(start, [station.latitude, station.longitude]) < 1e-6)]
    if mode == 'cost':
        origin_ids = {station.pk for station in origins}
        candidates = [candidate for candidate in candidates if candidate[2].pk not in origin_ids and candidate[2].pk not in excluded]
        if origins:
            station = min(origins, key=lambda item: (item.price, item.source_id))
            candidates.append((0.0, 0.0, station))
        candidates.sort(key=lambda item: (item[0], item[2].source_id))
        positions = [0.0] + [item[0] for item in candidates] + [road['distance_miles']]
        legs = [max(0.0, b - a) for a, b in zip(positions, positions[1:])]
        result = optimize(legs, [item[2].price for item in candidates], fuel)
        if result is None:
            return None
        chosen = [item[2] for item, purchase in zip(candidates, result['purchases']) if purchase['gallons'] > 1e-8]
        if fuel == 0 and (not chosen or (chosen[0].latitude, chosen[0].longitude) != tuple(start)):
            return None
        return chosen
    included = {candidate[2].pk for candidate in candidates}
    candidates.extend((0.0, 0.0, station) for station in origins if station.pk not in included)
    positions = {c[2].pk: c[0] for c in candidates}
    chosen = list(prefix)
    if any(station.pk not in positions for station in chosen):
        return None
    position = positions[chosen[-1].pk] if chosen else 0.0
    available = TANK * MPG if chosen else fuel * MPG
    slack = 2 * corridor
    forced = reach is not None
    if forced:
        available, slack = max(0.0, reach), 0.0
    for _ in range(30):
        if not forced and road['distance_miles'] - position <= available + 1e-7:
            return chosen
        forced = False
        reachable = [c for c in candidates if c[2].pk not in excluded and (c[0] > position + 0.01 or (not chosen and distance(start, [c[2].latitude, c[2].longitude]) < 1e-6)) and c[0] - position <= available + slack + 1e-7 and (not chosen or c[2].pk != chosen[-1].pk)]
        if not chosen and fuel == 0:
            reachable = [c for c in reachable if (c[2].latitude, c[2].longitude) == tuple(start)]
        if not reachable:
            return None
        furthest = max(c[0] for c in reachable)
        shortlist = [c for c in reachable if c[0] >= furthest - 25]
        pick = max(shortlist, key=lambda c: (c[0], -c[2].price, c[2].source_id))
        chosen.append(pick[2]); position = pick[0]; available = TANK * MPG; slack = 2 * corridor
    return None


def unavailable(road, reason):
    return {'verified': False, 'reason': reason, 'road': road, 'consumed_gallons': road['distance_miles'] / MPG, 'purchased_gallons': None, 'purchase_cost_usd': None, 'remaining_gallons': None}


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
        result['stops'].append({**station_data(station), **purchase, 'purchase': purchase['gallons'] > 0, 'waypoint_index': i + 1, 'cost_usd': float(charge), 'route_position_miles': cumulative})
    for point in result['lowest_fuel_points']:
        if point['point'].startswith('stop_'):
            index = int(point['point'].removeprefix('stop_'))
            point.update(station_id=stops[index - 1].source_id, waypoint_index=index)
    result['_cost'] = total
    result['purchase_cost_usd'] = float(total)
    return {'verified': True, 'road': road, **result}


def estimated_cost(road, stops, stations, fuel, start):
    positions = {station.pk: pos for pos, _, station in nearby(road, stations)}
    positions.update({station.pk: 0.0 for station in stops if distance(start, [station.latitude, station.longitude]) < 1e-6})
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
    return {**result, 'baseline_original_road': shape(result['baseline_original_road']), 'baseline': baseline, 'alternatives': alternatives, 'recommended': next((new for old, new in pairs if old is recommended), None), 'geometries': geometries}


def normalize_legacy(result):
    if 'geometries' in result:
        return result
    geometries = {}
    shape = shaper(geometries)
    def candidate(item):
        return {**item, 'road': shape(item['road'])} if isinstance(item, dict) and isinstance(item.get('road'), dict) and 'geometry' in item['road'] else item
    return {**result, 'baseline_original_road': shape(result['baseline_original_road']) if 'geometry' in result.get('baseline_original_road', {}) else result.get('baseline_original_road'), 'baseline': candidate(result.get('baseline')), 'alternatives': [candidate(item) for item in result.get('alternatives', [])], 'recommended': candidate(result.get('recommended')), 'geometries': geometries}


def plan(start, finish, fuel, stations):
    roads = sorted(route([start, finish], alternatives=True), key=lambda r: (r['duration_seconds'], r['distance_miles']))[:3]
    baseline_road = roads[0]
    baseline_stops = proposal(baseline_road, stations, start, fuel)
    attempts = 0

    def verify(road, stops):
        nonlocal attempts
        if stops is None:
            return unavailable(road, 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE')
        if not stops:
            return evaluate(road, [], fuel) or unavailable(road, 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE')
        if attempts >= 2:
            return unavailable(road, 'VERIFICATION_BUDGET_EXHAUSTED')
        attempts += 1
        try:
            actual = route([start] + [[s.latitude, s.longitude] for s in stops] + [finish])[0]
        except RouteCoverageError:
            return unavailable(road, 'ROUTING_COVERAGE_UNAVAILABLE')
        except ProviderError:
            return unavailable(road, 'VERIFICATION_PROVIDER_FAILURE')
        return evaluate(actual, stops, fuel) or unavailable(actual, 'VERIFICATION_FAILED_OR_INSUFFICIENT_VERIFIED_PRICE_COVERAGE')

    baseline = verify(baseline_road, baseline_stops)
    failure = failed_leg(baseline['road'], baseline_stops, fuel) if not baseline['verified'] and baseline_stops and attempts < 2 and baseline.get('reason') == 'VERIFICATION_FAILED_OR_INSUFFICIENT_VERIFIED_PRICE_COVERAGE' else None
    if failure:
        index, excess, limit = failure
        excluded = {baseline_stops[index].pk} if index < len(baseline_stops) else set()
        repair = proposal(baseline_road, stations, start, fuel, excluded=excluded, prefix=baseline_stops[:index], reach=limit - excess)
        if repair is not None and repair != baseline_stops:
            baseline = verify(baseline_road, repair)

    choices = []
    for index, road in enumerate(roads):
        modes = ('cost',) if index == 0 else ('progress', 'cost')
        for mode in modes:
            stops = proposal(road, stations, start, fuel, mode=mode)
            if stops is None or (index == 0 and stops == baseline_stops):
                continue
            choices.append((estimated_cost(road, stops, stations, fuel, start), index, mode, road, stops))
    choices.sort(key=lambda c: (c[0], c[3]['duration_seconds'], c[1], c[2]))
    alternatives = [verify(choices[0][3], choices[0][4])] if choices else []
    results = [baseline, *alternatives]
    feasible = [r for r in results if r['verified']]
    recommended = min(feasible, key=lambda r: (r['_cost'], r['road']['duration_seconds'], r['road']['distance_miles'])) if feasible else None
    comparison = {'status': 'compared' if baseline['verified'] and any(r['verified'] for r in alternatives) else 'alternative_unavailable' if baseline['verified'] else 'baseline_unavailable', 'savings_usd': None, 'extra_miles': None, 'extra_duration_seconds': None}
    if baseline['verified'] and any(r['verified'] for r in alternatives) and recommended:
        comparison.update(savings_usd=float(baseline['_cost']-recommended['_cost']), extra_miles=recommended['road']['distance_miles']-baseline['road']['distance_miles'], extra_duration_seconds=recommended['road']['duration_seconds']-baseline['road']['duration_seconds'])
    for candidate in feasible:
        candidate.pop('_cost')
    provider_failed = any(r.get('reason') == 'VERIFICATION_PROVIDER_FAILURE' for r in results)
    routing_unavailable = any(r.get('reason') == 'ROUTING_COVERAGE_UNAVAILABLE' for r in results)
    status = 'ok' if recommended else 'PROVIDER_FAILURE' if provider_failed else 'ROUTING_COVERAGE_UNAVAILABLE' if routing_unavailable else 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE'
    reasons = list(dict.fromkeys(candidate['reason'] for candidate in results if not candidate['verified'] and candidate.get('reason')))
    messages = {'ROUTING_COVERAGE_UNAVAILABLE': 'No drivable route found in loaded road data', 'INSUFFICIENT_VERIFIED_PRICE_COVERAGE': 'No feasible fuel plan found within verified station data and search bounds.', 'PROVIDER_FAILURE': 'Route verification provider unavailable.'}
    return compact({'status': status, 'code': status if status != 'ok' else None, 'reasons': reasons, 'message': messages.get(status), 'baseline_original_road': baseline_road, 'baseline': baseline, 'alternatives': alternatives, 'comparison': comparison}, recommended)
