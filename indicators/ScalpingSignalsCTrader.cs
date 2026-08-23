// Trend Pullback + Momentum Confirmation — scalping signal indicator (cTrader / cAlgo.API)
// For XAUUSD / US30 on M5-M15. Educational use only, no profit guarantee.
//
// Utilisation : ouvrir cTrader > Automate > Indicators > New Indicator, coller ce fichier
// (ou l'ajouter dans le dossier Indicators de votre répertoire cAlgo), puis Build.
// Logique identique à indicators/scalping_signals.pine (TradingView), portée en C#.

using System;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Indicators
{
    [Indicator(IsOverlay = true, TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class ScalpingSignalsCTrader : Indicator
    {
        [Parameter("Timeframe biais (H1 recommandé)", DefaultValue = "Hour", Group = "Biais de tendance (HTF)")]
        public TimeFrame HtfTimeFrame { get; set; }

        [Parameter("EMA rapide HTF", DefaultValue = 50, MinValue = 1, Group = "Biais de tendance (HTF)")]
        public int EmaFastPeriod { get; set; }

        [Parameter("EMA lente HTF", DefaultValue = 200, MinValue = 1, Group = "Biais de tendance (HTF)")]
        public int EmaSlowPeriod { get; set; }

        [Parameter("EMA pullback (locale)", DefaultValue = 21, MinValue = 1, Group = "Pullback / structure locale")]
        public int EmaPullbackPeriod { get; set; }

        [Parameter("Lookback swing (barres) pour SL", DefaultValue = 10, MinValue = 2, Group = "Pullback / structure locale")]
        public int SwingLookback { get; set; }

        [Parameter("Longueur ADX/DMI", DefaultValue = 14, MinValue = 1, Group = "Filtre de force de tendance (ADX/DMI)")]
        public int AdxPeriod { get; set; }

        [Parameter("Seuil ADX minimum (20-25)", DefaultValue = 22.0, MinValue = 0, Group = "Filtre de force de tendance (ADX/DMI)")]
        public double AdxThreshold { get; set; }

        [Parameter("Longueur RSI", DefaultValue = 14, MinValue = 1, Group = "Momentum (RSI)")]
        public int RsiPeriod { get; set; }

        [Parameter("Niveau survente RSI", DefaultValue = 30, MinValue = 1, MaxValue = 50, Group = "Momentum (RSI)")]
        public int RsiOversold { get; set; }

        [Parameter("Niveau surachat RSI", DefaultValue = 70, MinValue = 50, MaxValue = 99, Group = "Momentum (RSI)")]
        public int RsiOverbought { get; set; }

        [Parameter("Longueur ATR", DefaultValue = 14, MinValue = 1, Group = "Stop Loss / Take Profit (indicatif)")]
        public int AtrPeriod { get; set; }

        [Parameter("Multiplicateur ATR pour buffer SL", DefaultValue = 1.0, MinValue = 0.1, Step = 0.1, Group = "Stop Loss / Take Profit (indicatif)")]
        public double AtrMultiplier { get; set; }

        [Parameter("RR TP1", DefaultValue = 1.0, MinValue = 0.1, Step = 0.1, Group = "Stop Loss / Take Profit (indicatif)")]
        public double RrTp1 { get; set; }

        [Parameter("RR TP2", DefaultValue = 2.0, MinValue = 0.1, Step = 0.1, Group = "Stop Loss / Take Profit (indicatif)")]
        public double RrTp2 { get; set; }

        [Parameter("RR TP3 (référence trailing)", DefaultValue = 3.0, MinValue = 0.1, Step = 0.1, Group = "Stop Loss / Take Profit (indicatif)")]
        public double RrTp3 { get; set; }

        [Parameter("Afficher labels SL/TP", DefaultValue = true, Group = "Affichage")]
        public bool ShowLabels { get; set; }

        [Parameter("Alerte sonore (dernière barre)", DefaultValue = false, Group = "Alertes")]
        public bool EnableSoundAlert { get; set; }

        [Parameter("Fichier son (.wav)", DefaultValue = "Alert1.wav", Group = "Alertes")]
        public string SoundFile { get; set; }

        [Output("EMA Pullback (locale)", LineColor = "Orange", Thickness = 1)]
        public IndicatorDataSeries EmaPullbackLine { get; set; }

        [Output("EMA rapide HTF", LineColor = "DodgerBlue", Thickness = 1)]
        public IndicatorDataSeries EmaFastHtfLine { get; set; }

        [Output("EMA lente HTF", LineColor = "Crimson", Thickness = 1)]
        public IndicatorDataSeries EmaSlowHtfLine { get; set; }

        [Output("Buy Signal", LineColor = "Lime", PlotType = PlotType.Points, Thickness = 5)]
        public IndicatorDataSeries BuySignal { get; set; }

        [Output("Sell Signal", LineColor = "Red", PlotType = PlotType.Points, Thickness = 5)]
        public IndicatorDataSeries SellSignal { get; set; }

        private MovingAverage _emaPullback;
        private MovingAverage _htfEmaFast;
        private MovingAverage _htfEmaSlow;
        private DirectionalMovementSystem _dmi;
        private RelativeStrengthIndex _rsi;
        private AverageTrueRange _atr;
        private Bars _htfBars;

        private int _lastAlertedIndex = -1;

        protected override void Initialize()
        {
            _htfBars = MarketData.GetBars(HtfTimeFrame);

            _emaPullback = Indicators.MovingAverage(Bars.ClosePrices, EmaPullbackPeriod, MovingAverageType.Exponential);
            _htfEmaFast = Indicators.MovingAverage(_htfBars.ClosePrices, EmaFastPeriod, MovingAverageType.Exponential);
            _htfEmaSlow = Indicators.MovingAverage(_htfBars.ClosePrices, EmaSlowPeriod, MovingAverageType.Exponential);

            _dmi = Indicators.DirectionalMovementSystem(AdxPeriod);
            _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, RsiPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Exponential);
        }

        public override void Calculate(int index)
        {
            BuySignal[index] = double.NaN;
            SellSignal[index] = double.NaN;
            EmaPullbackLine[index] = _emaPullback.Result[index];

            // --- Biais de tendance HTF (H1) ---
            int htfIndex = _htfBars.OpenTimes.GetIndexByTime(Bars.OpenTimes[index]);
            if (htfIndex < 1)
                return;

            double htfEmaFast = _htfEmaFast.Result[htfIndex];
            double htfEmaSlow = _htfEmaSlow.Result[htfIndex];
            double htfClose = _htfBars.ClosePrices[htfIndex];

            EmaFastHtfLine[index] = htfEmaFast;
            EmaSlowHtfLine[index] = htfEmaSlow;

            bool biasBullish = htfEmaFast > htfEmaSlow && htfClose > htfEmaFast;
            bool biasBearish = htfEmaFast < htfEmaSlow && htfClose < htfEmaFast;

            if (index < SwingLookback + 1)
                return;

            double close = Bars.ClosePrices[index];
            double open = Bars.OpenPrices[index];
            double high = Bars.HighPrices[index];
            double low = Bars.LowPrices[index];
            double closePrev = Bars.ClosePrices[index - 1];
            double openPrev = Bars.OpenPrices[index - 1];

            double emaPullback = _emaPullback.Result[index];

            // --- Zone de pullback (EMA21 locale) ---
            bool nearPullbackLong = low <= emaPullback && close >= emaPullback;
            bool nearPullbackShort = high >= emaPullback && close <= emaPullback;

            // --- Swing du pullback (pour le SL) : inclut la barre courante ---
            double swingLow = low;
            double swingHigh = high;
            for (int i = index - SwingLookback + 1; i < index; i++)
            {
                swingLow = Math.Min(swingLow, Bars.LowPrices[i]);
                swingHigh = Math.Max(swingHigh, Bars.HighPrices[i]);
            }

            // --- Micro-structure (hors barre courante) : pour la cassure ---
            double microHigh = double.MinValue;
            double microLow = double.MaxValue;
            for (int i = index - SwingLookback; i < index; i++)
            {
                microHigh = Math.Max(microHigh, Bars.HighPrices[i]);
                microLow = Math.Min(microLow, Bars.LowPrices[i]);
            }

            // --- Filtre ADX/DMI ---
            double adxValue = _dmi.ADX[index];
            bool adxOk = adxValue > AdxThreshold;

            // --- Momentum RSI : sortie de zone extrême ---
            double rsiValue = _rsi.Result[index];
            double rsiPrev = _rsi.Result[index - 1];
            bool rsiExitOversold = rsiValue > RsiOversold && rsiPrev <= RsiOversold;
            bool rsiExitOverbought = rsiValue < RsiOverbought && rsiPrev >= RsiOverbought;

            // --- Pattern de bougie : engulfing simple ---
            bool bullEngulfing = closePrev < openPrev && close > open && close >= openPrev && open <= closePrev;
            bool bearEngulfing = closePrev > openPrev && close < open && close <= openPrev && open >= closePrev;

            // --- Cassure de micro-structure ---
            bool structureBreakUp = close > microHigh;
            bool structureBreakDown = close < microLow;

            // --- Confirmation d'entrée : au moins un signal parmi les trois ---
            bool confirmLong = bullEngulfing || rsiExitOversold || structureBreakUp;
            bool confirmShort = bearEngulfing || rsiExitOverbought || structureBreakDown;

            bool longSignal = biasBullish && nearPullbackLong && adxOk && confirmLong;
            bool shortSignal = biasBearish && nearPullbackShort && adxOk && confirmShort;

            double atrValue = _atr.Result[index];

            if (longSignal)
            {
                BuySignal[index] = low - atrValue * 0.5;

                double sl = swingLow - atrValue * AtrMultiplier;
                double risk = close - sl;
                double tp1 = close + risk * RrTp1;
                double tp2 = close + risk * RrTp2;
                double tp3 = close + risk * RrTp3;

                if (ShowLabels)
                {
                    string text = string.Format("BUY\nSL: {0:F5}\nTP1: {1:F5}\nTP2: {2:F5}\nTP3: {3:F5}", sl, tp1, tp2, tp3);
                    var label = Chart.DrawText("buy_" + index, text, index, low - atrValue * 0.7, Color.Lime);
                    label.FontSize = 9;
                }

                RaiseAlert(index, "BUY", sl, tp1, tp2);
            }

            if (shortSignal)
            {
                SellSignal[index] = high + atrValue * 0.5;

                double sl = swingHigh + atrValue * AtrMultiplier;
                double risk = sl - close;
                double tp1 = close - risk * RrTp1;
                double tp2 = close - risk * RrTp2;
                double tp3 = close - risk * RrTp3;

                if (ShowLabels)
                {
                    string text = string.Format("SELL\nSL: {0:F5}\nTP1: {1:F5}\nTP2: {2:F5}\nTP3: {3:F5}", sl, tp1, tp2, tp3);
                    var label = Chart.DrawText("sell_" + index, text, index, high + atrValue * 0.7, Color.Red);
                    label.FontSize = 9;
                }

                RaiseAlert(index, "SELL", sl, tp1, tp2);
            }
        }

        // N'alerte qu'une seule fois par barre, uniquement sur la barre courante/en cours de formation
        // (évite les alertes répétées lors du repaint historique au chargement de l'indicateur).
        private void RaiseAlert(int index, string direction, double sl, double tp1, double tp2)
        {
            if (!IsLastBar || _lastAlertedIndex == index)
                return;

            _lastAlertedIndex = index;

            string message = string.Format(
                "Scalping {0} signal ({1} {2}) - Trend Pullback + Momentum | SL: {3:F5} TP1: {4:F5} TP2: {5:F5}",
                direction, SymbolName, TimeFrame, sl, tp1, tp2);

            Print(message);

            if (EnableSoundAlert)
                Notifications.PlaySound(SoundFile);
        }
    }
}
