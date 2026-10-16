# Bot de scalping XAUUSD / US30

Implémentation Python de la stratégie décrite dans [`STRATEGIE_SCALPING_XAUUSD_US30.md`](STRATEGIE_SCALPING_XAUUSD_US30.md)
(« Trend Pullback + Momentum Confirmation »), avec backtester et exécution live sur **MetaTrader 5**.

> ⚠️ **Aucun gain n'est garanti.** Le scalping sur l'or et le Dow Jones est très sensible au spread, au slippage et aux
> news ; la majorité des scalpeurs particuliers perdent de l'argent. Ce code n'a **pas** été validé sur des données de
> marché réelles (l'environnement de développement n'y avait pas accès) : **backtestez sur vos propres données, puis
> démo, puis seulement ensuite envisagez du réel avec une taille minimale.**

## Ce que fait le bot

| Élément | Règle |
|---|---|
| Biais (H1) | EMA50 > EMA200 et clôture au-dessus des deux (long) / inverse (short) |
| Filtre (M15) | ADX(14) > 22 |
| Entrée (M5) | Retour sur l'EMA21 **et** au moins un signal : engulfing, sortie RSI de 30/70, cassure de micro-structure |
| Stop | Swing des 10 dernières bougies M5 ± 1×ATR(14) ; stop serveur posé dès l'ouverture |
| Sorties | TP1 à 1R (50 %) → stop à breakeven ; TP2 à 2R (25 %) ; 25 % restant en trailing 1,5×ATR |
| Sessions (Paris) | 09:00–11:30 et 14:30–17:00 ; positions clôturées en fin de session |
| Risque | 0,5 % par trade, 3 trades/jour/instrument, stop journalier −2 %, hebdo −6 %, filtre de spread, fenêtres de news |

Les signaux sont calculés à la **clôture** des bougies et exécutés à l'ouverture de la suivante ; les bougies H1/M15 ne sont
utilisées qu'une fois clôturées (pas de lookahead — testé).

## Installation

```bash
pip install -r requirements.txt           # pandas, numpy
pip install MetaTrader5                   # Windows uniquement, pour le live
cp config.example.json config.json        # puis ajustez (voir ci-dessous)
```

## 1. Backtest

Exportez des bougies **M5** de votre broker (MT5 : *Affichage → Symboles → Barres*, ou un outil comme Dukascopy) :

```bash
python run_backtest.py --csv data/XAUUSD_M5.csv --symbol XAUUSD --data-tz Europe/Athens --config config.json
python run_backtest.py --csv data/US30_M5.csv   --symbol US30   --data-tz Europe/Athens --save-trades trades_us30.csv
python run_backtest.py --demo                    # données SYNTHÉTIQUES, pour tester le code seulement
```

Il faut de l'historique M5 sur plusieurs mois (≥ 100 trades pour que les stats veuillent dire quelque chose ; au moins
10 jours avant la première bougie testée pour chauffer l'EMA200 H1). Le simulateur applique spread, slippage, commission,
entrée à l'ouverture suivante, et une hypothèse **pessimiste** intrabarre (stop avant objectif si les deux sont dans la
même bougie). Ce qu'il ne sait pas faire : spreads variables (news, rollover), rejets d'ordres, gaps de week-end.

**À régler dans `config.json` avec les valeurs de VOTRE broker** (sinon tout est faux) :
`value_per_point_per_lot` (XAUUSD : 100 pour un lot de 100 oz ; US30 : 1, 10… selon le contrat), `min_lot`/`lot_step`,
`spread`, `slippage`, `commission_per_lot`, `max_spread`. Et `data_tz` / `--data-tz` = fuseau des timestamps de vos CSV.

## 2. Live (MT5)

Le terminal MT5 doit être ouvert et connecté. **Commencez par un compte démo.**

```bash
# a) Observation : calcule et affiche les signaux, n'envoie AUCUN ordre (faites-le au moins une journée)
python run_live.py mt5 --config config.json --symbols XAUUSD=XAUUSD US30=US30Cash --observe

# b) Trading automatique sur compte démo (le bot refuse un compte réel sans --allow-real)
python run_live.py mt5 --config config.json --symbols XAUUSD=XAUUSD US30=US30Cash
```

* `--symbols CLE=NOM_BROKER` : le nom du symbole varie (`XAUUSD`, `GOLD`, `XAUUSD.r`, `US30`, `DJ30`, `US30Cash`…).
* Vérifiez la ligne « Décalage serveur MT5 détecté » au démarrage ; sinon forcez `--server-utc-offset 2` (ou 3 en été).
* Un fichier `STOP` dans le dossier courant bloque toute nouvelle entrée ; `Ctrl+C` arrête le bot (les stops serveur restent
  actifs, l'état `bot_state.json` est repris au redémarrage). Chaque trade clos est ajouté à `journal.csv`.
* Calendrier de news : renseignez `risk.news_times` (ISO 8601 avec fuseau) ; le bot n'ouvre rien ±30 min autour.
* `python run_live.py replay --csv ...` fait passer un historique dans le moteur live (sans broker) pour vérifier la plomberie.

## Architecture

```
bot/indicators.py   EMA, RSI, ATR, ADX (lissage de Wilder)
bot/strategy.py     signaux multi-timeframe sans lookahead
bot/trade.py        machine à états d'un trade (TP1/BE/TP2/trailing) — partagée backtest + live
bot/backtest.py     simulateur bar-par-bar        bot/live.py   moteur live (état souhaité vs position réelle)
bot/brokers/        interface Broker, adaptateur MT5, ReplayBroker
tests/              python -m pytest -q
```

## Limites connues

* Adaptateur MT5 testé uniquement contre un faux module (câblage des requêtes), pas contre un vrai terminal.
* Un seul trade ouvert à la fois par instrument ; `max_daily_loss_pct` s'applique à l'équité du compte.
* La plus petite taille de lot peut dépasser votre risque cible sur de petits comptes : le trade est alors **refusé**
  (jamais arrondi à la hausse). Sur de petites tailles, les sorties partielles se dégradent (arrondi au `lot_step`).
