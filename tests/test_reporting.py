from datetime import date
from pathlib import Path

from mcmahon_dispatch.services.reporting_service import money


def test_money_formatting() -> None:
    assert money(123456) == "$1,234.56"
    assert money(-250) == "$-2.50"


def test_reporting_files_exist() -> None:
    root = Path(__file__).parents[1]
    assert (root / "src/mcmahon_dispatch/repositories/reporting_repository.py").exists()
    assert (root / "src/mcmahon_dispatch/services/reporting_service.py").exists()
    assert (root / "src/mcmahon_dispatch/ui/pages/reporting_page.py").exists()
