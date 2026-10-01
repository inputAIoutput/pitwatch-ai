import pytest
from pitwatch.cli import parse_args


def test_cli_argument_parsing():
    args = parse_args(["--year", "2024", "--round", "12", "--speed", "5.0", "--frames", "25", "--driver", "44", "--lap", "1"])
    assert args.year == 2024
    assert args.round == 12
    assert args.speed == 5.0
    assert args.frames == 25
    assert args.driver == 44
    assert args.lap == 1
    assert not args.serve


def test_cli_serve_argument_parsing():
    args = parse_args(["--serve", "--host", "0.0.0.0", "--port", "8000"])
    assert args.serve is True
    assert args.host == "0.0.0.0"
    assert args.port == 8000

