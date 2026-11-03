from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import JETFOOD_SOURCE, jetfood_source_brand


class Command(OperatorCommand):
    help = "Resolve Jet Food stations from published locator records."
    source_url = JETFOOD_SOURCE
    namespaces = {'JET FOOD': 'JET FOOD'}
    datasource_name = 'Jet Food Stores'
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return jetfood_source_brand(name)
