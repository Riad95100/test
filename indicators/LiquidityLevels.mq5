//+------------------------------------------------------------------+
//| LiquidityLevels.mq5                                              |
//| Niveaux de liquidité : BSL/SSL (swings), EQH/EQL, PDH/PDL,       |
//| PWH/PWL, PMH/PML. Fonctionne sur n'importe quel symbole / TF.    |
//| Usage éducatif uniquement, aucune garantie de performance.       |
//|                                                                  |
//| BSL = liquidité acheteuse (stops au-dessus d'un plus haut)       |
//| SSL = liquidité vendeuse  (stops sous un plus bas)               |
//| EQH/EQL = Equal Highs / Equal Lows (liquidité plus dense)        |
//| Un niveau balayé (swept) s'arrête et passe en gris.              |
//+------------------------------------------------------------------+
#property copyright   "Educational use only"
#property version     "1.00"
#property description "Liquidity Levels : BSL/SSL, EQH/EQL, PDH/PDL, PWH/PWL, PMH/PML"
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

enum ENUM_SWEEP_MODE
  {
   SWEEP_WICK  = 0, // Mèche (sweep)
   SWEEP_CLOSE = 1  // Clôture (break)
  };

input group "Swings (BSL / SSL)"
input bool   InpShowSwings = true;   // Afficher les swings BSL / SSL
input int    InpSwingLen   = 5;      // Longueur du pivot (barres de chaque côté)
input int    InpMaxLevels  = 8;      // Niveaux actifs max par côté
input int    InpLookback   = 1500;   // Historique analysé (barres)

input group "Equal Highs / Equal Lows"
input bool   InpShowEq     = true;   // Détecter EQH / EQL
input double InpEqTol      = 0.15;   // Tolérance (x ATR)
input int    InpAtrLen     = 14;     // Longueur ATR

input group "Sweep (niveau balayé)"
input ENUM_SWEEP_MODE InpSweepMode = SWEEP_WICK; // Détection
input bool   InpShowSwept  = true;   // Garder les niveaux balayés (grisés)
input int    InpMaxSwept   = 10;     // Niveaux balayés max affichés

input group "Niveaux de périodes précédentes"
input bool   InpShowPD     = true;   // Jour précédent (PDH / PDL)
input bool   InpShowPW     = true;   // Semaine précédente (PWH / PWL)
input bool   InpShowPM     = true;   // Mois précédent (PMH / PML)

input group "Style"
input color  InpColBSL     = C'242,54,69';   // Couleur BSL / EQH
input color  InpColSSL     = C'8,153,129';   // Couleur SSL / EQL
input color  InpColPeriod  = C'255,179,0';   // Couleur PDH/PDL/PWH/PWL/PMH/PML
input color  InpColSwept   = clrGray;        // Couleur niveau balayé
input ENUM_LINE_STYLE InpLineStyle = STYLE_DASH; // Style de ligne (EQH/EQL toujours en continu)
input int    InpLineWidth  = 1;      // Épaisseur (1 requis pour tirets/pointillés)
input int    InpFontSize   = 8;      // Taille des labels
input int    InpLabelOffset = 3;     // Décalage des labels à droite (barres)

input group "Alertes (sweep d'un niveau actif)"
input bool   InpAlertPopup = true;   // Pop-up
input bool   InpAlertPush  = false;  // Notification push
input bool   InpAlertSound = false;  // Son

#define PFX "LQ_"

struct Lvl
  {
   datetime t;        // heure de la bougie du pivot
   double   price;
   bool     isHigh;
   bool     eq;
   int      iSwept;   // index de la bougie du sweep (-1 = actif)
   datetime tSwept;   // heure du sweep (0 = actif)
  };

Lvl      g_lv[];
datetime g_lastBar = 0;
bool     g_ready   = false;
int      g_retries = 0;
bool     g_needRetry = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME, "Liquidity Levels");
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, PFX);
  }
//+------------------------------------------------------------------+
string LvlName(const Lvl &l)
  {
   if(l.isHigh)
      return(l.eq ? "EQH" : "BSL");
   return(l.eq ? "EQL" : "SSL");
  }
//+------------------------------------------------------------------+
void Trend(const string name, const datetime t1, const double p1, const datetime t2, const double p2,
           const color c, const ENUM_LINE_STYLE st, const int w, const bool ray)
  {
   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, st);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, w);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, ray);
   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }
//+------------------------------------------------------------------+
void Txt(const string name, const datetime t, const double p, const string s, const color c)
  {
   if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, p))
      return;
   ObjectSetString(0, name, OBJPROP_TEXT, s);
   ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpFontSize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }
