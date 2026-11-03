"""Hermetic archive reconciliation and ECGC rules regression gates."""
import sqlite3
from collections import Counter

import pytest

from app import ecgc_importer as ei, match_engine as me

COUNTS = {
    "players": 128, "seasons": 18, "teams": 244, "team_members": 632,
    "events": 206, "matches": 1611, "rounds": 5521,
    "hole_scores": 49689, "standings": 698, "brackets": 11,
}


def archive_snapshot(conn):
    return {name: Counter(conn.execute(f'SELECT * FROM ecgc_{name}').fetchall()) for name in COUNTS}


def test_archive_reimport_is_lossless_and_idempotent(db_path, tmp_path):
    # Use only the bundled reconciled archive, never an external live database.
    source = tmp_path / "source.sqlite"
    brackets = tmp_path / "brackets.json"
    import json
    with sqlite3.connect(db_path) as conn, sqlite3.connect(source) as src:
        before = archive_snapshot(conn)
        for name, expected in COUNTS.items():
            assert sum(before[name].values()) == expected
        for name in ("players", "teams", "team_members", "events", "matches", "rounds", "hole_scores", "standings"):
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info(ecgc_{name})')]
            # Importer selects source columns explicitly, so the normalized archive
            # is a lossless local fixture for the original source schema.
            src.execute(f'CREATE TABLE league_{name} ({", ".join(chr(34)+c+chr(34) for c in columns)})')
            rows = list(conn.execute(f'SELECT * FROM ecgc_{name}'))
            src.executemany(f'INSERT INTO league_{name} VALUES ({",".join("?" for _ in columns)})', rows)
        conn.row_factory = sqlite3.Row
        bracket_rows = [dict(r) for r in conn.execute('SELECT * FROM ecgc_brackets')]
        # Match the original bracket manifest keys expected by the importer.
        brackets.write_text(json.dumps([{
            **r, "year": r["season_year"],
        } for r in bracket_rows]))
        src.commit()
        ei.import_ecgc_data(conn, source, brackets)
        conn.row_factory = None
        after = archive_snapshot(conn)
        for name in ("players", "teams", "events", "matches", "rounds", "hole_scores", "standings"):
            assert after[name] == before[name], name
        ei.import_ecgc_data(conn, source, brackets)
        assert archive_snapshot(conn) == after


@pytest.mark.parametrize("net,expected", [(34, 1), (35, 1), (36, 0), (37, -1)])
def test_net_bonus_boundaries(net, expected):
    assert me.compute_ecgc_pt(net) == expected


def test_both_partners_net_34_and_sub_credit():
    player = {"handicap": 0, "gross_scores": [4, 4, 4, 3, 5, 4, 4, 3, 3]}
    team = {"team_name": "Canonical Team", "player1": dict(player), "player2": {**player, "is_sub": True, "player_name": "SUB"}}
    result = me.score_ecgc_2person_match(team, team, ei.ECGC_HOLE_RANKS, ei.ECGC_PARS)
    assert result["team_a"]["player1"]["net_total"] == 34
    assert result["team_a"]["player2"]["net_total"] == 34
    assert result["team_a"]["pt_bonus_total"] == 2
    assert result["team_a"]["total_points"] == 6.5
    assert team["team_name"] == "Canonical Team"


@pytest.mark.parametrize("hcp,expected", [(-1, [0,0,0,0,0,0,0,0,-1]), (-3, [-1,0,0,0,0,0,0,-1,-1])])
def test_plus_handicap_easiest_holes(hcp, expected):
    assert me.strokes_per_hole(hcp, ei.ECGC_HOLE_RANKS, 9) == expected


@pytest.mark.parametrize("a,b,points", [(4,0,6.5), (0,4,2.5), (0,0,4.5)])
def test_team_differential(a, b, points):
    def team(hcp):
        return {"player1": {"handicap": hcp, "gross_scores": ei.ECGC_PARS}, "player2": {"handicap": 0, "gross_scores": ei.ECGC_PARS}}
    result = me.score_ecgc_2person_match(team(a), team(b), ei.ECGC_HOLE_RANKS, ei.ECGC_PARS)
    assert result["team_a"]["hole_points"] == points
    assert result["team_a"]["hole_points"] + result["team_b"]["hole_points"] == 9


def test_split_standings_playoffs_and_career_analytics(client, db_path):
    with sqlite3.connect(db_path) as conn:
        for split in ("first_half", "second_half", "final"):
            expected = conn.execute('SELECT COUNT(*) FROM ecgc_standings WHERE gls_league_id=20261 AND split_name=?', (split,)).fetchone()[0]
            rows = client.get('/api/ecgc/standings?league_id=20261').json()[split]
            assert len(rows) == expected > 0
        assert client.get('/api/ecgc/brackets').json()['count'] == 11
        players = client.get('/api/ecgc/players').json()['players']
        assert len(players) == 128
        for player in players:
            expected = conn.execute('SELECT COUNT(*), COALESCE(SUM(points_adjustment),0) FROM ecgc_rounds WHERE player_id=?', (player['id'],)).fetchone()
            assert player['career_rounds'] == expected[0]
            assert player['total_pt_points'] == round(expected[1], 1)
        pid = max(players, key=lambda p: p['career_rounds'])['id']
        profile = client.get(f'/api/ecgc/players/{pid}').json()
        assert sum(s['rounds_played'] for s in profile['season_summary']) == max(p['career_rounds'] for p in players)
        assert len(profile['rounds']) <= 50


@pytest.mark.parametrize('payload', [{'holes_count': 'bad'}, {'net_bonus_pts': []}, {'holes_count': None}])
def test_rules_config_rejects_bad_types(client, payload):
    assert client.post('/api/rules/config/20261', json=payload).status_code == 422


def test_rules_config_rejects_nonexistent_league(client):
    assert client.post('/api/rules/config/99999', json={}).status_code == 404


@pytest.mark.parametrize('payload', [{'team_a': []}, {'team_a': {'player1': {'gross_scores': ['bad'] * 9}}}, {'hole_ranks': [1]}, {'rules': []}])
def test_simulation_rejects_malformed_payloads(client, payload):
    assert client.post('/api/rules/simulate', json=payload).status_code == 422
