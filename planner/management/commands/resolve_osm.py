import csv
import math
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import in_us, load_boundary
from planner.management.commands.load_data import norm, station_match
from planner.evidence import COLUMNS
from planner.road import road_marker_keys
from planner.models import Station


def address_keys(address):
    address = norm(address)
    keys = {('address', address)}
    keys.update(('road_marker', *key) for key in (road_marker_keys(address) or ()))
    return keys


def match_node(tags, latitude, longitude, node_id, index, boundary):
    if tags.get('amenity') != 'fuel' or not all(math.isfinite(v) for v in (latitude, longitude)):
        return []
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return []
    name = tags.get('name', '').strip()
    ref = tags.get('ref', '').strip()
    if re.fullmatch(r'\d+[A-Za-z]?', ref):
        name = f'{name} #{ref}'
    address = tags.get('addr:full', '').strip() or ' '.join(tags.get(k, '').strip() for k in ('addr:housenumber', 'addr:street')).strip()
    city, state = norm(tags.get('addr:city', '')), norm(tags.get('addr:state', ''))
    if not name or not address or not city or not state:
        return []
    candidates = {}
    for key in address_keys(address):
        for station in index.get((city, state, key), ()):
            candidates[station.pk] = station
    matched = [station for station in candidates.values() if station_match({norm(row['Truckstop Name']) for row in station.rows}, station.address, name, address)]
    if not matched or not in_us([latitude, longitude], boundary):
        return []
    found = []
    for station in matched:
        found.append((station.pk, {
            'station_id': station.source_id, 'address': station.address, 'city': station.city,
            'state': station.state, 'latitude': latitude, 'longitude': longitude,
            'matched_name': name, 'matched_address': address,
            'source': f'https://www.openstreetmap.org/node/{node_id}',
            'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))),
            'place_id': str(node_id), 'datasource_name': 'OpenStreetMap',
            'datasource_license': 'ODbL', 'datasource_attribution': 'OpenStreetMap contributors',
            'datasource_url': 'https://www.openstreetmap.org/copyright',
        }))
    return found


class Command(BaseCommand):
    help = 'Resolve station evidence offline from fuel nodes in a local OSM PBF.'

    def add_arguments(self, parser):
        parser.add_argument('--pbf', required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, pbf, output, unresolved, **options):
        try:
            import osmium
        except ImportError as exc:
            raise CommandError('Install optional osmium package to read a local PBF.') from exc
        pbf_path, output_path, unresolved_path = map(Path, (pbf, output, unresolved))
        if not pbf_path.is_file():
            raise CommandError('PBF input does not exist.')
        if len({p.resolve() for p in (pbf_path, output_path, unresolved_path)}) != 3:
            raise CommandError('Input and output paths must be distinct.')
        if output_path.exists() or unresolved_path.exists():
            raise CommandError('Output exists; choose new output paths.')
        try:
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
        except (OSError, UnicodeError, ValueError) as exc:
            raise CommandError('Valid US boundary required.') from exc
        stations = list(Station.objects.order_by('pk'))
        index, candidates, node_groups = defaultdict(list), defaultdict(dict), defaultdict(set)
        for station in stations:
            for key in address_keys(station.address):
                index[(norm(station.city), norm(station.state), key)].append(station)

        class Handler(osmium.SimpleHandler):
            def node(self, node):
                if node.tags.get('amenity') != 'fuel' or not node.location.valid():
                    return
                tags = {tag.k: tag.v for tag in node.tags}
                for station_pk, row in match_node(tags, node.location.lat, node.location.lon, node.id, index, boundary):
                    candidates[station_pk][node.id] = row
                    node_groups[node.id].add(station_pk)

        try:
            pool = osmium.io.ThreadPool(1, 2)
            with osmium.io.Reader(str(pbf_path), osmium.osm.osm_entity_bits.NODE, thread_pool=pool) as reader:
                osmium.apply(reader, osmium.filter.TagFilter(('amenity', 'fuel')), Handler())
        except (OSError, RuntimeError) as exc:
            raise CommandError('Could not read OSM PBF.') from exc
        evidence, missing = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and len(node_groups[next(iter(matches))]) == 1:
                evidence.append(next(iter(matches.values())))
            else:
                missing.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state,
                                'reason': 'ambiguous_match' if matches else 'no_matching_fuel_node'})
        for path, columns, rows in ((output_path, COLUMNS, evidence), (unresolved_path, ('station_id', 'address', 'city', 'state', 'reason'), missing)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        self.stdout.write(f'Evidence rows: {len(evidence)}. Unresolved groups: {len(missing)}.')
