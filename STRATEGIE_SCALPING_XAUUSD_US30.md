# Stratégie de Scalping — XAUUSD & US30 (M5/M15)

## "Trend Pullback + Momentum Confirmation"

> ⚠️ **Disclaimer** : ce document décrit une stratégie de trading à titre **éducatif**. Aucune stratégie ne garantit de profit. Les marchés XAUUSD (or) et US30 (Dow Jones) sont volatils et le levier amplifie les pertes autant que les gains. **Testez systématiquement en démo avant tout capital réel.** Vous êtes seul responsable de vos décisions de trading.

---

## 1. Vue d'ensemble

Stratégie de scalping multi-timeframe basée sur :
1. Un **biais de tendance** défini sur un timeframe supérieur (H1).
2. Une **zone d'entrée** identifiée sur timeframe intermédiaire (M15) lors d'un pullback.
3. Un **timing d'entrée précis** sur timeframe inférieur (M5) avec confirmation de momentum.

Objectif : entrer dans le sens de la tendance dominante après une respiration du prix (pullback), avec un ratio risque/rendement favorable et un taux de réussite exploitable grâce à des filtres de qualité (ADX, RSI, structure de prix).

---

## 2. Structure multi-timeframe

### 2.1 H1 — Biais de tendance
- **EMA 50** et **EMA 200** sur H1.
- **Tendance haussière** : EMA50 > EMA200 et prix au-dessus des deux moyennes.
- **Tendance baissière** : EMA50 < EMA200 et prix en dessous des deux moyennes.
- Si les EMA sont entremêlées / plates → **pas de biais clair, aucun trade**.

### 2.2 M15 — Zone d'entrée (pullback)
- Attendre un retracement du prix vers :
  - l'**EMA21** (zone de valeur dynamique), ou
  - un **niveau clé** (ancien support/résistance, zone de liquidité, figure de range précédente).
- **Filtre anti-range obligatoire** : **ADX(14) sur M15 doit être > 20-25**.
  - ADX < 20 → marché sans direction claire, on **n'entre pas** (trop de faux signaux en range).
  - ADX 20-25 → tendance naissante, prudence.
  - ADX > 25 → tendance confirmée, zone favorable au setup.

### 2.3 M5 — Timing d'entrée précis
Une fois le prix dans la zone de pullback (M15) avec ADX validé, chercher sur M5 **un des trois signaux de confirmation** :
1. **Pattern de bougie** : engulfing (englobante) haussière/baissière ou pin bar (rejet de mèche) dans le sens de la tendance H1.
2. **Sortie du RSI(14) d'une zone extrême** : RSI qui remonte au-dessus de 30 (achat) ou qui redescend sous 70 (vente) — signe que la pression de retracement s'essouffle.
3. **Cassure de micro-structure M5** : rupture d'un plus haut/plus bas mineur qui confirme la reprise du mouvement dans le sens de la tendance.

**Règle** : au moins **un** de ces trois signaux doit être présent pour valider l'entrée (idéalement deux pour un setup à haute confiance).

---

## 3. Stop Loss — basé sur la structure

- **Jamais de SL fixe arbitraire** (ex. "20 pips" sans justification).
- Le SL se place **au-delà du swing du pullback** :
  - Achat : sous le plus bas du pullback (le point le plus bas avant la reprise haussière).
  - Vente : au-dessus du plus haut du pullback.
- Ajouter un **buffer de sécurité = 1 × ATR(14) sur M5** au-delà de ce swing, pour éviter d'être sorti par du bruit/mèches.
- **Formule** :
  - Achat : `SL = plus_bas_swing - ATR(14)`
  - Vente : `SL = plus_haut_swing + ATR(14)`

---

## 4. Gestion du Risk/Reward avec scaling

Approche en paliers pour sécuriser les gains tout en laissant courir le potentiel :

