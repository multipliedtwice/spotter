from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import GOOD2GO_SOURCE, good2go_source_brand


class Command(OperatorCommand):
    help = "Resolve Good 2 Go stations from published locator records."
    source_url = GOOD2GO_SOURCE
    namespaces = {'GOOD 2 GO': 'GOOD 2 GO'}
    datasource_name = 'Good 2 Go'
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return good2go_source_brand(name)
