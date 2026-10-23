//+------------------------------------------------------------------+
//| Niveles de los profesionales, en el grafico de precio:           |
//|  - EMA 16 / 64 / 256  (cruces de Carver)                         |
//|  - Canal de 55 dias   (entrada de las Tortugas)                  |
//|  - Canal de 20 dias   (salida de las Tortugas)                   |
//| Usar en grafico DIARIO (D1).                                     |
//+------------------------------------------------------------------+
#property copyright "backtester-mt5/laboratorio"
#property indicator_chart_window
#property indicator_buffers 7
#property indicator_plots   7

#property indicator_label1 "EMA 16"
#property indicator_type1  DRAW_LINE
#property indicator_color1 clrDodgerBlue
#property indicator_width1 1
#property indicator_label2 "EMA 64"
#property indicator_type2  DRAW_LINE
#property indicator_color2 clrOrange
#property indicator_width2 2
#property indicator_label3 "EMA 256"
#property indicator_type3  DRAW_LINE
#property indicator_color3 clrCrimson
#property indicator_width3 2
#property indicator_label4 "Maximo 55"
#property indicator_type4  DRAW_LINE
#property indicator_color4 clrSeaGreen
#property indicator_style4 STYLE_DASH
#property indicator_label5 "Minimo 55"
#property indicator_type5  DRAW_LINE
#property indicator_color5 clrSeaGreen
#property indicator_style5 STYLE_DASH
#property indicator_label6 "Maximo 20"
#property indicator_type6  DRAW_LINE
#property indicator_color6 clrSilver
#property indicator_style6 STYLE_DOT
#property indicator_label7 "Minimo 20"
#property indicator_type7  DRAW_LINE
#property indicator_color7 clrSilver
#property indicator_style7 STYLE_DOT

input int Entrada = 55;   // canal de entrada (dias)
input int Salida  = 20;   // canal de salida (dias)

double e16[], e64[], e256[], h55[], l55[], h20[], l20[];

int OnInit()
  {
   SetIndexBuffer(0, e16);  SetIndexBuffer(1, e64);  SetIndexBuffer(2, e256);
   SetIndexBuffer(3, h55);  SetIndexBuffer(4, l55);  SetIndexBuffer(5, h20);  SetIndexBuffer(6, l20);
   for(int p = 0; p < 7; p++) PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetString(INDICATOR_SHORTNAME, "Profesionales: EMA 16/64/256 + canal 55/20");
   return(INIT_SUCCEEDED);
  }

double Extremo(const double &x[], int fin, int n, bool maximo)
  {
   double v = x[fin];
   for(int k = fin - n + 1; k <= fin; k++) v = maximo ? MathMax(v, x[k]) : MathMin(v, x[k]);
   return v;
  }

int OnCalculate(const int total, const int prev, const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[])
  {
   int inicio = (prev > 0) ? prev - 1 : 0;
   for(int i = inicio; i < total; i++)
     {
      if(i == 0) { e16[i] = e64[i] = e256[i] = close[i]; }
      else
        {
         e16[i]  = e16[i-1]  + 2.0 / 17.0  * (close[i] - e16[i-1]);
         e64[i]  = e64[i-1]  + 2.0 / 65.0  * (close[i] - e64[i-1]);
         e256[i] = e256[i-1] + 2.0 / 257.0 * (close[i] - e256[i-1]);
        }
      // canales con los dias ANTERIORES: si el cierre los cruza, hay ruptura
      h55[i] = (i > Entrada) ? Extremo(high, i - 1, Entrada, true)  : EMPTY_VALUE;
      l55[i] = (i > Entrada) ? Extremo(low,  i - 1, Entrada, false) : EMPTY_VALUE;
      h20[i] = (i > Salida)  ? Extremo(high, i - 1, Salida,  true)  : EMPTY_VALUE;
      l20[i] = (i > Salida)  ? Extremo(low,  i - 1, Salida,  false) : EMPTY_VALUE;
     }
   return(total);
  }
