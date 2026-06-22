//+------------------------------------------------------------------+
//|                          TrailingStop_Milestones.mq5              |
//|   Trailing stop hibrido ATR-based para multi-par / multi-MAGIC    |
//|   Gerencia TODAS as posicoes da conta (qualquer MAGIC).           |
//|   Anexar a UM grafico generico qualquer.                          |
//+------------------------------------------------------------------+
#property copyright "Natan-Souz"
#property version   "1.00"

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>

CTrade        trade;
CPositionInfo posinfo;

//============================ INPUTS ================================
input group "=== Escopo ==="
input bool   InpAllMagics      = true;   // Gerenciar todas as posicoes (qualquer MAGIC)
input long   InpFilterMagic    = 0;      // Se InpAllMagics=false, gerenciar so este MAGIC

input group "=== ATR ==="
input ENUM_TIMEFRAMES InpATRTimeframe = PERIOD_M5; // Timeframe do ATR
input int    InpATRPeriod      = 14;     // Periodo do ATR

input group "=== Trailing ==="
input double InpTrailStartATR  = 1.0;    // Inicia trailing apos lucro >= X*ATR
input double InpTrailDistATR   = 1.0;    // Distancia do SL ao preco em multiplos de ATR
input double InpStepATR        = 0.5;    // Move o SL a cada avanco de X*ATR
input double InpBE_BufferATR   = 0.1;    // Colchao do breakeven em multiplos de ATR

input group "=== Empurrar TP (forca real) ==="
input bool   InpEnablePushTP   = true;   // Habilitar empurrao de TP sob forca
input double InpForceTriggerATR= 1.5;    // Empurra TP quando lucro >= X*ATR
input double InpPushTP_ATR      = 1.0;   // Empurra TP em X*ATR adiante (repetidamente)

input group "=== Execucao / Broker ==="
input double InpMinChangePips  = 0.1;    // So modifica se mudanca de SL/TP > X pips
input int    InpSlippage       = 10;     // Desvio maximo (points)
input bool   InpVerboseLog     = true;   // Logs detalhados no Experts

//==================== ESTADO INTERNO (cache) =======================
// Cacheia o ATR por simbolo, recalculado so no fechamento de candle M5.
struct SymCache
{
   string   symbol;
   double   atr;          // valor ATR atual (em preco)
   datetime last_bar;     // ultimo candle processado
};
SymCache g_cache[];

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetDeviationInPoints(InpSlippage);
   trade.LogLevel(LOG_LEVEL_ERRORS);
   Print("TrailingStop ATR-hibrido iniciado. Escopo: ",
         (InpAllMagics ? "TODAS as posicoes" : "MAGIC="+(string)InpFilterMagic));
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
//| Tick: arrasto roda por tick; ATR/forca so em candle novo         |
//+------------------------------------------------------------------+
void OnTick()
{
   int total = PositionsTotal();
   for(int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!posinfo.SelectByTicket(ticket)) continue;

      // ---- filtro de escopo (MAGIC) ----
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(!InpAllMagics && magic != InpFilterMagic) continue;

      string symbol = PositionGetString(POSITION_SYMBOL);

      // ---- ATR cacheado, recalculado so em candle M5 novo ----
      double atr = GetCachedATR(symbol);
      if(atr <= 0.0) continue; // ATR indisponivel ainda

      ManagePosition(ticket, symbol, atr);
   }
}

//+------------------------------------------------------------------+
//| Retorna ATR cacheado; recalcula no fechamento de candle          |
//+------------------------------------------------------------------+
double GetCachedATR(const string symbol)
{
   // procura no cache
   int idx = -1;
   for(int i = 0; i < ArraySize(g_cache); i++)
      if(g_cache[i].symbol == symbol) { idx = i; break; }

   datetime cur_bar = (datetime)SeriesInfoInteger(symbol, InpATRTimeframe, SERIES_LASTBAR_DATE);

   if(idx == -1)
   {
      // novo simbolo no cache
      int n = ArraySize(g_cache);
      ArrayResize(g_cache, n + 1);
      g_cache[n].symbol   = symbol;
      g_cache[n].atr      = CalcATR(symbol);
      g_cache[n].last_bar = cur_bar;
      return g_cache[n].atr;
   }

   // recalcula so se candle mudou
   if(cur_bar != g_cache[idx].last_bar)
   {
      double v = CalcATR(symbol);
      if(v > 0.0)
      {
         g_cache[idx].atr      = v;
         g_cache[idx].last_bar = cur_bar;
      }
   }
   return g_cache[idx].atr;
}

