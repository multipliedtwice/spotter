import csv
from collections import defaultdict
from django.core.management.base import BaseCommand
from planner.models import Station

class Command(BaseCommand):
    help = 'Export a geographically and address-format diverse station sample for independent review.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--count', type=int, default=100)

    def handle(self, path, count, **options):
        groups = defaultdict(list)
        for station in Station.objects.order_by('state', 'source_id', 'pk'):
            kind = 'exit' if 'EXIT' in station.address else 'intersection' if '&' in station.address else 'street'
            brand = next((name for name in ('PILOT', "LOVE'S", 'LOVES', 'TRAVELCENTERS', 'TA ') if name in station.name.upper()), 'OTHER')
            groups[(station.state, kind, brand)].append(station)
        selected = []
        while groups and len(selected) < count:
            for group in list(groups):
                selected.append(groups[group].pop(0))
                if not groups[group]:
                    del groups[group]
                if len(selected) >= count:
                    break
        with open(path, 'w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['station_id', 'name', 'address', 'city', 'state'])
            writer.writerows((s.source_id, s.name, s.address, s.city, s.state) for s in selected)
        self.stdout.write(f'Exported {len(selected)} source records for independent review.')
