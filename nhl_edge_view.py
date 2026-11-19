"""Seasonal NHL EDGE comparisons for the Streamlit dashboard."""

import json
from datetime import date

import streamlit as st


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

    rows = []
    config = {}
    for location, label in locations.items():
        row = {"Emplacement": label}
        for abbrev, club in teams.items():
            values = club[group].get(location, {})
            shots, goals = values.get(count), values.get("goals")
            divisor = club["gamesPlayed"] if per_game else 1
            for metric, value in (("Tirs", shots), ("Buts", goals)):
                key = f"{abbrev} · {metric}"
                row[key] = value / divisor if divisor and value is not None else None
                config[key] = st.column_config.NumberColumn(format="%.2f" if per_game else "%d")
            rate = values.get("shootingPctg")
            if shots and rate is None and goals is not None:
                rate = goals / shots
            key = f"{abbrev} · Réussite"
            row[key] = percent(rate) if shots else None
            config[key] = st.column_config.NumberColumn(format="%.1f %%")
        rows.append(row)
    st.dataframe(rows, column_config=config, hide_index=True, width="stretch",
                 height="content")
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
        st.dataframe(ranks, hide_index=True, width="stretch")


def show_zones(teams):
    st.subheader("Temps en zone")
    strength = st.radio("Situation de jeu", tuple(STRENGTHS), format_func=STRENGTHS.get,
                        horizontal=True, key="edge_strength")
    st.caption("Part du temps de jeu pendant laquelle le palet se trouve dans chaque zone, "
               "quelle que soit l’équipe qui le contrôle.")
    rows, config = [], {}
    for zone, name in ZONES.items():
        row = {"Zone": name}
        for abbrev, club in teams.items():
            values = club["zones"][strength]
            row[abbrev] = percent(values.get(f"{zone}ZonePctg"))
            row[f"Rang {abbrev}"] = values.get(f"{zone}ZoneRank")
            config[abbrev] = st.column_config.NumberColumn(format="%.1f %%")
        league = [club["zones"][strength].get(f"{zone}ZoneLeagueAvg") for club in teams.values()]
        row["Moyenne NHL"] = percent(next((x for x in league if x is not None), None))
        rows.append(row)
    config["Moyenne NHL"] = st.column_config.NumberColumn(format="%.1f %%")
    st.bar_chart(rows, x="Zone", y=list(teams), y_label="Temps en zone (%)",
                 stack=False, sort=False, height=230, width="stretch")
    st.dataframe(rows, column_order=["Zone", *teams, "Moyenne NHL", *(f"Rang {t}" for t in teams)],
                 column_config=config, hide_index=True, width="stretch")


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
        st.dataframe(rows, hide_index=True, width="stretch")
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
        st.dataframe(season_rows, hide_index=True, width="stretch")

    with st.expander("Distance patinée lors des 10 derniers matchs"):
        for column, (abbrev, club) in zip(st.columns(2), teams.items()):
            column.markdown(f"**{abbrev}**")
            games = [{"Date": g["date"], "Adversaire": g["away"] if abbrev == g["home"] else g["home"],
                      "Lieu": "Domicile" if abbrev == g["home"] else "Extérieur",
                      "Distance (km)": g["km"]} for g in reversed(club["last10"])]
            if games:
                column.dataframe(games, column_config={
                    "Distance (km)": st.column_config.NumberColumn(format="%.2f")},
                    hide_index=True, width="stretch")
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
    stamp = date.fromisoformat(payload["collectedUTC"][:10]).strftime("%d/%m/%Y")
    st.caption(f"Saison régulière · {a} {teams[a]['gamesPlayed']} matchs · "
               f"{b} {teams[b]['gamesPlayed']} matchs · Relevé du {stamp}.")
    show_shots(matchup)
    show_zones(matchup)
    show_tracking(matchup)
    st.caption("[Source NHL EDGE](https://www.nhl.com/nhl-edge/teams)")
