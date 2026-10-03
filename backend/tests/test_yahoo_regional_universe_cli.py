import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "import_yahoo_regional_universe.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "import_yahoo_regional_universe",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_parser_has_bounded_defaults() -> None:
    module = _load_module()
    args = module.build_parser().parse_args([])

    assert args.page_size == 100
    assert args.max_pages == 1
    assert "de" in args.regions.split(",")
    assert "jp" in args.regions.split(",")


def test_cli_parser_accepts_explicit_regions_and_limits() -> None:
    module = _load_module()
    args = module.build_parser().parse_args(
        [
            "--regions",
            "de,fr,jp",
            "--page-size",
            "50",
            "--max-pages",
            "2",
        ]
    )

    assert args.regions == "de,fr,jp"
    assert args.page_size == 50
    assert args.max_pages == 2


def test_run_import_returns_serializable_quality_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()

    class FakeReport:
        source_id = "yahoo_regional_screener"
        received = 3
        accepted = 3
        rejected = 0
        inserted = 3
        updated = 0
        unchanged = 0
        deactivated = 0
        reconciliation_applied = False

    class FakeImporter:
        def __init__(self, **kwargs):
            pass

        def import_source(self, source):
            return FakeReport()

    class FakeMemberships:
        def __init__(self, database=None):
            pass

        def count_active_for_source(self, source_id):
            return 3

    class FakeQuality:
        def to_api_dict(self):
            return {
                "isGlobalReady": True,
                "globallyUsableCount": 3,
                "usableCoverage": 1.0,
            }

    class FakeUniverseService:
        def __init__(self, database=None):
            pass

        def get_quality_report(self):
            return FakeQuality()

    class FakeSource:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(module, "SourceAwareUniverseImportService", FakeImporter)
    monkeypatch.setattr(module, "InstrumentSourceMembershipRepository", FakeMemberships)
    monkeypatch.setattr(module, "PersistedMarketUniverseService", FakeUniverseService)
    monkeypatch.setattr(module, "YahooRegionalUniverseSource", FakeSource)

    result = module.run_import(
        database_path=tmp_path / "athena.db",
        regions=("us", "de", "jp"),
        page_size=10,
        max_pages=1,
    )

    quality = result["catalogQuality"]
    assert isinstance(quality, dict)
    assert quality["isGlobalReady"] is True
    assert quality["globallyUsableCount"] == 3
