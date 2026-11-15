DONNÉES NHL — NIVEAU DE JEU DES ÉQUIPES
============================================

Date de génération (UTC) : 2026-11-15T08:57:22.442510+00:00
Période : saisons 2021-22 à 2025-26, plus 2026-27 en cours.
Matchs réguliers dans l’archive : 6,845
Nouveaux matchs terminés ajoutés : 40
Matchs avec statistiques d’équipe : 6,885
Lignes équipe-match : 13,770
Lignes de forme pré-match : 13,770
Échecs d’API / matchs manquants : 0 / 0
Matchs PBP discordants écartés des variables d’événements : 113

DÉFINITIONS
- Corsi : buts + tirs cadrés + tirs manqués + tentatives bloquées.
- Fenwick : buts + tirs cadrés + tirs manqués.
- 5 contre 5 : uniquement les événements portant le code de situation 1551.
- Tentatives bloquées : tirs bloqués de l’équipe qui tire; les blocs défensifs sont exclus.
- Les tirs et événements d’OT sont conservés; les tirs de fusillade sont exclus.
- Les buts de forme utilisent le score après 60 minutes.
- Les moyennes 5/10/15 n’utilisent que les matchs antérieurs de la même saison.
- Si moins de 5/10/15 matchs sont disponibles, la moyenne utilise les matchs antérieurs disponibles; le nombre figure dans prior_games_lastN.

LIMITES DE COUVERTURE
- Saison 2008 : l’échantillon NHL PBP consulté ne contient pas les catégories d’événements nécessaires; seuls les buts à 60 minutes sont conservés.
- Les statistiques 5v5 sont laissées vides si le code de situation manque sur au moins une tentative du match.
- Les statistiques d’événements PBP n’entrent dans les fenêtres que si les tirs cadrés PBP concordent avec le total NHL GameCenter. Le total officiel des tirs cadrés reste utilisable séparément.
- Cette base valide l’extraction et construit les indicateurs; elle ne valide pas encore leur pouvoir prédictif.
- Aucun flux MoneyPuck ni cote de bookmaker n’est utilisé.

FICHIERS
- nhl_team_game_stats.csv : deux lignes par match, une par équipe.
- nhl_team_form_prematch_5_10_15.csv : forme pré-match 5/10/15, une ligne par équipe et match.
- nhl_coverage_by_season.csv : couverture des données par saison.
