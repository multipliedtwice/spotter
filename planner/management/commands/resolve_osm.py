import csv
import math
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import in_us, load_boundary
from planner.management.commands.load_data import norm
from planner.evidence import COLUMNS
from planner.models import Station


class Command(BaseCommand):
    help = 'Resolve station evidence from a compact, reference-complete local OSM extract.'

    def add_arguments(self, parser):
        parser.add_argument('--pbf', required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, pbf, output, unresolved, **options):
        import json
        from planner.models import City
        from planner.osm_evidence import JUNCTION_LINK_ROADS, JUNCTION_MAIN_ROADS, area_point, canonical_name, canonical_source_name, distance_miles, evidence_city_key, exact_ref, identities, identity_tags, intersection_constraint, is_business, junction_exit_keys, junction_markers, matched_values, street_key, supported_exit_keys, supported_street_address, typed_roads, valid_context

        try:
            import osmium
        except ImportError as exc:
            raise CommandError('Install optional osmium package to read a local PBF.') from exc
        pbf_path, output_path, unresolved_path = map(Path, (pbf, output, unresolved))
        if not pbf_path.is_file() or pbf_path.stat().st_size > 256 * 1024 * 1024:
            raise CommandError('A compact OSM extract of at most 256 MiB is required.')
        if len({p.resolve() for p in (pbf_path, output_path, unresolved_path)}) != 3:
            raise CommandError('Input and output paths must be distinct.')
        if output_path.exists() or unresolved_path.exists():
            raise CommandError('Output exists; choose new output paths.')
        if output_path.resolve() in unresolved_path.resolve().parents or unresolved_path.resolve() in output_path.resolve().parents:
            raise CommandError('Output paths cannot contain one another.')
        try:
            for path in (output_path, unresolved_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.parent.is_dir():
                    raise CommandError('Output parent must be a directory.')
        except OSError as exc:
            raise CommandError('Cannot prepare output directories.') from exc
        try:
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            states = {f['properties']['STUSPS']: f for f in boundary['features']}
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('Valid state boundary features required.') from exc
        stations = list(Station.objects.order_by('pk'))
        cities = defaultdict(list)
        for city in City.objects.all():
            cities[(evidence_city_key(city.name), norm(city.state))].append([city.latitude, city.longitude])
        streets, exits, intersections = defaultdict(list), defaultdict(list), defaultdict(list)
        constraints = {}
        for station in stations:
            streets[street_key(station.address)].append(station)
            for key in supported_exit_keys(station.address, station.state):
                if key[2] == 'exit':
                    exits[key].append(station)
            constraint = intersection_constraint(station.address, station.state)
            if constraint:
                constraints[station.pk] = constraint
                for kind, number in constraint[0]:
                    intersections[(kind, number)].append(station)
                    if kind == 'SR':
                        intersections[(f'STATE:{station.state}', number)].append(station)
        features, sites, junctions, roads, ramps = [], [], {}, [], []
        evidence_fields = {'amenity', 'name', 'brand', 'operator', 'ref', 'website', 'addr:full', 'addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'shop', 'highway', 'landuse'}
        try:
            pool = osmium.io.ThreadPool(1, 2)
            processor = osmium.FileProcessor(str(pbf_path), thread_pool=pool).with_areas()
            factory = osmium.geom.GeoJSONFactory()
            for obj in processor:
                tags = {tag.k: tag.v for tag in obj.tags}
                if obj.is_node():
                    if not obj.location.valid():
                        continue
                    point = [obj.location.lat, obj.location.lon]
                    if tags.get('highway') == 'motorway_junction':
                        junctions[obj.id] = {'id': obj.id, 'point': point, 'ref': tags.get('ref', ''), 'old_ref': tags.get('old_ref', ''), 'highway': tags['highway'], 'url': f'https://www.openstreetmap.org/node/{obj.id}'}
                    if tags.get('amenity') == 'fuel' or is_business(tags):
                        feature = {'type': 'node', 'id': obj.id, 'tags': {k: v for k, v in tags.items() if k in evidence_fields}, 'geometry': {'type': 'Point', 'coordinates': [point[1], point[0]]}, 'point': point}
                        (features if tags.get('amenity') == 'fuel' else sites).append(feature)
                elif obj.is_way() and tags.get('highway') in JUNCTION_MAIN_ROADS | JUNCTION_LINK_ROADS and (tags.get('ref') or tags.get('destination:ref')):
                    nodes = [n.ref for n in obj.nodes]
                    if any(node in junctions for node in nodes):
                        base = {'id': obj.id, 'highway': tags['highway'], 'nodes': nodes, 'url': f'https://www.openstreetmap.org/way/{obj.id}'}
                        if tags['highway'] in JUNCTION_MAIN_ROADS and tags.get('ref'):
                            roads.append({**base, 'ref': tags['ref']})
                        if tags['highway'] in JUNCTION_LINK_ROADS and tags.get('destination:ref'):
                            ramps.append({**base, 'destination:ref': tags['destination:ref']})
                elif obj.is_area() and (tags.get('amenity') == 'fuel' or is_business(tags)):
                    try:
                        geometry = json.loads(factory.create_multipolygon(obj))
                        point = area_point(geometry)
                    except (RuntimeError, ValueError, TypeError, KeyError, IndexError):
                        continue
                    if point:
                        feature = {'type': 'way' if obj.from_way() else 'relation', 'id': obj.orig_id(), 'tags': {k: v for k, v in tags.items() if k in evidence_fields}, 'geometry': geometry, 'point': point}
                        (features if tags.get('amenity') == 'fuel' else sites).append(feature)
        except (OSError, RuntimeError) as exc:
            raise CommandError('Could not read OSM extract.') from exc
        ramps_by_junction = defaultdict(list)
        for ramp in ramps:
            for node in ramp['nodes']:
                if node in junctions:
                    ramps_by_junction[node].append(ramp)
        linked = []
        for road in roads:
            for node in road['nodes']:
                if node in junctions:
                    linked.append({**junctions[node], 'road': road, 'ramps': ramps_by_junction[node]})
        # Grid bounds junction searches without comparing every station to every feature.
        grid = defaultdict(list)
        for junction in linked:
            lat, lon = junction['point']
            main_refs = typed_roads(junction['road']['ref'])
            interchange_refs = set(main_refs)
            for ramp in junction['ramps']:
                interchange_refs.update(typed_roads(ramp['destination:ref']))
            grid[(math.floor(lat * 10), math.floor(lon * 10))].append((junction, main_refs, interchange_refs))
        site_grid = defaultdict(list)
        for site in sites:
            if site['type'] == 'node' or not (site['tags'].get('highway') == 'services' or site['tags'].get('landuse') == 'retail'):
                continue
            geometry = site['geometry']
            polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
            points = [p for poly in polygons for ring in poly for p in ring]
            west, east = min(p[0] for p in points), max(p[0] for p in points)
            south, north = min(p[1] for p in points), max(p[1] for p in points)
            min_x, max_x = math.floor(west * 10), math.floor(east * 10)
            min_y, max_y = math.floor(south * 10), math.floor(north * 10)
            if (max_x - min_x + 1) * (max_y - min_y + 1) > 1000:
                continue
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    site_grid[(y, x)].append((site, (south, north, west, east)))
        pairs = [(feature, None) for feature in features + sites]
        for feature in features:
            lat, lon = feature['point']
            for site, (south, north, west, east) in site_grid.get((math.floor(lat * 10), math.floor(lon * 10)), ()):
                if south <= lat <= north and west <= lon <= east and in_us(feature['point'], site['geometry']):
                    pairs.append((feature, site))
        candidates = defaultdict(dict)
        for feature, site in pairs:
            point = feature['point']
            tags = site['tags'] if site else feature['tags']
            _, address = matched_values(tags)
            possibilities = [(station, None) for station in streets.get(street_key(address), ())]
            cell = (math.floor(point[0] * 10), math.floor(point[1] * 10))
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    for junction, main_refs, interchange_refs in grid.get((cell[0] + dy, cell[1] + dx), ()):
                        if distance_miles(point, junction['point']) > 1:
                            continue
                        keys = junction_exit_keys(junction['road']['ref'], junction)
                        for kind, _ in typed_roads(junction['road']['ref']):
                            if kind.startswith('STATE:') and kind[6:] in states:
                                keys.update(junction_exit_keys(junction['road']['ref'], junction, kind[6:]))
                        for key in keys:
                            possibilities.extend((station, junction) for station in exits.get(key, ()))
                        for key in main_refs:
                            for station in intersections.get(key, ()):
                                required, marker = constraints[station.pk]
                                def present(route, refs):
                                    kind, number = route
                                    return route in refs or (kind == 'SR' and (f'STATE:{station.state}', number) in refs)
                                if (not marker or marker in junction_markers(junction)) and any(present(route, main_refs) for route in required) and all(present(route, interchange_refs) for route in required):
                                    possibilities.append((station, junction))
            for station, junction in possibilities:
                context = {k: v for k, v in feature.items() if k != 'point'}
                if site:
                    context['site'] = {k: v for k, v in site.items() if k != 'point'}
                    context['site']['url'] = f"https://www.openstreetmap.org/{site['type']}/{site['id']}"
                if junction:
                    context['junction'] = junction
                if station.state not in states or not valid_context(station, context, point, states[station.state], cities[(evidence_city_key(station.city), norm(station.state))]):
                    continue
                key = (feature['type'], feature['id'], site['type'] if site else '', site['id'] if site else 0)
                candidates[station.pk][key] = (feature, context)
        # Prefer exact store numbers, then recompute ownership across preferred sets.
        reverse = defaultdict(set)
        for station in stations:
            matches = candidates[station.pk]
            strong = {key: value for key, value in matches.items() if exact_ref(station, identity_tags(value[1]))}
            if strong:
                candidates[station.pk] = strong
            for key, (_, context) in candidates[station.pk].items():
                reverse[key[:2]].add(station.pk)
                if context.get('site'):
                    reverse[(context['site']['type'], context['site']['id'])].add(station.pk)
        input_names = {canonical_name(name) for feature in features + sites for name in identities(feature['tags'])[0] if name}
        evidence, missing = [], []
        for station in stations:
            matches = candidates[station.pk]
            unique = all(len(reverse[key[:2]]) == 1 and (not context.get('site') or len(reverse[(context['site']['type'], context['site']['id'])]) == 1) for key, (_, context) in matches.items())
            values = sorted(matches.values(), key=lambda item: item[0]['tags'].get('amenity') != 'fuel')
            if len(values) > 1 and unique:
                def same_site(left_item, right_item):
                    left, left_context = left_item
                    right, right_context = right_item
                    def object_ids(feature, context):
                        ids = {(feature['type'], feature['id'])}
                        if context.get('site'):
                            ids.add((context['site']['type'], context['site']['id']))
                        return ids
                    if object_ids(left, left_context) & object_ids(right, right_context):
                        return True
                    left_refs, right_refs = identities(left['tags'])[1], identities(right['tags'])[1]
                    shared = bool(left_refs & right_refs) and distance_miles(left['point'], right['point']) <= 0.1
                    containment = (left['type'] == 'node' and right['type'] != 'node' and in_us(left['point'], right['geometry'])) or (right['type'] == 'node' and left['type'] != 'node' and in_us(right['point'], left['geometry']))
                    return shared or containment
                connected, pending = {0}, [0]
                while pending:
                    current = pending.pop()
                    for index in range(len(values)):
                        if index not in connected and same_site(values[current], values[index]):
                            connected.add(index)
                            pending.append(index)
                unique = len(connected) == len(values)
            if values and unique:
                feature, context = values[0]
                tags = identity_tags(context)
                name, address = matched_values(tags)
                evidence.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state,
                                 'latitude': feature['point'][0], 'longitude': feature['point'][1], 'matched_name': name, 'matched_address': address,
                                 'source': f"https://www.openstreetmap.org/{feature['type']}/{feature['id']}", 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))),
                                 'place_id': str(feature['id']), 'datasource_name': 'OpenStreetMap', 'datasource_license': 'ODbL', 'datasource_attribution': 'OpenStreetMap contributors',
                                 'datasource_url': 'https://www.openstreetmap.org/copyright', 'osm_evidence': json.dumps(context, separators=(',', ':'))})
            else:
                if values:
                    reason = 'ambiguous_match'
                elif not supported_exit_keys(station.address, station.state) and not intersection_constraint(station.address, station.state) and not supported_street_address(station.address):
                    reason = 'unsupported_source_address'
                elif not any(canonical_source_name(row['Truckstop Name']) in input_names for row in station.rows):
                    reason = 'no_matching_osm_identity'
                else:
                    reason = 'no_supported_feature'
                missing.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'reason': reason})
        for path, columns, rows in ((output_path, COLUMNS, evidence), (unresolved_path, ('station_id', 'address', 'city', 'state', 'reason'), missing)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
                writer.writeheader()
                writer.writerows(rows)
        self.stdout.write(f'Evidence rows: {len(evidence)}. Unresolved groups: {len(missing)}.')
