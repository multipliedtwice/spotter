from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import DANDY_SOURCE, dandy_source_brand


class Command(OperatorCommand):
    help = "Resolve Dandy stations from published locator records."
    source_url = DANDY_SOURCE
    namespaces = {'DANDY': 'DANDY'}
    datasource_name = 'Dandy'
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return dandy_source_brand(name)
