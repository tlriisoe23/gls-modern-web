"""Deterministic unit tests for golf_engine pure helpers."""
import sqlite3

import pytest

from app import golf_engine as ge


@pytest.fixture
def mem_db():
    """Yields a fresh in-memory SQLite connection and closes it afterward."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_round_half_up():
    assert ge.round_half_up(2.5) == 3
    assert ge.round_half_up(2.49) == 2
    assert ge.round_half_up(-2.5) == -3


def test_safe_int():
    assert ge.safe_int(None) == 0
    assert ge.safe_int("10") == 10
    assert ge.safe_int(5.5) == 5
    assert ge.safe_int("invalid", default=2) == 2


def test_table_exists(mem_db):
    mem_db.execute("CREATE TABLE Test (id INTEGER)")
    assert ge.table_exists(mem_db, "Test") is True
    assert ge.table_exists(mem_db, "Missing") is False


def test_rows_as_dicts(mem_db):
    mem_db.execute("CREATE TABLE Users (id INTEGER, name TEXT)")
    mem_db.execute("INSERT INTO Users VALUES (1, 'Alice'), (2, 'Bob')")
    cur = mem_db.execute("SELECT * FROM Users")
    rows = ge.rows_as_dicts(cur)
    assert len(rows) == 2
    assert rows[0] == {"id": 1, "name": "Alice"}
    assert rows[1] == {"id": 2, "name": "Bob"}


def test_rows_as_dicts_empty(mem_db):
    mem_db.execute("CREATE TABLE Empty (id INTEGER)")
    cur = mem_db.execute("SELECT * FROM Empty")
    rows = ge.rows_as_dicts(cur)
    assert rows == []


@pytest.mark.xfail(strict=True, reason="Bug: stroke_index_map returns sorted rank order instead of per-hole rank (expected [3,1,4,2])")
def test_stroke_index_map():
    holes_meta = [
        {"stroke_index": 5},
        {"stroke_index": 1},
        {"stroke_index": 9},
        {"stroke_index": 3}
    ]
    ranks = ge.stroke_index_map(holes_meta)
    assert ranks == [3, 1, 4, 2]


def test_strokes_on_hole():
    # Example: player hcp 10, hole rank 5 (receives a stroke)
    assert ge.strokes_on_hole(10.0, 5, num_holes=18) == 1
    # Example: player hcp 20, hole rank 2 (receives two strokes)
    assert ge.strokes_on_hole(20.0, 2, num_holes=18) == 2
    # Edge case: zero handicap
    assert ge.strokes_on_hole(0.0, 1, num_holes=18) == 0
    # 9-hole league, player hcp 5, hole rank 3 -> 1 stroke
    assert ge.strokes_on_hole(5.0, 3, num_holes=9) == 1
    # Very high handicap
    assert ge.strokes_on_hole(40.0, 1, num_holes=18) == 3


def test_apply_esc_cap():
    # AdjustScores = 1 (Double Bogey Max)
    # par 4 + 2 = 6 max
    assert ge.apply_esc_cap(score=7, par=4, player_hcp=10, adjust_mode=1) == 6
    assert ge.apply_esc_cap(score=5, par=4, player_hcp=10, adjust_mode=1) == 5

    # AdjustScores = 2 (USGA Handicap ESC)
    # Course handicap 9 or less -> max 2 over par
    assert ge.apply_esc_cap(score=8, par=4, player_hcp=9, adjust_mode=2) == 6
    # Course handicap 10-19 -> max 7
    assert ge.apply_esc_cap(score=8, par=4, player_hcp=10, adjust_mode=2) == 7
    # Course handicap 20-29 -> max 8
    assert ge.apply_esc_cap(score=9, par=4, player_hcp=20, adjust_mode=2) == 8
    # Course handicap 30-39 -> max 9
    assert ge.apply_esc_cap(score=10, par=4, player_hcp=30, adjust_mode=2) == 9
    # Course handicap 40+ -> max 10
    assert ge.apply_esc_cap(score=12, par=4, player_hcp=40, adjust_mode=2) == 10

    # adjust_mode = 0 (No adjustment)
    assert ge.apply_esc_cap(score=15, par=4, player_hcp=10, adjust_mode=0) == 15


def test_hole_stableford_pts_characterization():
    # Characterization test based on what the function currently returns.
    assert ge.hole_stableford_pts(score=2, par=5) == 5   # -3
    assert ge.hole_stableford_pts(score=2, par=4) == 4   # -2
    assert ge.hole_stableford_pts(score=3, par=4) == 2   # -1 (Birdie returned 2)
    assert ge.hole_stableford_pts(score=4, par=4) == 1   # 0 (Par returned 1)
    assert ge.hole_stableford_pts(score=5, par=4) == 0   # +1 (Bogey returned 0)
    assert ge.hole_stableford_pts(score=6, par=4) == -1  # +2 (Double returned -1)
