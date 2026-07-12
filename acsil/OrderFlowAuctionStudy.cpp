// ============================================================================
//  OrderFlowAuctionStudy.cpp
//
//  Sierra Chart custom study (ACSIL). Ground-up rebuild.
//
//  STRUCTURAL LAYER (Phase 1): Prior-day POC/VAH/VAL (true volume-at-price,
//  projected onto the next trading day), Initial Balance, Weekly VPOC +
//  prior-week high/low, no-man's-land distance readout (D-004).
//
//  ORDER-FLOW SIGNAL LAYER (Phase 2/3, added 2026-07-12): the UNGATED
//  FOLLOW/FADE event engine only -- delta/CVD divergence, absorption,
//  exhaustion, trade-and-rest acceptance -- mirroring signals/engine.py +
//  features/{delta,absorption,exhaustion,acceptance}.py exactly. This is
//  the "trustworthy core" validated in Python with costs across three
//  regime periods (docs/phase2_interim_report.md, 2026-07-12): +0.130R/
//  trade combined (n=256), FADE positive in all six period x bar-basis
//  cells. Per CLAUDE.md dev rule #2, ONLY this validated slice is ported.
//
//  EXPLICITLY NOT PORTED (do not add without a decisions.md entry):
//    - D-013 regime gates (open-drive/gap-holds/narrow-IB) and the live
//      conflict veto (fusion/decision.py) -- measured in-sample only
//      (+0.35-0.51R) and FAILED weak-OOS on unseen thin-contract periods
//      (D-013 re-test note, docs/decisions.md): fusion was NEGATIVE
//      (-0.057R) vs the ungated baseline (+0.017R) on data the rules never
//      saw. Do not gate/veto signals in this file until a LIQUID unseen
//      period (forward data) supports it.
//    - MOMO pullback/retest engine (signals/momentum.py) -- lost to FOLLOW
//      head-to-head combined (-0.074R vs +0.115R); regime-complementary but
//      no working regime gate to select between them.
//    - REV, day-type scoring, IVB, and all other legacy signal logic.
//
//  Includes a pipe-delimited signal+decision logger (ACSIL gotcha, CLAUDE.md
//  6.8) so live-fired signals can be reconciled against the Python backtest
//  (Phase 7) and accumulate genuine forward out-of-sample data -- the
//  single most important open question left (every D-013/MOMO verdict above
//  is in-sample or weak-OOS; only forward tracking settles it for real).
//
//  WINDOW CORRECTION (D-011, docs/decisions.md): the legacy study and its
//  accompanying notes describe the prior-day value area as RTH-only
//  (09:30-16:00 ET). Real-data reconciliation against a live chart reading
//  FALSIFIED that -- the value area that actually reproduces what Sierra
//  displays is the FULL 18:00-ET-anchored session (prior day's 18:00 reopen
//  through the current day's RTH close: Asia+UK+US). This study accumulates
//  volume-at-price across the FULL trading day, not just RTH bars. RTH
//  bars are still tracked separately for Initial Balance and RTH open/high/
//  low/close (gap calc), since IB is inherently an RTH concept.
//
//  Mirrors structure/levels.py + structure/value_area.py + structure/
//  sessions.py from the Python research track. If the two diverge, the
//  Python side (backtested, unit-tested) is authoritative -- fix this file
//  to match it, not the other way around.
//
//  TIMEZONE: session/day-boundary inputs are in YOUR CHART'S timezone.
//  Chart must be set to US Eastern for the defaults (09:30/16:00/18:00) to
//  be correct -- see the timezone-bleed warning in
//  docs/phase1_foundation_engine.md.
//
//  BUILD: place in "ACS_Source", Analysis >> Build Custom Studies DLL, add
//  "Order-Flow Auction Study - Structure (Phase 1)".
// ============================================================================

#include "sierrachart.h"
#include <map>
#include <vector>
#include <cmath>
#include <cstdio>
#include <cstring>

SCDLLName("OrderFlowAuctionStudy")

// ---------------------------------------------------------------------------
// Data structures
// ---------------------------------------------------------------------------

struct DayProfile
{
    int DayKey;                          // 18:00-ET-anchored trading day (YYMMDD-ish)
    SCDateTime FullStart, FullEnd;        // full 18:00 -> next 18:00 window actually observed
    float POC, VAH, VAL;                  // from FULL-session volume-at-price (D-011)
    bool Valid;
    float FullHigh, FullLow;              // full-session high/low (context/ATR)

    bool RTHValid;
    int RTHStartIdx, RTHEndIdx;
    float RTHOpen, RTHHigh, RTHLow, RTHClose;

    DayProfile() : DayKey(0), POC(0), VAH(0), VAL(0), Valid(false),
        FullHigh(0), FullLow(0), RTHValid(false), RTHStartIdx(-1), RTHEndIdx(-1),
        RTHOpen(0), RTHHigh(0), RTHLow(0), RTHClose(0) {}
};

struct WeekProfile
{
    int WeekKey;
    SCDateTime StartDT, EndDT;
    float High, Low, VPOC;
    bool Valid;
    WeekProfile() : WeekKey(0), High(0), Low(0), VPOC(0), Valid(false) {}
};

// ---------------------------------------------------------------------------
// Pure helpers (mirror structure/value_area.py and structure/sessions.py)
// ---------------------------------------------------------------------------

