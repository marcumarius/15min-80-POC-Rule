// ============================================================================
//  OrderFlowAuctionStudy.cpp
//
//  Sierra Chart custom study (ACSIL). Ground-up rebuild, Phase 1 slice ONLY.
//
//  SCOPE (deliberate): structural context, NOT triggers. Per CLAUDE.md dev
//  rule #2 ("a trigger is not written into ACSIL until it is validated in
//  Python with costs, OOS, and a regime split"), this study draws:
//    - Prior-day POC / VAH / VAL (true volume-at-price, projected onto the
//      next trading day)
//    - Initial Balance high/low
//    - Weekly VPOC + prior-week high/low
//    - A no-man's-land distance readout (D-004)
//  It does NOT contain FADE/FOLLOW/REV signal logic, alerts, day-type
//  scoring, or any of the legacy study's time-based triggers -- those are
//  the entire reason for the rebuild (D-007) and belong in Python first
//  (Phase 2/3), ported here only once validated. Do not add signal logic to
//  this file without a decisions.md entry backing it.
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
        In_LineWidth = sc.Input[20], In_ShowLabels = sc.Input[21];
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
        hud.Append("-- structure only; no signals ported yet (Phase 2/3 pending) --");

        Sub_HUD.PrimaryColor = In_HUDColor.GetColor(); Sub_HUD.LineWidth = In_HUDFontSize.GetInt();
        sc.AddAndManageSingleTextDrawingForStudy(sc, 0, In_HUDHoriz.GetInt(), In_HUDVert.GetInt(),
            Sub_HUD, 1, hud, 1, 1);
    }
}
