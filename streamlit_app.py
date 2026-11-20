import csv
import io
import math
from pathlib import Path

import streamlit as st
from nhl_dashboard_ui import (
    GOAL_COLORS,
    corsi_trend,
    dashboard_styles,
    full_table,
    grouped_bars,
    team_banner,
    team_colors,
)
from nhl_edge_view import pick_teams, render_edge

import subprocess
import sys

st.set_page_config(page_title="NHL — Face-à-face", page_icon="🏒", layout="wide")

dashboard_styles()
st.title("🏒 NHL — Face-à-face")

app_dir = Path(__file__).resolve().parent

view = st.radio(
    "Vue du face-à-face",
    ("Forme récente", "NHL EDGE", "Gardiens"),
    horizontal=True,
    key="vs_view",
)
local_file = app_dir / "nhl_current_team_form.csv"
uploaded_file = None

with st.expander("Données NHL", expanded=view == "Forme récente" and not local_file.exists()):
    if st.button("🔄 Actualiser les données NHL", type="primary"):
        for title, script, workers in (("Forme récente", "refresh_nhl_data.py", "8"),
                                       ("NHL EDGE", "collect_nhl_edge_teams.py", "4")):
            with st.spinner(f"Actualisation en cours · {title}"):
                result = subprocess.run([sys.executable, str(app_dir / script), "--workers", workers],
                                        cwd=app_dir, capture_output=True, text=True)
            if result.returncode == 0:
                st.success(f"{title} · données actualisées.")
            else:
                st.error(f"{title} · échec de l’actualisation.")
                st.code((result.stdout + "\n" + result.stderr)[-3000:])
    if view == "Forme récente" and not local_file.exists():
        uploaded_file = st.file_uploader("Importe le fichier nhl_current_team_form.csv", type=["csv"])

if view == "NHL EDGE":
    render_edge(app_dir / "nhl_edge_data")
    st.stop()

if view == "Gardiens":
    st.title("Gardiens")
    st.info("La fiche gardiens sera ajoutée ici.")
    st.stop()

if local_file.exists():
    csv_bytes = local_file.read_bytes()
elif uploaded_file is not None:
    csv_bytes = uploaded_file.getvalue()
else:
    csv_bytes = None

if csv_bytes is None:
    st.info("Importe le fichier CSV pour afficher les statistiques.")
    st.stop()

try:
    text = csv_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
except Exception as error:
    st.error(f"Impossible de lire le CSV : {error}")
    st.stop()

if not rows:
    st.error("Le fichier CSV ne contient aucune ligne.")
    st.stop()

# Vérifie que le fichier contient les colonnes attendues.
required_columns = {"team", "as_of_date", "matches_played_season"}

for n in (5, 10, 15):
    required_columns.update({
        f"matches_in_last{n}",
        f"valid_pbp_games_last{n}",
        f"valid_5v5_games_last{n}",
        f"avg_goals_for_60_last{n}",
        f"avg_goals_against_60_last{n}",
        f"avg_sog_for_last{n}",
        f"avg_sog_against_last{n}",
        f"corsi_share_pct_last{n}",
        f"fenwick_share_pct_last{n}",
        f"corsi_5v5_share_pct_last{n}",
        f"fenwick_5v5_share_pct_last{n}",
        f"faceoff_win_pct_last{n}",
        f"avg_hits_last{n}",
        f"avg_giveaways_last{n}",
        f"avg_takeaways_last{n}",
        f"avg_penalties_last{n}",
    })

missing_columns = required_columns - set(rows[0].keys())

if missing_columns:
    st.error("Ce CSV ne semble pas être le fichier de forme attendu.")
    st.write("Colonnes manquantes :", ", ".join(sorted(missing_columns)))
    st.stop()

teams = sorted({
    row["team"].strip()
    for row in rows
    if row.get("team", "").strip()
})

