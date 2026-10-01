import pytest
from pitwatch.cli import parse_args


def test_cli_argument_parsing():
    args = parse_args(["--year", "2024", "--round", "12", "--speed", "5.0", "--frames", "25", "--driver", "44"])
    assert args.year == 2024
    assert args.round == 12
    assert args.speed == 5.0
    assert args.frames == 25
    assert args.driver == 44
