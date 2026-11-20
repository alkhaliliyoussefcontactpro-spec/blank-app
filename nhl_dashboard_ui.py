"""Shared presentation for the NHL matchup views."""

from html import escape

import altair as alt
import streamlit as st


TEAM_COLORS = {
    "ANA": "#E76B19", "ARI": "#9D334B", "BOS": "#D19D15", "BUF": "#396CC5",
    "CAR": "#D03453", "CBJ": "#4676AE", "CGY": "#D34336", "CHI": "#D82D44",
    "COL": "#8C476A", "DAL": "#16835E", "DET": "#D42F55", "EDM": "#E66D29",
    "FLA": "#BF3349", "LAK": "#728094", "MIN": "#248069", "MTL": "#B93152",
    "NJD": "#E23E52", "NSH": "#CC9A21", "NYI": "#E77B2D", "NYR": "#3576C8",
    "OTT": "#D5435B", "PHI": "#E66B30", "PIT": "#BE911B", "SEA": "#318389",
    "SJS": "#1D838C", "STL": "#406DC0", "TBL": "#3B63B7", "TOR": "#3F69AB",
    "UTA": "#61A5CF", "VAN": "#418757", "VGK": "#B58E43", "WPG": "#526C98",
    "WSH": "#BC365C",
}
GOAL_COLORS = ["#00866E", "#DA7030"]


def team_colors(teams):
    palette = [TEAM_COLORS.get(team, "#64748B") for team in teams]
    if len(palette) == 2:
        first, second = (
            tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
            for color in palette
        )
        if sum((a - b) ** 2 for a, b in zip(first, second)) < 90 ** 2:
            palette[1] = "#7658C3" if first[0] > first[2] else "#DB8130"
    return palette


def logo(team):
    if team not in TEAM_COLORS:
        return ""
    return (
        f'<img src="https://assets.nhle.com/logos/nhl/svg/{team}_light.svg" '
        'alt="" width="48" height="48" loading="lazy">'
    )


def team_banner(teams):
    cards = []
    for team, color in zip(teams, team_colors(teams)):
        cards.append(
            f'<div class="nhl-team" style="--team:{color}">'
            f'{logo(team)}<strong>{escape(team)}</strong></div>'
        )
    st.html('<div class="nhl-matchup">' + "".join(cards) + "</div>")


def dashboard_styles():
    st.html("""
        <style>
        .nhl-matchup { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.75rem; }
        .nhl-team {
            display:flex; align-items:center; gap:.65rem; min-height:4.5rem; padding:.55rem 1rem;
            border:1px solid color-mix(in srgb,currentColor 16%,transparent);
            border-left:5px solid var(--team); border-radius:.65rem;
            background:color-mix(in srgb,var(--team) 12%,transparent);
        }
        .nhl-team img { background:#fff; border-radius:.35rem; object-fit:contain; }
        .nhl-team strong { font-size:1.25rem; }
        table.nhl-table {
            width:100%; display:table; table-layout:fixed; border-collapse:collapse;
            margin:.25rem 0 1rem; font-variant-numeric:tabular-nums;
        }
        .nhl-table th, .nhl-table td {
            padding:.55rem .65rem; border-bottom:1px solid color-mix(in srgb,currentColor 15%,transparent);
            text-align:right; overflow-wrap:anywhere;
        }
        .nhl-table th:first-child { text-align:left; width:34%; }
        .nhl-table tbody th { font-weight:500; }
        .nhl-table thead th, .nhl-table tr:nth-child(even) {
            background:color-mix(in srgb,currentColor 5%,transparent);
        }
        .nhl-table td.nhl-best { background:color-mix(in srgb,var(--team) 19%,transparent); }
        @media(max-width:600px) {
            .nhl-table th, .nhl-table td { font-size:.8rem; padding:.42rem .25rem; }
            .nhl-team { padding:.45rem .6rem; }
        }
        </style>
    """)


def full_table(rows, columns=None, winners=(), colors=None):
    """Render a full-height table with optional emphasis on individual cells."""
    if not rows:
        return
    columns = list(rows[0]) if columns is None else columns
    colors = colors or {}
    winners = set(winners)
    header = "".join(f'<th scope="col">{escape(col)}</th>' for col in columns)
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, col in enumerate(columns):
            value = row.get(col)
            display = escape(str(value)) if value is not None else "—"
            if j == 0:
                cells.append(f'<th scope="row">{display}</th>')
            elif (i, col) in winners:
                color = colors.get(col, "#00866E")
                cells.append(
                    f'<td class="nhl-best" style="--team:{color}"><strong>{display}</strong></td>'
                )
            else:
                cells.append(f"<td>{display}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.html(f'<table class="nhl-table"><thead><tr>{header}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def grouped_bars(labels, series, colors, *, x_title, y_title, height, domain=None, angle=0,
                 show_values=False):
    names = list(series)
    rows = [
        {"Catégorie": label, "Série": name, "Valeur": value}
        for name, values in series.items()
        for label, value in zip(labels, values)
    ]
    values = [row["Valeur"] for row in rows if row["Valeur"] is not None]
    if not values:
        st.info("Aucune donnée disponible pour ce graphique.")
        return
    if domain is None:
        domain = [0, max(1, max(values) * 1.12)]
    scale = alt.Scale(domain=domain, nice=False)
    chart = alt.Chart(alt.Data(values=rows)).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("Catégorie:N", title=x_title, sort=labels, scale=alt.Scale(domain=labels),
                axis=alt.Axis(labelAngle=angle)),
        xOffset=alt.XOffset("Série:N", sort=names),
        y=alt.Y("Valeur:Q", title=y_title, scale=scale, stack=None),
        color=alt.Color("Série:N", title=None, scale=alt.Scale(domain=names, range=colors),
                        legend=alt.Legend(orient="top")),
        tooltip=["Catégorie:N", "Série:N", alt.Tooltip("Valeur:Q", format=".2~f")],
    )
    if show_values:
        labels_layer = chart.mark_text(dy=-7).encode(
            text=alt.Text("Valeur:Q", format=".2f"),
        )
        chart = chart + labels_layer
    st.altair_chart(chart.properties(height=height), width="stretch")


def corsi_trend(labels, shares, color):
    rows = [{"Match": label, "Corsi": share} for label, share in zip(labels, shares)]
    line = alt.Chart(alt.Data(values=rows)).mark_line(
        color=color, strokeWidth=3, point=alt.OverlayMarkDef(filled=True, color=color, size=42),
        invalid="break-paths-show-path-domains",
    ).encode(
        x=alt.X("Match:N", title=None, sort=labels, axis=alt.Axis(labelAngle=-40)),
        y=alt.Y("Corsi:Q", title="Part Corsi 5v5 (%)", scale=alt.Scale(domain=[0, 100])),
        tooltip=["Match:N", alt.Tooltip("Corsi:Q", title="Corsi 5v5 (%)", format=".1f")],
    )
    midpoint = alt.Chart(alt.Data(values=[{"Repère": 50}])).mark_rule(
        color="#77869A", strokeDash=[5, 4],
    ).encode(y="Repère:Q")
    st.altair_chart((midpoint + line).properties(height=370), width="stretch")
