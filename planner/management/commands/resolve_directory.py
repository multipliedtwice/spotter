import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import distance, load_boundary
from planner.directory_evidence import OPIS_SOURCE, directory_key, valid_directory_record
from planner.evidence import COLUMNS
from planner.models import Station
from planner.osm_evidence import canonical_name, canonical_source_name, evidence_city_key, normalized, refs
from planner.management.commands.resolve_kwiktrip import nearby_junctions, read_junctions


class Command(BaseCommand):
    help = 'Resolve station evidence from a local structured truck-stop directory asset.'

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)
        parser.add_argument('--pbf')

    def handle(self, input, output, unresolved, pbf=None, **options):
        source, output_path, unresolved_path = map(Path, (input, output, unresolved))
        paths = [source, output_path, unresolved_path] + ([Path(pbf)] if pbf else [])
        if len({path.resolve() for path in paths}) != len(paths):
            raise CommandError('Input and output paths must be distinct.')
        if output_path.exists() or unresolved_path.exists():
            raise CommandError('Output exists; choose new output paths.')
        if pbf and (not Path(pbf).is_file() or Path(pbf).stat().st_size > 256 * 1024 * 1024):
            raise CommandError('A compact OSM extract of at most 256 MiB is required.')
        try:
            asset = json.loads(source.read_text(encoding='utf-8'))
            if not isinstance(asset, dict) or not isinstance(asset.get('records'), list):
                raise ValueError()
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            if boundary.get('type') != 'FeatureCollection' or not isinstance(boundary.get('features'), list):
                raise ValueError()
            states = {f['properties']['STUSPS']: f for f in boundary['features']}
            if len(states) != len(boundary['features']) or not states:
                raise ValueError()
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('Valid directory asset and state boundary data required.') from exc
        grid = read_junctions(Path(pbf)) if pbf else {}
        records = asset['records']
        counts = Counter(directory_key(r) for r in records if isinstance(r, dict))
        by_name, by_ref, by_id = defaultdict(list), defaultdict(list), defaultdict(list)
        for index, record in enumerate(records):
            key = directory_key(record)
            if key and counts[key] == 1 and isinstance(record.get('name'), str):
                if record['source'] == OPIS_SOURCE:
                    by_id[key[1]].append((index, record))
                    continue
                if not isinstance(record.get('city'), str) or not isinstance(record.get('state'), str):
                    continue
                city, state = evidence_city_key(record['city']), normalized(record['state'])
                by_name[(canonical_name(record['name']), city, state)].append((index, record))
                for number in refs(record['name']):
                    by_ref[(number, city, state)].append((index, record))
        stations = list(Station.objects.order_by('pk'))
        candidates, owners = defaultdict(list), defaultdict(set)
        for station in stations:
            names = {canonical_source_name(row['Truckstop Name']) for row in station.rows}
            city, state = evidence_city_key(station.city), normalized(station.state)
            possibilities = {index: record for name in names for index, record in by_name.get((name, city, state), ())}
            if station.source_id.isdigit():
                possibilities.update(by_id.get(str(int(station.source_id)), ()))
            if names & {'TRAVELCENTERS OF AMERICA', 'PETRO', 'TA EXPRESS', 'QUICK', 'QUICKFUEL', 'TOOTN TOTUM'}:
                for row in station.rows:
                    for number in refs(row['Truckstop Name']):
                        possibilities.update(by_ref.get((number, city, state), ()))
            for index, record in possibilities.items():
                point = [record.get('latitude'), record.get('longitude')]
                context = record
                if valid_directory_record(station, record, point, states.get(station.state)):
                    candidates[station.pk].append((index, context))
                    owners[index].add(station.pk)
                elif grid and record.get('source') != OPIS_SOURCE:
                    from planner.osm_evidence import valid_point
                    if not valid_point(point):
                        continue
                    matches = []
                    for junction in nearby_junctions(grid, point, max_distance=1):
                        context = {'record': record, 'junction': junction}
                        if valid_directory_record(station, context, point, states.get(station.state)):
                            matches.append(context)
                    if matches:
                        chosen = min(matches, key=lambda item: (distance(point, item['junction']['point']), item['junction']['id'], item['junction']['road']['id']))
                        candidates[station.pk].append((index, chosen))
                        owners[index].add(station.pk)
        rows, missing = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and len(owners[matches[0][0]]) == 1:
                context = matches[0][1]
                record = context['record'] if isinstance(context, dict) and 'junction' in context else context
                opis = record['source'] == OPIS_SOURCE
                rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city,
                             'state': station.state, 'latitude': record['latitude'], 'longitude': record['longitude'],
                             'matched_name': record['name'], 'matched_address': record['address2'] if opis else record['address'], 'source': record['source'],
                             'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))),
                             'place_id': record['id'] if opis else '', 'datasource_name': 'OPIS' if opis else 'Find Fuel Stops', 'datasource_url': record['source'],
                             'directory_evidence': json.dumps(context, separators=(',', ':'))})
            else:
                missing.append({'station_id': station.source_id, 'address': station.address, 'city': station.city,
                                'state': station.state, 'reason': 'ambiguous_match' if matches else 'no_matching_directory_record'})
        for path, columns, entries in ((output_path, COLUMNS, rows), (unresolved_path, ('station_id', 'address', 'city', 'state', 'reason'), missing)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(entries)
        self.stdout.write(f'Evidence rows: {len(rows)}. Unresolved groups: {len(missing)}.')
