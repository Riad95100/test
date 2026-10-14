//+------------------------------------------------------------------+
//| LiquidityLevels.mq5                                              |
//| Niveaux de liquidité : BSL/SSL (swings), EQH/EQL, PDH/PDL,       |
//| PWH/PWL, PMH/PML, plages Asie / Londres / New York.              |
//| Fonctionne sur n'importe quel symbole / TF.                      |
//| Usage éducatif uniquement, aucune garantie de performance.       |
//|                                                                  |
//| BSL = liquidité acheteuse (stops au-dessus d'un plus haut)       |
//| SSL = liquidité vendeuse  (stops sous un plus bas)               |
//| EQH/EQL = Equal Highs / Equal Lows (liquidité plus dense)        |
//| Asia/London/NY H & L = extrêmes de session, actifs jusqu'au sweep|
//| Un niveau balayé (swept) s'arrête et passe en gris.              |
//+------------------------------------------------------------------+
#property copyright   "Educational use only"
#property version     "1.10"
#property description "Liquidity Levels : BSL/SSL, EQH/EQL, PDH/PDL, PWH/PWL, PMH/PML, sessions"
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

input group "Sessions (heures UTC, timeframes intraday)"
input int    InpServerUtcOffset = 2;             // Décalage UTC de l'heure serveur du broker (ex: 2 ou 3)
input bool   InpShowAsia   = true;               // Session Asie
input string InpAsiaRange  = "00:00-08:00";      // Plage Asie (HH:MM-HH:MM, UTC)
input bool   InpShowLondon = true;               // Session Londres
input string InpLondonRange = "07:00-16:00";     // Plage Londres (HH:MM-HH:MM, UTC)
input bool   InpShowNY     = true;               // Session New York
input string InpNYRange    = "12:00-21:00";      // Plage New York (HH:MM-HH:MM, UTC)
input bool   InpShowSessBox = true;              // Dessiner la plage de chaque session (rectangle)
input int    InpMaxSessBoxes = 10;               // Rectangles max par session
input int    InpMaxSessLevels = 2;               // Niveaux actifs max par session et par côté
input color  InpColAsia    = C'156,39,176';      // Couleur Asie
input color  InpColLondon  = C'41,98,255';       // Couleur Londres
input color  InpColNY      = C'236,64,122';      // Couleur New York

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
#define NSESS 3

struct Lvl
  {
   datetime t;        // heure de la bougie du pivot / du début de session
   double   price;
   bool     isHigh;
   bool     eq;
   int      iSwept;   // index de la bougie du sweep (-1 = actif)
   datetime tSwept;   // heure du sweep (0 = actif)
   int      kind;     // 0 = swing, 1..3 = Asie / Londres / New York
   string   tag;      // libellé des niveaux de session
  };

struct SessBox
  {
   datetime t1;
   datetime t2;
   double   hi;
   double   lo;
   int      kind;     // 1..3
  };

Lvl      g_lv[];
SessBox  g_bx[];
datetime g_lastBar = 0;
bool     g_ready   = false;
int      g_retries = 0;
bool     g_needRetry = false;

// Configuration des sessions (index 0..2)
bool     g_sOn[NSESS];
int      g_sFrom[NSESS];   // minutes depuis 00:00 UTC
int      g_sTo[NSESS];
string   g_sName[NSESS] = {"Asia", "London", "NY"};
color    g_sCol[NSESS];

//+------------------------------------------------------------------+
//| "HH:MM-HH:MM" -> minutes de début / fin                          |
//+------------------------------------------------------------------+
bool ParseRange(const string s, int &from, int &to)
  {
   string r[];
   if(StringSplit(s, '-', r) != 2)
      return(false);
   int v[2];
   for(int k = 0; k < 2; k++)
     {
      string p[];
      if(StringSplit(r[k], ':', p) != 2)
         return(false);
      int h = (int)StringToInteger(p[0]);
      int m = (int)StringToInteger(p[1]);
      if(h < 0 || h > 24 || m < 0 || m > 59)
         return(false);
      v[k] = h * 60 + m;
     }
   from = v[0];
   to   = v[1];
   return(from != to);
  }