// Same true-VAP algorithm as the legacy study's ComputeProfile, unchanged --
// this part was never in question; matches tests/test_value_area.py exactly
// (POC ties favor the lower price; expansion ties favor the upper neighbor).
static void ComputeValueArea(const std::map<int, double>& vap, float tickSize,
                             float vaFraction, float& poc, float& vah, float& val, bool& valid)
{
    valid = false;
    if (vap.empty() || tickSize <= 0.0f) return;
    double total = 0.0; int pocTks = vap.begin()->first; double pocVol = -1.0;
    for (std::map<int, double>::const_iterator it = vap.begin(); it != vap.end(); ++it)
    { total += it->second; if (it->second > pocVol) { pocVol = it->second; pocTks = it->first; } }
    if (total <= 0.0) return;
    std::vector<std::pair<int, double> > rows(vap.begin(), vap.end());
    int pocIdx = 0; for (size_t k = 0; k < rows.size(); ++k) if (rows[k].first == pocTks) { pocIdx = (int)k; break; }
    double target = total * vaFraction; double acc = rows[pocIdx].second; int up = pocIdx, dn = pocIdx;
    while (acc < target && (up < (int)rows.size() - 1 || dn > 0))
    {
        bool canUp = up < (int)rows.size() - 1, canDn = dn > 0;
        double upVol = canUp ? rows[up + 1].second : -1.0, dnVol = canDn ? rows[dn - 1].second : -1.0;
        if (canUp && (!canDn || upVol >= dnVol)) acc += rows[++up].second; else if (canDn) acc += rows[--dn].second; else break;
    }
    poc = pocTks * tickSize; vah = rows[up].first * tickSize; val = rows[dn].first * tickSize; valid = true;
}

static float VPOCfromMap(const std::map<int, double>& vap, float tickSize)
{
    if (vap.empty()) return 0.0f; int tks = vap.begin()->first; double v = -1.0;
    for (std::map<int, double>::const_iterator it = vap.begin(); it != vap.end(); ++it)
        if (it->second > v) { v = it->second; tks = it->first; }
    return tks * tickSize;
}

// Mirrors structure/sessions.py::trading_day() -- 18:00 ET boundary, next-day
// roll. D-011 depends on this being right: the daily bucket key must match
// this boundary, not a plain calendar date.
static int TradingDayKey(const SCDateTime& bdt, int dayBoundarySec)
{
    SCDateTime d = bdt.GetDate();
    if (bdt.GetTimeInSeconds() >= dayBoundarySec) d = d + SCDateTime::DAYS(1);
    return (d.GetYear() - 2000) * 10000 + d.GetMonth() * 100 + d.GetDay();
}

// ---------------------------------------------------------------------------
// Order-flow feature helpers (Phase 2/3, mirror features/*.py exactly --
// see file header. All operate on 0-indexed vectors of TODAY's RTH bars
// only; index k in these vectors corresponds to bar sc index rthStart+k.)
// ---------------------------------------------------------------------------

// Mirrors features/_stats.py::rolling_zscore -- z-score of v[idx] against
// the trailing `lookback` values strictly BEFORE idx. 0.0 on insufficient
// history or zero variance (never a false positive; callers gate on a
// minimum).
static float RollingZ(const std::vector<float>& v, int idx, int lookback)
{
    int start = idx - lookback;
    if (start < 0 || lookback < 2) return 0.0f;
    double sum = 0.0;
    for (int k = start; k < idx; ++k) sum += v[k];
    double mean = sum / lookback;
    double sq = 0.0;
    for (int k = start; k < idx; ++k) { double d = v[k] - mean; sq += d * d; }
    double sd = sqrt(sq / lookback);
    if (sd <= 0.0) return 0.0f;
    return (float)((v[idx] - mean) / sd);
}

// Mirrors features/delta.py::detect_divergence for a single bar k: price
// makes a new `lookback`-bar extreme while CVD does not confirm.
static void DivergenceAt(const std::vector<float>& hi, const std::vector<float>& lo,
                         const std::vector<float>& cvd, int k, int lookback,
                         bool& bearish, bool& bullish)
{
    bearish = false; bullish = false;
    if (k < lookback) return;
    float wHi = -1e30f, wLo = 1e30f, wCvdHi = -1e30f, wCvdLo = 1e30f;
    for (int j = k - lookback; j < k; ++j)
    {
        if (hi[j] > wHi) wHi = hi[j];
        if (lo[j] < wLo) wLo = lo[j];
        if (cvd[j] > wCvdHi) wCvdHi = cvd[j];
        if (cvd[j] < wCvdLo) wCvdLo = cvd[j];
    }
    if (hi[k] > wHi && cvd[k] <= wCvdHi) bearish = true;
    if (lo[k] < wLo && cvd[k] >= wCvdLo) bullish = true;
}

// Mirrors features/absorption.py::detect_absorption for a single bar k.
// Returns -1 (bearish: heavy buying absorbed), +1 (bullish: heavy selling
// absorbed), or 0 (none).
static int AbsorptionAt(const std::vector<float>& absDelta, const std::vector<float>& deltaSigned,
                        const std::vector<float>& hi, const std::vector<float>& lo,
                        int k, int lookback, float volZ, float stallTicks, float tickSize)
{
    float z = RollingZ(absDelta, k, lookback);
    if (z < volZ) return 0;
    if ((hi[k] - lo[k]) > stallTicks * tickSize) return 0;
    return deltaSigned[k] < 0 ? 1 : -1;
}

// Mirrors features/exhaustion.py::detect_exhaustion, evaluated per
// confirm-bar k (climax is bar k-1, confirm_bars=1 fixed here to match the
// validated default). Returns -1/+1/0.
static int ExhaustionConfirmedAt(const std::vector<float>& absDelta, const std::vector<float>& hi,
                                 const std::vector<float>& lo, int k, int lookback, float climaxZ)
{
    int c = k - 1;
    if (c < lookback) return 0;
    float z = RollingZ(absDelta, c, lookback);
    if (z < climaxZ) return 0;
    float wHi = -1e30f, wLo = 1e30f;
    for (int j = c - lookback; j < c; ++j) { if (hi[j] > wHi) wHi = hi[j]; if (lo[j] < wLo) wLo = lo[j]; }
    bool isUpClimax = hi[c] > wHi, isDnClimax = lo[c] < wLo;
    if (isUpClimax && hi[k] <= hi[c]) return -1;
    if (isDnClimax && lo[k] >= lo[c]) return 1;
    return 0;
}

// Append a SIGNAL line to the log file (ACSIL gotcha, CLAUDE.md 6.8) --
// pipe-delimited so Python can reconcile live-fired signals against the
// backtest (Phase 7 replay-log cross-check).
static void LogSig(const char* fn, const SCDateTime& dt, const char* msg)
{
    if (!fn || strlen(fn) < 2) return;
    FILE* f = fopen(fn, "a");
    if (f) { fprintf(f, "SIGNAL | %04d-%02d-%02d %02d:%02d:%02d | %s\n",
             dt.GetYear(), dt.GetMonth(), dt.GetDay(), dt.GetHour(), dt.GetMinute(), dt.GetSecond(), msg);
             fclose(f); }
}

