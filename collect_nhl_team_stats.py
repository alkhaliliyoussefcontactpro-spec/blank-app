#!/usr/bin/env python3
"""Collecte NHL GameCenter PBP, statistiques par équipe et forme pré-match 5/10/15.

Source : API publique GameCenter NHL.
Dépendances : bibliothèque standard Python uniquement.
Relancer le script pour reprendre les matchs manquants et actualiser les scores récents.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "input" / "NHL_scores_60min_HISTORIQUE_COMPLET_21893.csv"
OUT = ROOT / "output_recent5_plus_current"
RAW_PATH = OUT / "nhl_team_game_stats.csv"
FORM_PATH = OUT / "nhl_team_form_prematch_5_10_15.csv"
FAIL_PATH = OUT / "nhl_failed_game_ids.csv"
COVERAGE_PATH = OUT / "nhl_coverage_by_season.csv"
REPORT_PATH = OUT / "README_nhl_team_data.txt"

FINAL_STATES = {"OFF", "FINAL", "FINAL_OT", "FINAL_SO"}
ATTEMPT_TYPES = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
SOG_TYPES = {"goal", "shot-on-goal"}
FENWICK_TYPES = {"goal", "shot-on-goal", "missed-shot"}
WINDOWS = (5, 10, 15)
MIN_SEASON = 2021  # 2021-22 through 2025-26: five complete seasons
MAX_SEASON = 2026  # include 2026-27 current season-to-date separately

RAW_FIELDS = [
    "game_id", "date", "season", "game_type", "team", "opponent", "home_away",
    "fetch_status", "goals_for_60", "goals_against_60",
    "goals_pbp_non_so_for", "goals_pbp_non_so_against",
    "shots_on_goal_for", "shots_on_goal_against",
    "missed_shots_for", "missed_shots_against",
    "blocked_attempts_for", "blocked_attempts_against",
    "corsi_for", "corsi_against", "fenwick_for", "fenwick_against",
    "corsi_5v5_for", "corsi_5v5_against",
    "fenwick_5v5_for", "fenwick_5v5_against",
    "hits", "giveaways", "takeaways", "faceoff_wins", "faceoff_losses", "penalties",
    "api_sog_total", "pbp_sog_matches_api",
    "event_stats_quality",
    "attempt_events", "attempt_events_without_situation",
    "situation_code_attempt_coverage", "five_v_five_complete",
    "pbp_events_total",
]

BASE_ROLL_METRICS = [
    "goals_for_60", "goals_against_60",
    "shots_on_goal_for", "shots_on_goal_against",
    "missed_shots_for", "missed_shots_against",
    "blocked_attempts_for", "blocked_attempts_against",
    "corsi_for", "corsi_against", "fenwick_for", "fenwick_against",
    "hits", "giveaways", "takeaways", "faceoff_wins", "faceoff_losses", "penalties",
]
FIVE_V_FIVE_METRICS = [
    "corsi_5v5_for", "corsi_5v5_against",
    "fenwick_5v5_for", "fenwick_5v5_against",
]


def as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_json(url, attempts=4, timeout=45):
    last_error = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "NHLTeamFormResearch/0.1",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = min(20.0, float(retry_after)) if retry_after else 1.5 * (attempt + 1)
            except ValueError:
                delay = 1.5 * (attempt + 1)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def read_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def append_csv(path, rows, fields):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    need_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if need_header:
            writer.writeheader()
        writer.writerows(rows)


def normalize_game_id(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip()


def game_type(game_id):
    return game_id[4:6] if len(game_id) >= 6 else ""


def load_source_games():
    if not INPUT.exists():
        raise FileNotFoundError(f"Fichier source introuvable : {INPUT}")
    rows = read_csv(INPUT)
    games = {}
    for row in rows:
        gid = normalize_game_id(row.get("game_id"))
        if not gid:
            continue
        row = dict(row)
        row["game_id"] = gid
        row["date"] = row.get("date", "")[:10]
        row["season"] = as_int(row.get("season")) or as_int(gid[:4])
        row["game_type"] = game_type(gid)
        if row["game_type"] == "02" and MIN_SEASON <= row["season"] <= MAX_SEASON:
            games[gid] = row
    return games


def add_recent_completed_games(games, existing_stats):
    archive_dates = [r["date"] for r in games.values() if r.get("date")]
    if not archive_dates:
        return 0, []
    archive_latest = date.fromisoformat(max(archive_dates))

    existing_dates = [
        r.get("date", "")[:10]
        for r in existing_stats
        if r.get("date")
    ]
    start = archive_latest + timedelta(days=1)
    if existing_dates:
        latest_output = date.fromisoformat(max(existing_dates))
        refresh_start = latest_output - timedelta(days=7)
        if refresh_start > start:
            start = refresh_start

    today = datetime.now(timezone.utc).date()
    if start > today:
        return 0, []

    dates = []
    current = start
    while current <= today:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    failures = []

    def fetch_scoreboard(day):
        try:
            data = get_json(f"https://api-web.nhle.com/v1/score/{day}", attempts=3, timeout=30)
            return day, data.get("games", []), None
        except Exception as exc:
            return day, [], f"{type(exc).__name__}: {exc}"

    fetched = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(dates)))) as pool:
        futures = [pool.submit(fetch_scoreboard, day) for day in dates]
        for future in as_completed(futures):
            day, day_games, error = future.result()
            if error:
                failures.append({"game_id": "", "date": day, "error": "score endpoint: " + error})
                continue
            for game in day_games:
                gid = normalize_game_id(game.get("id"))
                state = str(game.get("gameState", "")).upper()
                if not gid or game_type(gid) != "02" or state not in FINAL_STATES:
                    continue
                home = game.get("homeTeam", {})
                away = game.get("awayTeam", {})
                home_abbrev = home.get("abbrev", "")
                away_abbrev = away.get("abbrev", "")
                if isinstance(home_abbrev, dict):
                    home_abbrev = home_abbrev.get("default", "")
                if isinstance(away_abbrev, dict):
                    away_abbrev = away_abbrev.get("default", "")
                fetched.append({
                    "game_id": gid,
                    "date": game.get("gameDate", day),
                    "season": as_int(gid[:4]),
                    "game_type": "02",
                    "home_team": home_abbrev,
                    "away_team": away_abbrev,
                    "home_60": "",
                    "away_60": "",
                })

    added = 0
    for row in fetched:
        gid = row["game_id"]
        if gid not in games:
            games[gid] = row
            added += 1
    return added, failures


def empty_counters():
    return {
        "goals_pbp_non_so": 0,
        "shots_on_goal_for": 0,
        "missed_shots_for": 0,
        "blocked_attempts_for": 0,
        "corsi_for": 0,
        "corsi_against": 0,
        "fenwick_for": 0,
        "fenwick_against": 0,
        "corsi_5v5_for": 0,
        "corsi_5v5_against": 0,
        "fenwick_5v5_for": 0,
        "fenwick_5v5_against": 0,
        "goals_regulation": 0,
        "hits": 0,
        "giveaways": 0,
        "takeaways": 0,
        "faceoff_wins": 0,
        "faceoff_losses": 0,
        "penalties": 0,
    }


def roster_team_map(roster):
    result = {}
    for player in roster or []:
        pid = as_int(player.get("playerId"))
        tid = as_int(player.get("teamId"))
        if pid is not None and tid is not None:
            result[pid] = tid
    return result


def make_team_rows(meta, home_stats, away_stats, home_id, away_id,
                   home_sog_api, away_sog_api, attempt_events,
                   missing_situation, situation_covered, unassigned_attempts,
                   event_count, regulation_goals):
    home_60 = as_int(meta.get("home_60"))
    away_60 = as_int(meta.get("away_60"))
    if home_60 is None:
        home_60 = regulation_goals.get(home_id, 0)
    if away_60 is None:
        away_60 = regulation_goals.get(away_id, 0)

    five_complete = (
        attempt_events > 0
        and missing_situation == 0
        and unassigned_attempts == 0
        and situation_covered == attempt_events
    )
    coverage = (situation_covered / attempt_events) if attempt_events else None

    team_meta = [
        (home_id, "home", meta.get("home_team", ""), meta.get("away_team", ""),
         home_stats, away_stats, home_60, away_60, home_sog_api),
        (away_id, "away", meta.get("away_team", ""), meta.get("home_team", ""),
         away_stats, home_stats, away_60, home_60, away_sog_api),
    ]
    out = []
    for tid, side, team, opponent, own, other, goals_for_60, goals_against_60, api_sog in team_meta:
        row = {
            "game_id": meta["game_id"],
            "date": meta.get("date", ""),
            "season": meta.get("season", ""),
            "game_type": meta.get("game_type", "02"),
            "team": team,
            "opponent": opponent,
            "home_away": side,
            "fetch_status": "ok",
            "goals_for_60": goals_for_60,
            "goals_against_60": goals_against_60,
            "goals_pbp_non_so_for": own["goals_pbp_non_so"],
            "goals_pbp_non_so_against": other["goals_pbp_non_so"],
            "shots_on_goal_for": own["shots_on_goal_for"],
            "shots_on_goal_against": other["shots_on_goal_for"],
            "missed_shots_for": own["missed_shots_for"],
            "missed_shots_against": other["missed_shots_for"],
            "blocked_attempts_for": own["blocked_attempts_for"],
            "blocked_attempts_against": other["blocked_attempts_for"],
            "corsi_for": own["corsi_for"],
            "corsi_against": own["corsi_against"],
            "fenwick_for": own["fenwick_for"],
            "fenwick_against": own["fenwick_against"],
            "corsi_5v5_for": own["corsi_5v5_for"] if five_complete else None,
            "corsi_5v5_against": own["corsi_5v5_against"] if five_complete else None,
            "fenwick_5v5_for": own["fenwick_5v5_for"] if five_complete else None,
            "fenwick_5v5_against": own["fenwick_5v5_against"] if five_complete else None,
            "hits": own["hits"],
            "giveaways": own["giveaways"],
            "takeaways": own["takeaways"],
            "faceoff_wins": own["faceoff_wins"],
            "faceoff_losses": own["faceoff_losses"],
            "penalties": own["penalties"],
            "api_sog_total": api_sog,
            "pbp_sog_matches_api": (
                int(api_sog) == own["shots_on_goal_for"] if api_sog is not None else None
            ),
            "attempt_events": attempt_events,
            "attempt_events_without_situation": missing_situation,
            "situation_code_attempt_coverage": coverage,
            "five_v_five_complete": int(five_complete),
            "pbp_events_total": event_count,
        }
        out.append(row)
    return out


def parse_pbp(meta, pbp):
    home_id = as_int(pbp.get("homeTeam", {}).get("id"))
    away_id = as_int(pbp.get("awayTeam", {}).get("id"))
    if home_id is None or away_id is None or home_id == away_id:
        raise ValueError("Identifiants homeTeam/awayTeam absents ou invalides")

    stats = {home_id: empty_counters(), away_id: empty_counters()}
    roster_map = roster_team_map(pbp.get("rosterSpots", []))
    attempt_events = 0
    missing_situation = 0
    situation_covered = 0
    unassigned_attempts = 0
    event_count = 0

    for play in pbp.get("plays", []):
        event_count += 1
        period_type = str(play.get("periodDescriptor", {}).get("periodType", "")).upper()
        if period_type == "SO":
            continue

        event = str(play.get("typeDescKey", "")).lower()
        details = play.get("details", {}) or {}
        owner = as_int(details.get("eventOwnerTeamId"))

        if event in ATTEMPT_TYPES:
            attempt_events += 1
            situation = play.get("situationCode")
            if situation is None or str(situation).strip() == "":
                missing_situation += 1
            else:
                situation_covered += 1

            if owner not in stats:
                player_id = None
                if event == "goal":
                    player_id = as_int(details.get("scoringPlayerId"))
                else:
                    player_id = as_int(details.get("shootingPlayerId"))
                owner = roster_map.get(player_id)

            if owner not in stats:
                unassigned_attempts += 1
                continue

            own = stats[owner]
            other_id = away_id if owner == home_id else home_id
            other = stats[other_id]
            own["corsi_for"] += 1
            other["corsi_against"] += 1

            if event in SOG_TYPES:
                own["shots_on_goal_for"] += 1
            if event == "missed-shot":
                own["missed_shots_for"] += 1
            if event == "blocked-shot":
                own["blocked_attempts_for"] += 1
            if event in FENWICK_TYPES:
                own["fenwick_for"] += 1
                other["fenwick_against"] += 1
            if event == "goal":
                own["goals_pbp_non_so"] += 1
                other["goals_pbp_non_so"] += 0
                if period_type == "REG":
                    own["goals_regulation"] += 1

            if str(situation).strip() == "1551":
                own["corsi_5v5_for"] += 1
                other["corsi_5v5_against"] += 1
                if event in FENWICK_TYPES:
                    own["fenwick_5v5_for"] += 1
                    other["fenwick_5v5_against"] += 1

        elif event in {"hit", "giveaway", "takeaway", "penalty"}:
            if owner not in stats:
                continue
            if event == "hit":
                stats[owner]["hits"] += 1
            elif event == "giveaway":
                stats[owner]["giveaways"] += 1
            elif event == "takeaway":
                stats[owner]["takeaways"] += 1
            else:
                stats[owner]["penalties"] += 1

        elif event == "faceoff":
            winner = roster_map.get(as_int(details.get("winningPlayerId")))
            loser = roster_map.get(as_int(details.get("losingPlayerId")))
            if winner in stats and loser in stats and winner != loser:
                stats[winner]["faceoff_wins"] += 1
                stats[loser]["faceoff_losses"] += 1

    home_team_obj = pbp.get("homeTeam", {})
    away_team_obj = pbp.get("awayTeam", {})
    home_sog_api = as_int(home_team_obj.get("sog"))
    away_sog_api = as_int(away_team_obj.get("sog"))
    regulation_goals = {
        home_id: stats[home_id]["goals_regulation"],
        away_id: stats[away_id]["goals_regulation"],
    }
    return make_team_rows(
        meta, stats[home_id], stats[away_id], home_id, away_id,
        home_sog_api, away_sog_api, attempt_events,
        missing_situation, situation_covered, unassigned_attempts,
        event_count, regulation_goals,
    )


def legacy_scores_only(meta):
    home_60 = as_int(meta.get("home_60"))
    away_60 = as_int(meta.get("away_60"))
    rows = []
    for side, team, opponent, goals_for, goals_against in (
        ("home", meta.get("home_team", ""), meta.get("away_team", ""), home_60, away_60),
        ("away", meta.get("away_team", ""), meta.get("home_team", ""), away_60, home_60),
    ):
        row = {field: None for field in RAW_FIELDS}
        row.update({
            "game_id": meta["game_id"],
            "date": meta.get("date", ""),
            "season": meta.get("season", ""),
            "game_type": meta.get("game_type", "02"),
            "team": team,
            "opponent": opponent,
            "home_away": side,
            "fetch_status": "legacy_scores_only",
            "goals_for_60": goals_for,
            "goals_against_60": goals_against,
            "five_v_five_complete": 0,
        })
        rows.append(row)
    return rows


def fetch_one(meta):
    gid = meta["game_id"]
    try:
        data = get_json(
            f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play",
            attempts=4,
            timeout=45,
        )
        return gid, parse_pbp(meta, data), None
    except Exception as exc:
        return gid, [], {
            "game_id": gid,
            "date": meta.get("date", ""),
            "error": f"{type(exc).__name__}: {exc}",
        }


def event_stats_are_trusted(row):
    return (
        row.get("fetch_status") == "ok"
        and row.get("event_stats_quality") == "PBP_SOG_MATCH"
    )


def label_event_quality(rows):
    by_game = defaultdict(list)
    for row in rows:
        by_game[row.get("game_id", "")].append(row)
    for game_rows in by_game.values():
        statuses = {row.get("fetch_status") for row in game_rows}
        comparisons = [str(row.get("pbp_sog_matches_api", "")).lower() for row in game_rows]
        if statuses == {"legacy_scores_only"}:
            quality = "SCORE_ONLY_LEGACY"
        elif "false" in comparisons or "0" in comparisons:
            quality = "PBP_SOG_MISMATCH"
        elif statuses == {"ok"} and all(value in {"true", "1"} for value in comparisons):
            quality = "PBP_SOG_MATCH"
        else:
            quality = "PBP_SOG_UNVERIFIED"
        for row in game_rows:
            row["event_stats_quality"] = quality
    return rows


def numeric_average(rows, field, official_sog_lookup):
    values = [metric_value(row, field, official_sog_lookup) for row in rows]
    values = [value for value in values if value is not None]
    return mean(values) if values else None


def metric_value(row, field, official_sog_lookup):
    if field in {"goals_for_60", "goals_against_60"}:
        return as_float(row.get(field))
    if field == "shots_on_goal_for":
        official = as_float(row.get("api_sog_total"))
        return official if official is not None else None
    if field == "shots_on_goal_against":
        official = official_sog_lookup.get((row.get("game_id"), row.get("opponent")))
        return official if official is not None else None
    if not event_stats_are_trusted(row):
        return None
    return as_float(row.get(field))


def sum_pair(rows, left, right, official_sog_lookup):
    pairs = []
    for row in rows:
        a = metric_value(row, left, official_sog_lookup)
        b = metric_value(row, right, official_sog_lookup)
        if a is not None and b is not None:
            pairs.append((a, b))
    if not pairs:
        return None, None, 0
    return sum(a for a, _ in pairs), sum(b for _, b in pairs), len(pairs)


def build_form_rows(team_rows):
    valid = label_event_quality([
        dict(r) for r in team_rows
        if r.get("fetch_status") in {"ok", "legacy_scores_only"}
    ])
    valid.sort(key=lambda r: (r.get("team", ""), str(r.get("season", "")), r.get("date", ""), r.get("game_id", "")))
    official_sog_lookup = {
        (row.get("game_id"), row.get("team")): as_float(row.get("api_sog_total"))
        for row in valid
        if as_float(row.get("api_sog_total")) is not None
    }

    form_fields = [
        "game_id", "date", "season", "game_type", "team", "opponent",
        "home_away", "fetch_status", "event_stats_quality",
    ]
    for window in WINDOWS:
        form_fields.extend([
            f"prior_games_last{window}",
            f"valid_event_games_last{window}",
            f"valid_5v5_games_last{window}",
        ])
        for metric in BASE_ROLL_METRICS:
            form_fields.append(f"avg_{metric}_last{window}")
        for metric in FIVE_V_FIVE_METRICS:
            form_fields.append(f"avg_{metric}_last{window}")
        form_fields.extend([
            f"corsi_share_last{window}",
            f"fenwick_share_last{window}",
            f"corsi_5v5_share_last{window}",
            f"fenwick_5v5_share_last{window}",
            f"faceoff_win_pct_last{window}",
        ])

    grouped = defaultdict(list)
    for row in valid:
        grouped[(row.get("team", ""), str(row.get("season", "")), row.get("game_type", "02"))].append(row)

    output = []
    for group_rows in grouped.values():
        group_rows.sort(key=lambda r: (r.get("date", ""), r.get("game_id", "")))
        history = []
        for current in group_rows:
            form = {field: current.get(field, "") for field in form_fields[:9]}
            for window in WINDOWS:
                prior = history[-window:]
                event_rows = [row for row in prior if event_stats_are_trusted(row)]
                form[f"prior_games_last{window}"] = len(prior)
                form[f"valid_event_games_last{window}"] = len(event_rows)
                five_rows = [
                    row for row in prior
                    if event_stats_are_trusted(row)
                    if as_float(row.get("corsi_5v5_for")) is not None
                    and as_float(row.get("corsi_5v5_against")) is not None
                ]
                form[f"valid_5v5_games_last{window}"] = len(five_rows)

                for metric in BASE_ROLL_METRICS:
                    source_rows = prior if metric in {"goals_for_60", "goals_against_60", "shots_on_goal_for", "shots_on_goal_against"} else event_rows
                    form[f"avg_{metric}_last{window}"] = numeric_average(source_rows, metric, official_sog_lookup)
                for metric in FIVE_V_FIVE_METRICS:
                    form[f"avg_{metric}_last{window}"] = numeric_average(five_rows, metric, official_sog_lookup)

                for name, left, right in (
                    ("corsi_share", "corsi_for", "corsi_against"),
                    ("fenwick_share", "fenwick_for", "fenwick_against"),
                    ("corsi_5v5_share", "corsi_5v5_for", "corsi_5v5_against"),
                    ("fenwick_5v5_share", "fenwick_5v5_for", "fenwick_5v5_against"),
                    ("faceoff_win_pct", "faceoff_wins", "faceoff_losses"),
                ):
                    source_rows = five_rows if "5v5" in name else event_rows
                    a, b, n = sum_pair(source_rows, left, right, official_sog_lookup)
                    form[f"{name}_last{window}"] = (a / (a + b)) if n and a + b else None

            output.append(form)
            history.append(current)

    output.sort(key=lambda r: (r.get("date", ""), r.get("game_id", ""), r.get("team", "")))
    return output, form_fields


def build_coverage(team_rows):
    by_season = defaultdict(list)
    for row in team_rows:
        by_season[str(row.get("season", ""))].append(row)
    rows = []
    for season, entries in sorted(by_season.items()):
        by_game = defaultdict(list)
        for row in entries:
            by_game[row.get("game_id", "")].append(row)
        games = list(by_game.values())
        statuses = Counter((g[0].get("fetch_status", "") if g else "") for g in games)
        quality_counts = Counter((g[0].get("event_stats_quality", "") if g else "") for g in games)
        five_complete = sum(
            1 for g in games if g and str(g[0].get("five_v_five_complete", "")) == "1"
        )
        sog_evaluable = [
            row for row in entries if row.get("pbp_sog_matches_api") not in (None, "")
        ]
        sog_matches = sum(str(row.get("pbp_sog_matches_api")).lower() in {"1", "true"} for row in sog_evaluable)
        sog_mismatches = sum(str(row.get("pbp_sog_matches_api")).lower() in {"0", "false"} for row in sog_evaluable)
        rows.append({
            "season": season,
            "games_in_dataset": len(games),
            "games_pbp_ok": statuses.get("ok", 0),
            "games_legacy_scores_only": statuses.get("legacy_scores_only", 0),
            "games_pbp_sog_match": quality_counts.get("PBP_SOG_MATCH", 0),
            "games_pbp_sog_mismatch": quality_counts.get("PBP_SOG_MISMATCH", 0),
            "games_five_v_five_complete": five_complete,
            "team_rows_with_sog_api_comparison": len(sog_evaluable),
            "team_rows_sog_match_api": sog_matches,
            "team_rows_sog_mismatch_api": sog_mismatches,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="Limite optionnelle pour une collecte partielle")
    args = parser.parse_args()
    if not 1 <= args.workers <= 32:
        raise SystemExit("--workers doit être compris entre 1 et 32")

    OUT.mkdir(parents=True, exist_ok=True)
    games = load_source_games()
    existing_stats = read_csv(RAW_PATH)
    recent_added, score_failures = add_recent_completed_games(games, existing_stats)
    print(f"Matchs regular season dans l'archive : {len(games) - recent_added:,}")
    print(f"Nouveaux matchs terminés trouvés via NHL Score : {recent_added:,}")
    if score_failures:
        print(f"Jours scoreboard non lus : {len(score_failures)}")

    existing_by_game = defaultdict(list)
    for row in existing_stats:
        if row.get("game_id"):
            existing_by_game[row["game_id"]].append(row)
    completed = {
        gid for gid, rows in existing_by_game.items()
        if len(rows) >= 2 and all(r.get("fetch_status") in {"ok", "legacy_scores_only"} for r in rows[:2])
    }

    new_legacy = []
    for gid, meta in games.items():
        if gid not in completed and as_int(meta.get("season")) == 2008:
            new_legacy.extend(legacy_scores_only(meta))
            completed.add(gid)
    if new_legacy:
        append_csv(RAW_PATH, new_legacy, RAW_FIELDS)
        existing_stats.extend(new_legacy)
        print(f"Saison 2008 : {len(new_legacy)//2:,} matchs conservés avec scores seulement (PBP incomplet).")

    pending = [
        meta for gid, meta in games.items()
        if gid not in completed and as_int(meta.get("season")) != 2008
    ]
    pending.sort(key=lambda r: (r.get("date", ""), r["game_id"]))
    if args.limit and args.limit > 0:
        pending = pending[:args.limit]
    print(f"Matchs PBP à récupérer : {len(pending):,} ; threads : {args.workers}", flush=True)

    failures = list(score_failures)
    successful = 0
    processed = 0
    buffer = []
    started = time.monotonic()
    flush_every = 100

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for batch_start in range(0, len(pending), 250):
            batch = pending[batch_start:batch_start + 250]
            futures = [pool.submit(fetch_one, meta) for meta in batch]
            for future in as_completed(futures):
                gid, rows, error = future.result()
                processed += 1
                if error:
                    failures.append(error)
                else:
                    buffer.extend(rows)
                    successful += 1
                    completed.add(gid)

                if len(buffer) >= flush_every * 2:
                    append_csv(RAW_PATH, buffer, RAW_FIELDS)
                    existing_stats.extend(buffer)
                    buffer.clear()

                if processed % 250 == 0 or processed == len(pending):
                    elapsed = max(0.1, time.monotonic() - started)
                    speed = processed / elapsed
                    print(
                        f"Progression PBP : {processed:,}/{len(pending):,} | "
                        f"réussis {successful:,} | échecs {len(failures):,} | "
                        f"{speed:.2f} matchs/s",
                        flush=True,
                    )
            if buffer:
                append_csv(RAW_PATH, buffer, RAW_FIELDS)
                existing_stats.extend(buffer)
                buffer.clear()
            if failures:
                write_csv_atomic(FAIL_PATH, failures, ["game_id", "date", "error"])

    # Le fichier brut est réordonné et réécrit pour faciliter les reprises et les analyses.
    all_stats = read_csv(RAW_PATH)
    all_stats = label_event_quality(all_stats)
    all_stats.sort(key=lambda r: (r.get("date", ""), r.get("game_id", ""), r.get("home_away", "")))
    write_csv_atomic(RAW_PATH, all_stats, RAW_FIELDS)

    form_rows, form_fields = build_form_rows(all_stats)
    write_csv_atomic(FORM_PATH, form_rows, form_fields)
    coverage = build_coverage(all_stats)
    write_csv_atomic(COVERAGE_PATH, coverage, [
        "season", "games_in_dataset", "games_pbp_ok", "games_legacy_scores_only",
        "games_pbp_sog_match", "games_pbp_sog_mismatch",
        "games_five_v_five_complete", "team_rows_with_sog_api_comparison",
        "team_rows_sog_match_api", "team_rows_sog_mismatch_api",
    ])

    failed_game_ids = {f.get("game_id") for f in failures if f.get("game_id")}
    result_game_ids = {r.get("game_id") for r in all_stats}
    sog_mismatch_game_ids = {
        r.get("game_id") for r in all_stats
        if r.get("event_stats_quality") == "PBP_SOG_MISMATCH"
    }
    missing = sorted(set(games) - result_game_ids)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_archive": INPUT.name,
        "source_archive_games": len(load_source_games()),
        "recent_completed_games_added_this_run": recent_added,
        "games_with_team_stats": len(result_game_ids),
        "team_rows": len(all_stats),
        "form_rows": len(form_rows),
        "failed_game_ids": len(failed_game_ids),
        "missing_game_ids": len(missing),
        "games_pbp_sog_mismatch_excluded_from_event_windows": len(sog_mismatch_game_ids),
        "pending_after_limit": bool(args.limit and len(pending) < len(games)),
        "files": {
            "team_game_stats": RAW_PATH.name,
            "prematch_form": FORM_PATH.name,
            "coverage_by_season": COVERAGE_PATH.name,
            "failures": FAIL_PATH.name if failures else None,
        },
        "definitions": {
            "regular_season_only": True,
            "shootout_events_excluded": True,
            "overtime_events_kept_for_shots_and_events": True,
            "goals_for_60_from_archive_or_regulation_goals": True,
            "strict_5v5_situation_code": "1551",
            "defensive_blocked_shots_excluded": True,
            "rolling_windows_reset_each_season": True,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        f.write("DONNÉES NHL — NIVEAU DE JEU DES ÉQUIPES\n")
        f.write("=" * 44 + "\n\n")
        f.write(f"Date de génération (UTC) : {report['generated_at_utc']}\n")
        f.write("Période : saisons 2021-22 à 2025-26, plus 2026-27 en cours.\n")
        f.write(f"Matchs réguliers dans l’archive : {report['source_archive_games']:,}\n")
        f.write(f"Nouveaux matchs terminés ajoutés : {recent_added:,}\n")
        f.write(f"Matchs avec statistiques d’équipe : {len(result_game_ids):,}\n")
        f.write(f"Lignes équipe-match : {len(all_stats):,}\n")
        f.write(f"Lignes de forme pré-match : {len(form_rows):,}\n")
        f.write(f"Échecs d’API / matchs manquants : {len(failed_game_ids):,} / {len(missing):,}\n")
        f.write(f"Matchs PBP discordants écartés des variables d’événements : {len(sog_mismatch_game_ids):,}\n\n")
        f.write("DÉFINITIONS\n")
        f.write("- Corsi : buts + tirs cadrés + tirs manqués + tentatives bloquées.\n")
        f.write("- Fenwick : buts + tirs cadrés + tirs manqués.\n")
        f.write("- 5 contre 5 : uniquement les événements portant le code de situation 1551.\n")
        f.write("- Tentatives bloquées : tirs bloqués de l’équipe qui tire; les blocs défensifs sont exclus.\n")
        f.write("- Les tirs et événements d’OT sont conservés; les tirs de fusillade sont exclus.\n")
        f.write("- Les buts de forme utilisent le score après 60 minutes.\n")
        f.write("- Les moyennes 5/10/15 n’utilisent que les matchs antérieurs de la même saison.\n")
        f.write("- Si moins de 5/10/15 matchs sont disponibles, la moyenne utilise les matchs antérieurs disponibles; le nombre figure dans prior_games_lastN.\n\n")
        f.write("LIMITES DE COUVERTURE\n")
        f.write("- Saison 2008 : l’échantillon NHL PBP consulté ne contient pas les catégories d’événements nécessaires; seuls les buts à 60 minutes sont conservés.\n")
        f.write("- Les statistiques 5v5 sont laissées vides si le code de situation manque sur au moins une tentative du match.\n")
        f.write("- Les statistiques d’événements PBP n’entrent dans les fenêtres que si les tirs cadrés PBP concordent avec le total NHL GameCenter. Le total officiel des tirs cadrés reste utilisable séparément.\n")
        f.write("- Cette base valide l’extraction et construit les indicateurs; elle ne valide pas encore leur pouvoir prédictif.\n")
        f.write("- Aucun flux MoneyPuck ni cote de bookmaker n’est utilisé.\n\n")
        f.write("FICHIERS\n")
        f.write(f"- {RAW_PATH.name} : deux lignes par match, une par équipe.\n")
        f.write(f"- {FORM_PATH.name} : forme pré-match 5/10/15, une ligne par équipe et match.\n")
        f.write(f"- {COVERAGE_PATH.name} : couverture des données par saison.\n")
        if failures:
            f.write(f"- {FAIL_PATH.name} : requêtes à reprendre lors de la prochaine exécution.\n")

    if failures:
        write_csv_atomic(FAIL_PATH, failures, ["game_id", "date", "error"])
    print(f"Terminé. Statistiques : {RAW_PATH}")
    print(f"Forme pré-match : {FORM_PATH}")
    print(f"Couverture : {COVERAGE_PATH}")
    print(f"Rapport : {REPORT_PATH}")
    print(
        f"Résumé : {len(result_game_ids):,} matchs disponibles; "
        f"{len(failed_game_ids):,} échecs; {len(missing):,} manquants."
    )


if __name__ == "__main__":
    main()

