"""Seasonal NHL EDGE comparisons for the Streamlit dashboard."""

import json
from datetime import date

import streamlit as st

from nhl_dashboard_ui import full_table, grouped_bars, team_banner, team_colors


LOCATIONS = {
    "high": "Zone à haut danger", "mid": "Mi-distance",
    "long": "Longue distance", "all": "Tous les emplacements",
}
AREAS = {
    "Crease": "Territoire du gardien", "Low Slot": "Bas de l’enclave", "High Slot": "Haut de l’enclave",
    "L Net Side": "À gauche du filet", "R Net Side": "À droite du filet",
    "L Circle": "Cercle gauche", "R Circle": "Cercle droit",
    "Outside L": "Extérieur gauche", "Outside R": "Extérieur droit",
    "L Corner": "Coin gauche", "R Corner": "Coin droit", "Behind the Net": "Derrière le filet",
    "L Point": "Pointe gauche", "Center Point": "Pointe centrale", "R Point": "Pointe droite",
    "Offensive Neutral Zone": "Zone neutre, moitié offensive", "Beyond Red Line": "Au-delà de la ligne rouge",
}
STRENGTHS = {
    "all": "Général", "es": "Égalité numérique", "pp": "Avantage numérique",
    "pk": "Désavantage numérique",
}
ZONES = {"offensive": "Offensive", "neutral": "Neutre", "defensive": "Défensive"}


def pick_teams(teams, view):
    """Keep the matchup when switching views or seasons that contain both clubs."""
    columns = st.columns(2)
    picked = []
    for index, (side, default) in enumerate((("A", "CAR"), ("B", "CBJ"))):
        options = [team for team in teams if team not in picked]
        key = f"{view}_club_{side}"
        last = st.session_state.get(f"matchup_{side}", default)
        if st.session_state.get(key) not in options:
            st.session_state[key] = last if last in options else options[0]
        club = columns[index].selectbox(f"Équipe {side}", options, key=key)
        st.session_state[f"matchup_{side}"] = club
        picked.append(club)
    return tuple(picked)


def percent(value):
    return 100 * value if value is not None else None


def show_shots(teams):
    st.subheader("Tirs par emplacement")
    split = st.radio("Découpage de la patinoire", ("Grandes catégories", "Zones détaillées"),
                     horizontal=True, key="edge_shot_split")
    basis = st.radio("Volumes de tirs et de buts", ("Cumul saison", "Par match"),
                     horizontal=True, key="edge_shot_basis")
    per_game = basis == "Par match"
    detailed = split == "Zones détaillées"
    group, count, labels = ("areas", "sog", AREAS) if detailed else ("shots", "shots", LOCATIONS)
    # Also display any new area the NHL may introduce in a subsequent release.
    locations = dict(labels)
    if detailed:
        for club in teams.values():
            for name in club[group]:
                locations.setdefault(name, name)

    rows, winners = [], set()
    colors = {}
    palette = team_colors(tuple(teams))
    for i, (location, label) in enumerate(locations.items()):
        row = {"Emplacement": label}
        metrics = {"Tirs": [], "Buts": [], "Réussite": []}
        for (abbrev, club), color in zip(teams.items(), palette):
            values = club[group].get(location, {})
            shots, goals = values.get(count), values.get("goals")
            divisor = club["gamesPlayed"] if per_game else 1
            rate = values.get("shootingPctg")
            if shots and rate is None and goals is not None:
                rate = goals / shots
            for metric, value, precision, unit in (
                ("Tirs", shots / divisor if divisor and shots is not None else None,
                 2 if per_game else 0, ""),
                ("Buts", goals / divisor if divisor and goals is not None else None,
                 2 if per_game else 0, ""),
                ("Réussite", percent(rate) if shots else None, 1, " %"),
            ):
                key = f"{abbrev} · {metric}"
                row[key] = formatted(value, precision) + unit if value is not None else None
                colors[key] = color
                metrics[metric].append((key, value))
        for metric in ("Buts", "Réussite"):
            (key_a, a), (key_b, b) = metrics[metric]
            if a is not None and b is not None and row[key_a] != row[key_b]:
                winners.add((i, key_a if a > b else key_b))
        rows.append(row)
    full_table(rows, winners=winners, colors=colors)
    st.caption("Réussite = buts / tirs cadrés. « Par match » divise les volumes de la saison "
               "par les matchs joués. Le total couvre tous les emplacements suivis par EDGE.")

    with st.expander("Repères de la ligue pour les tirs"):
        ranks = []
        fields = (("Tirs cadrés", "shots"),)
        if not detailed:
            fields += (("Buts", "goals"), ("Réussite", "shootingPctg"))
        for location, label in locations.items():
            for metric, field in fields:
                rank = {"Emplacement": label, "Indicateur": metric}
                for abbrev, club in teams.items():
                    values = club[group].get(location, {})
                    rank[f"Rang {abbrev}"] = values.get(f"{field}Rank")
                    average = values.get(f"{field}LeagueAvg")
                    if average is not None:
                        rank["Moyenne NHL"] = (formatted(percent(average), 1) + " %"
                                               if field == "shootingPctg" else formatted(average, 1))
                ranks.append(rank)
        st.caption("Classements NHL sur l’ensemble de la saison régulière.")
        full_table(ranks, ["Emplacement", "Indicateur", *(f"Rang {club}" for club in teams),
                           "Moyenne NHL"])