//+------------------------------------------------------------------+
//| Niveaux jour / semaine / mois précédents                         |
//+------------------------------------------------------------------+
void DrawPeriod(const ENUM_TIMEFRAMES tf, const string hTag, const string lTag,
                const bool on, const datetime tLast)
  {
   if(!on)
      return;
   int ps = PeriodSeconds(_Period);
   if(ps >= PeriodSeconds(tf))
      return;

   double   h  = iHigh(_Symbol, tf, 1);
   double   l  = iLow(_Symbol, tf, 1);
   datetime t0 = iTime(_Symbol, tf, 0);
   if(h <= 0.0 || l <= 0.0 || t0 == 0)
     {
      g_needRetry = true;   // données de la période pas encore chargées
      return;
     }

   Trend(PFX + "P" + hTag, t0, h, t0 + ps, h, InpColPeriod, STYLE_SOLID, 1, true);
   Trend(PFX + "P" + lTag, t0, l, t0 + ps, l, InpColPeriod, STYLE_SOLID, 1, true);
   Txt(PFX + "PT" + hTag, tLast + (datetime)(ps * InpLabelOffset), h, hTag, InpColPeriod);
   Txt(PFX + "PT" + lTag, tLast + (datetime)(ps * InpLabelOffset), l, lTag, InpColPeriod);
  }
//+------------------------------------------------------------------+
void DrawAll(const int total, const datetime &time[])
  {
   ObjectsDeleteAll(0, PFX);
   g_needRetry = false;

   datetime tLast = time[total - 1];
   int      ps    = PeriodSeconds(_Period);
   datetime tLbl  = tLast + (datetime)(ps * InpLabelOffset);
   int      n     = ArraySize(g_lv);

   if(InpShowSwings)
     {
      // Niveaux actifs : les plus récents d'abord, limités par côté
      int cntH = 0, cntL = 0;
      for(int q = n - 1; q >= 0; q--)
        {
         if(g_lv[q].tSwept != 0)
            continue;
         if(g_lv[q].isHigh)
           {
            if(cntH >= InpMaxLevels)
               continue;
            cntH++;
           }
         else
           {
            if(cntL >= InpMaxLevels)
               continue;
            cntL++;
           }
         color c = g_lv[q].isHigh ? InpColBSL : InpColSSL;
         ENUM_LINE_STYLE st = g_lv[q].eq ? STYLE_SOLID : InpLineStyle;
         int w = g_lv[q].eq ? InpLineWidth + 1 : InpLineWidth;
         string id = IntegerToString(q);
         Trend(PFX + "A" + id, g_lv[q].t, g_lv[q].price, g_lv[q].t + ps, g_lv[q].price, c, st, w, true);
         Txt(PFX + "AT" + id, tLbl, g_lv[q].price, LvlName(g_lv[q]), c);
        }

      // Niveaux balayés : les InpMaxSwept plus récents (tri par date de sweep)
      if(InpShowSwept)
        {
         int sw[];
         int ns = 0;
         for(int q = 0; q < n; q++)
           {
            if(g_lv[q].tSwept == 0)
               continue;
            ArrayResize(sw, ns + 1);
            sw[ns] = q;
            ns++;
           }
         for(int a = 1; a < ns; a++)
           {
            int key = sw[a];
            int b = a - 1;
            while(b >= 0 && g_lv[sw[b]].tSwept > g_lv[key].tSwept)
              {
               sw[b + 1] = sw[b];
               b--;
              }
            sw[b + 1] = key;
           }
         for(int a = MathMax(0, ns - InpMaxSwept); a < ns; a++)
           {
            int q = sw[a];
            string id = IntegerToString(q);
            Trend(PFX + "S" + id, g_lv[q].t, g_lv[q].price, g_lv[q].tSwept, g_lv[q].price,
                  InpColSwept, STYLE_DOT, 1, false);
            Txt(PFX + "ST" + id, g_lv[q].tSwept, g_lv[q].price, LvlName(g_lv[q]) + " x", InpColSwept);
           }
        }
     }

   DrawPeriod(PERIOD_D1,  "PDH", "PDL", InpShowPD, tLast);
   DrawPeriod(PERIOD_W1,  "PWH", "PWL", InpShowPW, tLast);
   DrawPeriod(PERIOD_MN1, "PMH", "PML", InpShowPM, tLast);
  }
//+------------------------------------------------------------------+
void Notify(const string msg)
  {
   if(InpAlertPopup)
      Alert(msg);
   if(InpAlertPush)
      SendNotification(msg);
   if(InpAlertSound)
      PlaySound("alert.wav");
  }
