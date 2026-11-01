from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from planner.models import Station
from planner.osm_evidence import canonical_name, canonical_source_name, is_business


class Command(BaseCommand):
    help = 'Select named business site objects from a local OSM file without caching geometry.'

    def add_arguments(self, parser):
        parser.add_argument('--pbf', required=True)
        parser.add_argument('--output', required=True)

    def handle(self, pbf, output, **options):
        import osmium

        source, target = Path(pbf), Path(output)
        if not source.is_file():
            raise CommandError('OSM input does not exist.')
        if source.resolve() == target.resolve() or target.exists():
            raise CommandError('Output must be a new path distinct from input.')
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CommandError('Cannot prepare output directory.') from exc
        names = {canonical_source_name(row['Truckstop Name']) for rows in Station.objects.values_list('rows', flat=True) for row in rows}
        names.discard('')
        pool = osmium.io.ThreadPool(1, 2)
        try:
            with osmium.SimpleWriter(str(target), thread_pool=pool) as writer:
                class Selector(osmium.SimpleHandler):
                    def accept(self, obj, write):
                        tags = {tag.k: tag.v for tag in obj.tags}
                        if is_business(tags) and any(canonical_name(tags.get(key, '')) in names for key in ('name', 'brand', 'operator')):
                            write(obj)

                    def node(self, obj):
                        self.accept(obj, writer.add_node)

                    def way(self, obj):
                        self.accept(obj, writer.add_way)

                    def relation(self, obj):
                        self.accept(obj, writer.add_relation)

                with osmium.io.Reader(str(source), thread_pool=pool) as reader:
                    osmium.apply(reader, osmium.filter.TagFilter(('shop', 'convenience'), ('highway', 'services'), ('landuse', 'retail')), Selector())
        except (OSError, RuntimeError) as exc:
            raise CommandError('Could not select OSM site objects.') from exc
