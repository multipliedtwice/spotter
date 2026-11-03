import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import load_boundary
from planner.evidence import COLUMNS
from planner.models import Station
from planner.onvo_evidence import branch_key, onvo_observed_point, onvo_view, valid_onvo_record
from planner.osm_evidence import evidence_city_key


class Command(BaseCommand):
    help = 'Resolve Onvo branch evidence from local published location facts.'

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, input, output, unresolved, **options):
        source, out, missing = map(Path, (input, output, unresolved))
        if len({p.resolve() for p in (source, out, missing)}) != 3 or out.exists() or missing.exists():
            raise CommandError('Input and new output paths must be distinct.')
        try:
            asset = json.loads(source.read_text())
            if not isinstance(asset, dict) or set(asset) != {'records'} or not isinstance(asset['records'], list):
                raise ValueError()
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            if boundary.get('type') != 'FeatureCollection':
                raise ValueError()
            states = {feature['properties']['STUSPS']: feature for feature in boundary['features']}
            if not states or len(states) != len(boundary['features']):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('Valid Onvo facts and state boundaries required.') from exc
        records = asset['records']
        urls = Counter(record['source_url'] for record in records if isinstance(record, dict) and isinstance(record.get('source_url'), str))
        points = Counter(tuple(point) for record in records if (point := onvo_observed_point(record)) is not None)
        index = defaultdict(list)
        for record in records:
            view = onvo_view(record)
            if view and urls[view['source']] == 1 and points[(view['latitude'], view['longitude'])] == 1:
                index[(branch_key(view['name'], native=True), evidence_city_key(view['city'], view['state']), view['state'])].append((record, view))
        stations = list(Station.objects.order_by('pk'))
        candidates, owners = defaultdict(list), defaultdict(set)
        for station in stations:
            branches = {branch_key(row['Truckstop Name']) for row in station.rows} - {''}
            for branch in branches:
                for record, view in index.get((branch, evidence_city_key(station.city, station.state), station.state), ()):
                    context = {'source': view['source'], 'record': record}
                    if valid_onvo_record(station, context, [view['latitude'], view['longitude']], states.get(station.state)):
                        candidates[station.pk].append((context, view))
                        owners[view['source']].add(station.pk)
        rows, unresolved_rows = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and len(owners[matches[0][1]['source']]) == 1:
                context, view = matches[0]
                rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'latitude': view['latitude'], 'longitude': view['longitude'], 'matched_name': view['name'], 'matched_address': view['address'], 'source': view['source'], 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))), 'place_id': '', 'datasource_name': 'Onvo', 'datasource_url': view['source'], 'directory_evidence': json.dumps(context, separators=(',', ':'))})
            elif any(branch_key(row['Truckstop Name']) for row in station.rows):
                unresolved_rows.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state, 'reason': 'ambiguous_match' if matches else 'no_matching_operator_branch'})
        for path, columns, entries in ((out, COLUMNS, rows), (missing, ('station_id', 'address', 'city', 'state', 'reason'), unresolved_rows)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
                writer.writeheader()
                writer.writerows(entries)
