#!/usr/bin/env python3
"""Run the NHL collector and refresh the files read by the Streamlit dashboard."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import collect_nhl_team_stats as collector


ROOT = Path(__file__).resolve().parent
COLLECTOR_PATH = ROOT / "collect_nhl_team_stats.py"
RAW_SOURCE = ROOT / "output_recent5_plus_current" / "nhl_team_game_stats.csv"
APP_RAW_PATH = ROOT / "nhl_team_game_stats.csv"
APP_FORM_PATH = ROOT / "nhl_current_team_form.csv"
WINDOWS = (5, 10, 15)


def cell(value):
    """Format values for CSV; blank means unavailable, never the string 'None'."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return value


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def snapshot_fields():
    fields = [
        "season", "as_of_date", "team", "matches_played_season", "last_game_date"
    ]
    for window in WINDOWS:
        fields.extend([
            f"matches_in_last{window}",
            f"valid_pbp_games_last{window}",
            f"valid_5v5_games_last{window}",
            f"avg_goals_for_60_last{window}",
            f"avg_goals_against_60_last{window}",
            f"avg_sog_for_last{window}",
            f"avg_sog_against_last{window}",
            f"avg_corsi_for_last{window}",
            f"avg_corsi_against_last{window}",
            f"corsi_share_pct_last{window}",
            f"avg_fenwick_for_last{window}",
            f"avg_fenwick_against_last{window}",
            f"fenwick_share_pct_last{window}",
            f"corsi_5v5_share_pct_last{window}",
            f"fenwick_5v5_share_pct_last{window}",
            f"faceoff_win_pct_last{window}",
            f"avg_hits_last{window}",
            f"avg_giveaways_last{window}",
            f"avg_takeaways_last{window}",
            f"avg_penalties_last{window}",
        ])
    return fields


def make_current_form(raw_rows):
    usable = collector.label_event_quality([
        dict(row)
        for row in raw_rows
        if row.get("fetch_status") in {"ok", "legacy_scores_only"}
    ])
    regular = [row for row in usable if row.get("game_type", "02") == "02"]
    seasons = [collector.as_int(row.get("season")) for row in regular]
    seasons = [season for season in seasons if season is not None]
    if not seasons:
        raise RuntimeError("Aucune statistique de saison régulière exploitable.")

    current_season = max(seasons)
    season_rows = [
        row for row in regular
        if collector.as_int(row.get("season")) == current_season
    ]
    if not season_rows:
        raise RuntimeError("Aucun match trouvé pour la saison la plus récente.")

    as_of_date = max((row.get("date", "") for row in season_rows), default="")
    official_sog_lookup = {
        (row.get("game_id"), row.get("team")):
            collector.as_float(row.get("api_sog_total"))
        for row in season_rows
        if collector.as_float(row.get("api_sog_total")) is not None
    }

    by_team = defaultdict(list)
    for row in season_rows:
        if row.get("team"):
            by_team[row["team"]].append(row)

    output = []
    for team, history in sorted(by_team.items()):
        history.sort(key=lambda row: (row.get("date", ""), row.get("game_id", "")))
        record = {
            "season": current_season,
            "as_of_date": as_of_date,
            "team": team,
            "matches_played_season": len(history),
            "last_game_date": history[-1].get("date", ""),
        }

        for window in WINDOWS:
            recent = history[-window:]
            event_rows = [row for row in recent if collector.event_stats_are_trusted(row)]
            five_rows = [
                row for row in event_rows
                if collector.as_float(row.get("corsi_5v5_for")) is not None
                and collector.as_float(row.get("corsi_5v5_against")) is not None
            ]

            record[f"matches_in_last{window}"] = len(recent)
            record[f"valid_pbp_games_last{window}"] = len(event_rows)
            record[f"valid_5v5_games_last{window}"] = len(five_rows)

            for output_name, source_name in (
                (f"avg_goals_for_60_last{window}", "goals_for_60"),
                (f"avg_goals_against_60_last{window}", "goals_against_60"),
                (f"avg_sog_for_last{window}", "shots_on_goal_for"),
                (f"avg_sog_against_last{window}", "shots_on_goal_against"),
                (f"avg_corsi_for_last{window}", "corsi_for"),
                (f"avg_corsi_against_last{window}", "corsi_against"),
                (f"avg_fenwick_for_last{window}", "fenwick_for"),
                (f"avg_fenwick_against_last{window}", "fenwick_against"),
                (f"avg_hits_last{window}", "hits"),
                (f"avg_giveaways_last{window}", "giveaways"),
                (f"avg_takeaways_last{window}", "takeaways"),
                (f"avg_penalties_last{window}", "penalties"),
            ):
                source_rows = recent if source_name in {
                    "goals_for_60", "goals_against_60",
                    "shots_on_goal_for", "shots_on_goal_against",
                } else event_rows
                record[output_name] = collector.numeric_average(
                    source_rows, source_name, official_sog_lookup
                )

            for output_name, left, right, source_rows in (
                (f"corsi_share_pct_last{window}", "corsi_for", "corsi_against", event_rows),
                (f"fenwick_share_pct_last{window}", "fenwick_for", "fenwick_against", event_rows),
                (f"corsi_5v5_share_pct_last{window}", "corsi_5v5_for", "corsi_5v5_against", five_rows),
                (f"fenwick_5v5_share_pct_last{window}", "fenwick_5v5_for", "fenwick_5v5_against", five_rows),
                (f"faceoff_win_pct_last{window}", "faceoff_wins", "faceoff_losses", event_rows),
            ):
                value_for, value_against, n = collector.sum_pair(
                    source_rows, left, right, official_sog_lookup
                )
                value = (
                    value_for / (value_for + value_against)
                    if n and value_for + value_against
                    else None
                )
                if value is not None:
                    value *= 100
                record[output_name] = value

        output.append(record)

    return output, snapshot_fields()


