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
