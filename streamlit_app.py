import csv
import io
import math
from pathlib import Path

import streamlit as st

import subprocess
import sys

st.set_page_config(page_title="NHL — Forme des équipes", page_icon="🏒", layout="wide")

st.title("🏒 NHL — Forme des équipes")
st.caption("Version 0 : affichage descriptif des données, sans prédiction ni cotes.")

app_dir = Path(__file__).resolve().parent

if st.button("🔄 Actualiser les données NHL", type="primary"):
    refresh_script = app_dir / "refresh_nhl_data.py"

    with st.spinner("Collecte NHL en cours… Laisse la page ouverte jusqu’à la fin."):
        result = subprocess.run(
            [sys.executable, str(refresh_script), "--workers", "8"],
            cwd=app_dir,
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        st.success("Données actualisées.")
        st.rerun()
    else:
        st.error("La collecte a échoué. Voici le journal :")
        log = (result.stdout or "") + "\n" + (result.stderr or "")
        st.code(log[-6000:])

uploaded_file = st.file_uploader(
    "Importe le fichier nhl_current_team_form.csv",
    type=["csv"],
)

# Permet aussi de lire le CSV s'il est placé dans le dossier de l'application.
local_file = Path("nhl_current_team_form.csv")

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

info_col1, info_col2 = st.columns(2)
info_col1.metric("Équipes dans le fichier", len(teams))
info_col2.metric("Date du relevé", latest_date or "—")

def number(row, column, decimals=1, suffix=""):
    try:
        value = float(row.get(column, ""))
        if not math.isfinite(value):
            return "—"
        return f"{value:.{decimals}f}".replace(".", ",") + suffix
    except (TypeError, ValueError):
        return "—"

def pair(row, column_for, column_against, decimals=1):
    return (
        f"{number(row, column_for, decimals)} / "
        f"{number(row, column_against, decimals)}"
    )

col_a, col_b = st.columns(2)

default_a = teams.index("CAR") if "CAR" in teams else 0
default_b = teams.index("CBJ") if "CBJ" in teams else 1

with col_a:
    team_a = st.selectbox("Équipe A", teams, index=default_a)

with col_b:
    team_b = st.selectbox("Équipe B", teams, index=default_b)

window = st.radio(
    "Forme récente",
    [5, 10, 15],
    format_func=lambda n: f"{n} derniers matchs",
    horizontal=True,
)

row_a = next(row for row in rows if row["team"].strip() == team_a)
row_b = next(row for row in rows if row["team"].strip() == team_b)

suffix = f"last{window}"

comparison = [
    {
        "Indicateur": "Buts pour / contre par match",
        team_a: pair(row_a, f"avg_goals_for_60_{suffix}", f"avg_goals_against_60_{suffix}"),
        team_b: pair(row_b, f"avg_goals_for_60_{suffix}", f"avg_goals_against_60_{suffix}"),
    },
    {
        "Indicateur": "Tirs cadrés pour / contre par match",
        team_a: pair(row_a, f"avg_sog_for_{suffix}", f"avg_sog_against_{suffix}"),
        team_b: pair(row_b, f"avg_sog_for_{suffix}", f"avg_sog_against_{suffix}"),
    },
    {
        "Indicateur": "Part Corsi globale",
        team_a: number(row_a, f"corsi_share_pct_{suffix}", 2, " %"),
        team_b: number(row_b, f"corsi_share_pct_{suffix}", 2, " %"),
    },
    {
        "Indicateur": "Part Corsi stricte à 5 contre 5",
        team_a: number(row_a, f"corsi_5v5_share_pct_{suffix}", 2, " %"),
        team_b: number(row_b, f"corsi_5v5_share_pct_{suffix}", 2, " %"),
    },
    {
        "Indicateur": "Part Fenwick globale",
        team_a: number(row_a, f"fenwick_share_pct_{suffix}", 2, " %"),
        team_b: number(row_b, f"fenwick_share_pct_{suffix}", 2, " %"),
    },
    {
        "Indicateur": "Part Fenwick à 5 contre 5",
        team_a: number(row_a, f"fenwick_5v5_share_pct_{suffix}", 2, " %"),
        team_b: number(row_b, f"fenwick_5v5_share_pct_{suffix}", 2, " %"),
    },
    {
        "Indicateur": "Mises au jeu gagnées",
        team_a: number(row_a, f"faceoff_win_pct_{suffix}", 1, " %"),
        team_b: number(row_b, f"faceoff_win_pct_{suffix}", 1, " %"),
    },
    {
        "Indicateur": "Mises en échec par match",
        team_a: number(row_a, f"avg_hits_{suffix}"),
        team_b: number(row_b, f"avg_hits_{suffix}"),
    },
    {
        "Indicateur": "Pertes de rondelle par match",
        team_a: number(row_a, f"avg_giveaways_{suffix}"),
        team_b: number(row_b, f"avg_giveaways_{suffix}"),
    },
    {
        "Indicateur": "Récupérations de rondelle par match",
        team_a: number(row_a, f"avg_takeaways_{suffix}"),
        team_b: number(row_b, f"avg_takeaways_{suffix}"),
    },
    {
        "Indicateur": "Pénalités par match",
        team_a: number(row_a, f"avg_penalties_{suffix}"),
        team_b: number(row_b, f"avg_penalties_{suffix}"),
    },
]

st.subheader(f"Face-à-face : {team_a} contre {team_b}")

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
st.dataframe(comparison, hide_index=True, width="stretch")

def chart_number(row, column):
    try:
        value = float(row.get(column, ""))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


windows = [5, 10, 15]
window_labels = [f"{n} matchs" for n in windows]

st.subheader("Corsi strict à 5 contre 5")

label_a = f"{team_a} — équipe A"
label_b = f"{team_b} — équipe B"

corsi_data = {
    "Fenêtre": window_labels,
    label_a: [
        chart_number(row_a, f"corsi_5v5_share_pct_last{n}")
        for n in windows
    ],
    label_b: [
        chart_number(row_b, f"corsi_5v5_share_pct_last{n}")
        for n in windows
    ],
}

st.bar_chart(
    corsi_data,
    x="Fenêtre",
    y=[label_a, label_b],
    stack=False,
    height=300,
    width="stretch",
)

st.subheader("Buts marqués et encaissés par match")

goal_col_a, goal_col_b = st.columns(2)

with goal_col_a:
    st.markdown(f"**{team_a}**")
    goals_a = {
        "Fenêtre": window_labels,
        "Marqués": [
            chart_number(row_a, f"avg_goals_for_60_last{n}")
            for n in windows
        ],
        "Encaissés": [
            chart_number(row_a, f"avg_goals_against_60_last{n}")
            for n in windows
        ],
    }
    st.bar_chart(
        goals_a,
        x="Fenêtre",
        y=["Marqués", "Encaissés"],
        stack=False,
        height=280,
        width="stretch",
    )

with goal_col_b:
    st.markdown(f"**{team_b}**")
    goals_b = {
        "Fenêtre": window_labels,
        "Marqués": [
            chart_number(row_b, f"avg_goals_for_60_last{n}")
            for n in windows
        ],
        "Encaissés": [
            chart_number(row_b, f"avg_goals_against_60_last{n}")
            for n in windows
        ],
    }
    st.bar_chart(
        goals_b,
        x="Fenêtre",
        y=["Marqués", "Encaissés"],
        stack=False,
        height=280,
        width="stretch",
    )

st.caption(
    "Les fenêtres 5, 10 et 15 matchs se chevauchent. "
    "Ces graphiques montrent des moyennes descriptives, pas une prédiction."
)

st.subheader("Forme match par match — 15 derniers matchs")

game_stats_path = Path("nhl_team_game_stats.csv")

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
            corsi_for = chart_number(game, "corsi_5v5_for")
            corsi_against = chart_number(game, "corsi_5v5_against")

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

    team_a_games = recent_games(team_a, row_a)
    team_b_games = recent_games(team_b, row_b)

    chart_col_a, chart_col_b = st.columns(2)

    for column, team, games in (
        (chart_col_a, team_a, team_a_games),
        (chart_col_b, team_b, team_b_games),
    ):
        with column:
            st.markdown(f"### {team}")

            if not games:
                st.info("Aucun match trouvé pour cette équipe et cette saison.")
                continue

            labels = match_labels(games)
            shares = corsi_shares(games)
            valid_corsi = sum(value is not None for value in shares)

            st.caption(f"{len(games)} matchs, du plus ancien au plus récent.")

            if valid_corsi:
                st.markdown("**Part Corsi à 5 contre 5 (%)**")
                st.line_chart(
                    {
                        "Match": labels,
                        "Corsi 5v5 (%)": shares,
                    },
                    x="Match",
                    y="Corsi 5v5 (%)",
                    height=250,
                    width="stretch",
                )
                st.caption(
                    f"Corsi disponible et vérifié pour "
                    f"{valid_corsi}/{len(games)} matchs."
                )
            else:
                st.info("Pas de Corsi 5v5 vérifié sur ces matchs.")

            st.markdown("**Buts par match à 60 minutes**")
            goals_data = {
                "Match": labels,
                "Marqués": [
                    chart_number(game, "goals_for_60") for game in games
                ],
                "Encaissés": [
                    chart_number(game, "goals_against_60") for game in games
                ],
            }

            st.bar_chart(
                goals_data,
                x="Match",
                y=["Marqués", "Encaissés"],
                stack=False,
                sort=False,
                height=280,
                width="stretch",
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

st.dataframe(overview, hide_index=True, width="stretch")

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

    st.dataframe(coverage, hide_index=True, width="stretch")

st.info(
    "Cette page compare les statistiques descriptives. "
    "Elle ne calcule pas encore de prédiction de résultat."
)