| Palier | Niveau | Action |
|--------|--------|--------|
| **TP1** | 1:1 (RR = 1) | Clôturer **50%** de la position, déplacer le SL au **breakeven** (prix d'entrée) sur le reste |
| **TP2** | 1:2 (RR = 2) | Clôturer **25%** supplémentaires |
| **Reste (25%)** | Trailing stop | Suivre avec l'**EMA21** (M5/M15) ou un trailing **ATR** pour viser **1:3 à 1:5** |

- Cette gestion protège le capital dès TP1 (position à risque nul après breakeven) tout en gardant une exposition sur les mouvements étendus.
- Le trailing peut se faire en sortant si la clôture d'une bougie M5 passe de l'autre côté de l'EMA21, ou avec un stop dynamique à distance `1.5 × ATR(14)` du prix.

---

## 5. Sessions de trading (heure de Paris, CET/CEST)

| Session | Horaire | Statut |
|---------|---------|--------|
| Ouverture de Londres | 09:00 – 11:30 | ✅ Privilégiée (volatilité + liquidité) |
| Chevauchement Londres/New York | 14:30 – 17:00 | ✅ Privilégiée (meilleure volatilité de la journée) |
| Session asiatique | ~01:00 – 08:00 | ❌ À éviter (faible volatilité, ranges étroits, faux signaux) |
| 30 min avant/après news à fort impact | NFP, CPI, FOMC, décisions de taux | ❌ À éviter (spreads élargis, mouvements erratiques, stop hunt) |

**Recommandation** : vérifier un calendrier économique chaque matin avant de trader et bloquer les créneaux ±30 min autour des publications à fort impact sur XAUUSD et US30.

---

## 6. Money management

- **Risque par trade** : 0,5% à 1% du capital, jamais plus.
- **Nombre maximum de trades** : 2 à 3 par actif et par jour (évite le sur-trading et la vengeance après une perte).
- **Stop journalier** : arrêt de trading si la perte cumulée atteint **-2% à -3%** du capital sur la journée.
- **Stop hebdomadaire recommandé** : envisager une pause si -6% sur la semaine, pour réévaluer.
- Ne jamais augmenter la taille de position après une perte pour "se refaire" (pas de martingale).

---

## 7. Checklist d'entrée résumée

Avant chaque trade, valider **tous** les points suivants :

- [ ] **H1** : biais de tendance clair (EMA50/EMA200 alignées et prix du bon côté).
- [ ] **M15** : prix en zone de pullback (EMA21 ou niveau clé).
- [ ] **M15** : ADX(14) > 20-25 (marché directionnel, pas de range).
- [ ] **M5** : au moins un signal de confirmation (engulfing/pin bar, sortie RSI de zone extrême, cassure de micro-structure).
- [ ] **Session** : dans une plage horaire favorable (Londres ou overlap Londres/NY).
- [ ] **News** : pas de publication à fort impact dans les 30 prochaines minutes.
- [ ] **SL** : calculé sur la structure du swing + 1×ATR(14), jamais arbitraire.
- [ ] **Risque** : taille de position calculée pour ne risquer que 0,5-1% du capital.
- [ ] **Limite journalière** : nombre de trades du jour et perte cumulée encore dans les limites fixées.

Si une seule case n'est pas cochée → **pas de trade**.

---

## 8. Méthode de validation avant capital réel

Ne jamais passer directement en réel après avoir lu une stratégie. Étapes recommandées :

1. **Backtest manuel ou semi-automatisé** : 100 à 150 trades minimum sur données historiques (XAUUSD et US30 séparément), en respectant strictement la checklist.
2. **Calcul de l'espérance mathématique** :

   ```
   Espérance = (Winrate × Gain_moyen) - (Taux_perte × Perte_moyenne)
   ```

   - L'espérance doit être **positive** et idéalement permettre un facteur de profit (profit factor) > 1,3-1,5 pour absorber les frais/spread/slippage.
3. **Phase démo** : 2 à 4 semaines de trading en compte démo dans les conditions réelles de marché (spread, exécution, sessions), en tenant un journal de trading (raison d'entrée, résultat, respect de la checklist).
4. **Analyse du journal** : vérifier la cohérence entre les résultats démo et le backtest (winrate, RR moyen réalisé, respect du money management).
5. **Passage en réel progressif** : démarrer avec une taille de compte réduite et le risque minimal (0,5%), puis augmenter progressivement seulement si les statistiques restent stables sur plusieurs semaines supplémentaires.

---

## 9. Résumé des paramètres techniques

| Paramètre | Valeur |
|-----------|--------|
| EMA tendance (H1) | 50 / 200 |
| EMA pullback (M15/M5) | 21 |
| ADX filtre (M15) | Période 14, seuil > 20-25 |
| RSI momentum (M5) | Période 14, zones 30/70 |
| ATR pour SL (M5) | Période 14, multiplicateur ×1 |
| TP1 | RR 1:1 — clôture 50% + SL breakeven |
| TP2 | RR 1:2 — clôture 25% |
| Reste | Trailing EMA21 / ATR — cible 1:3 à 1:5 |
| Risque par trade | 0,5% - 1% du capital |
| Trades max/jour/actif | 2-3 |
| Stop journalier | -2% à -3% |

---

## 10. Rappel final

Cette stratégie est un **cadre de travail**, pas une martingale garantie. Le winrate et le RR réels dépendent de la discipline d'exécution, des conditions de marché, du spread/slippage du broker, et de la gestion émotionnelle du trader. **Validez toujours en démo avant d'engager du capital réel**, et n'investissez jamais plus que ce que vous êtes prêt à perdre.