if len(teams) < 2:
    st.error("Il faut au moins deux équipes dans le fichier.")
    st.stop()

latest_date = max(row.get("as_of_date", "") for row in rows)

def pair(row, column_for, column_against, decimals=1):
    return (
        f"{number(row, column_for, decimals)} / "
        f"{number(row, column_against, decimals)}"
    )

team_a, team_b = pick_teams(teams, "form")

window = st.radio(
    "Forme récente",
    [5, 10, 15],
    format_func=lambda n: f"{n} derniers matchs",
    horizontal=True,
)

row_a = next(row for row in rows if row["team"].strip() == team_a)
row_b = next(row for row in rows if row["team"].strip() == team_b)

suffix = f"last{window}"

st.subheader(f"Face-à-face · {team_a} contre {team_b}")
team_banner((team_a, team_b))
palette = team_colors((team_a, team_b))

def raw_value(row, column):
    try:
        value = float(row.get(column, ""))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def display_value(value, decimals=1, unit=""):
    if value is None:
        return "—"
    return f"{value:.{decimals}f}".replace(".", ",") + unit


def number(row, column, decimals=1, suffix=""):
    return display_value(raw_value(row, column), decimals, suffix)


def display_gap(value, decimals=1, unit=""):
    if value is None:
        return "—"
    return f"{value:+.{decimals}f}".replace(".", ",") + unit


corsi_a = raw_value(row_a, f"corsi_5v5_share_pct_{suffix}")
corsi_b = raw_value(row_b, f"corsi_5v5_share_pct_{suffix}")

gf_a = raw_value(row_a, f"avg_goals_for_60_{suffix}")
ga_a = raw_value(row_a, f"avg_goals_against_60_{suffix}")
gf_b = raw_value(row_b, f"avg_goals_for_60_{suffix}")
ga_b = raw_value(row_b, f"avg_goals_against_60_{suffix}")

net_a = gf_a - ga_a if gf_a is not None and ga_a is not None else None
net_b = gf_b - ga_b if gf_b is not None and ga_b is not None else None

corsi_gap = corsi_a - corsi_b if corsi_a is not None and corsi_b is not None else None
goals_gap = net_a - net_b if net_a is not None and net_b is not None else None

st.markdown(f"**Synthèse descriptive — {window} derniers matchs**")

summary_row_1 = st.columns(2)
summary_row_1[0].metric(f"Corsi 5v5 — {team_a}", display_value(corsi_a, 1, " %"))
summary_row_1[1].metric(f"Corsi 5v5 — {team_b}", display_value(corsi_b, 1, " %"))

summary_row_2 = st.columns(2)
summary_row_2[0].metric("Écart Corsi 5v5 (A − B)", display_gap(corsi_gap, 1, " pts"))
summary_row_2[1].metric(
    "Écart différentiel de buts (A − B)",
    display_gap(goals_gap, 2, " buts/match"),
)

st.caption(
    f"Un écart positif signifie que la valeur affichée est plus élevée pour {team_a}. "
    "C’est descriptif, pas une probabilité de victoire."
)