// ---------------------------------------------------------------------------
// Study
// ---------------------------------------------------------------------------

SCSFExport scsf_OrderFlowAuctionStudy(SCStudyInterfaceRef sc)
{
    SCInputRef In_SessionStart = sc.Input[0], In_SessionEnd = sc.Input[1],
        In_DayBoundary = sc.Input[2], In_ValueAreaPct = sc.Input[3],
        In_IBMinutes = sc.Input[4], In_DaysToDraw = sc.Input[5],
        In_WeeksToDraw = sc.Input[6], In_ATRPeriod = sc.Input[7],
        In_NoMansLandATR = sc.Input[8], In_ShowHUD = sc.Input[9],
        In_HUDVert = sc.Input[10], In_HUDHoriz = sc.Input[11],
        In_HUDFontSize = sc.Input[12], In_HUDColor = sc.Input[13],
        In_VAHColor = sc.Input[14], In_VALColor = sc.Input[15], In_POCColor = sc.Input[16],
        In_IBColor = sc.Input[17], In_PWHLColor = sc.Input[18], In_WVPOCColor = sc.Input[19],
        In_LineWidth = sc.Input[20], In_ShowLabels = sc.Input[21],
        In_ShowSignals = sc.Input[22], In_FeatureLookback = sc.Input[23],
        In_DeltaDivLookback = sc.Input[24], In_AbsorptionVolZ = sc.Input[25],
        In_AbsorptionStallTicks = sc.Input[26], In_ExhaustionClimaxZ = sc.Input[27],
        In_AcceptMinVolZ = sc.Input[28], In_LongSignalColor = sc.Input[29],
        In_ShortSignalColor = sc.Input[30], In_LogEnable = sc.Input[31],
        In_LogFile = sc.Input[32];
    SCSubgraphRef Sub_HUD = sc.Subgraph[0];

    if (sc.SetDefaults)
    {
        sc.GraphName = "Order-Flow Auction Study - Structure (Phase 1)";
        sc.StudyDescription = "Ground-up rebuild, structural layer only (no signals yet -- "
            "see CLAUDE.md dev rule #2). Full-session (18:00 ET anchored) prior-day value "
            "area per D-011, Initial Balance, weekly VPOC/PWH/PWL, no-man's-land readout.";
        sc.AutoLoop = 0; sc.GraphRegion = 0; sc.MaintainVolumeAtPriceData = 1;
        sc.DrawZeros = 0; sc.ValueFormat = VALUEFORMAT_INHERITED;

        In_SessionStart.Name = "RTH Session Start (chart time)"; In_SessionStart.SetTime(HMS_TIME(9, 30, 0));
        In_SessionEnd.Name = "RTH Session End (chart time)"; In_SessionEnd.SetTime(HMS_TIME(16, 0, 0));
        In_DayBoundary.Name = "Trading-Day Boundary (D-011 full-session anchor)"; In_DayBoundary.SetTime(HMS_TIME(18, 0, 0));
        In_ValueAreaPct.Name = "Value Area Percentage"; In_ValueAreaPct.SetFloat(70.0f); In_ValueAreaPct.SetFloatLimits(1.0f, 100.0f);
        In_IBMinutes.Name = "Initial Balance Duration (minutes)"; In_IBMinutes.SetInt(60); In_IBMinutes.SetIntLimits(5, 390);
        In_DaysToDraw.Name = "Number of Days to Draw"; In_DaysToDraw.SetInt(60); In_DaysToDraw.SetIntLimits(1, 250);
        In_WeeksToDraw.Name = "Number of Weeks to Draw"; In_WeeksToDraw.SetInt(4); In_WeeksToDraw.SetIntLimits(1, 52);
        In_ATRPeriod.Name = "ATR Period (days)"; In_ATRPeriod.SetInt(14); In_ATRPeriod.SetIntLimits(2, 50);
        In_NoMansLandATR.Name = "No-Man's-Land Max Distance (x ATR, D-004)"; In_NoMansLandATR.SetFloat(0.5f); In_NoMansLandATR.SetFloatLimits(0.1f, 3.0f);
        In_ShowHUD.Name = "Show Structural HUD"; In_ShowHUD.SetYesNo(1);
        In_HUDVert.Name = "HUD Vertical Position (0-150)"; In_HUDVert.SetInt(92); In_HUDVert.SetIntLimits(0, 150);
        In_HUDHoriz.Name = "HUD Horizontal Position (0-150)"; In_HUDHoriz.SetInt(2); In_HUDHoriz.SetIntLimits(0, 150);
        In_HUDFontSize.Name = "HUD Font Size"; In_HUDFontSize.SetInt(13); In_HUDFontSize.SetIntLimits(6, 40);
        In_HUDColor.Name = "HUD Text Color"; In_HUDColor.SetColor(235, 235, 235);
        In_VAHColor.Name = "VAH Line Color"; In_VAHColor.SetColor(0, 170, 0);
        In_VALColor.Name = "VAL Line Color"; In_VALColor.SetColor(210, 0, 0);
        In_POCColor.Name = "POC Line Color"; In_POCColor.SetColor(255, 0, 255);
        In_IBColor.Name = "Initial Balance Color"; In_IBColor.SetColor(120, 120, 200);
        In_PWHLColor.Name = "Prior-Week High/Low Color"; In_PWHLColor.SetColor(200, 140, 0);
        In_WVPOCColor.Name = "Weekly VPOC Color"; In_WVPOCColor.SetColor(180, 120, 220);
        In_LineWidth.Name = "Line Width"; In_LineWidth.SetInt(2); In_LineWidth.SetIntLimits(1, 10);
        In_ShowLabels.Name = "Show Labels / Price"; In_ShowLabels.SetYesNo(1);

        // NOTE: the validated "+0.130R/trade" numbers (docs/phase2_interim_report.md)
        // came from a 1-MINUTE chart. Run this study on a 1-min chart for fidelity to
        // that backtest. An 800-trade/tick basis was tested (2026-07-12) as extra FADE
        // evidence and measured SLIGHTLY NEGATIVE vs the minute-bar baseline -- if you
        // run this on your preferred tick chart anyway, treat its signals as unvalidated
        // until a matching Python backtest is run on that same bar basis.
        In_ShowSignals.Name = "Show FOLLOW/FADE Signals (Phase 2/3, ungated)"; In_ShowSignals.SetYesNo(1);
        In_FeatureLookback.Name = "Order-Flow Feature Lookback (bars)"; In_FeatureLookback.SetInt(20); In_FeatureLookback.SetIntLimits(5, 60);
        In_DeltaDivLookback.Name = "Delta/CVD Divergence Lookback (bars)"; In_DeltaDivLookback.SetInt(5); In_DeltaDivLookback.SetIntLimits(3, 12);
        In_AbsorptionVolZ.Name = "Absorption Volume Z-Score"; In_AbsorptionVolZ.SetFloat(2.0f); In_AbsorptionVolZ.SetFloatLimits(1.5f, 3.5f);
        In_AbsorptionStallTicks.Name = "Absorption Price Stall (ticks)"; In_AbsorptionStallTicks.SetFloat(3.0f); In_AbsorptionStallTicks.SetFloatLimits(1.0f, 48.0f);
        In_ExhaustionClimaxZ.Name = "Exhaustion Climax Z-Score"; In_ExhaustionClimaxZ.SetFloat(2.5f); In_ExhaustionClimaxZ.SetFloatLimits(1.5f, 4.0f);
        In_AcceptMinVolZ.Name = "Acceptance Min Volume Z-Score"; In_AcceptMinVolZ.SetFloat(1.5f); In_AcceptMinVolZ.SetFloatLimits(0.5f, 3.0f);
        In_LongSignalColor.Name = "FOLLOW/FADE Long Marker Color"; In_LongSignalColor.SetColor(0, 220, 0);
        In_ShortSignalColor.Name = "FOLLOW/FADE Short Marker Color"; In_ShortSignalColor.SetColor(220, 0, 0);
        In_LogEnable.Name = "LOG: write signals to text file"; In_LogEnable.SetYesNo(0);
        In_LogFile.Name = "LOG: file name (in Data folder)"; In_LogFile.SetString("OrderFlowSignals_log.txt");

        Sub_HUD.Name = "Structural HUD"; Sub_HUD.DrawStyle = DRAWSTYLE_IGNORE;
        Sub_HUD.PrimaryColor = RGB(235, 235, 235); Sub_HUD.LineWidth = 13;
        return;
    }

    int& lastSize = sc.GetPersistentInt(1);
    bool newBar = (sc.ArraySize != lastSize);
    if (!sc.IsFullRecalculation && !newBar) return;
    lastSize = sc.ArraySize;
    if (sc.VolumeAtPriceForBars == NULL || sc.ArraySize == 0 || sc.TickSize <= 0.0f) return;

    const int sessStartSec = In_SessionStart.GetTime(), sessEndSec = In_SessionEnd.GetTime();
    const int dayBoundarySec = In_DayBoundary.GetTime();
    const float vaFraction = In_ValueAreaPct.GetFloat() / 100.0f;
    double barMin = (double)sc.SecondsPerBar / 60.0;
    int ibBars = (barMin > 0.0) ? (int)((In_IBMinutes.GetInt() / barMin) + 0.5) : 2;
    if (ibBars < 1) ibBars = 1;

    // ---- Pass 1: build daily (18:00-anchored, FULL session) + weekly (RTH,
    // Monday-anchored -- unchanged from legacy; D-011 has not been tested
    // against weekly VPOC yet, so it stays RTH-only until it is) profiles.
    std::vector<DayProfile> days;
    std::vector<WeekProfile> weeks;
    std::map<int, double> vap, wvap;
    int curDayKey = -1; DayProfile cur;
    int curWeekKey = -1; float wHigh = 0, wLow = 0; SCDateTime wStart(0.0), wEnd(0.0);

    for (int i = 0; i < sc.ArraySize; ++i)
    {
        const SCDateTime bdt = sc.BaseDateTimeIn[i];
        const int secs = bdt.GetTimeInSeconds();
        const bool inRTH = (secs >= sessStartSec && secs < sessEndSec);

        // ---- daily bucket (D-011: FULL session, every bar counts) ----
        const int dayKey = TradingDayKey(bdt, dayBoundarySec);
        if (dayKey != curDayKey)
        {
            if (curDayKey != -1 && !vap.empty())
            {
                ComputeValueArea(vap, sc.TickSize, vaFraction, cur.POC, cur.VAH, cur.VAL, cur.Valid);
                if (cur.Valid) { cur.DayKey = curDayKey; days.push_back(cur); }
            }
            vap.clear(); cur = DayProfile(); curDayKey = dayKey;
            cur.FullStart = bdt; cur.FullHigh = sc.High[i]; cur.FullLow = sc.Low[i];
        }
        cur.FullEnd = bdt;
        if (sc.High[i] > cur.FullHigh) cur.FullHigh = sc.High[i];
        if (sc.Low[i] < cur.FullLow) cur.FullLow = sc.Low[i];

        if (inRTH)
        {
            if (!cur.RTHValid) { cur.RTHStartIdx = i; cur.RTHOpen = sc.Open[i]; cur.RTHHigh = sc.High[i]; cur.RTHLow = sc.Low[i]; cur.RTHValid = true; }
            cur.RTHEndIdx = i; cur.RTHClose = sc.Close[i];
            if (sc.High[i] > cur.RTHHigh) cur.RTHHigh = sc.High[i];
            if (sc.Low[i] < cur.RTHLow) cur.RTHLow = sc.Low[i];
        }

        const int n = (int)sc.VolumeAtPriceForBars->GetSizeAtBarIndex(i);
        for (int jj = 0; jj < n; ++jj)
        {
            s_VolumeAtPriceV2* p = NULL; sc.VolumeAtPriceForBars->GetVAPElementAtIndex(i, jj, &p);
            if (p != NULL) vap[p->PriceInTicks] += (double)p->Volume;
        }

        // ---- weekly bucket (RTH-only, Monday-anchored, unchanged) ----
        if (inRTH)
        {
            int dow = bdt.GetDayOfWeek(); int back = (dow + 6) % 7;
            SCDateTime monday = bdt.GetDate() - SCDateTime::DAYS(back);
            int wkey = (monday.GetYear() - 2000) * 10000 + monday.GetMonth() * 100 + monday.GetDay();
            if (wkey != curWeekKey)
            {
                if (curWeekKey != -1 && !wvap.empty())
                {
                    WeekProfile wp; wp.WeekKey = curWeekKey; wp.StartDT = wStart; wp.EndDT = wEnd;
                    wp.High = wHigh; wp.Low = wLow; wp.VPOC = VPOCfromMap(wvap, sc.TickSize); wp.Valid = true;
                    weeks.push_back(wp);
                }
                wvap.clear(); curWeekKey = wkey; wStart = bdt; wHigh = sc.High[i]; wLow = sc.Low[i];
            }
            wEnd = bdt;
            if (sc.High[i] > wHigh) wHigh = sc.High[i];
            if (sc.Low[i] < wLow) wLow = sc.Low[i];
            for (int jj = 0; jj < n; ++jj)
            {
                s_VolumeAtPriceV2* p = NULL; sc.VolumeAtPriceForBars->GetVAPElementAtIndex(i, jj, &p);
                if (p != NULL) wvap[p->PriceInTicks] += (double)p->Volume;
            }
        }
    }
    if (curDayKey != -1 && !vap.empty())
    {
        ComputeValueArea(vap, sc.TickSize, vaFraction, cur.POC, cur.VAH, cur.VAL, cur.Valid);
        if (cur.Valid) { cur.DayKey = curDayKey; days.push_back(cur); }
    }
    if (curWeekKey != -1 && !wvap.empty())
    {
        WeekProfile wp; wp.WeekKey = curWeekKey; wp.StartDT = wStart; wp.EndDT = wEnd;
        wp.High = wHigh; wp.Low = wLow; wp.VPOC = VPOCfromMap(wvap, sc.TickSize); wp.Valid = true;
        weeks.push_back(wp);
    }

    sc.DeleteACSChartDrawing(sc.ChartNumber, TOOL_DELETE_ALL, 0);
    const int total = (int)days.size();
    if (total == 0) return;

    // Daily ATR (simple mean True Range, matches structure/levels.py::daily_atr
    // -- a plain running average, not Wilder-smoothed) from FULL-session H/L/C.
    float atrDaily = 0.0f;
    {
        int L = In_ATRPeriod.GetInt(); double ts = 0; int tn = 0;
        for (int k = (total - 1 - L > 1 ? total - 1 - L : 1); k <= total - 1 && k >= 1; ++k)
        {
            const DayProfile& sk = days[k]; const DayProfile& pk = days[k - 1];
            float pkClose = pk.RTHValid ? pk.RTHClose : (pk.FullHigh + pk.FullLow) / 2.0f;
            float tr = sk.FullHigh - sk.FullLow;
            float d2 = sk.FullHigh - pkClose; if (d2 < 0) d2 = -d2; if (d2 > tr) tr = d2;
            float d3 = sk.FullLow - pkClose; if (d3 < 0) d3 = -d3; if (d3 > tr) tr = d3;
            ts += tr; tn++;
        }
        if (tn > 0) atrDaily = (float)(ts / tn);
    }

    const int daysToDraw = In_DaysToDraw.GetInt();
    int firstDraw = total - daysToDraw; if (firstDraw < 0) firstDraw = 0;
    const int lineWidth = In_LineWidth.GetInt();
    const bool showLabels = In_ShowLabels.GetYesNo() != 0;

    // Most recent day still developing? Its VA recomputes every bar, so it
    // must not be drawn as a frozen "PD" reference (line-drift bug class).
    bool lastInProgress = false;
    {
        const SCDateTime lb = sc.BaseDateTimeIn[sc.ArraySize - 1];
        if (TradingDayKey(lb, dayBoundarySec) == days[total - 1].DayKey &&
            lb.GetTimeInSeconds() < sessEndSec && lb.GetTimeInSeconds() >= sessStartSec)
            lastInProgress = true;
    }
    const int curPDidx = lastInProgress ? total - 2 : total - 1;
    const SCDateTime farRight = sc.BaseDateTimeIn[sc.ArraySize - 1] + SCDateTime::DAYS(1);

    // ---- Pass 2: project prior day's value area onto the next day --------
    for (int i = firstDraw; i < total; ++i)
    {
        if (i == total - 1 && lastInProgress) continue;
        const DayProfile& d = days[i];
        SCDateTime beginDT = d.FullEnd;
        SCDateTime endDT = (i >= curPDidx) ? farRight : (i + 1 < total ? days[i + 1].FullEnd : d.FullEnd + SCDateTime::DAYS(1));
        const int ln = 100000 + d.DayKey * 10; s_UseTool t;
        t.Clear(); t.ChartNumber = sc.ChartNumber; t.DrawingType = DRAWING_LINE; t.LineNumber = ln + 1;
        t.BeginDateTime = beginDT; t.EndDateTime = endDT; t.BeginValue = d.VAH; t.EndValue = d.VAH;
        t.Color = In_VAHColor.GetColor(); t.LineWidth = lineWidth; t.AddMethod = UTAM_ADD_OR_ADJUST;
        t.ShowPrice = showLabels ? 1 : 0; if (showLabels) t.Text = "PD VAH"; sc.UseTool(t);
        t.Clear(); t.ChartNumber = sc.ChartNumber; t.DrawingType = DRAWING_LINE; t.LineNumber = ln + 2;
        t.BeginDateTime = beginDT; t.EndDateTime = endDT; t.BeginValue = d.VAL; t.EndValue = d.VAL;
        t.Color = In_VALColor.GetColor(); t.LineWidth = lineWidth; t.AddMethod = UTAM_ADD_OR_ADJUST;
        t.ShowPrice = showLabels ? 1 : 0; if (showLabels) t.Text = "PD VAL"; sc.UseTool(t);
        t.Clear(); t.ChartNumber = sc.ChartNumber; t.DrawingType = DRAWING_LINE; t.LineNumber = ln + 3;
        t.BeginDateTime = beginDT; t.EndDateTime = endDT; t.BeginValue = d.POC; t.EndValue = d.POC;
        t.Color = In_POCColor.GetColor(); t.LineWidth = lineWidth; t.AddMethod = UTAM_ADD_OR_ADJUST;
        t.ShowPrice = 0; if (showLabels) t.Text = "PD POC"; sc.UseTool(t);

        if (d.RTHValid)
        {
            const int iln = 400000 + d.DayKey * 10;
            SCDateTime ibBegin = sc.BaseDateTimeIn[d.RTHStartIdx];
            int ibLast = d.RTHStartIdx + ibBars - 1;
            if (ibLast <= d.RTHEndIdx)
            {
                float ibHigh = sc.High[d.RTHStartIdx], ibLow = sc.Low[d.RTHStartIdx];
                bool allClosed = true;
                for (int b = d.RTHStartIdx; b <= ibLast; ++b)
                {
                    if (sc.GetBarHasClosedStatus(b) != BHCS_BAR_HAS_CLOSED) { allClosed = false; break; }
                    if (sc.High[b] > ibHigh) ibHigh = sc.High[b];
                    if (sc.Low[b] < ibLow) ibLow = sc.Low[b];
                }
                if (allClosed)
                {
                    SCDateTime ibEnd = (i + 1 < total) ? d.FullEnd : d.FullEnd + SCDateTime::HOURS(2);
                    s_UseTool ib;
                    ib.Clear(); ib.ChartNumber = sc.ChartNumber; ib.DrawingType = DRAWING_LINE; ib.LineNumber = iln + 1;
                    ib.BeginDateTime = ibBegin; ib.EndDateTime = ibEnd; ib.BeginValue = ibHigh; ib.EndValue = ibHigh;
                    ib.Color = In_IBColor.GetColor(); ib.LineWidth = 1; ib.LineStyle = LINESTYLE_DASH;
                    ib.AddMethod = UTAM_ADD_OR_ADJUST; ib.ShowPrice = showLabels ? 1 : 0; if (showLabels) ib.Text = "IB High"; sc.UseTool(ib);
                    ib.Clear(); ib.ChartNumber = sc.ChartNumber; ib.DrawingType = DRAWING_LINE; ib.LineNumber = iln + 2;
                    ib.BeginDateTime = ibBegin; ib.EndDateTime = ibEnd; ib.BeginValue = ibLow; ib.EndValue = ibLow;
                    ib.Color = In_IBColor.GetColor(); ib.LineWidth = 1; ib.LineStyle = LINESTYLE_DASH;
                    ib.AddMethod = UTAM_ADD_OR_ADJUST; ib.ShowPrice = showLabels ? 1 : 0; if (showLabels) ib.Text = "IB Low"; sc.UseTool(ib);
                }
            }
        }
    }

    // ---- Pass 2b: weekly levels (prior week projected onto current week) -
    const int numWk = (int)weeks.size();
    bool weeklyValid = numWk >= 2 && weeks[numWk - 2].Valid;
    float PWH = 0, PWL = 0, WVPOC = 0;
    if (weeklyValid) { PWH = weeks[numWk - 2].High; PWL = weeks[numWk - 2].Low; WVPOC = weeks[numWk - 2].VPOC; }
    if (numWk >= 2)
    {
        int weeksToDraw = In_WeeksToDraw.GetInt();
        int firstWk = numWk - weeksToDraw; if (firstWk < 1) firstWk = 1;
        for (int w = firstWk; w < numWk; ++w)
        {
            const WeekProfile& pw = weeks[w - 1];
            SCDateTime b = weeks[w].StartDT, e = (w + 1 < numWk) ? weeks[w + 1].StartDT : weeks[w].EndDT + SCDateTime::DAYS(3);
            const int wln = 500000 + pw.WeekKey * 10; s_UseTool t;
            t.Clear(); t.ChartNumber = sc.ChartNumber; t.DrawingType = DRAWING_LINE; t.LineNumber = wln + 1;
            t.BeginDateTime = b; t.EndDateTime = e; t.BeginValue = pw.High; t.EndValue = pw.High;
            t.Color = In_PWHLColor.GetColor(); t.LineWidth = lineWidth; t.LineStyle = LINESTYLE_DOT;
            t.AddMethod = UTAM_ADD_OR_ADJUST; t.ShowPrice = showLabels ? 1 : 0; if (showLabels) t.Text = "PW High"; sc.UseTool(t);
            t.Clear(); t.ChartNumber = sc.ChartNumber; t.DrawingType = DRAWING_LINE; t.LineNumber = wln + 2;
            t.BeginDateTime = b; t.EndDateTime = e; t.BeginValue = pw.Low; t.EndValue = pw.Low;
            t.Color = In_PWHLColor.GetColor(); t.LineWidth = lineWidth; t.LineStyle = LINESTYLE_DOT;
            t.AddMethod = UTAM_ADD_OR_ADJUST; t.ShowPrice = showLabels ? 1 : 0; if (showLabels) t.Text = "PW Low"; sc.UseTool(t);
            t.Clear(); t.ChartNumber = sc.ChartNumber; t.DrawingType = DRAWING_LINE; t.LineNumber = wln + 3;
            t.BeginDateTime = b; t.EndDateTime = e; t.BeginValue = pw.VPOC; t.EndValue = pw.VPOC;
            t.Color = In_WVPOCColor.GetColor(); t.LineWidth = lineWidth; t.LineStyle = LINESTYLE_DASHDOT;
            t.AddMethod = UTAM_ADD_OR_ADJUST; t.ShowPrice = showLabels ? 1 : 0; if (showLabels) t.Text = "Weekly VPOC"; sc.UseTool(t);
        }
    }

    // ---- Pass 3: no-man's-land readout + frozen structural HUD -----------
    if (In_ShowHUD.GetYesNo() && curPDidx >= 0)
    {
        const DayProfile& ref = days[curPDidx];
        int lastClosed = sc.ArraySize - 1;
        if (lastClosed > 0 && sc.GetBarHasClosedStatus(lastClosed) != BHCS_BAR_HAS_CLOSED) lastClosed--;
        const float px = sc.Close[lastClosed];

        // nearest_structure()/no_mans_land() (D-004), mirrors structure/levels.py
        const float walls[6] = { ref.POC, ref.VAH, ref.VAL,
            (weeklyValid ? WVPOC : 0.0f), (weeklyValid ? PWH : 0.0f), (weeklyValid ? PWL : 0.0f) };
        float nearUp = 1e30f, nearDn = 1e30f;
        for (int k = 0; k < 6; ++k)
        {
            float w = walls[k]; if (w <= 0) continue;
            if (w > px && (w - px) < nearUp) nearUp = w - px;
            if (w < px && (px - w) < nearDn) nearDn = px - w;
        }
        const float maxDist = In_NoMansLandATR.GetFloat() * atrDaily;
        const bool noMansUp = (atrDaily > 0 && nearUp < 1e30f) ? (nearUp > maxDist) : false;
        const bool noMansDn = (atrDaily > 0 && nearDn < 1e30f) ? (nearDn > maxDist) : false;

        SCString hud, line;
        hud.Append("===== STRUCT (frozen PD reference) =====\n");
        line.Format("PD VA  %.2f / %.2f / %.2f  (VAH/POC/VAL)\n", ref.VAH, ref.POC, ref.VAL); hud.Append(line.GetChars());
        if (ref.RTHValid) { line.Format("RTH O/H/L/C  %.2f / %.2f / %.2f / %.2f\n", ref.RTHOpen, ref.RTHHigh, ref.RTHLow, ref.RTHClose); hud.Append(line.GetChars()); }
        if (weeklyValid) { line.Format("Weekly VPOC %.2f | PW %.2f / %.2f\n", WVPOC, PWH, PWL); hud.Append(line.GetChars()); }
        line.Format("ATR(%d) %.2f\n", In_ATRPeriod.GetInt(), atrDaily); hud.Append(line.GetChars());
        line.Format("Nearest structure: up %.2f%s | down %.2f%s\n",
            nearUp < 1e30f ? nearUp : 0.0f, noMansUp ? " [NO-MANS-LAND]" : "",
            nearDn < 1e30f ? nearDn : 0.0f, noMansDn ? " [NO-MANS-LAND]" : "");
        hud.Append(line.GetChars());

        // ---- Pass 4: order-flow FOLLOW/FADE signal engine (live day only) --
        // UNGATED (see file header): mirrors signals/engine.py exactly. Runs
        // once per recalc over today's RTH bars so far; only NEWLY-fired
        // signals get logged/alerted (persistent-int guard keyed by day).
        hud.Append("===== ORDER-FLOW SIGNALS (ungated, validated core) =====\n");
        if (In_ShowSignals.GetYesNo() && ref.Valid && lastInProgress && days[total - 1].RTHValid)
        {
            const DayProfile& liveDay = days[total - 1];
            int rthStart = liveDay.RTHStartIdx;
            int rthEnd = lastClosed;
            if (rthEnd >= rthStart && ref.VAH > 0 && ref.VAL > 0 && sc.TickSize > 0)
            {
                const int n = rthEnd - rthStart + 1;
                std::vector<float> absDelta(n), deltaSigned(n), cvd(n), volArr(n), hiArr(n), loArr(n), clArr(n);
                float running = 0.0f;
                for (int k = 0; k < n; ++k)
                {
                    int idx = rthStart + k;
                    float delta = sc.AskVolume[idx] - sc.BidVolume[idx];
                    deltaSigned[k] = delta; absDelta[k] = delta < 0 ? -delta : delta;
                    running += delta; cvd[k] = running;
                    volArr[k] = sc.Volume[idx];
                    hiArr[k] = sc.High[idx]; loArr[k] = sc.Low[idx]; clArr[k] = sc.Close[idx];
                }

                const int lookback = In_FeatureLookback.GetInt();
                const int divLookback = In_DeltaDivLookback.GetInt();
                const float absorbZ = In_AbsorptionVolZ.GetFloat();
                const float absorbStall = In_AbsorptionStallTicks.GetFloat();
                const float exhaustZ = In_ExhaustionClimaxZ.GetFloat();
                const float acceptZ = In_AcceptMinVolZ.GetFloat();

                // first-qualifying-bar acceptance (trade_and_rest), precomputed
                // once -- equivalent to Python's growing-slice re-scan (features/
                // acceptance.py), since only the FIRST qualifying bar ever matters.
                int firstAcceptUp = -1, firstAcceptDn = -1;
                for (int k = 0; k < n; ++k)
                {
                    if (firstAcceptUp < 0 && loArr[k] > ref.VAH && RollingZ(volArr, k, lookback) >= acceptZ) firstAcceptUp = k;
                    if (firstAcceptDn < 0 && hiArr[k] < ref.VAL && RollingZ(volArr, k, lookback) >= acceptZ) firstAcceptDn = k;
                }

                struct SigOut { int dir; int idx; bool isFollow; float price; float level; SCString why; };
                std::vector<SigOut> todaySignals;
                int followState[2] = { 0, 0 };   // [0]=long(dir+1) [1]=short(dir-1); 0=idle 1=armed 2=fired
                int fadeState[2] = { 0, 0 };      // fadeDir index: [0]=fadeDir+1 [1]=fadeDir-1
                int excursionExtIdx[2] = { -1, -1 };

                for (int k = 0; k < n; ++k)
                {
                    for (int dSel = 0; dSel < 2; ++dSel)
                    {
                        const int direction = dSel == 0 ? 1 : -1;
                        const float edge = dSel == 0 ? ref.VAH : ref.VAL;
                        const int fadeDirSel = dSel == 0 ? 1 : 0;
                        const bool fullyBeyond = direction > 0 ? (loArr[k] > edge) : (hiArr[k] < edge);
                        if (fullyBeyond)
                        {
                            if (followState[dSel] == 0) followState[dSel] = 1;
                            if (fadeState[fadeDirSel] == 0) fadeState[fadeDirSel] = 1;
                            int prevExt = excursionExtIdx[fadeDirSel];
                            bool takeExt = prevExt < 0;
                            if (!takeExt) { if (direction > 0 && hiArr[k] > hiArr[prevExt]) takeExt = true;
                                            if (direction < 0 && loArr[k] < loArr[prevExt]) takeExt = true; }
                            if (takeExt) excursionExtIdx[fadeDirSel] = k;
                        }

                        // ---- FOLLOW: acceptance beyond the edge, no absorption against ----
                        if (followState[dSel] == 1)
                        {
                            int firstAccept = direction > 0 ? firstAcceptUp : firstAcceptDn;
                            if (firstAccept == k)
                            {
                                int a = AbsorptionAt(absDelta, deltaSigned, hiArr, loArr, k, lookback, absorbZ, absorbStall, sc.TickSize);
                                bool against = (direction > 0 && a == -1) || (direction < 0 && a == 1);
                                if (!against)
                                {
                                    SigOut s; s.dir = direction; s.idx = k; s.isFollow = true;
                                    s.price = clArr[k]; s.level = edge; s.why = "Acceptance";
                                    todaySignals.push_back(s);
                                    followState[dSel] = 2;
                                }
                            }
                        }

                        // ---- FADE: re-entry + evidence the excursion FAILED ----
                        if (fadeState[fadeDirSel] == 1)
                        {
                            bool backInside = clArr[k] > ref.VAL && clArr[k] < ref.VAH;
                            if (backInside)
                            {
                                const int fadeDirActual = fadeDirSel == 0 ? 1 : -1;
                                int extIdx = excursionExtIdx[fadeDirSel];
                                bool hasFailure = false; SCString why;
                                if (extIdx >= 0)
                                {
                                    for (int j = extIdx; j <= k; ++j)
                                    {
                                        int a = AbsorptionAt(absDelta, deltaSigned, hiArr, loArr, j, lookback, absorbZ, absorbStall, sc.TickSize);
                                        if ((fadeDirActual < 0 && a == -1) || (fadeDirActual > 0 && a == 1)) { hasFailure = true; why.Append("Absorption "); }
                                        bool bear, bull; DivergenceAt(hiArr, loArr, cvd, j, divLookback, bear, bull);
                                        if ((fadeDirActual < 0 && bear) || (fadeDirActual > 0 && bull)) { hasFailure = true; why.Append("Divergence "); }
                                        int x = ExhaustionConfirmedAt(absDelta, hiArr, loArr, j, lookback, exhaustZ);
                                        if ((fadeDirActual < 0 && x == -1) || (fadeDirActual > 0 && x == 1)) { hasFailure = true; why.Append("Exhaustion "); }
                                    }
                                }
                                if (hasFailure)
                                {
                                    SigOut s; s.dir = fadeDirActual; s.idx = k; s.isFollow = false;
                                    s.price = clArr[k]; s.level = edge; s.why = why;
                                    todaySignals.push_back(s);
                                    fadeState[fadeDirSel] = 2;
                                }
                            }
                        }
                    }
                }

                // draw markers + log/alert only NEWLY-fired signals this day
                int& loggedDayKey = sc.GetPersistentInt(20);
                int& loggedCount = sc.GetPersistentInt(21);
                if (loggedDayKey != liveDay.DayKey) { loggedDayKey = liveDay.DayKey; loggedCount = 0; }

                for (size_t si = 0; si < todaySignals.size(); ++si)
                {
                    const SigOut& s = todaySignals[si];
                    SCDateTime sTs = sc.BaseDateTimeIn[rthStart + s.idx];
                    s_UseTool m; m.Clear(); m.ChartNumber = sc.ChartNumber; m.DrawingType = DRAWING_TEXT;
                    m.LineNumber = 900000 + liveDay.DayKey * 100 + (int)si;
                    m.BeginDateTime = sTs; m.BeginValue = s.price;
                    m.Color = s.dir > 0 ? In_LongSignalColor.GetColor() : In_ShortSignalColor.GetColor();
                    m.FontSize = 11; m.FontBold = 1; m.AddMethod = UTAM_ADD_OR_ADJUST;
                    m.Text.Format("%s %s\n%.2f", s.isFollow ? "FOLLOW" : "FADE", s.dir > 0 ? "LONG ^" : "SHORT v", s.price);
                    sc.UseTool(m);

                    if ((int)si >= loggedCount)
                    {
                        SCString msg; msg.Format("%s %s @ %.2f (level %.2f) | %s",
                            s.isFollow ? "FOLLOW" : "FADE", s.dir > 0 ? "LONG" : "SHORT", s.price, s.level, s.why.GetChars());
                        if (In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sTs, msg.GetChars());
                        sc.AddMessageToLog(msg, 1);
                    }
                }
                loggedCount = (int)todaySignals.size();

                if (todaySignals.empty()) hud.Append("(none yet today)\n");
                else
                {
                    const SigOut& last = todaySignals.back();
                    line.Format("%d today | last: %s %s @ %.2f\n", (int)todaySignals.size(),
                        last.isFollow ? "FOLLOW" : "FADE", last.dir > 0 ? "LONG" : "SHORT", last.price);
                    hud.Append(line.GetChars());
                }
            }
        }
        else hud.Append("(waiting for live RTH day / valid PD VA)\n");
        hud.Append("-- D-013 gates/veto NOT applied (failed weak-OOS); MOMO not ported --");

        Sub_HUD.PrimaryColor = In_HUDColor.GetColor(); Sub_HUD.LineWidth = In_HUDFontSize.GetInt();
        sc.AddAndManageSingleTextDrawingForStudy(sc, 0, In_HUDHoriz.GetInt(), In_HUDVert.GetInt(),
            Sub_HUD, 1, hud, 1, 1);
    }
}
