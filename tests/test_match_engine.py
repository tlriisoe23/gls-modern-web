from app import match_engine as me


def test_esc_cap():
    assert me.esc_cap(4, 5.0, 0) is None
    assert me.esc_cap(4, 5.0, 1) is None
    assert me.esc_cap(4, 5.0, 2) == 6
    assert me.esc_cap(5, 5.0, 2) == 7
    assert me.esc_cap(3, 9.0, 3) == 5
    assert me.esc_cap(4, 15.0, 3) == 7
    assert me.esc_cap(5, 25.0, 3) == 8
    assert me.esc_cap(3, 35.0, 3) == 9
    assert me.esc_cap(4, 45.0, 3) == 10


def test_apply_esc():
    holes = [3, 4, 5, 0, -1, 10, 8]
    pars =  [3, 4, 5, 3, 4,  4,  5]
    assert me.apply_esc(holes, pars, 15.0, 3) == [3, 4, 5, 0, 0, 7, 7]
    assert me.apply_esc(holes, pars, 5.0, 2) == [3, 4, 5, 0, 0, 6, 7]
    assert me.apply_esc(holes, pars, 15.0, 0) == [3, 4, 5, 0, 0, 10, 8]


def test_nine_ranks():
    # Example caps18: hole 1 has cap 17, hole 2 has cap 1, etc.
    caps18 = [17, 1, 15, 3, 13, 5, 11, 7, 9,
              18, 2, 16, 4, 14, 6, 12, 8, 10]
    assert me.nine_ranks(caps18, "front") == [9, 1, 8, 2, 7, 3, 6, 4, 5]
    assert me.nine_ranks(caps18, "back") == [9, 1, 8, 2, 7, 3, 6, 4, 5]


def test_strokes_per_hole():
    ranks = [9, 1, 8, 2, 7, 3, 6, 4, 5]
    assert me.strokes_per_hole(5.0, ranks, 9) == [0, 1, 0, 1, 0, 1, 0, 1, 1]
    assert me.strokes_per_hole(12.0, ranks, 9) == [1, 2, 1, 2, 1, 2, 1, 1, 1]
    assert me.strokes_per_hole(0.0, ranks, 9) == [0, 0, 0, 0, 0, 0, 0, 0, 0]


def test_stableford_points():
    matrix = me.MODIFIED_STABLEFORD_DEFAULT
    net_or_gross = [3, 4, 5, 6, 3, 4, 0, 10, 8]
    pars =         [4, 4, 4, 4, 3, 3, 3, 4,  5]
    # diffs: -1, 0, 1, 2, 0, 1, None, 6, 3
    # pts: 2, 0, -1, -3, 0, -1, 0, -3, -3
    assert me.stableford_points(net_or_gross, pars, matrix) == -9


def test_split_points():
    assert me.split_points(35.0, 36.0, 2.0) == (2.0, 0.0)
    assert me.split_points(36.0, 35.0, 2.0) == (0.0, 2.0)
    assert me.split_points(35.0, 35.0, 2.0) == (1.0, 1.0)
    assert me.split_points(35.0, 35.0, 0.0) == (0.0, 0.0)


def test_holes_won():
    a = [3, 4, 5, 0, 4]
    b = [4, 4, 4, 3, 0]
    aw, bw, codes = me.holes_won(a, b)
    assert aw == 1.5
    assert bw == 1.5
    assert codes == ["A", "T", "B", "-", "-"]


def test_field_points():
    entries = [(1, 35.0), (2, 36.0), (3, 36.0), (4, 38.0)]
    # Pool 0: 10
    # Pool 1 (ties): 9 + 8 = 17 / 2 = 8.5
    # Pool 2: 7
    res = me.field_points(entries, 10.0, 1.0)
    assert res == {1: 10.0, 2: 8.5, 3: 8.5, 4: 7.0}
    assert me.field_points([], 10.0, 1.0) == {}
    assert me.field_points([(1, 35.0)], 0.0, 1.0) == {}


def test_tee_times():
    assert me.tee_times(None, None, 3) == ["5:30 PM", "5:40 PM", "5:50 PM"]
    assert me.tee_times("04:00 PM", 15, 2) == ["4:00 PM", "4:15 PM"]
    assert me.tee_times("14:30", 8, 3) == ["2:30 PM", "2:38 PM", "2:46 PM"]
    assert me.tee_times("invalid", 10, 2) == ["5:30 PM", "5:40 PM"]
