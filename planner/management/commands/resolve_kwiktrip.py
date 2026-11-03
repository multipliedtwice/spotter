import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import distance as distance_miles, load_boundary
from planner.evidence import COLUMNS
from planner.kwiktrip_evidence import SOURCE, valid_operator_record
from planner.operator_evidence import operator_display, operator_store_key, ta_branch_key
from planner.models import Station
from planner.osm_evidence import JUNCTION_LINK_ROADS, JUNCTION_MAIN_ROADS, canonical_source_name, refs, valid_point
from planner.operator_roads import nearby_road_refs, whole_source_routes
from planner.roadranger_evidence import roadranger_address_key
from planner.shared_operator_approval import approved_shared_operator, load_shared_operator_approvals


def nearby_junctions(grid, point, max_distance=5):
    cell = (math.floor(point[0] * 10), math.floor(point[1] * 10))
    lat_cells = math.ceil(max_distance * 10 / 68) + 1
    lon_cells = math.ceil(max_distance * 10 / (68 * max(0.01, abs(math.cos(math.radians(point[0])))))) + 1
    return (junction for dy in range(-lat_cells, lat_cells + 1) for dx in range(-lon_cells, lon_cells + 1) for junction in grid.get((cell[0] + dy, cell[1] + dx), ()) if distance_miles(point, junction['point']) <= max_distance)


def supporting_roads(station, point, state_boundary, ways):
    required = whole_source_routes(station.address)
    if not required:
        return []
    pending = set(required)
    chosen = []
    for way in ways:
        present = nearby_road_refs(way, point, station.state, state_boundary)
        if pending & present:
            chosen.append((way, present))
            pending -= present
            if not pending:
                break
    if pending:
        return []
    for item in chosen[:]:
        other = set().union(*(refs_found for candidate, refs_found in chosen if candidate is not item[0]))
        if required <= other:
            chosen.remove(item)
    return [way for way, _ in chosen]


def read_junctions(path):
    try:
        import osmium
    except ImportError as exc:
        raise CommandError('Install optional osmium package to read a local PBF.') from exc
    junctions, roads, ramps = {}, [], []
    ways_started = False
    try:
        pool = osmium.io.ThreadPool(1, 2)
        for obj in osmium.FileProcessor(str(path), thread_pool=pool):
            tags = {tag.k: tag.v for tag in obj.tags}
            if obj.is_node():
                if ways_started:
                    raise CommandError('OSM extract must place nodes before ways.')
                if tags.get('highway') == 'motorway_junction' and obj.location.valid():
                    junctions[obj.id] = {'id': obj.id, 'point': [obj.location.lat, obj.location.lon], 'ref': tags.get('ref', ''), 'old_ref': tags.get('old_ref', ''), 'highway': 'motorway_junction', 'url': f'https://www.openstreetmap.org/node/{obj.id}'}
            elif obj.is_way():
                ways_started = True
                kind = tags.get('highway')
                if kind not in JUNCTION_MAIN_ROADS | JUNCTION_LINK_ROADS:
                    continue
                nodes = [node.ref for node in obj.nodes]
                if not any(node in junctions for node in nodes):
                    continue
                base = {'id': obj.id, 'highway': kind, 'nodes': nodes, 'url': f'https://www.openstreetmap.org/way/{obj.id}'}
                if kind in JUNCTION_MAIN_ROADS and tags.get('ref'):
                    roads.append({**base, 'ref': tags['ref']})
                elif kind in JUNCTION_LINK_ROADS and tags.get('destination:ref'):
                    ramps.append({**base, 'destination:ref': tags['destination:ref']})
    except (OSError, RuntimeError) as exc:
        raise CommandError('Could not read OSM extract.') from exc
    ramps_by_node = defaultdict(list)
    for ramp in ramps:
        for node in ramp['nodes']:
            if node in junctions:
                ramps_by_node[node].append(ramp)
    grid = defaultdict(list)
    for road in roads:
        for node in road['nodes']:
            if node in junctions:
                junction = {**junctions[node], 'road': road, 'ramps': ramps_by_node[node]}
                lat, lon = junction['point']
                grid[(math.floor(lat * 10), math.floor(lon * 10))].append(junction)
    return grid