def show_zones(teams):
    st.subheader("Temps en zone")
    strength = st.radio("Situation de jeu", tuple(STRENGTHS), format_func=STRENGTHS.get,
                        horizontal=True, key="edge_strength")
    st.caption("Part du temps de jeu pendant laquelle le palet se trouve dans chaque zone, "
               "quelle que soit l’équipe qui le contrôle.")
    rows, winners = [], set()
    palette = team_colors(tuple(teams))
    series = {club: [] for club in teams}
    for i, (zone, name) in enumerate(ZONES.items()):
        row = {"Zone": name}
        for abbrev, club in teams.items():
            values = club["zones"][strength]
            rate = percent(values.get(f"{zone}ZonePctg"))
            series[abbrev].append(rate)
            row[abbrev] = formatted(rate, 1) + " %" if rate is not None else None
            row[f"Rang {abbrev}"] = values.get(f"{zone}ZoneRank")
        league = [club["zones"][strength].get(f"{zone}ZoneLeagueAvg") for club in teams.values()]
        league_rate = percent(next((x for x in league if x is not None), None))
        row["Moyenne NHL"] = formatted(league_rate, 1) + " %" if league_rate is not None else None
        club_a, club_b = teams
        a, b = series[club_a][-1], series[club_b][-1]
        if zone != "neutral" and a is not None and b is not None and row[club_a] != row[club_b]:
            leader = club_a if (a > b) == (zone == "offensive") else club_b
            winners.add((i, leader))
        rows.append(row)
    grouped_bars(
        list(ZONES.values()), series, palette,
        x_title=None, y_title="Temps en zone (%)", height=360, show_values=True,
    )
    full_table(
        rows, ["Zone", *teams, "Moyenne NHL", *(f"Rang {t}" for t in teams)],
        winners=winners, colors=dict(zip(teams, palette)),
    )


def formatted(value, decimals=0):
    return "—" if value is None else f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def show_tracking(teams):
    with st.expander("Patinage, vitesse des tirs et bilan de saison"):
        metrics = (
            ("total", "Distance patinée (km)", 1),
            ("speedMax", "Vitesse maximale de patinage (km/h)", 2),
            ("burstsOver20", "Accélérations à 20 mph ou plus", 0),
            ("burstsOver22", "Accélérations à 22 mph ou plus", 0),
            ("topShotSpeed", "Tir le plus rapide (km/h)", 1),
            ("shotAttemptsOver90", "Tentatives de tir à 90 mph ou plus", 0),
        )
        rows = []
        for key, label, precision in metrics:
            row = {"Indicateur": label}
            for abbrev, club in teams.items():
                metric = club["tracking"][key]
                row[abbrev] = formatted(metric["value"], precision)
                row[f"Rang {abbrev}"] = metric["rank"]
                if metric["leagueAvg"] is not None:
                    row["Moyenne NHL"] = formatted(metric["leagueAvg"], precision)
            rows.append(row)
        full_table(rows, ["Indicateur", *teams, *(f"Rang {club}" for club in teams), "Moyenne NHL"])
        season_rows = []
        for abbrev, club in teams.items():
            season_rows.append({
                "Équipe": abbrev, "MJ": club["gamesPlayed"], "V": club["wins"],
                "D": club["losses"], "D en prolongation / tirs au but": club["otLosses"],
                "Pts": club["points"],
                "Différentiel de tentatives (EDGE)": club["shotDifferential"].get("shotAttemptDifferential"),
                "Rang tentatives": club["shotDifferential"].get("shotAttemptDifferentialRank"),
                "Différentiel de tirs cadrés (EDGE)": club["shotDifferential"].get("sogDifferential"),
                "Rang tirs cadrés": club["shotDifferential"].get("sogDifferentialRank"),
            })
        full_table(season_rows)

    with st.expander("Distance patinée lors des 10 derniers matchs"):
        for column, (abbrev, club) in zip(st.columns(2), teams.items()):
            column.markdown(f"**{abbrev}**")
            games = [{"Date": g["date"], "Adversaire": g["away"] if abbrev == g["home"] else g["home"],
                      "Lieu": "Domicile" if abbrev == g["home"] else "Extérieur",
                      "Distance (km)": g["km"]} for g in reversed(club["last10"])]
            if games:
                for game in games:
                    game["Distance (km)"] = formatted(game["Distance (km)"], 2)
                with column:
                    full_table(games)
            else:
                column.caption("Aucune distance par match disponible pour cette équipe.")


def render_edge(data_dir):
    paths = {p.stem: p for p in data_dir.glob("[0-9]" * 8 + ".json")}
    if not paths:
        st.info("Aucune saison NHL EDGE disponible. Actualise les données pour charger la saison en cours.")
        return
    season = st.selectbox("Saison régulière", sorted(paths, reverse=True),
                          format_func=lambda s: f"{s[:4]}–{s[-2:]}", key="edge_season")
    try:
        payload = json.loads(paths[season].read_text(encoding="utf-8"))
        teams = payload["teams"]
        if payload["season"] != season or payload["gameType"] != 2 or len(teams) < 2:
            raise ValueError("Fichier de saison incomplet.")
    except (OSError, ValueError, KeyError) as error:
        st.error(f"Impossible de lire la saison NHL EDGE. {error}")
        return

    a, b = pick_teams(sorted(teams), "edge")
    matchup = {a: teams[a], b: teams[b]}
    st.subheader(f"{a} contre {b} · {season[:4]}–{season[-2:]}")
    team_banner((a, b))
    stamp = date.fromisoformat(payload["collectedUTC"][:10]).strftime("%d/%m/%Y")
    st.caption(f"Saison régulière · {a} {teams[a]['gamesPlayed']} matchs · "
               f"{b} {teams[b]['gamesPlayed']} matchs · Relevé du {stamp}.")
    show_shots(matchup)
    show_zones(matchup)
    show_tracking(matchup)
    st.caption("[Source NHL EDGE](https://www.nhl.com/nhl-edge/teams)")