//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME, "Liquidity Levels");

   bool   on[NSESS];
   string rng[NSESS];
   color  col[NSESS];
   on[0] = InpShowAsia;   rng[0] = InpAsiaRange;   col[0] = InpColAsia;
   on[1] = InpShowLondon; rng[1] = InpLondonRange; col[1] = InpColLondon;
   on[2] = InpShowNY;     rng[2] = InpNYRange;     col[2] = InpColNY;
   for(int s = 0; s < NSESS; s++)
     {
      g_sCol[s] = col[s];
      g_sOn[s]  = on[s] && ParseRange(rng[s], g_sFrom[s], g_sTo[s]);
      if(on[s] && !g_sOn[s])
         PrintFormat("Liquidity Levels: plage de session invalide pour %s : '%s' (format HH:MM-HH:MM)",
                     g_sName[s], rng[s]);
     }
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
   if(l.kind > 0)
      return(l.tag);
   if(l.isHigh)
      return(l.eq ? "EQH" : "BSL");
   return(l.eq ? "EQL" : "SSL");
  }
//+------------------------------------------------------------------+
color LvlColor(const Lvl &l)
  {
   if(l.kind > 0)
      return(g_sCol[l.kind - 1]);
   return(l.isHigh ? InpColBSL : InpColSSL);
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
void Rect(const string name, const datetime t1, const double p1, const datetime t2, const double p2, const color c)
  {
   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_FILL, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
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

   // Niveaux actifs : les plus récents d'abord, limités par catégorie et par côté
   // (swings : InpMaxLevels ; chaque session : InpMaxSessLevels)
   int cnt[NSESS + 1][2];
   ArrayInitialize(cnt, 0);
   for(int q = n - 1; q >= 0; q--)
     {
      if(g_lv[q].tSwept != 0)
         continue;
      int side = g_lv[q].isHigh ? 0 : 1;
      int cap  = (g_lv[q].kind == 0) ? InpMaxLevels : InpMaxSessLevels;
      if(cnt[g_lv[q].kind][side] >= cap)
         continue;
      cnt[g_lv[q].kind][side]++;

      color c = LvlColor(g_lv[q]);
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

   // Rectangles de session : les plus récents de chaque session
   if(InpShowSessBox)
     {
      int bc[NSESS + 1];
      ArrayInitialize(bc, 0);
      for(int q = ArraySize(g_bx) - 1; q >= 0; q--)
        {
         int kd = g_bx[q].kind;
         if(bc[kd] >= InpMaxSessBoxes)
            continue;
         bc[kd]++;
         Rect(PFX + "B" + IntegerToString(q), g_bx[q].t1, g_bx[q].hi, g_bx[q].t2, g_bx[q].lo, g_sCol[kd - 1]);
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
//| Première bougie >= from qui dépasse le niveau (-1 si aucune)     |
//+------------------------------------------------------------------+
int FindSweep(const bool isHigh, const double price, const int from, const int last,
              const double &high[], const double &low[], const double &close[])
  {
   for(int j = from; j <= last; j++)
     {
      if(isHigh)
        {
         if((InpSweepMode == SWEEP_WICK ? high[j] : close[j]) > price)
            return(j);
        }
      else
        {
         if((InpSweepMode == SWEEP_WICK ? low[j] : close[j]) < price)
            return(j);
        }
     }
   return(-1);
  }
//+------------------------------------------------------------------+
void AddLevel(const datetime t, const double price, const bool isHigh, const bool eq, const int sw,
              const datetime &time[], const int kind, const string tag)
  {
   int n = ArraySize(g_lv);
   ArrayResize(g_lv, n + 1);
   g_lv[n].t      = t;
   g_lv[n].price  = price;
   g_lv[n].isHigh = isHigh;
   g_lv[n].eq     = eq;
   g_lv[n].iSwept = sw;
   g_lv[n].tSwept = (sw >= 0) ? time[sw] : 0;
   g_lv[n].kind   = kind;
   g_lv[n].tag    = tag;
  }
//+------------------------------------------------------------------+
void AddBox(const int kind, const datetime t1, const datetime t2, const double hi, const double lo)
  {
   int n = ArraySize(g_bx);
   ArrayResize(g_bx, n + 1);
   g_bx[n].t1   = t1;
   g_bx[n].t2   = t2;
   g_bx[n].hi   = hi;
   g_bx[n].lo   = lo;
   g_bx[n].kind = kind;
  }
//+------------------------------------------------------------------+
//| Plages d'une session : extrêmes, rectangles et niveaux de        |
//| liquidité (high / low) à la fin de chaque session                |
//+------------------------------------------------------------------+
void BuildSession(const int s, const int total, const int start, const datetime &time[],
                  const double &high[], const double &low[], const double &close[])
  {
   const int last = total - 1;
   const int from = g_sFrom[s];
   const int to   = g_sTo[s];
   const bool wrap = (from > to);   // session à cheval sur minuit
   const int kind = s + 1;

   long   prevKey = -1;
   double sh = 0.0, sl = 0.0;
   int    sIdx = 0;

   for(int i = start; i <= last; i++)
     {
      long u   = (long)time[i] - (long)InpServerUtcOffset * 3600;
      int  mod = (int)((u % 86400) / 60);
      long day = u / 86400;

      bool inS = wrap ? (mod >= from || mod < to) : (mod >= from && mod < to);
      long key = -1;
      if(inS)
         key = (wrap && mod < to) ? day - 1 : day;

      if(key != prevKey)
        {
         // la session précédente vient de se terminer à la bougie i (non incluse)
         if(prevKey != -1)
           {
            AddBox(kind, time[sIdx], time[i - 1], sh, sl);
            AddLevel(time[sIdx], sh, true,  false, FindSweep(true,  sh, i, last, high, low, close), time, kind, g_sName[s] + " H");
            AddLevel(time[sIdx], sl, false, false, FindSweep(false, sl, i, last, high, low, close), time, kind, g_sName[s] + " L");
           }
         if(key != -1)
           {
            sh = high[i];
            sl = low[i];
            sIdx = i;
           }
         prevKey = key;
        }
      else
         if(key != -1)
           {
            sh = MathMax(sh, high[i]);
            sl = MathMin(sl, low[i]);
           }
     }

   // Session en cours : rectangle seulement (le niveau naît à la fin de la session)
   if(prevKey != -1)
      AddBox(kind, time[sIdx], time[last], sh, sl);
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

   ArrayResize(g_lv, 0);
   ArrayResize(g_bx, 0);

   // --- Swings, EQH/EQL ------------------------------------------------
   if(InpShowSwings)
     {
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
            int    sw    = FindSweep(isHigh, price, i + 1, last, high, low, close);

            // Equal Highs / Lows : niveau de même côté encore actif à la confirmation du pivot
            bool eq = false;
            if(InpShowEq)
              {
               double tol = InpEqTol * atr[i + L];
               for(int q = 0; q < ArraySize(g_lv); q++)
                 {
                  if(g_lv[q].kind != 0 || g_lv[q].isHigh != isHigh)
                     continue;
                  bool alive = (g_lv[q].iSwept < 0 || g_lv[q].iSwept > i + L);
                  if(alive && MathAbs(g_lv[q].price - price) <= tol)
                    {
                     g_lv[q].eq = true;
                     eq = true;
                    }
                 }
              }
            AddLevel(time[i], price, isHigh, eq, sw, time, 0, "");
           }
        }
     }

   // --- Sessions -------------------------------------------------------
   if(PeriodSeconds(_Period) < PeriodSeconds(PERIOD_D1))
     {
      for(int s = 0; s < NSESS; s++)
         if(g_sOn[s])
            BuildSession(s, total, start, time, high, low, close);
     }

   // Alertes : un niveau actif avant recalcul qui est maintenant balayé
   if(g_ready && total >= 2)
     {
      int n = ArraySize(g_lv);
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
   if(!redo && InpSweepMode == SWEEP_WICK)
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