class Command(BaseCommand):
    help = 'Resolve Kwik Trip and Kwik Star stations from a local operator asset.'
    source_url = SOURCE
    namespaces = {'KWIK TRIP': 'KWIK', 'KWIK STAR': 'KWIK'}
    datasource_name = 'Kwik Trip'
    ta_branches = False
    unique_operator_points = False
    unique_operator_addresses = False
    wrap_raw_records = False

    def source_brand(self, name):
        return canonical_source_name(name)

    def source_numbers(self, name):
        return refs(name)

    def catalog_stores(self, asset):
        return asset['stores']

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--pbf')
        parser.add_argument('--roads')
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, input, output, unresolved, pbf=None, roads=None, **options):
        source, out, missing_path = map(Path, (input, output, unresolved))
        paths = [source, out, missing_path] + ([Path(pbf)] if pbf else []) + ([Path(roads)] if roads else [])
        if len({p.resolve() for p in paths}) != len(paths) or out.exists() or missing_path.exists():
            raise CommandError('Input and new output paths must be distinct.')
        if pbf and (not Path(pbf).is_file() or Path(pbf).stat().st_size > 256 * 1024 * 1024):
            raise CommandError('A compact OSM extract of at most 256 MiB is required.')
        if roads and (not Path(roads).is_file() or Path(roads).stat().st_size > 64 * 1024 * 1024):
            raise CommandError('A road geometry asset of at most 64 MiB is required.')
        try:
            asset = json.loads(source.read_text(encoding='utf-8'))
            if not isinstance(asset, dict) or (self.source_url is not None and asset.get('source') != self.source_url) or not isinstance(asset.get('stores'), list):
                raise ValueError()
            raw_stores = self.catalog_stores(asset)
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            if boundary.get('type') != 'FeatureCollection':
                raise ValueError()
            states = {f['properties']['STUSPS']: f for f in boundary['features']}
            if not states or len(states) != len(boundary['features']):
                raise ValueError()
            road_asset = json.loads(Path(roads).read_text(encoding='utf-8')) if roads else {'ways': []}
            if not isinstance(road_asset, dict) or set(road_asset) != {'ways'} or not isinstance(road_asset['ways'], list):
                raise ValueError()
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('Valid operator asset and state boundaries required.') from exc
        grid = read_junctions(Path(pbf)) if pbf else {}
        stores = [{'source': asset['source'], 'record': item} if isinstance(item, dict) else item for item in raw_stores] if self.wrap_raw_records else raw_stores
        numbers = Counter(operator_store_key(s) for s in stores if isinstance(s, dict))
        points = Counter()
        addresses = Counter()
        if self.unique_operator_points:
            for store in stores:
                try:
                    view = operator_display(store)
                    point = [view.get('latitude'), view.get('longitude')]
                    if valid_point(point):
                        points[tuple(point)] += 1
                    if self.unique_operator_addresses:
                        key = roadranger_address_key(store)
                        if key:
                            addresses[key] += 1
                except (KeyError, TypeError, AttributeError):
                    continue
        by_number, by_branch = defaultdict(list), defaultdict(set)
        for store in stores:
            key = operator_store_key(store) if isinstance(store, dict) else None
            if key and numbers[key] == 1:
                by_number[key].append(store)
                if self.ta_branches and key[0] == 'TA' and ta_branch_key(store['name']):
                    by_branch[ta_branch_key(store['name'])].add(key)
        stations = list(Station.objects.order_by('pk'))
        station_by_pk = {station.pk: station for station in stations}
        shared_approvals = load_shared_operator_approvals(settings.BASE_DIR)
        candidates, owners = defaultdict(list), defaultdict(set)
        for station in stations:
            station_keys = {(self.namespaces[brand], number) for row in station.rows for brand in [self.source_brand(row['Truckstop Name'])] if brand in self.namespaces for number in self.source_numbers(row['Truckstop Name'])}
            if self.ta_branches:
                all_refs = set().union(*(refs(row['Truckstop Name']) for row in station.rows))
                for row in station.rows:
                    branch = ta_branch_key(row['Truckstop Name'])
                    if branch:
                        station_keys.update(('TA', number) for number in refs(row['Truckstop Name']))
                        if not all_refs and branch[1]:
                            station_keys.update(by_branch.get(branch, ()))
            for key in station_keys:
                for store in by_number.get(key, ()):
                    try:
                        view = operator_display(store)
                        point = [view.get('latitude'), view.get('longitude')]
                    except (KeyError, TypeError, AttributeError):
                        continue
                    if not valid_point(point):
                        continue
                    if self.unique_operator_points and points[tuple(point)] != 1:
                        continue
                    if self.unique_operator_addresses and addresses[roadranger_address_key(store)] != 1:
                        continue
                    contexts = [{'store': store}]
                    contexts.extend({'store': store, 'junction': junction} for junction in nearby_junctions(grid, point))
                    match = next((context for context in contexts if valid_operator_record(station, context, point, states.get(station.state))), None)
                    if not match:
                        ways = supporting_roads(station, point, states.get(station.state), road_asset['ways'])
                        context = {'store': store, 'roads': ways}
                        if ways and valid_operator_record(station, context, point, states.get(station.state)):
                            match = context
                    if not match:
                        context = {'store': store, 'identity_only': True}
                        if valid_operator_record(station, context, point, states.get(station.state)):
                            match = context
                    if match:
                        candidates[station.pk].append((key, match))
                        owners[key].add(station.pk)
        rows, missing = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and (len(owners[matches[0][0]]) == 1 or approved_shared_operator([station_by_pk[pk] for pk in owners[matches[0][0]]], matches[0][1]['store'], shared_approvals)):
                context = matches[0][1]
                store = context['store']
                view = operator_display(store)
                rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'latitude': view['latitude'], 'longitude': view['longitude'], 'matched_name': view['name'], 'matched_address': view['address'], 'source': view['source'], 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))), 'place_id': view['number'], 'datasource_name': self.datasource_name, 'datasource_url': view['source'], 'operator_evidence': json.dumps(context, separators=(',', ':'))})
            else:
                missing.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'reason': 'ambiguous_match' if matches else 'no_matching_operator_store'})
        for path, columns, entries in ((out, COLUMNS, rows), (missing_path, ('station_id', 'address', 'city', 'state', 'reason'), missing)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(entries)
        self.stdout.write(f'Evidence rows: {len(rows)}. Unresolved groups: {len(missing)}.')
