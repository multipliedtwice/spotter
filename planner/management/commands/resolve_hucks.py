from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import HUCKS_SOURCE, hucks_source_brand


class Command(OperatorCommand):
    help = "Resolve Huck's stations from local published locator records."
    source_url = HUCKS_SOURCE
    namespaces = {'HUCKS': 'HUCKS'}
    datasource_name = "Huck's"
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return hucks_source_brand(name)
