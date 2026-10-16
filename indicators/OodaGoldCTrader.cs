// OODA GOLD — Signaux BUY / SELL avec 1 Stop Loss + 2 Take Profits (XAUUSD) — cTrader / cAlgo.API
// Port C# de indicators/ooda_gold.pine (TradingView). Usage éducatif, aucune garantie de profit.
//
// Utilisation : cTrader > Automate > Indicators > New Indicator, coller ce fichier, puis Build.
// Ajouter l'indicateur sur un graphique XAUUSD en M15 (ou M5).
//
// Boucle OODA exécutée uniquement sur bougie CLÔTURÉE (pas de repaint) :
//   OBSERVER : EMA HTF 50/200 (bougie HTF précédente), EMA 21/50, ADX/DMI, RSI, MACD, VWAP, ATR, pivots.
//   ORIENTER : score 0-100 (HTF 25, tendance locale 15, ADX 15, RSI 10, MACD 10, VWAP 10, structure 15)
//              + filtres de session et de volatilité.
//   DÉCIDER  : biais HTF + score >= seuil + pullback EMA21 puis reprise + prix non sur-étendu + SL raisonnable.
//   AGIR     : entrée = clôture ; SL = swing -/+ buffer ATR (borné) ; TP1 = 1R (50 %) puis SL à break-even ;
//              TP2 = 2R. Backtest interne (winrate, R total, profit factor) affiché en haut à gauche.
//              Si SL et TP sont touchés dans la même bougie, le SL est compté en premier.