//+------------------------------------------------------------------+
//| Recalcule tous les niveaux sur la fenêtre InpLookback            |
//+------------------------------------------------------------------+
void Recompute(const int total, const datetime &time[], const double &high[],
               const double &low[], const double &close[])
  {
   const int L    = InpSwingLen;
   const int last = total - 1;
   const int start = MathMax(1, total - InpLookback);

   // Niveaux actifs connus avant recalcul (pour détecter les nouveaux sweeps)
   datetime pT[];
   double   pP[];
   bool     pH[];
   int      np = 0;
   for(int q = 0; q < ArraySize(g_lv); q++)
     {
      if(g_lv[q].tSwept != 0)
         continue;
      ArrayResize(pT, np + 1);
      ArrayResize(pP, np + 1);
      ArrayResize(pH, np + 1);
      pT[np] = g_lv[q].t;
      pP[np] = g_lv[q].price;
      pH[np] = g_lv[q].isHigh;
      np++;
     }

   // ATR (moyenne simple du True Range)
   double tr[], atr[];
   ArrayResize(tr, total);
   ArrayResize(atr, total);
   ArrayInitialize(tr, 0.0);
   ArrayInitialize(atr, 0.0);
   int    a0  = MathMax(1, start - InpAtrLen);
   double sum = 0.0;
   for(int i = a0; i < total; i++)
     {
      double t = MathMax(high[i] - low[i], MathMax(MathAbs(high[i] - close[i - 1]), MathAbs(low[i] - close[i - 1])));
      tr[i] = t;
      sum += t;
      if(i - a0 >= InpAtrLen)
         sum -= tr[i - InpAtrLen];
      atr[i] = sum / (double)MathMin(i - a0 + 1, InpAtrLen);
     }

   // Détection des pivots, du sweep et des EQH/EQL
   ArrayResize(g_lv, 0);
   int n = 0;
   for(int i = start + L; i <= last - L; i++)
     {
      bool isPH = true, isPL = true;
      for(int k = 1; k <= L && (isPH || isPL); k++)
        {
         if(!(high[i] > high[i - k]))  isPH = false;
         if(!(high[i] >= high[i + k])) isPH = false;
         if(!(low[i] < low[i - k]))    isPL = false;
         if(!(low[i] <= low[i + k]))   isPL = false;
        }

      for(int side = 0; side < 2; side++)
        {
         bool isHigh = (side == 0);
         if(isHigh ? !isPH : !isPL)
            continue;

         double price = isHigh ? high[i] : low[i];

         // Premier dépassement du niveau après le pivot
         int sw = -1;
         for(int j = i + 1; j <= last; j++)
           {
            bool crossed;
            if(isHigh)
               crossed = ((InpSweepMode == SWEEP_WICK ? high[j] : close[j]) > price);
            else
               crossed = ((InpSweepMode == SWEEP_WICK ? low[j] : close[j]) < price);
            if(crossed)
              {
               sw = j;
               break;
              }
           }

         // Equal Highs / Lows : niveau de même côté encore actif à la confirmation du pivot
         bool eq = false;
         if(InpShowEq)
           {
            double tol = InpEqTol * atr[i + L];
            for(int q = 0; q < n; q++)
              {
               if(g_lv[q].isHigh != isHigh)
                  continue;
               bool alive = (g_lv[q].iSwept < 0 || g_lv[q].iSwept > i + L);
               if(alive && MathAbs(g_lv[q].price - price) <= tol)
                 {
                  g_lv[q].eq = true;
                  eq = true;
                 }
              }
           }

         ArrayResize(g_lv, n + 1);
         g_lv[n].t      = time[i];
         g_lv[n].price  = price;
         g_lv[n].isHigh = isHigh;
         g_lv[n].eq     = eq;
         g_lv[n].iSwept = sw;
         g_lv[n].tSwept = (sw >= 0) ? time[sw] : 0;
         n++;
        }
     }

   // Alertes : un niveau actif avant recalcul qui est maintenant balayé
   if(g_ready && total >= 2)
     {
      for(int p = 0; p < np; p++)
        {
         for(int q = 0; q < n; q++)
           {
            if(g_lv[q].t == pT[p] && g_lv[q].isHigh == pH[p] && MathAbs(g_lv[q].price - pP[p]) < _Point / 2.0)
              {
               if(g_lv[q].tSwept != 0 && g_lv[q].tSwept >= time[total - 2])
                  Notify(StringFormat("%s %s: %s balayée @ %s", _Symbol, EnumToString(_Period),
                                      LvlName(g_lv[q]), DoubleToString(g_lv[q].price, _Digits)));
               break;
              }
           }
        }
     }

   DrawAll(total, time);
   g_ready = true;
   ChartRedraw();
  }
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total < 2 * InpSwingLen + 3)
      return(0);

   ArraySetAsSeries(time, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);

   int  last   = rates_total - 1;
   bool redo   = (prev_calculated == 0 || time[last] != g_lastBar);

   // Détection en direct d'un sweep par mèche (évite d'attendre la prochaine bougie)
   if(!redo && InpShowSwings && InpSweepMode == SWEEP_WICK)
     {
      for(int q = 0; q < ArraySize(g_lv); q++)
        {
         if(g_lv[q].tSwept != 0)
            continue;
         if(g_lv[q].isHigh ? high[last] > g_lv[q].price : low[last] < g_lv[q].price)
           {
            redo = true;
            break;
           }
        }
     }

   // Données D1/W1/MN1 pas encore disponibles : quelques tentatives
   if(!redo && g_needRetry && g_retries < 20)
     {
      g_retries++;
      redo = true;
     }

   if(redo)
     {
      if(time[last] != g_lastBar)
         g_retries = 0;
      g_lastBar = time[last];
      Recompute(rates_total, time, high, low, close);
     }

   return(rates_total);
  }
//+------------------------------------------------------------------+
