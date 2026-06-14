"""Tests for jidou.main."""

import pytest

from jidou.main import main


def test_main_runs(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    captured = capsys.readouterr()
    assert "Hello from Jidou!" in captured.out
