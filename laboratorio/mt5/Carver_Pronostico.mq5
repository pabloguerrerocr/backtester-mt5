//+------------------------------------------------------------------+
//| Pronostico de tendencia de Robert Carver (EWMAC), ventana aparte |
//| Promedio de 4 cruces de EMA (8/32, 16/64, 32/128, 64/256), cada  |
//| uno dividido por la volatilidad diaria y escalado. Rango -20..20:|
//|   > +10 compra fuerte, 0..10 compra chica, < 0 venta.            |
//| Es la misma cuenta que laboratorio/estrategias.py carver_ewmac.  |
//| Usar en grafico DIARIO (D1).                                     |
//+------------------------------------------------------------------+
#property copyright "backtester-mt5/laboratorio"
#property indicator_separate_window
#property indicator_buffers 2
#property indicator_plots   1
#property indicator_minimum -20
#property indicator_maximum 20
#property indicator_level1  10
#property indicator_level2  0
#property indicator_level3  -10
#property indicator_label1 "Pronostico Carver"
#property indicator_type1  DRAW_COLOR_HISTOGRAM
#property indicator_color1 clrSeaGreen, clrCrimson
#property indicator_width1 2

double pron[], color_[];
double rap[4], len[4];
const int    N[4]   = {8, 16, 32, 64};
const double ESC[4] = {5.3, 3.75, 2.65, 1.87};

int OnInit()
  {
   SetIndexBuffer(0, pron, INDICATOR_DATA);
   SetIndexBuffer(1, color_, INDICATOR_COLOR_INDEX);
   IndicatorSetString(INDICATOR_SHORTNAME, "Pronostico Carver (EWMAC 8-256)");
   IndicatorSetInteger(INDICATOR_DIGITS, 1);
   return(INIT_SUCCEEDED);
  }

int OnCalculate(const int total, const int prev, const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[])
  {
   // se recalcula todo cada vez: es barato en diario y evita guardar estado
   double a = 2.0 / 37.0, media = 0, var = 0;
   for(int j = 0; j < 4; j++) { rap[j] = close[0]; len[j] = close[0]; }
   for(int i = 0; i < total; i++)
     {
      if(i > 0)
        {
         double d = close[i] - close[i-1], m0 = media;
         media = m0 + a * (d - m0);
         var   = (1 - a) * (var + a * (d - m0) * (d - m0));
        }
      double vol = MathSqrt(var), suma = 0;
      for(int j = 0; j < 4; j++)
        {
         rap[j] += 2.0 / (N[j] + 1.0)     * (close[i] - rap[j]);
         len[j] += 2.0 / (4 * N[j] + 1.0) * (close[i] - len[j]);
         double f = (vol > 0) ? (rap[j] - len[j]) / vol * ESC[j] : 0;
         suma += MathMax(-20, MathMin(20, f));
        }
      pron[i]   = (i < 300) ? 0 : MathMax(-20, MathMin(20, suma / 4));
      color_[i] = (pron[i] >= 0) ? 0 : 1;
     }
   return(total);
  }