st.caption(
    f"Échantillon réellement disponible : "
    f"{row_a[f'matches_in_{suffix}']} matchs pour {team_a} et "
    f"{row_b[f'matches_in_{suffix}']} pour {team_b}."
)
indicators = (
    ("Buts marqués par match", "avg_goals_for_60", 1, "", "max"),
    ("Buts encaissés par match", "avg_goals_against_60", 1, "", "min"),
    ("Tirs cadrés pour par match", "avg_sog_for", 1, "", "max"),
    ("Tirs cadrés contre par match", "avg_sog_against", 1, "", "min"),
    ("Part Corsi globale", "corsi_share_pct", 2, " %", "max"),
    ("Part Corsi stricte à 5 contre 5", "corsi_5v5_share_pct", 2, " %", "max"),
    ("Part Fenwick globale", "fenwick_share_pct", 2, " %", "max"),
    ("Part Fenwick à 5 contre 5", "fenwick_5v5_share_pct", 2, " %", "max"),
    ("Mises au jeu gagnées", "faceoff_win_pct", 1, " %", "max"),
    ("Mises en échec par match", "avg_hits", 1, "", None),
    ("Pertes de rondelle par match", "avg_giveaways", 1, "", "min"),
    ("Récupérations de rondelle par match", "avg_takeaways", 1, "", "max"),
    ("Pénalités par match", "avg_penalties", 1, "", "min"),
)
comparison, winners = [], set()
for i, (label, metric, decimals, unit, direction) in enumerate(indicators):
    a, b = (raw_value(row, f"{metric}_{suffix}") for row in (row_a, row_b))
    rendered_a, rendered_b = (display_value(value, decimals, unit) for value in (a, b))
    comparison.append({"Indicateur": label, team_a: rendered_a, team_b: rendered_b})
    if direction and a is not None and b is not None and rendered_a != rendered_b:
        leader = team_a if (a > b) == (direction == "max") else team_b
        winners.add((i, leader))

full_table(comparison, winners=winners, colors=dict(zip((team_a, team_b), palette)))

windows = [5, 10, 15]
window_labels = [f"{n} matchs" for n in windows]

st.subheader("Corsi strict à 5 contre 5")
grouped_bars(
    window_labels,
    {
        team: [raw_value(row, f"corsi_5v5_share_pct_last{n}") for n in windows]
        for team, row in ((team_a, row_a), (team_b, row_b))
    },
    palette, x_title=None, y_title="Part Corsi 5v5 (%)", height=385, show_values=True,
)

st.subheader("Buts marqués et encaissés par match")
goal_series = {
    team: {
        label: [raw_value(row, f"{field}_last{n}") for n in windows]
        for label, field in (("Marqués", "avg_goals_for_60"), ("Encaissés", "avg_goals_against_60"))
    }
    for team, row in ((team_a, row_a), (team_b, row_b))
}
max_goals = max(
    (value for series in goal_series.values() for values in series.values()
     for value in values if value is not None),
    default=0,
)
for column, team in zip(st.columns(2), goal_series):
    with column:
        st.markdown(f"**{team}**")
        grouped_bars(
            window_labels, goal_series[team], GOAL_COLORS,
            x_title=None, y_title="Buts par match à 60 min", height=365,
            domain=[0, max(1, math.ceil(max_goals))],
        )

st.caption("Les fenêtres 5, 10 et 15 matchs se chevauchent.")

st.subheader("Forme match par match — 15 derniers matchs")

game_stats_path = app_dir / "nhl_team_game_stats.csv"

if not game_stats_path.exists():
    st.warning("Fichier nhl_team_game_stats.csv introuvable à la racine du projet.")