def write_snapshot(rows, fields, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in fields})
    os.replace(temporary, destination)


def main():
    parser = argparse.ArgumentParser(
        description="Actualise les données NHL lues par le tableau Streamlit."
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if not COLLECTOR_PATH.exists():
        raise SystemExit(f"Collecteur introuvable : {COLLECTOR_PATH}")
    if not (ROOT / "input" / "NHL_scores_60min_HISTORIQUE_COMPLET_21893.csv").exists():
        raise SystemExit("Le fichier d’archive NHL manque dans le dossier input/. Vérifie que tu as copié le contenu du paquet dans le dossier du projet.")

    print("Lancement du collecteur NHL…", flush=True)
    result = subprocess.run(
        [sys.executable, str(COLLECTOR_PATH), "--workers", str(args.workers)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Le collecteur s’est arrêté avec le code {result.returncode}; les fichiers du tableau n’ont pas été remplacés.")
    if not RAW_SOURCE.exists():
        raise SystemExit(f"Fichier de statistiques introuvable après collecte : {RAW_SOURCE}")

    raw_rows = collector.read_csv(RAW_SOURCE)
    if not raw_rows:
        raise SystemExit("Le fichier de statistiques NHL est vide; aucun fichier du tableau n’a été remplacé.")

    snapshot_rows, fields = make_current_form(raw_rows)
    atomic_copy(RAW_SOURCE, APP_RAW_PATH)
    write_snapshot(snapshot_rows, fields, APP_FORM_PATH)
    print(f"Terminé : {len(snapshot_rows)} équipes; saison {snapshot_rows[0]['season']}; données du {snapshot_rows[0]['as_of_date']}.", flush=True)
    print(f"Fichiers mis à jour : {APP_FORM_PATH.name} et {APP_RAW_PATH.name}", flush=True)


if __name__ == "__main__":
    main()
