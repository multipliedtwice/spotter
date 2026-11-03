import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.ambest_evidence import SOURCE, name_key, native_point, observed_point, valid_ambest_record
from planner.core import load_boundary
from planner.evidence import COLUMNS
from planner.management.commands.resolve_kwiktrip import nearby_junctions, read_junctions
from planner.models import Station
from planner.osm_evidence import evidence_city_key, normalized


class Command(BaseCommand):
    help = 'Resolve stations using local AMBEST directory records and independent road evidence.'

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--intersections')
        parser.add_argument('--pbf')
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, input, output, unresolved, intersections=None, pbf=None, **options):
        source, out, missing = map(Path, (input, output, unresolved))
        paths = [source, out, missing] + ([Path(intersections)] if intersections else []) + ([Path(pbf)] if pbf else [])
        if len({path.resolve() for path in paths}) != len(paths) or out.exists() or missing.exists():
            raise CommandError('Input and new output paths must be distinct.')
        if pbf and (not Path(pbf).is_file() or Path(pbf).stat().st_size > 256 * 1024 * 1024):
            raise CommandError('A compact OSM extract of at most 256 MiB is required.')
        try:
            asset = json.loads(source.read_text())
            if set(asset) != {'source', 'records'} or asset['source'] != SOURCE or not isinstance(asset['records'], list):
                raise ValueError()
            proof_asset = json.loads(Path(intersections).read_text()) if intersections else {'records': []}
            if set(proof_asset) != {'records'} or not isinstance(proof_asset['records'], list):
                raise ValueError()
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            if boundary.get('type') != 'FeatureCollection':
                raise ValueError()
            states = {f['properties']['STUSPS']: f for f in boundary['features']}
            if not states or len(states) != len(boundary['features']):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('Valid AMBEST facts and state boundaries required.') from exc
        grid = read_junctions(Path(pbf)) if pbf else {}
        records = asset['records']
        ids = Counter(r.get('id') for r in records if isinstance(r, dict) and type(r.get('id')) is int)
        points = Counter(tuple(p) for r in records if (p := observed_point(r)) is not None)
        index = defaultdict(list)
        for r in records:
            point = native_point(r)
            if point and ids[r['id']] == 1 and points[tuple(point)] == 1:
                index[(name_key(r['name']), evidence_city_key(r['city']), normalized(r['state']))].append(r)
        stations = list(Station.objects.order_by('pk'))
        candidates, owners = defaultdict(list), defaultdict(set)
        for station in stations:
            names = {name_key(row['Truckstop Name']) for row in station.rows}
            possibles = [r for name in names for r in index.get((name, evidence_city_key(station.city), normalized(station.state)), ())]
            for record in possibles:
                point = native_point(record)
                context = {'source': SOURCE, 'record': record}
                options = [context]
                options.extend({**context, 'intersection': proof} for proof in proof_asset['records'])
                options.extend({**context, 'junction': node} for node in nearby_junctions(grid, point, max_distance=1))
                match = next((item for item in options if valid_ambest_record(station, item, point, states.get(station.state))), None)
                if match:
                    candidates[station.pk].append(match)
                    owners[record['id']].add(station.pk)
        rows, unresolved_rows = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and len(owners[matches[0]['record']['id']]) == 1:
                context = matches[0]
                r = context['record']
                point = native_point(r)
                rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'latitude': point[0], 'longitude': point[1], 'matched_name': r['name'], 'matched_address': r['directory_address'], 'source': SOURCE, 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))), 'place_id': str(r['id']), 'datasource_name': 'AMBEST', 'datasource_url': SOURCE, 'directory_evidence': json.dumps(context, separators=(',', ':'))})
            else:
                unresolved_rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'reason': 'ambiguous_match' if matches else 'no_matching_directory_record'})
        for path, columns, entries in ((out, COLUMNS, rows), (missing, ('station_id', 'address', 'city', 'state', 'reason'), unresolved_rows)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
                writer.writeheader()
                writer.writerows(entries)