else:
    with game_stats_path.open("r", encoding="utf-8-sig", newline="") as file:
        game_rows = list(csv.DictReader(file))

    def recent_games(team, form_row):
        season = str(form_row.get("season", "")).strip()

        selected = [
            game for game in game_rows
            if game.get("team", "").strip() == team
            and str(game.get("season", "")).strip() == season
            and str(game.get("game_type", "")).strip() == "02"
            and game.get("fetch_status", "") in {"ok", "legacy_scores_only"}
        ]

        selected.sort(
            key=lambda game: (
                game.get("date", ""),
                game.get("game_id", ""),
            )
        )
        return selected[-15:]

    def match_labels(games):
        labels = []
        for game in games:
            date = game.get("date", "")
            short_date = date[5:] if len(date) >= 10 else date
            location = "vs" if game.get("home_away") == "home" else "@"
            labels.append(
                f"{short_date} {location} {game.get('opponent', '')}"
            )
        return labels

    def corsi_shares(games):
        shares = []

        for game in games:
            corsi_for = raw_value(game, "corsi_5v5_for")
            corsi_against = raw_value(game, "corsi_5v5_against")

            trusted = (
                game.get("fetch_status") == "ok"
                and game.get("event_stats_quality") == "PBP_SOG_MATCH"
            )

            if (
                trusted
                and corsi_for is not None
                and corsi_against is not None
                and corsi_for + corsi_against > 0
            ):
                shares.append(
                    round(100 * corsi_for / (corsi_for + corsi_against), 1)
                )
            else:
                shares.append(None)

        return shares

    match_tabs = st.tabs([team_a, team_b])
    games_by_team = (recent_games(team_a, row_a), recent_games(team_b, row_b))
    recent_goal_max = max(
        (value for games in games_by_team for game in games
         for field in ("goals_for_60", "goals_against_60")
         if (value := raw_value(game, field)) is not None),
        default=0,
    )

    for tab, games, color in zip(match_tabs, games_by_team, palette):
        with tab:
            if not games:
                st.info("Aucun match trouvé pour cette équipe et cette saison.")
                continue

            labels = match_labels(games)
            shares = corsi_shares(games)
            valid_corsi = sum(value is not None for value in shares)
            st.caption(f"{len(games)} matchs, du plus ancien au plus récent.")

            st.markdown("**Part Corsi à 5 contre 5 (%)**")
            if valid_corsi:
                corsi_trend(labels, shares, color)
                st.caption(f"Corsi disponible et vérifié pour {valid_corsi}/{len(games)} matchs.")
            else:
                st.info("Pas de Corsi 5v5 vérifié sur ces matchs.")

            st.markdown("**Buts par match à 60 minutes**")
            grouped_bars(
                labels,
                {
                    "Marqués": [raw_value(game, "goals_for_60") for game in games],
                    "Encaissés": [raw_value(game, "goals_against_60") for game in games],
                },
                GOAL_COLORS, x_title=None, y_title="Buts à 60 min", height=385, angle=-40,
                domain=[0, max(1, recent_goal_max)],
            )

st.subheader("Forme de toutes les équipes")

overview = []

for row in sorted(rows, key=lambda item: item["team"]):
    overview.append({
        "Équipe": row["team"],
        "Matchs joués cette saison": number(row, "matches_played_season", 0),
        "Buts pour / contre — 5 matchs": pair(
            row, "avg_goals_for_60_last5", "avg_goals_against_60_last5"
        ),
        "Corsi 5v5 — 5 matchs": number(row, "corsi_5v5_share_pct_last5", 1, " %"),
        "Corsi 5v5 — 10 matchs": number(row, "corsi_5v5_share_pct_last10", 1, " %"),
        "Corsi 5v5 — 15 matchs": number(row, "corsi_5v5_share_pct_last15", 1, " %"),
    })

st.caption(f"{len(teams)} équipes · Données du {latest_date or '—'}")
full_table(overview)

with st.expander("Vérifier la couverture des données"):
    coverage = []

    for row in sorted(rows, key=lambda item: item["team"]):
        coverage.append({
            "Équipe": row["team"],
            "Play-by-play valides — 5 matchs":
                f"{row['valid_pbp_games_last5']}/{row['matches_in_last5']}",
            "5 contre 5 valides — 5 matchs":
                f"{row['valid_5v5_games_last5']}/{row['matches_in_last5']}",
            "Play-by-play valides — 10 matchs":
                f"{row['valid_pbp_games_last10']}/{row['matches_in_last10']}",
            "5 contre 5 valides — 10 matchs":
                f"{row['valid_5v5_games_last10']}/{row['matches_in_last10']}",
            "Play-by-play valides — 15 matchs":
                f"{row['valid_pbp_games_last15']}/{row['matches_in_last15']}",
            "5 contre 5 valides — 15 matchs":
                f"{row['valid_5v5_games_last15']}/{row['matches_in_last15']}",
        })

    full_table(coverage)
