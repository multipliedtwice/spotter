import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import load_boundary
from planner.evidence import COLUMNS
from planner.management.commands.resolve_kwiktrip import nearby_junctions, read_junctions
from planner.models import Station
from planner.osm_evidence import canonical_source_name, evidence_city_key, normalized, refs
from planner.wex_evidence import ENDPOINT, SOURCE, business_name_key, native_point, observed_point, valid_wex_record


class Command(BaseCommand):
    help = 'Resolve stations using local WEX directory and independent road evidence.'

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--junctions')
        parser.add_argument('--intersections')
        parser.add_argument('--pbf')
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, input, output, unresolved, junctions=None, intersections=None, pbf=None, **options):
        source, out, missing = map(Path, (input, output, unresolved))
        paths = [source, out, missing] + ([Path(junctions)] if junctions else []) + ([Path(intersections)] if intersections else []) + ([Path(pbf)] if pbf else [])
        if len({path.resolve() for path in paths}) != len(paths) or out.exists() or missing.exists():
            raise CommandError('Input and new output paths must be distinct.')
        if pbf and (not Path(pbf).is_file() or Path(pbf).stat().st_size > 256 * 1024 * 1024):
            raise CommandError('A compact OSM extract of at most 256 MiB is required.')
        try:
            asset = json.loads(source.read_text())
            if not isinstance(asset, dict) or asset.get('source') != SOURCE or asset.get('endpoint') != ENDPOINT or not isinstance(asset.get('records'), list):
                raise ValueError()
            evidence = json.loads(Path(junctions).read_text()) if junctions else {'records': []}
            if not isinstance(evidence, dict) or set(evidence) != {'records'} or not isinstance(evidence['records'], list):
                raise ValueError()
            crossings = json.loads(Path(intersections).read_text()) if intersections else {'records': []}
            if not isinstance(crossings, dict) or set(crossings) != {'records'} or not isinstance(crossings['records'], list):
                raise ValueError()
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            if boundary.get('type') != 'FeatureCollection':
                raise ValueError()
            states = {f['properties']['STUSPS']: f for f in boundary['features']}
            if not states or len(states) != len(boundary['features']):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('Valid WEX facts and state boundaries required.') from exc
        grid = read_junctions(Path(pbf)) if pbf else {}
        records = asset['records']
        ids = Counter(record['siteId'] for record in records if isinstance(record, dict) and isinstance(record.get('siteId'), str))
        points = Counter(tuple(point) for record in records if (point := observed_point(record)) is not None)
        index, names_index, proofs, intersection_proofs = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        for record in records:
            point = native_point(record)
            if point and ids[record['siteId']] == 1 and points[tuple(point)] == 1:
                names_index[(business_name_key(record['name']), evidence_city_key(record['city']), normalized(record['state']))].append(record)
                numbers = refs(record['name'])
                if len(numbers) == 1:
                    index[(next(iter(numbers)), evidence_city_key(record['city']), normalized(record['state']))].append(record)
        for proof in evidence['records']:
            if isinstance(proof, dict) and set(proof) == {'siteId', 'junction'} and isinstance(proof['siteId'], str) and isinstance(proof['junction'], dict):
                proofs[proof['siteId']].append(proof['junction'])
        for proof in crossings['records']:
            if isinstance(proof, dict) and set(proof) == {'siteId', 'intersection'} and isinstance(proof['siteId'], str) and isinstance(proof['intersection'], dict):
                intersection_proofs[proof['siteId']].append(proof['intersection'])
        stations = list(Station.objects.order_by('pk'))
        candidates, owners = defaultdict(list), defaultdict(set)
        for station in stations:
            names = [row['Truckstop Name'] for row in station.rows]
            if not names:
                continue
            if any(canonical_source_name(name) == 'CASEYS' for name in names):
                numbers = set().union(*(refs(name) for name in names))
                if len(numbers) != 1 or not all(canonical_source_name(name) == 'CASEYS' for name in names):
                    continue
                records_to_check = index.get((next(iter(numbers)), evidence_city_key(station.city), normalized(station.state)), ())
            else:
                keys = {business_name_key(name) for name in names}
                if len(keys) != 1 or not next(iter(keys)):
                    continue
                records_to_check = names_index.get((next(iter(keys)), evidence_city_key(station.city), normalized(station.state)), ())
            for record in records_to_check:
                point = native_point(record)
                base = {'source': SOURCE, 'record': record}
                contexts = [base] + [{**base, 'junction': proof} for proof in proofs[record['siteId']]]
                contexts.extend({**base, 'intersection': proof} for proof in intersection_proofs[record['siteId']])
                contexts.extend({**base, 'junction': node} for node in nearby_junctions(grid, point, max_distance=1))
                match = next((context for context in contexts if valid_wex_record(station, context, point, states.get(station.state))), None)
                if match:
                    candidates[station.pk].append(match)
                    owners[record['siteId']].add(station.pk)
        rows, unresolved_rows = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and len(owners[matches[0]['record']['siteId']]) == 1:
                context = matches[0]
                record = context['record']
                point = native_point(record)
                rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'latitude': point[0], 'longitude': point[1], 'matched_name': record['name'], 'matched_address': record['address'], 'source': SOURCE, 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))), 'place_id': record['siteId'], 'datasource_name': 'WEX', 'datasource_url': SOURCE, 'directory_evidence': json.dumps(context, separators=(',', ':'))})
            else:
                unresolved_rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'reason': 'ambiguous_match' if matches else 'no_matching_directory_record'})
        for path, columns, entries in ((out, COLUMNS, rows), (missing, ('station_id', 'address', 'city', 'state', 'reason'), unresolved_rows)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
                writer.writeheader()
                writer.writerows(entries)
