"""Collect one regular-season NHL EDGE team comparison for the dashboard."""

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "nhl_edge_data"
BASE_URL = "https://api-web.nhle.com/v1/edge"
REGULAR_SEASON = 2
LOCATIONS = ("high", "mid", "long", "all")
STRENGTHS = ("all", "es", "pp", "pk")
# Official club IDs of the franchises active throughout the six editions.
COMMON_CLUB_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18,
                   19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30, 52, 54, 55)


def season_id(value):
    value = str(value)
    if len(value) == 4 and value.isdigit():
        value += str(int(value) + 1)
    if (len(value) != 8 or not value.isdigit() or
            int(value[4:]) != int(value[:4]) + 1 or int(value[:4]) < 2021):
        raise ValueError(f"Saison NHL EDGE invalide ({value}).")
    return value


def latest_season():
    # The existing collector writes the starting year of the regular season.
    form = ROOT / "nhl_current_team_form.csv"
    if form.exists():
        with form.open(encoding="utf-8-sig", newline="") as f:
            seasons = [season_id(row["season"]) for row in csv.DictReader(f)]
            if seasons:
                return max(seasons)
    return max(season_id(p.stem) for p in DATA_DIR.glob("[0-9]" * 8 + ".json"))


def fetch_json(endpoint, club, season):
    url = f"{BASE_URL}/{endpoint}/{club}/{season}/{REGULAR_SEASON}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            if isinstance(error, HTTPError) and error.code < 500 and error.code != 429:
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def indexed(rows, field):
    result = {row[field]: {k: v for k, v in row.items() if k != field} for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Clé NHL en double ({field}).")
    return result


def make_team(club, season, fetch=fetch_json):
    detail = fetch("team-detail", club, season)
    comparison = fetch("team-comparison", club, season)
    zone_data = fetch("team-zone-time-details", club, season)
    team = detail["team"]
    if team["id"] != club or comparison["team"]["id"] != club:
        raise ValueError(f"Identifiant de club inattendu ({club}, {season}).")
    if team["gamesPlayed"] != comparison["team"]["gamesPlayed"]:
        raise ValueError(f"Les relevés NHL portent sur des nombres de matchs différents ({club}).")

    shots = indexed(detail["sogSummary"], "locationCode")
    areas = indexed(comparison["shotLocationDetails"], "area")
    area_ranks = indexed(detail["sogDetails"], "area")
    totals = indexed(comparison["shotLocationTotals"], "locationCode")
    zones = indexed(zone_data["zoneTimeDetails"], "strengthCode")
    if not (set(LOCATIONS) <= shots.keys() and set(STRENGTHS) <= zones.keys() and areas):
        raise ValueError(f"Répartition NHL EDGE incomplète ({club}, {season}).")
    if areas.keys() != area_ranks.keys():
        raise ValueError(f"Emplacements de tir incohérents ({club}, {season}).")
    for code in LOCATIONS:
        if (shots[code]["shots"], shots[code]["goals"]) != (totals[code]["sog"], totals[code]["goals"]):
            raise ValueError(f"Totaux de tirs incohérents ({club}, {code}).")
    for name, row in areas.items():
        rank = area_ranks.get(name, {})
        if rank.get("shots") == row["sog"]:
            row["shotsRank"] = rank.get("shotsRank")

    tracking = {}
    for group, key, unit in (
        ("shotSpeed", "shotAttemptsOver90", "value"), ("shotSpeed", "topShotSpeed", "metric"),
        ("skatingSpeed", "burstsOver20", "value"), ("skatingSpeed", "burstsOver22", "value"),
        ("skatingSpeed", "speedMax", "metric"), ("distanceSkated", "total", "metric"),
    ):
        record = detail.get(group, {}).get(key) or {}
        tracking[key] = {
            "value": record.get(unit), "rank": record.get("rank"),
            "leagueAvg": (record.get("leagueAvg") or {}).get(unit),
        }

    games = []
    for game in comparison["skatingDistanceLast10"]:
        home = game["homeTeam"]["abbrev"]
        away = game["awayTeam"]["abbrev"]
        game_id = game["gameCenterLink"].rstrip("/").rsplit("/", 1)[-1]
        if (team["abbrev"] not in (home, away) or not game_id.isdigit()
                or game_id[:6] != season[:4] + "02"):
            raise ValueError(f"Match NHL EDGE incohérent ({club}, {game_id}).")
        games.append({"id": game_id, "date": game["gameDate"], "home": home, "away": away,
                      "km": (game.get("distanceSkated") or {}).get("metric")})
    if len({g["id"] for g in games}) != len(games) or (games and all(g["km"] is None for g in games)):
        raise ValueError(f"Historique de distance inexploitable ({club}, {season}).")
    return team["abbrev"], {
        "id": club, "gamesPlayed": team["gamesPlayed"], "wins": team["wins"],
        "losses": team["losses"], "otLosses": team["otLosses"], "points": team["points"],
        "shots": shots, "areas": areas, "zones": zones, "tracking": tracking,
        "shotDifferential": zone_data.get("shotDifferential") or {},
        "last10": sorted(games, key=lambda g: (g["date"], g["id"])),
    }


def collect(season, workers=4, folder=DATA_DIR, fetch=fetch_json):
    season = season_id(season)
    # The API distinguishes Arizona, Utah Hockey Club and Utah Mammoth.
    last_club = 53 if season < "20242025" else 59 if season == "20242025" else 68
    club_ids = (*COMMON_CLUB_IDS, last_club)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        teams = dict(pool.map(lambda club: make_team(club, season, fetch), club_ids))
    if len(teams) != len(club_ids):
        raise ValueError("Équipe manquante dans le relevé NHL EDGE.")

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{season}.json"
    payload = {"season": season, "gameType": REGULAR_SEASON,
               "collectedUTC": started, "teams": dict(sorted(teams.items()))}
    # Write only complete seasons; concurrent readers always see a complete file.
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, encoding="utf-8", delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(payload, f, ensure_ascii=False, indent=1, allow_nan=False)
            f.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous["teams"] == payload["teams"] or previous["collectedUTC"] > started:
                return path
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description="Actualiser la saison régulière NHL EDGE.")
    parser.add_argument("--season", help="Année de début ou identifiant NHL complet.")
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=4)
    args = parser.parse_args()
    try:
        path = collect(args.season or latest_season(), args.workers)
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"Échec de l’actualisation NHL EDGE. Dernier relevé conservé. {error}")
    print(f"Données NHL EDGE à jour ({path.stem}, saison régulière).")


if __name__ == "__main__":
    main()
