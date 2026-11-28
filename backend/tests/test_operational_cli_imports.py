import importlib


def test_nasdaq_cli_imports_as_module() -> None:
    module = importlib.import_module("scripts.import_nasdaq_universe")
    parser = module.build_parser()
    args = parser.parse_args([])
    assert args.database is None


def test_yahoo_regional_cli_imports_as_module() -> None:
    module = importlib.import_module("scripts.import_yahoo_regional_universe")
    parser = module.build_parser()
    args = parser.parse_args([])
    assert args.page_size == 100
    assert args.max_pages == 1