//+------------------------------------------------------------------+
//| Calcula ATR(period) no timeframe configurado para um simbolo     |
//+------------------------------------------------------------------+
double CalcATR(const string symbol)
{
   int handle = iATR(symbol, InpATRTimeframe, InpATRPeriod);
   if(handle == INVALID_HANDLE) return 0.0;

   double buf[];
   ArraySetAsSeries(buf, true);
   // copia o valor do ultimo candle FECHADO (indice 1)
   int copied = CopyBuffer(handle, 0, 1, 1, buf);
   IndicatorRelease(handle);
   if(copied <= 0) return 0.0;
   return buf[0];
}

//+------------------------------------------------------------------+
//| Logica central por posicao                                       |
//+------------------------------------------------------------------+
void ManagePosition(const ulong ticket, const string symbol, const double atr)
{
   long   type      = PositionGetInteger(POSITION_TYPE);
   double open      = PositionGetDouble(POSITION_PRICE_OPEN);
   double cur_sl    = PositionGetDouble(POSITION_SL);
   double cur_tp    = PositionGetDouble(POSITION_TP);

   double point     = SymbolInfoDouble(symbol, SYMBOL_POINT);
   int    digits    = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

   double bid       = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask       = SymbolInfoDouble(symbol, SYMBOL_ASK);

   // preco "atual" relevante para lucro: para BUY usa BID (saida), SELL usa ASK
   double cur_price = (type == POSITION_TYPE_BUY) ? bid : ask;

   // lucro corrente em PRECO
   double profit_price = (type == POSITION_TYPE_BUY) ? (cur_price - open)
                                                     : (open - cur_price);
   if(profit_price <= 0) return; // so age em lucro

   // distancias derivadas do ATR
   double trail_start = InpTrailStartATR * atr;
   double trail_dist  = InpTrailDistATR  * atr;
   double be_buffer   = InpBE_BufferATR  * atr;

   // ===== 1) so inicia trailing apos lucro >= trail_start =====
   if(profit_price < trail_start) return;

   // ===== 2) calcula SL candidato =====
   // SL base = preco atual - trail_dist (BUY) ; nunca abaixo de breakeven+buffer
   double new_sl;
   if(type == POSITION_TYPE_BUY)
   {
      double trailed = cur_price - trail_dist;
      double be_lock = open + be_buffer;
      new_sl = MathMax(trailed, be_lock);   // garante pelo menos breakeven+colchao
   }
   else
   {
      double trailed = cur_price + trail_dist;
      double be_lock = open - be_buffer;
      new_sl = MathMin(trailed, be_lock);
   }

   // ===== 3) discretiza por step (move so a cada InpStepATR de avanco) =====
   // Arredonda o SL para multiplos de step a partir do open (mantem ordem mais limpa).
   double step = InpStepATR * atr;
   if(step > 0)
   {
      if(type == POSITION_TYPE_BUY)
      {
         double steps = MathFloor((new_sl - open) / step);
         new_sl = open + steps * step;
         if(new_sl < open + be_buffer) new_sl = open + be_buffer; // piso
      }
      else
      {
         double steps = MathFloor((open - new_sl) / step);
         new_sl = open - steps * step;
         if(new_sl > open - be_buffer) new_sl = open - be_buffer; // teto
      }
   }

   new_sl = NormalizeDouble(new_sl, digits);

   // ===== 4) monotonicidade: SL so MELHORA =====
   bool sl_improves = false;
   if(type == POSITION_TYPE_BUY)
      sl_improves = (cur_sl == 0.0) || (new_sl > cur_sl);
   else
      sl_improves = (cur_sl == 0.0) || (new_sl < cur_sl);

   // ===== 5) empurrar TP sob forca (lucro >= InpForceTriggerATR*ATR) =====
   double new_tp = cur_tp;
   bool   tp_changes = false;
   if(InpEnablePushTP && cur_tp != 0.0)
   {
      double force_lvl = InpForceTriggerATR * atr;
      // distancia atual do preco ate o TP
      double dist_to_tp = (type == POSITION_TYPE_BUY) ? (cur_tp - cur_price)
                                                      : (cur_price - cur_tp);
      // se ja temos forca E o preco esta perto/alem do TP, empurra TP +1 ATR
      if(profit_price >= force_lvl && dist_to_tp < step)
      {
         double push = InpPushTP_ATR * atr;
         new_tp = (type == POSITION_TYPE_BUY) ? (cur_tp + push) : (cur_tp - push);
         new_tp = NormalizeDouble(new_tp, digits);
         tp_changes = true;
      }
   }

   // ===== 6) respeitar stops_level / freeze_level do broker =====
   long stops_level  = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double min_dist   = (double)stops_level * point;

   // SL novo precisa estar a pelo menos min_dist do preco corrente
   if(sl_improves)
   {
      if(type == POSITION_TYPE_BUY)
      {
         if((cur_price - new_sl) < min_dist) sl_improves = false;
      }
      else
      {
         if((new_sl - cur_price) < min_dist) sl_improves = false;
      }
   }
   // TP novo idem
   if(tp_changes)
   {
      if(type == POSITION_TYPE_BUY)
      {
         if((new_tp - cur_price) < min_dist) tp_changes = false;
      }
      else
      {
         if((cur_price - new_tp) < min_dist) tp_changes = false;
      }
   }

   // Freeze level: broker bloqueia modificacao quando preco esta proximo
   // do SL/TP existente (zona de congelamento). Checa os valores ATUAIS.
   if(freeze_level > 0)
   {
      double freeze_dist = (double)freeze_level * point;
      if(sl_improves && cur_sl != 0.0)
      {
         bool sl_frozen = (type == POSITION_TYPE_BUY)
                          ? ((cur_price - cur_sl) < freeze_dist)
                          : ((cur_sl - cur_price) < freeze_dist);
         if(sl_frozen) sl_improves = false;
      }
      if(tp_changes && cur_tp != 0.0)
      {
         bool tp_frozen = (type == POSITION_TYPE_BUY)
                          ? ((cur_tp - cur_price) < freeze_dist)
                          : ((cur_price - cur_tp) < freeze_dist);
         if(tp_frozen) tp_changes = false;
      }
   }

   // ===== 7) idempotencia: so modifica se mudanca relevante =====
   double min_change = InpMinChangePips * PipSize(symbol);
   if(sl_improves && MathAbs(new_sl - cur_sl) < min_change) sl_improves = false;
   if(tp_changes  && MathAbs(new_tp - cur_tp) < min_change) tp_changes = false;

   if(!sl_improves && !tp_changes) return;

   double final_sl = sl_improves ? new_sl : cur_sl;
   double final_tp = tp_changes  ? new_tp : cur_tp;

   // ===== 8) envia modificacao =====
   if(trade.PositionModify(ticket, final_sl, final_tp))
   {
      if(InpVerboseLog)
         PrintFormat("[OK] #%I64u %s | SL %.*f->%.*f | TP %.*f->%.*f | ATR=%.*f",
                     ticket, symbol,
                     digits, cur_sl, digits, final_sl,
                     digits, cur_tp, digits, final_tp,
                     digits, atr);
   }
   else
   {
      if(InpVerboseLog)
         PrintFormat("[ERRO] #%I64u %s modify falhou ret=%d %s",
                     ticket, symbol, trade.ResultRetcode(),
                     trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Tamanho de 1 pip em preco (trata pares de 3/5 digitos)           |
//+------------------------------------------------------------------+
double PipSize(const string symbol)
{
   int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
   // 5 ou 3 digitos => 1 pip = 10 points ; 4 ou 2 digitos => 1 pip = 1 point
   if(digits == 5 || digits == 3) return point * 10.0;
   return point;
}
//+------------------------------------------------------------------+