using System;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Indicators
{
    [Indicator(IsOverlay = true, TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class OodaGoldCTrader : Indicator
    {
        // ---- 1. OBSERVER ----
        [Parameter("Timeframe du biais (HTF)", DefaultValue = "Hour", Group = "1. Observer")]
        public TimeFrame HtfTimeFrame { get; set; }

        [Parameter("EMA rapide HTF", DefaultValue = 50, MinValue = 1, Group = "1. Observer")]
        public int HtfFastPeriod { get; set; }

        [Parameter("EMA lente HTF", DefaultValue = 200, MinValue = 1, Group = "1. Observer")]
        public int HtfSlowPeriod { get; set; }

        [Parameter("EMA pullback (locale)", DefaultValue = 21, MinValue = 1, Group = "1. Observer")]
        public int EmaPullbackPeriod { get; set; }

        [Parameter("EMA tendance locale", DefaultValue = 50, MinValue = 1, Group = "1. Observer")]
        public int EmaTrendPeriod { get; set; }

        [Parameter("Longueur ADX/DMI", DefaultValue = 14, MinValue = 1, Group = "1. Observer")]
        public int AdxPeriod { get; set; }

        [Parameter("Longueur RSI", DefaultValue = 14, MinValue = 1, Group = "1. Observer")]
        public int RsiPeriod { get; set; }

        [Parameter("Longueur ATR", DefaultValue = 14, MinValue = 1, Group = "1. Observer")]
        public int AtrPeriod { get; set; }

        [Parameter("Pivots structure (barres de chaque côté)", DefaultValue = 3, MinValue = 1, Group = "1. Observer")]
        public int PivotLen { get; set; }

        // ---- 2. ORIENTER ----
        [Parameter("Score minimum (0-100)", DefaultValue = 70, MinValue = 40, MaxValue = 100, Group = "2. Orienter")]
        public int MinScore { get; set; }

        [Parameter("ADX minimum", DefaultValue = 20.0, MinValue = 0, Group = "2. Orienter")]
        public double AdxMin { get; set; }

        [Parameter("Filtrer par session", DefaultValue = true, Group = "2. Orienter")]
        public bool UseSession { get; set; }

        [Parameter("Session début (heure UTC)", DefaultValue = 7, MinValue = 0, MaxValue = 23, Group = "2. Orienter")]
        public int SessionStartHour { get; set; }

        [Parameter("Session fin (heure UTC)", DefaultValue = 20, MinValue = 1, MaxValue = 24, Group = "2. Orienter")]
        public int SessionEndHour { get; set; }

        [Parameter("Volatilité min (ATR / moyenne ATR)", DefaultValue = 0.6, MinValue = 0.1, Step = 0.1, Group = "2. Orienter")]
        public double VolMin { get; set; }

        [Parameter("Volatilité max (évite pics d'annonces)", DefaultValue = 2.5, MinValue = 1.0, Step = 0.1, Group = "2. Orienter")]
        public double VolMax { get; set; }

        // ---- 3. DÉCIDER ----
        [Parameter("Écart max prix / EMA21 (x ATR)", DefaultValue = 1.5, MinValue = 0.5, Step = 0.1, Group = "3. Décider")]
        public double MaxExtAtr { get; set; }

        [Parameter("Cooldown après clôture d'un trade (barres)", DefaultValue = 5, MinValue = 0, Group = "3. Décider")]
        public int Cooldown { get; set; }

        // ---- 4. AGIR ----
        [Parameter("Lookback swing pour le SL (barres)", DefaultValue = 10, MinValue = 3, Group = "4. Agir (SL / TP)")]
        public int SlLookback { get; set; }

        [Parameter("Buffer SL au-delà du swing (x ATR)", DefaultValue = 0.3, MinValue = 0.0, Step = 0.1, Group = "4. Agir (SL / TP)")]
        public double SlBuffer { get; set; }

        [Parameter("Distance SL minimale (x ATR)", DefaultValue = 1.0, MinValue = 0.1, Step = 0.1, Group = "4. Agir (SL / TP)")]
        public double SlMinAtr { get; set; }

        [Parameter("Distance SL maximale (x ATR)", DefaultValue = 2.5, MinValue = 0.5, Step = 0.1, Group = "4. Agir (SL / TP)")]
        public double SlMaxAtr { get; set; }

        [Parameter("TP1 - ratio R:R", DefaultValue = 1.0, MinValue = 0.1, Step = 0.1, Group = "4. Agir (SL / TP)")]
        public double Rr1 { get; set; }

        [Parameter("TP2 - ratio R:R", DefaultValue = 2.0, MinValue = 0.2, Step = 0.1, Group = "4. Agir (SL / TP)")]
        public double Rr2 { get; set; }

        [Parameter("% de la position clôturée au TP1", DefaultValue = 50, MinValue = 10, MaxValue = 90, Group = "4. Agir (SL / TP)")]
        public int Tp1Pct { get; set; }

        [Parameter("SL à break-even après TP1", DefaultValue = true, Group = "4. Agir (SL / TP)")]
        public bool MoveToBreakEven { get; set; }

        // ---- Affichage / alertes ----
        [Parameter("Afficher le tableau de stats", DefaultValue = true, Group = "Affichage")]
        public bool ShowStats { get; set; }

        [Parameter("Alerte sonore (dernière barre)", DefaultValue = false, Group = "Alertes")]
        public bool EnableSoundAlert { get; set; }

        [Parameter("Fichier son (.wav)", DefaultValue = "Alert1.wav", Group = "Alertes")]
        public string SoundFile { get; set; }

        [Output("EMA 21", LineColor = "Orange", Thickness = 1)]
        public IndicatorDataSeries Ema21Line { get; set; }

        [Output("EMA 50", LineColor = "DodgerBlue", Thickness = 1)]
        public IndicatorDataSeries Ema50Line { get; set; }

        [Output("VWAP", LineColor = "MediumPurple", Thickness = 1)]
        public IndicatorDataSeries VwapLine { get; set; }

        [Output("Buy Signal", LineColor = "Lime", PlotType = PlotType.Points, Thickness = 5)]
        public IndicatorDataSeries BuySignal { get; set; }

        [Output("Sell Signal", LineColor = "Red", PlotType = PlotType.Points, Thickness = 5)]
        public IndicatorDataSeries SellSignal { get; set; }

        private MovingAverage _ema21;
        private MovingAverage _ema50;
        private MovingAverage _htfEmaFast;
        private MovingAverage _htfEmaSlow;
        private DirectionalMovementSystem _dmi;
        private RelativeStrengthIndex _rsi;
        private AverageTrueRange _atr;
        private SimpleMovingAverage _atrAvg;
        private MacdHistogram _macd;
        private Bars _htfBars;

        private IndicatorDataSeries _cumPv;
        private IndicatorDataSeries _cumVol;

        // Progression : on ne traite que les barres clôturées, une seule fois, dans l'ordre.
        private int _lastProcessed = -1;

        // État du trade simulé
        private int _dir;            // 0 aucun, 1 long, -1 short
        private int _stage;          // 0 avant TP1, 1 après TP1
        private int _entryBar;
        private int _lastCloseBar = -1000;
        private int _tradeId;
        private double _entry, _sl, _tp1, _tp2;

        // Statistiques
        private int _trades;
        private int _wins;
        private double _totalR;
        private double _grossWin;
        private double _grossLoss;

        protected override void Initialize()
        {
            _htfBars = MarketData.GetBars(HtfTimeFrame);

            _ema21 = Indicators.MovingAverage(Bars.ClosePrices, EmaPullbackPeriod, MovingAverageType.Exponential);
            _ema50 = Indicators.MovingAverage(Bars.ClosePrices, EmaTrendPeriod, MovingAverageType.Exponential);
            _htfEmaFast = Indicators.MovingAverage(_htfBars.ClosePrices, HtfFastPeriod, MovingAverageType.Exponential);
            _htfEmaSlow = Indicators.MovingAverage(_htfBars.ClosePrices, HtfSlowPeriod, MovingAverageType.Exponential);

            _dmi = Indicators.DirectionalMovementSystem(AdxPeriod);
            _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, RsiPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Exponential);
            _atrAvg = Indicators.SimpleMovingAverage(_atr.Result, 100);
            _macd = Indicators.MacdHistogram(Bars.ClosePrices, 26, 12, 9);

            _cumPv = CreateDataSeries();
            _cumVol = CreateDataSeries();
        }

        public override void Calculate(int index)
        {
            // --- Séries de tracé et VWAP journalier (calculées sur toutes les barres, y compris la barre en cours) ---
            Ema21Line[index] = _ema21.Result[index];
            Ema50Line[index] = _ema50.Result[index];

            double typical = (Bars.HighPrices[index] + Bars.LowPrices[index] + Bars.ClosePrices[index]) / 3.0;
            double vol = Bars.TickVolumes[index];
            bool newDay = index == 0 || Bars.OpenTimes[index].Date != Bars.OpenTimes[index - 1].Date;
            _cumPv[index] = (newDay ? 0.0 : _cumPv[index - 1]) + typical * vol;
            _cumVol[index] = (newDay ? 0.0 : _cumVol[index - 1]) + vol;
            VwapLine[index] = _cumVol[index] > 0 ? _cumPv[index] / _cumVol[index] : double.NaN;

            // --- Traitement des barres clôturées uniquement (pas de repaint) ---
            int target = IsLastBar ? index - 1 : index;
            while (_lastProcessed < target)
            {
                _lastProcessed++;
                ProcessBar(_lastProcessed, IsLastBar && _lastProcessed == index - 1);
            }

            if (IsLastBar && ShowStats)
                DrawStats();
        }

        private void ProcessBar(int i, bool live)
        {
            // Échauffement : ATR moyen sur 100 barres + lookbacks
            if (i < 120)
                return;

            int htfIdx = _htfBars.OpenTimes.GetIndexByTime(Bars.OpenTimes[i]) - 1; // bougie HTF précédente, clôturée
            if (htfIdx < HtfSlowPeriod)
                return;

            double close = Bars.ClosePrices[i];
            double open = Bars.OpenPrices[i];
            double high = Bars.HighPrices[i];
            double low = Bars.LowPrices[i];

            // ================= 1) OBSERVER =================
            double htfFast = _htfEmaFast.Result[htfIdx];
            double htfSlow = _htfEmaSlow.Result[htfIdx];
            double htfClose = _htfBars.ClosePrices[htfIdx];

            double ema21 = _ema21.Result[i];
            double ema50 = _ema50.Result[i];
            double atr = _atr.Result[i];
            double atrAvg = _atrAvg.Result[i];
            double volRatio = atrAvg > 0 ? atr / atrAvg : 1.0;
            double rsi = _rsi.Result[i];
            double adx = _dmi.ADX[i];
            double diP = _dmi.DIPlus[i];
            double diM = _dmi.DIMinus[i];
            double macdH = _macd.Histogram[i];
            double macdHPrev = _macd.Histogram[i - 1];
            double vwap = VwapLine[i];

            double ph1, ph2, pl1, pl2;
            GetLastPivots(i, out ph1, out ph2, out pl1, out pl2);
            bool higherLows = !double.IsNaN(pl1) && !double.IsNaN(pl2) && pl1 > pl2;
            bool lowerHighs = !double.IsNaN(ph1) && !double.IsNaN(ph2) && ph1 < ph2;

            // ================= 2) ORIENTER =================
            bool htfBull = htfFast > htfSlow && htfClose > htfFast;
            bool htfBear = htfFast < htfSlow && htfClose < htfFast;
            bool locBull = close > ema50 && ema21 > ema50;
            bool locBear = close < ema50 && ema21 < ema50;
            bool adxOk = adx > AdxMin;
            bool vwapBull = !double.IsNaN(vwap) && close > vwap;
            bool vwapBear = !double.IsNaN(vwap) && close < vwap;

            int bullScore = (htfBull ? 25 : 0) + (locBull ? 15 : 0) + (adxOk && diP > diM ? 15 : 0)
                          + (rsi > 50 && rsi < 70 ? 10 : 0) + (macdH > 0 && macdH > macdHPrev ? 10 : 0)
                          + (vwapBull ? 10 : 0) + (higherLows ? 15 : 0);
            int bearScore = (htfBear ? 25 : 0) + (locBear ? 15 : 0) + (adxOk && diM > diP ? 15 : 0)
                          + (rsi < 50 && rsi > 30 ? 10 : 0) + (macdH < 0 && macdH < macdHPrev ? 10 : 0)
                          + (vwapBear ? 10 : 0) + (lowerHighs ? 15 : 0);

            int hour = Bars.OpenTimes[i].Hour;
            bool inSession = !UseSession || (hour >= SessionStartHour && hour < SessionEndHour);
            bool volOk = volRatio >= VolMin && volRatio <= VolMax;

            // ================= Gestion du trade actif =================
            if (_dir != 0 && i > _entryBar)
                ManageTrade(i, high, low, live);

            // ================= 3) DÉCIDER =================
            double body = Math.Abs(close - open);
            double lowerWick = Math.Min(open, close) - low;
            double upperWick = high - Math.Max(open, close);

            double lowest3 = Math.Min(low, Math.Min(Bars.LowPrices[i - 1], Bars.LowPrices[i - 2]));
            double highest3 = Math.Max(high, Math.Max(Bars.HighPrices[i - 1], Bars.HighPrices[i - 2]));
            bool trigLong = lowest3 <= ema21 && close > ema21 && close > open
                            && (close > Bars.HighPrices[i - 1] || lowerWick >= body * 1.5);
            bool trigShort = highest3 >= ema21 && close < ema21 && close < open
                             && (close < Bars.LowPrices[i - 1] || upperWick >= body * 1.5);

            bool notExtLong = (close - ema21) <= atr * MaxExtAtr;
            bool notExtShort = (ema21 - close) <= atr * MaxExtAtr;

            double swLow = low;
            double swHigh = high;
            for (int k = i - SlLookback + 1; k < i; k++)
            {
                swLow = Math.Min(swLow, Bars.LowPrices[k]);
                swHigh = Math.Max(swHigh, Bars.HighPrices[k]);
            }
            double riskLong = Math.Max(close - (swLow - atr * SlBuffer), atr * SlMinAtr);
            double riskShort = Math.Max((swHigh + atr * SlBuffer) - close, atr * SlMinAtr);
            bool riskOkLong = riskLong <= atr * SlMaxAtr;
            bool riskOkShort = riskShort <= atr * SlMaxAtr;

            bool canEnter = _dir == 0 && (i - _lastCloseBar > Cooldown) && inSession && volOk;
            bool buySig = canEnter && htfBull && bullScore >= MinScore && trigLong && notExtLong && riskOkLong;
            bool sellSig = canEnter && htfBear && bearScore >= MinScore && trigShort && notExtShort && riskOkShort;

            // ================= 4) AGIR =================
            if (buySig || sellSig)
            {
                int d = buySig ? 1 : -1;
                double risk = buySig ? riskLong : riskShort;
                int score = buySig ? bullScore : bearScore;

                _tradeId++;
                _dir = d;
                _stage = 0;
                _entryBar = i;
                _entry = close;
                _sl = close - d * risk;
                _tp1 = close + d * risk * Rr1;
                _tp2 = close + d * risk * Rr2;

                if (buySig)
                    BuySignal[i] = low - atr * 0.5;
                else
                    SellSignal[i] = high + atr * 0.5;

                string text = string.Format("{0} (score {1})\nEntrée: {2:F2}\nSL: {3:F2}\nTP1: {4:F2}\nTP2: {5:F2}",
                    d == 1 ? "BUY" : "SELL", score, _entry, _sl, _tp1, _tp2);
                var label = Chart.DrawText("sig_" + _tradeId, text, i,
                    d == 1 ? low - atr * 0.8 : high + atr * 0.8, d == 1 ? Color.Lime : Color.Red);
                label.FontSize = 9;

                DrawTradeLines(i);
                RaiseAlert(live, d == 1 ? "BUY" : "SELL", _entry, _sl, _tp1, _tp2);
            }
        }

        private void ManageTrade(int i, double high, double low, bool live)
        {
            bool slHit = _dir == 1 ? low <= _sl : high >= _sl;
            bool tp1Hit = _dir == 1 ? high >= _tp1 : low <= _tp1;
            bool tp2Hit = _dir == 1 ? high >= _tp2 : low <= _tp2;
            double share = Tp1Pct / 100.0;
            bool closed = false;
            double rRes = 0.0;
            string kind = "";

            if (_stage == 0)
            {
                if (slHit)
                {
                    rRes = -1.0;
                    kind = "SL";
                    closed = true;
                }
                else if (tp1Hit)
                {
                    _stage = 1;
                    var l1 = Chart.DrawText("tp1_" + _tradeId, "TP1 ✔", i, _tp1, Color.Teal);
                    l1.FontSize = 8;
                    if (MoveToBreakEven)
                        _sl = _entry;
                }
            }
            else
            {
                if (slHit)
                {
                    rRes = MoveToBreakEven ? share * Rr1 : share * Rr1 - (1.0 - share);
                    kind = MoveToBreakEven ? "BE" : "SL";
                    closed = true;
                }
                else if (tp2Hit)
                {
                    rRes = share * Rr1 + (1.0 - share) * Rr2;
                    kind = "TP2";
                    closed = true;
                }
            }

            DrawTradeLines(i);

            if (!closed)
                return;

            _trades++;
            _totalR += rRes;
            if (rRes > 0)
            {
                _wins++;
                _grossWin += rRes;
            }
            else
            {
                _grossLoss += -rRes;
            }

            string text = string.Format("{0} {1}{2:0.##}R", kind, rRes >= 0 ? "+" : "", rRes);
            var res = Chart.DrawText("res_" + _tradeId, text, i,
                _dir == 1 ? high : low, rRes > 0 ? Color.Lime : Color.Red);
            res.FontSize = 9;

            _dir = 0;
            _stage = 0;
            _lastCloseBar = i;
        }

        // Les deux derniers pivots hauts et bas confirmés (PivotLen barres de chaque côté) à la barre i.
        private void GetLastPivots(int i, out double ph1, out double ph2, out double pl1, out double pl2)
        {
            ph1 = ph2 = pl1 = pl2 = double.NaN;
            int start = i - PivotLen;
            int stop = Math.Max(PivotLen, i - 300);

            for (int p = start; p >= stop; p--)
            {
                bool isHigh = true;
                bool isLow = true;
                for (int k = 1; k <= PivotLen; k++)
                {
                    if (Bars.HighPrices[p - k] >= Bars.HighPrices[p] || Bars.HighPrices[p + k] > Bars.HighPrices[p])
                        isHigh = false;
                    if (Bars.LowPrices[p - k] <= Bars.LowPrices[p] || Bars.LowPrices[p + k] < Bars.LowPrices[p])
                        isLow = false;
                    if (!isHigh && !isLow)
                        break;
                }

                if (isHigh)
                {
                    if (double.IsNaN(ph1)) ph1 = Bars.HighPrices[p];
                    else if (double.IsNaN(ph2)) ph2 = Bars.HighPrices[p];
                }
                if (isLow)
                {
                    if (double.IsNaN(pl1)) pl1 = Bars.LowPrices[p];
                    else if (double.IsNaN(pl2)) pl2 = Bars.LowPrices[p];
                }

                if (!double.IsNaN(ph2) && !double.IsNaN(pl2))
                    break;
            }
        }

        private void DrawTradeLines(int i)
        {
            int x1 = _entryBar;
            int x2 = i + 1;
            Chart.DrawTrendLine("e_" + _tradeId, x1, _entry, x2, _entry, Color.Gray, 1, LineStyle.Lines);
            Chart.DrawTrendLine("sl_" + _tradeId, x1, _sl, x2, _sl, Color.Red, 2, LineStyle.Solid);
            Chart.DrawTrendLine("t1_" + _tradeId, x1, _tp1, x2, _tp1, Color.Teal, 1, LineStyle.Solid);
            Chart.DrawTrendLine("t2_" + _tradeId, x1, _tp2, x2, _tp2, Color.Green, 2, LineStyle.Solid);
        }

        private void DrawStats()
        {
            string winRate = _trades > 0 ? string.Format("{0:0.0} %", _wins * 100.0 / _trades) : "-";
            string pf = _grossLoss > 0 ? string.Format("{0:0.00}", _grossWin / _grossLoss) : "-";
            string state = _dir == 1 ? "LONG actif" : _dir == -1 ? "SHORT actif" : "En attente";

            string text = string.Format(
                "OODA GOLD\nÉtat: {0}\nTrades: {1}\nWinrate (R>0): {2}\nR total: {3}{4:0.##} R\nProfit factor: {5}",
                state, _trades, winRate, _totalR >= 0 ? "+" : "", _totalR, pf);

            Chart.DrawStaticText("ooda_stats", text, VerticalAlignment.Top, HorizontalAlignment.Left, Color.White);
        }

        // N'alerte qu'une fois, uniquement sur la bougie qui vient de se clôturer en temps réel
        // (évite les alertes en rafale lors du chargement de l'historique).
        private void RaiseAlert(bool live, string direction, double entry, double sl, double tp1, double tp2)
        {
            if (!live)
                return;

            string message = string.Format(
                "OODA Gold {0} ({1} {2}) | Entrée: {3:F2} SL: {4:F2} TP1: {5:F2} TP2: {6:F2}",
                direction, SymbolName, TimeFrame, entry, sl, tp1, tp2);

            Print(message);

            if (EnableSoundAlert)
                Notifications.PlaySound(SoundFile);
        }
    }
}
