// ============================================================================
//  PriorDayNY_ValueArea_80PctRule.cpp
//
//  Sierra Chart custom study (ACSIL).  >>> RUN ON A 30-MINUTE CHART <<<
//
//  INTRADAY (vs prior NY RTH session):
//    - PD VAH / VAL lines, PD POC box, optional VA shade (projected onto today)
//    - FADE  (80% Rule): opened OUTSIDE value -> N closes back INSIDE  -> fade
//    - FOLLOW (acceptance): N closes accepted OUTSIDE a VA edge        -> follow
//    - Initial Balance high/low (first N 30-min bars) + extension read
//
//  HIGHER TIMEFRAME (vs prior WEEK, RTH-based):
//    - Prior-week High (PWH) / Low (PWL) lines + Weekly VPOC line
//    - HUD classifies price: INSIDE weekly balance / AT weekly edge / OUTSIDE
//    - GATE line: confirms or flags conflict between the intraday call and the
//      weekly position (e.g. don't fade into a weekly breakout).
//
//  REGIME HUD (live day): open location, IB, PD value area, intraday verdict,
//    weekly location, and the combined GATE verdict.
//
//  TIMEZONE: session times are in YOUR CHART'S timezone.
//    Chart on US Eastern -> 09:30 / 16:00 ;  Chart on UK time -> 14:30 / 21:00
//    Assumes NY RTH does not cross midnight (US/UK/EU timezones). Weeks are
//    Monday-anchored and built from RTH sessions only.
//
//  BUILD: place in "ACS_Source", Analysis >> Build Custom Studies DLL, add
//  "80% Rule - Prior Day NY Value Area + Fade/Follow". Set a sound on the
//  study's Alert tab for audible alerts.
// ============================================================================

#include "sierrachart.h"
#include <map>
#include <vector>
#include <cstring>
#include <cstdio>
#include <cstdio>

SCDLLName("PriorDayNY_ValueArea_80PctRule")

struct SessionProfile
{
    int DateYMD; SCDateTime StartDT, EndDT; int StartIdx, EndIdx;
    float POC, VAH, VAL; bool Valid;
    float High, Low, Close;
    SessionProfile() : DateYMD(0), StartIdx(0), EndIdx(0), POC(0), VAH(0), VAL(0), Valid(false), High(0), Low(0), Close(0) {}
};

struct DayRange { int DateYMD, StartIdx, EndIdx; DayRange() : DateYMD(0), StartIdx(0), EndIdx(0) {} };

struct IVBData { float High, Low, Range, AvgVol; int LastIdx; bool Valid;
    IVBData() : High(0), Low(0), Range(0), AvgVol(0), LastIdx(0), Valid(false) {} };

struct WeekProfile
{
    int WeekKey; SCDateTime StartDT, EndDT;
    float High, Low, VPOC; bool Valid;
    WeekProfile() : WeekKey(0), High(0), Low(0), VPOC(0), Valid(false) {}
};

static SessionProfile ComputeProfile(const std::map<int, double>& vap, float tickSize, float vaFraction)
{
    SessionProfile sp;
    if (vap.empty() || tickSize <= 0.0f) return sp;
    double total = 0.0; int pocTks = vap.begin()->first; double pocVol = -1.0;
    for (std::map<int, double>::const_iterator it = vap.begin(); it != vap.end(); ++it)
    { total += it->second; if (it->second > pocVol) { pocVol = it->second; pocTks = it->first; } }
    if (total <= 0.0) return sp;
    std::vector<std::pair<int, double> > rows(vap.begin(), vap.end());
    int pocIdx = 0; for (size_t k = 0; k < rows.size(); ++k) if (rows[k].first == pocTks) { pocIdx = (int)k; break; }
    double target = total * vaFraction; double acc = rows[pocIdx].second; int up = pocIdx, dn = pocIdx;
    while (acc < target && (up < (int)rows.size() - 1 || dn > 0))
    {
        bool canUp = up < (int)rows.size() - 1, canDn = dn > 0;
        double upVol = canUp ? rows[up + 1].second : -1.0, dnVol = canDn ? rows[dn - 1].second : -1.0;
        if (canUp && (!canDn || upVol >= dnVol)) acc += rows[++up].second; else if (canDn) acc += rows[--dn].second; else break;
    }
    sp.POC = pocTks * tickSize; sp.VAH = rows[up].first * tickSize; sp.VAL = rows[dn].first * tickSize; sp.Valid = true; return sp;
}

static float VPOCfromMap(const std::map<int, double>& vap, float tickSize)
{
    if (vap.empty()) return 0.0f; int tks = vap.begin()->first; double v = -1.0;
    for (std::map<int, double>::const_iterator it = vap.begin(); it != vap.end(); ++it)
        if (it->second > v) { v = it->second; tks = it->first; }
    return tks * tickSize;
}

// Rejection/Reversal detector at level L over the window ending at 'bar'.
// Returns +1 = REV LONG fired, -1 = REV SHORT fired, 0 = none. scoreOut = magnitude.
// momFilter: also require momentum dying (later highs lower for a top / later lows higher for a bottom).
static int DetectRej(SCStudyInterfaceRef sc, int bar, int W, float L, float tol,
                     int minT, int minR, int cfb, bool momFilter, int& scoreOut)
{
    scoreOut=0;
    if (L<=0.0f || bar < W || bar < cfb+1) return 0;
    const int w0 = bar-W+1;
    int touches=0, rejUp=0, rejDn=0, accAbove=0, accBelow=0;
    for (int b=w0; b<=bar; ++b)
    {
        const float hi=sc.High[b], lo=sc.Low[b], c=sc.Close[b];
        if (lo<=L+tol && hi>=L-tol) touches++;
        if (hi>L && c<L) rejUp++;
        if (lo<L && c>L) rejDn++;
        if (c>L+tol) accAbove++;
        if (c<L-tol) accBelow++;
    }
    // momentum-dying check: compare first vs second half of the window
    bool momOKup=true, momOKdn=true;
    if (momFilter)
    {
        const int mid=(w0+bar)/2;
        float h1=-1e30f,h2=-1e30f,l1=1e30f,l2=1e30f;
        for(int b=w0;b<=mid;++b){ if(sc.High[b]>h1)h1=sc.High[b]; if(sc.Low[b]<l1)l1=sc.Low[b]; }
        for(int b=mid+1;b<=bar;++b){ if(sc.High[b]>h2)h2=sc.High[b]; if(sc.Low[b]<l2)l2=sc.Low[b]; }
        momOKup=(h2<=h1);   // later highs not exceeding earlier -> top failing
        momOKdn=(l2>=l1);   // later lows not undercutting earlier -> bottom holding
    }
    const float pxNow=sc.Close[bar];
    // REV SHORT: level acting as resistance, repeated up-wicks, no acceptance above, break down confirms
    if (pxNow<L && touches>=minT && rejUp>=minR && accAbove<=1 && momOKup)
    {
        float refLo=sc.Low[bar-1]; for(int b=bar-cfb;b<=bar-1;++b){ if(b>=0 && sc.Low[b]<refLo)refLo=sc.Low[b]; }
        if (sc.Close[bar]<refLo){ scoreOut=touches+rejUp; return -1; }
    }
    // REV LONG: level acting as support, repeated down-wicks, no acceptance below, break up confirms
    if (pxNow>L && touches>=minT && rejDn>=minR && accBelow<=1 && momOKdn)
    {
        float refHi=sc.High[bar-1]; for(int b=bar-cfb;b<=bar-1;++b){ if(b>=0 && sc.High[b]>refHi)refHi=sc.High[b]; }
        if (sc.Close[bar]>refHi){ scoreOut=touches+rejDn; return 1; }
    }
    return 0;
}

// Per-session reversal sensitivity dial from a bar's time-of-day (seconds).
static float RevDial(int secs, int usS, int usE, int ukS, int ukE, int aS, int aE,
                     float dUS, float dUK, float dAsia)
{
    if (secs>=usS && secs<usE) return dUS;
    if (secs>=ukS && secs<ukE) return dUK;
    bool inAsia = (aS<=aE) ? (secs>=aS && secs<aE) : (secs>=aS || secs<aE);
    if (inAsia) return dAsia;
    return dUK;   // off-session -> moderate default
}

// Append a SIGNAL line to the log file (fires once per signal at detection time).
static void LogSig(const char* fn, const SCDateTime& dt, const char* msg)
{
    if (!fn || strlen(fn)<2) return;
    FILE* f=fopen(fn,"a");
    if (f){ fprintf(f,"SIGNAL | %04d-%02d-%02d %02d:%02d:%02d | %s\n",
            dt.GetYear(),dt.GetMonth(),dt.GetDay(),dt.GetHour(),dt.GetMinute(),dt.GetSecond(), msg); fclose(f); }
}
// Append a frozen structural-score snapshot (logged once at IB completion).
static void LogDaily(const char* fn, const char* line)
{
    if (!fn || strlen(fn)<2) return;
    FILE* f=fopen(fn,"a");
    if (f){ fprintf(f,"IBSCORE | %s\n", line); fclose(f); }
}
// Append an end-of-day outcome line (logged once at RTH close).
static void LogEOD(const char* fn, const char* line)
{
    if (!fn || strlen(fn)<2) return;
    FILE* f=fopen(fn,"a");
    if (f){ fprintf(f,"EOD | %s\n", line); fclose(f); }
}


// and (optional) a swing-based trailing stop floored at 0.10x ATR. Live-day only.
static void DrawGuides(SCStudyInterfaceRef sc, int baseLN, int entryBar, int lastBar,
                       const SCDateTime& endDT, float entryPx, float stopPx, float tgtPx,
                       int dir, float atr, bool drawTrail, int cE, int cS, int cT, const char* tag)
{
    if (entryBar<0 || entryBar>=sc.ArraySize) return;
    const SCDateTime b0=sc.BaseDateTimeIn[entryBar];
    s_UseTool t; SCString lb;
    // entry
    t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=baseLN;
    t.BeginDateTime=b0; t.EndDateTime=endDT; t.BeginValue=entryPx; t.EndValue=entryPx;
    t.Color=(COLORREF)cE; t.LineWidth=1; t.LineStyle=LINESTYLE_SOLID; t.AddMethod=UTAM_ADD_OR_ADJUST;
    t.ShowPrice=1; sc.UseTool(t);   // entry (yellow) - see HUD legend
    // initial stop
    t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=baseLN+1;
    t.BeginDateTime=b0; t.EndDateTime=endDT; t.BeginValue=stopPx; t.EndValue=stopPx;
    t.Color=(COLORREF)cS; t.LineWidth=1; t.LineStyle=LINESTYLE_SOLID; t.AddMethod=UTAM_ADD_OR_ADJUST;
    t.ShowPrice=1; sc.UseTool(t);   // stop (red)
    // static target (green solid)
    t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=baseLN+2;
    t.BeginDateTime=b0; t.EndDateTime=endDT; t.BeginValue=tgtPx; t.EndValue=tgtPx;
    t.Color=(COLORREF)cT; t.LineWidth=1; t.LineStyle=LINESTYLE_SOLID; t.AddMethod=UTAM_ADD_OR_ADJUST;
    t.ShowPrice=1; sc.UseTool(t);   // target (green solid)
    // trailing stop (green dashed): swing-based, floored at 0.10x ATR, ratchets
    if (drawTrail && entryBar+1<=lastBar)
    {
        float trail=stopPx;
        for (int b=entryBar+1; b<=lastBar; ++b)
        {
            float sw = dir>0? sc.Low[b] : sc.High[b];
            for (int k=b-2; k<b; ++k){ if(k>=0){ if(dir>0){ if(sc.Low[k]<sw)sw=sc.Low[k]; } else { if(sc.High[k]>sw)sw=sc.High[k]; } } }
            float af = dir>0? sc.Close[b]-0.10f*atr : sc.Close[b]+0.10f*atr;
            float cand = dir>0? (sw>af?sw:af) : (sw<af?sw:af);
            if (dir>0){ if(cand>trail)trail=cand; } else { if(cand<trail)trail=cand; }
        }
        t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=baseLN+3;
        t.BeginDateTime=b0; t.EndDateTime=endDT; t.BeginValue=trail; t.EndValue=trail;
        t.Color=(COLORREF)cT; t.LineWidth=1; t.LineStyle=LINESTYLE_DASH; t.AddMethod=UTAM_ADD_OR_ADJUST;
        t.ShowPrice=1; sc.UseTool(t);   // trail (green dashed)
    }
}


// LONG must be above VWAP with clear space UP to the nearest wall; SHORT the mirror.
// walls[] holds PD POC/VAH/VAL + Weekly VPOC (HTF folded in). Returns true if allowed.
static bool RevGatePass(int dir, float px, float vwapv, float minSpace,
                        const float* walls, int nWalls, bool useVWAP, bool useSpace)
{
    if (dir>0)   // LONG
    {
        if (useVWAP && vwapv>0.0f && !(px>vwapv)) return false;
        if (useSpace){ float nn=1e30f; for(int i=0;i<nWalls;++i){ float w=walls[i]; if(w>0 && w>px && (w-px)<nn) nn=w-px; } if(nn<minSpace) return false; }
    }
    else if (dir<0)   // SHORT
    {
        if (useVWAP && vwapv>0.0f && !(px<vwapv)) return false;
        if (useSpace){ float nn=1e30f; for(int i=0;i<nWalls;++i){ float w=walls[i]; if(w>0 && w<px && (px-w)<nn) nn=px-w; } if(nn<minSpace) return false; }
    }
    return true;
}



static void DrawSignalTime(SCStudyInterfaceRef sc, int lineNum, int bar, float price, bool up,
                           int col, int fontSz, int offTicks)
{
    SCDateTime bdt = sc.BaseDateTimeIn[bar];
    SCString ts; ts.Format("%02d:%02d", bdt.GetHour(), bdt.GetMinute());
    s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=lineNum;
    m.BeginDateTime=bdt; m.BeginValue = price + (up ? 1 : -1) * offTicks * sc.TickSize;
    m.Color=(COLORREF)col; m.FontSize=fontSz; m.FontBold=0; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text=ts; sc.UseTool(m);
}

SCSFExport scsf_PriorDayNY_ValueArea(SCStudyInterfaceRef sc)
{
    SCInputRef In_SessionStart=sc.Input[0], In_SessionEnd=sc.Input[1], In_ValueAreaPct=sc.Input[2],
        In_DaysToDraw=sc.Input[3], In_POCBoxTicks=sc.Input[4], In_DrawVAFill=sc.Input[5],
        In_VAHColor=sc.Input[6], In_VALColor=sc.Input[7], In_POCColor=sc.Input[8], In_VAFillColor=sc.Input[9],
        In_LineWidth=sc.Input[10], In_ShowLabels=sc.Input[11], In_FadeAlert=sc.Input[12], In_DrawMarkers=sc.Input[13],
        In_DrawIB=sc.Input[14], In_IBColor=sc.Input[15], In_FollowAlert=sc.Input[16], In_ShowHUD=sc.Input[17],
        In_IBMin=sc.Input[18], In_AcceptWindow=sc.Input[19], In_DrawWeekly=sc.Input[20], In_PWHLColor=sc.Input[21],
        In_WVPOCColor=sc.Input[22], In_EdgeZonePct=sc.Input[23], In_WeeksToDraw=sc.Input[24], In_FadeGateMode=sc.Input[25],
        In_HUDVert=sc.Input[26], In_HUDHoriz=sc.Input[27], In_HUDFontSize=sc.Input[28], In_HUDColor=sc.Input[29], In_HUDTransp=sc.Input[30],
        In_UKSignals=sc.Input[31], In_UKStart=sc.Input[32], In_UKEnd=sc.Input[33],
        In_ShowTS=sc.Input[34], In_TSColor=sc.Input[35], In_TSFontSize=sc.Input[36], In_TSOffset=sc.Input[37],
        In_NtfyEnable=sc.Input[38], In_NtfyURL=sc.Input[39],
        In_AccUK=sc.Input[40], In_AccAsia=sc.Input[41], In_AsiaSignals=sc.Input[42], In_AsiaStart=sc.Input[43], In_AsiaEnd=sc.Input[44],
        In_IVBEnable=sc.Input[45], In_IVBMin=sc.Input[46], In_IVBUseVol=sc.Input[47], In_IVBVolMult=sc.Input[48], In_IVBSkewMode=sc.Input[49],
        In_IVBShortPen=sc.Input[50], In_IVBWidthFilter=sc.Input[51], In_IVBMaxWidth=sc.Input[52], In_IVBHTFAlign=sc.Input[53],
        In_IVBDrawTargets=sc.Input[54], In_IVBTargetColor=sc.Input[55],
        In_ScWidth=sc.Input[56], In_ScHTF=sc.Input[57], In_ScPOC=sc.Input[58], In_ScOpen=sc.Input[59],
        In_GapEnable=sc.Input[60], In_ATRlen=sc.Input[61], In_GapLargeX=sc.Input[62],
        In_OpenTypeEnable=sc.Input[63], In_OpenTypeBars=sc.Input[64], In_ValMigEnable=sc.Input[65],
        In_NakedEnable=sc.Input[66], In_NakedMax=sc.Input[67], In_NakedColor=sc.Input[68], In_LadderEnable=sc.Input[69],
        In_RevEnable=sc.Input[70], In_RevWindow=sc.Input[71], In_RevMinTouch=sc.Input[72], In_RevMinRej=sc.Input[73],
        In_RevTolTicks=sc.Input[74], In_RevConfirmBars=sc.Input[75], In_RevColor=sc.Input[76],
        In_RevDialUS=sc.Input[77], In_RevDialUK=sc.Input[78], In_RevDialAsia=sc.Input[79],
        In_RevMomFilter=sc.Input[80], In_RevATRNorm=sc.Input[81],
        In_VWAPStudyID=sc.Input[82], In_RevVWAPGate=sc.Input[83], In_RevSpaceGate=sc.Input[84],
        In_RevSpacePts=sc.Input[85], In_RevSpaceATR=sc.Input[86],
        In_GuidesEnable=sc.Input[87], In_GuidesTrail=sc.Input[88], In_GuideEntryColor=sc.Input[89],
        In_GuideStopColor=sc.Input[90], In_GuideTgtColor=sc.Input[91],
        In_RevUSonly=sc.Input[92], In_FollowEdge=sc.Input[93],
        In_LogEnable=sc.Input[94], In_LogFile=sc.Input[95];
    SCSubgraphRef Sub_HUD = sc.Subgraph[0];

    if (sc.SetDefaults)
    {
        sc.GraphName = "80% Rule - Prior Day NY Value Area + Fade/Follow";
        sc.StudyDescription = "Prior NY RTH value area + automated FADE/FOLLOW regime read, Initial Balance, "
                              "and a higher-timeframe gate (prior-week high/low, weekly VPOC). 30-min chart.";
        sc.AutoLoop = 0; sc.GraphRegion = 0; sc.MaintainVolumeAtPriceData = 1; sc.DrawZeros = 0; sc.ValueFormat = VALUEFORMAT_INHERITED;

        In_SessionStart.Name="NY RTH Session Start (chart time)"; In_SessionStart.SetTime(HMS_TIME(9,30,0));
        In_SessionEnd.Name="NY RTH Session End (chart time)";     In_SessionEnd.SetTime(HMS_TIME(16,0,0));
        In_ValueAreaPct.Name="Value Area Percentage"; In_ValueAreaPct.SetFloat(70.0f); In_ValueAreaPct.SetFloatLimits(1.0f,100.0f);
        In_DaysToDraw.Name="Number of Days to Draw"; In_DaysToDraw.SetInt(60); In_DaysToDraw.SetIntLimits(1,250);
        In_POCBoxTicks.Name="POC Box Half-Height (ticks)"; In_POCBoxTicks.SetInt(2); In_POCBoxTicks.SetIntLimits(0,200);
        In_DrawVAFill.Name="Shade Value Area (VAL-VAH)"; In_DrawVAFill.SetYesNo(0);
        In_VAHColor.Name="VAH Line Color"; In_VAHColor.SetColor(0,170,0);
        In_VALColor.Name="VAL Line Color"; In_VALColor.SetColor(210,0,0);
        In_POCColor.Name="POC Line Color"; In_POCColor.SetColor(255,0,255);
        In_VAFillColor.Name="Value Area Fill Color"; In_VAFillColor.SetColor(70,70,140);
        In_LineWidth.Name="Line Width"; In_LineWidth.SetInt(2); In_LineWidth.SetIntLimits(1,10);
        In_ShowLabels.Name="Show Labels / Price"; In_ShowLabels.SetYesNo(1);
        In_FadeAlert.Name="Enable FADE (80% Rule) Alert"; In_FadeAlert.SetYesNo(1);
        In_DrawMarkers.Name="Draw Fade/Follow Markers"; In_DrawMarkers.SetYesNo(1);
        In_DrawIB.Name="Draw Initial Balance"; In_DrawIB.SetYesNo(1);
        In_IBColor.Name="Initial Balance Color"; In_IBColor.SetColor(120,120,200);
        In_FollowAlert.Name="Enable FOLLOW (Breakout) Alert"; In_FollowAlert.SetYesNo(1);
        In_ShowHUD.Name="Show Regime HUD"; In_ShowHUD.SetYesNo(1);
        In_IBMin.Name="Initial Balance Duration (minutes)"; In_IBMin.SetInt(60); In_IBMin.SetIntLimits(5,390);
        In_AcceptWindow.Name="US Acceptance Window (minutes)"; In_AcceptWindow.SetCustomInputStrings("15;30;45;60"); In_AcceptWindow.SetCustomInputIndex(0);
        In_DrawWeekly.Name="Draw Weekly (PWH/PWL/VPOC)"; In_DrawWeekly.SetYesNo(1);
        In_PWHLColor.Name="Prior-Week High/Low Color"; In_PWHLColor.SetColor(200,140,0);
        In_WVPOCColor.Name="Weekly VPOC Color"; In_WVPOCColor.SetColor(180,120,220);
        In_EdgeZonePct.Name="Weekly Edge Zone (% of week range)"; In_EdgeZonePct.SetFloat(15.0f); In_EdgeZonePct.SetFloatLimits(1.0f,50.0f);
        In_WeeksToDraw.Name="Number of Weeks to Draw"; In_WeeksToDraw.SetInt(4); In_WeeksToDraw.SetIntLimits(1,52);
        In_FadeGateMode.Name="FADE Gate Mode"; In_FadeGateMode.SetCustomInputStrings("Open outside value;Touched outside during IB"); In_FadeGateMode.SetCustomInputIndex(1);
        In_HUDVert.Name="HUD Vertical Position (0-150)"; In_HUDVert.SetInt(92); In_HUDVert.SetIntLimits(0,150);
        In_HUDHoriz.Name="HUD Horizontal Position (0-150)"; In_HUDHoriz.SetInt(2); In_HUDHoriz.SetIntLimits(0,150);
        In_HUDFontSize.Name="HUD Font Size"; In_HUDFontSize.SetInt(13); In_HUDFontSize.SetIntLimits(6,40);
        In_HUDColor.Name="HUD Text Color"; In_HUDColor.SetColor(235,235,235);
        In_HUDTransp.Name="HUD Transparent Background"; In_HUDTransp.SetYesNo(1);
        In_UKSignals.Name="Enable UK-session FOLLOW signals"; In_UKSignals.SetYesNo(1);
        In_UKStart.Name="UK Session Start (chart time)"; In_UKStart.SetTime(HMS_TIME(3,0,0));
        In_UKEnd.Name="UK Session End (chart time)"; In_UKEnd.SetTime(HMS_TIME(9,30,0));
        In_AccUK.Name="UK Acceptance Window (minutes)"; In_AccUK.SetCustomInputStrings("15;30;45;60"); In_AccUK.SetCustomInputIndex(0);
        In_AccAsia.Name="Asia Acceptance Window (minutes)"; In_AccAsia.SetCustomInputStrings("15;30;45;60"); In_AccAsia.SetCustomInputIndex(3);
        In_AsiaSignals.Name="Enable Asia-session FOLLOW signals"; In_AsiaSignals.SetYesNo(1);
        In_AsiaStart.Name="Asia Session Start (chart time)"; In_AsiaStart.SetTime(HMS_TIME(18,0,0));
        In_AsiaEnd.Name="Asia Session End (chart time)"; In_AsiaEnd.SetTime(HMS_TIME(3,0,0));
        In_IVBEnable.Name="Enable IVB (Initial Volume Breakout)"; In_IVBEnable.SetYesNo(1);
        In_IVBMin.Name="IVB Range Duration (minutes)"; In_IVBMin.SetCustomInputStrings("30;45;60"); In_IVBMin.SetCustomInputIndex(0);
        In_IVBUseVol.Name="IVB Require Volume Expansion"; In_IVBUseVol.SetYesNo(1);
        In_IVBVolMult.Name="IVB Volume Multiplier (x avg)"; In_IVBVolMult.SetFloat(1.5f); In_IVBVolMult.SetFloatLimits(1.0f,10.0f);
        In_IVBSkewMode.Name="IVB Skew Mode"; In_IVBSkewMode.SetCustomInputStrings("Both equal;Favor longs;Long only"); In_IVBSkewMode.SetCustomInputIndex(1);
        In_IVBShortPen.Name="IVB Short Penalty (x, Favor-longs)"; In_IVBShortPen.SetFloat(1.3f); In_IVBShortPen.SetFloatLimits(1.0f,5.0f);
        In_IVBWidthFilter.Name="IVB Skip Wide-IB (rotation) Days"; In_IVBWidthFilter.SetYesNo(1);
        In_IVBMaxWidth.Name="IVB Max IB Width (x 20-day avg)"; In_IVBMaxWidth.SetFloat(1.5f); In_IVBMaxWidth.SetFloatLimits(1.0f,5.0f);
        In_IVBHTFAlign.Name="IVB Require HTF Alignment (vs Wk VPOC)"; In_IVBHTFAlign.SetYesNo(0);
        In_IVBDrawTargets.Name="IVB Draw Extension/Mid Targets"; In_IVBDrawTargets.SetYesNo(1);
        In_IVBTargetColor.Name="IVB Target Line Color"; In_IVBTargetColor.SetColor(0,200,200);
        In_ScWidth.Name="Score: use IB Width modifier"; In_ScWidth.SetYesNo(1);
        In_ScHTF.Name="Score: use HTF (Wk VPOC) modifier"; In_ScHTF.SetYesNo(1);
        In_ScPOC.Name="Score: use POC-vs-IB modifier"; In_ScPOC.SetYesNo(1);
        In_ScOpen.Name="Score: use Open-location modifier"; In_ScOpen.SetYesNo(1);
        In_GapEnable.Name="Gap: use Gap-vs-ATR fade/follow filter"; In_GapEnable.SetYesNo(1);
        In_ATRlen.Name="Gap: ATR length (days)"; In_ATRlen.SetInt(14); In_ATRlen.SetIntLimits(2,50);
        In_GapLargeX.Name="Gap: Large-gap threshold (x ATR)"; In_GapLargeX.SetFloat(1.2f); In_GapLargeX.SetFloatLimits(0.3f,5.0f);
        In_OpenTypeEnable.Name="Open: detect Opening Type (Dalton)"; In_OpenTypeEnable.SetYesNo(1);
        In_OpenTypeBars.Name="Open: bars to assess opening type"; In_OpenTypeBars.SetInt(3); In_OpenTypeBars.SetIntLimits(1,8);
        In_ValMigEnable.Name="Value: use Value-Migration context"; In_ValMigEnable.SetYesNo(1);
        In_NakedEnable.Name="Naked POC: draw untested prior POCs"; In_NakedEnable.SetYesNo(1);
        In_NakedMax.Name="Naked POC: max count to show"; In_NakedMax.SetInt(8); In_NakedMax.SetIntLimits(1,20);
        In_NakedColor.Name="Naked POC: line color"; In_NakedColor.SetColor(150,150,150);
        In_LadderEnable.Name="IVB: draw extension ladder (50/150/200%)"; In_LadderEnable.SetYesNo(0);
        In_RevEnable.Name="REV: enable Rejection/Reversal signal"; In_RevEnable.SetYesNo(1);
        In_RevWindow.Name="REV: lookback window (bars)"; In_RevWindow.SetInt(12); In_RevWindow.SetIntLimits(4,40);
        In_RevMinTouch.Name="REV: min touches at level"; In_RevMinTouch.SetInt(3); In_RevMinTouch.SetIntLimits(2,10);
        In_RevMinRej.Name="REV: min wick rejections"; In_RevMinRej.SetInt(2); In_RevMinRej.SetIntLimits(1,8);
        In_RevTolTicks.Name="REV: touch tolerance (ticks)"; In_RevTolTicks.SetInt(8); In_RevTolTicks.SetIntLimits(1,60);
        In_RevConfirmBars.Name="REV: break-back confirm bars"; In_RevConfirmBars.SetInt(2); In_RevConfirmBars.SetIntLimits(1,6);
        In_RevColor.Name="REV: marker/line color"; In_RevColor.SetColor(255,140,0);
        In_RevDialUS.Name="REV: US sensitivity dial"; In_RevDialUS.SetFloat(1.0f); In_RevDialUS.SetFloatLimits(0.5f,3.0f);
        In_RevDialUK.Name="REV: UK sensitivity dial"; In_RevDialUK.SetFloat(1.3f); In_RevDialUK.SetFloatLimits(0.5f,3.0f);
        In_RevDialAsia.Name="REV: Asia sensitivity dial"; In_RevDialAsia.SetFloat(1.7f); In_RevDialAsia.SetFloatLimits(0.5f,3.0f);
        In_RevMomFilter.Name="REV: require momentum-dying (LH/HL)"; In_RevMomFilter.SetYesNo(1);
        In_RevATRNorm.Name="REV: ATR-normalize touch tolerance"; In_RevATRNorm.SetYesNo(1);
        In_VWAPStudyID.Name="REV: VWAP study ID (0=auto-compute daily)"; In_VWAPStudyID.SetInt(5); In_VWAPStudyID.SetIntLimits(0,200);
        In_RevVWAPGate.Name="REV: gate by VWAP side (long>VWAP)"; In_RevVWAPGate.SetYesNo(1);
        In_RevSpaceGate.Name="REV: gate by clear-space to walls"; In_RevSpaceGate.SetYesNo(1);
        In_RevSpacePts.Name="REV: clear-space cap (points)"; In_RevSpacePts.SetFloat(100.0f); In_RevSpacePts.SetFloatLimits(5.0f,1000.0f);
        In_RevSpaceATR.Name="REV: clear-space ATR fraction"; In_RevSpaceATR.SetFloat(0.15f); In_RevSpaceATR.SetFloatLimits(0.02f,1.0f);
        In_GuidesEnable.Name="Guides: draw entry/stop/target lines"; In_GuidesEnable.SetYesNo(1);
        In_GuidesTrail.Name="Guides: draw trailing stop line"; In_GuidesTrail.SetYesNo(1);
        In_GuideEntryColor.Name="Guides: entry line color"; In_GuideEntryColor.SetColor(255,255,0);
        In_GuideStopColor.Name="Guides: stop line color"; In_GuideStopColor.SetColor(255,60,60);
        In_GuideTgtColor.Name="Guides: target/trail line color"; In_GuideTgtColor.SetColor(0,220,0);
        In_RevUSonly.Name="REV: US session only (5y-backtested)"; In_RevUSonly.SetYesNo(1);
        In_FollowEdge.Name="FOLLOW: mute dead cells (Asia-long/UK-short)"; In_FollowEdge.SetYesNo(1);
        In_LogEnable.Name="LOG: write signals + daily HUD to text file"; In_LogEnable.SetYesNo(0);
        In_LogFile.Name="LOG: file name (in Data folder)"; In_LogFile.SetString("PriorDay80_log.txt");
        In_ShowTS.Name="Show Signal Timestamps"; In_ShowTS.SetYesNo(1);
        In_TSColor.Name="Signal Timestamp Color"; In_TSColor.SetColor(255,255,255);
        In_TSFontSize.Name="Signal Timestamp Font Size"; In_TSFontSize.SetInt(9); In_TSFontSize.SetIntLimits(6,40);
        In_TSOffset.Name="Signal Timestamp Offset (ticks)"; In_TSOffset.SetInt(8); In_TSOffset.SetIntLimits(0,400);
        In_NtfyEnable.Name="Send ntfy Push on Signals"; In_NtfyEnable.SetYesNo(1);
        In_NtfyURL.Name="ntfy Topic URL"; In_NtfyURL.SetString("https://ntfy.sh/");
        Sub_HUD.Name="Regime HUD"; Sub_HUD.DrawStyle=DRAWSTYLE_IGNORE; Sub_HUD.PrimaryColor=RGB(235,235,235); Sub_HUD.LineWidth=13;
        return;
    }

    int& lastSize = sc.GetPersistentInt(1);
    bool newBar = (sc.ArraySize != lastSize);
    if (!sc.IsFullRecalculation && !newBar) return;
    lastSize = sc.ArraySize;
    if (sc.VolumeAtPriceForBars == NULL || sc.ArraySize == 0 || sc.TickSize <= 0.0f) return;

    const int sessStartSec = In_SessionStart.GetTime(), sessEndSec = In_SessionEnd.GetTime();
    const float vaFraction = In_ValueAreaPct.GetFloat()/100.0f;
    double barMin = (double)sc.SecondsPerBar / 60.0;             // chart bar length in minutes
    int ibBars = (barMin > 0.0) ? (int)((In_IBMin.GetInt() / barMin) + 0.5) : 2;
    if (ibBars < 1) ibBars = 1;
    const int gateMode = In_FadeGateMode.GetIndex();              // 0=open outside, 1=touched outside in IB
    const int accIdx = In_AcceptWindow.GetIndex();
    const int accMin = (accIdx==0?15: accIdx==1?30: accIdx==2?45: 60);
    int acceptN = (barMin > 0.0) ? (int)((accMin / barMin) + 0.5) : 2;
    if (acceptN < 1) acceptN = 1;
    const int accIdxUK = In_AccUK.GetIndex();
    const int accMinUK = (accIdxUK==0?15: accIdxUK==1?30: accIdxUK==2?45: 60);
    int acceptN_UK = (barMin > 0.0) ? (int)((accMinUK / barMin) + 0.5) : 2; if (acceptN_UK < 1) acceptN_UK = 1;
    const int accIdxAsia = In_AccAsia.GetIndex();
    const int accMinAsia = (accIdxAsia==0?15: accIdxAsia==1?30: accIdxAsia==2?45: 60);
    int acceptN_Asia = (barMin > 0.0) ? (int)((accMinAsia / barMin) + 0.5) : 2; if (acceptN_Asia < 1) acceptN_Asia = 1;

    // ---- Pass 1: build daily + weekly profiles -----------------------------
    std::vector<SessionProfile> sessions;
    std::vector<WeekProfile> weeks;
    std::map<int,double> vap, wvap;
    int curKey=-1, startIdx=0, endIdx=0;
    SCDateTime curStart(0.0), curEnd(0.0);
    int curWeek=-1; float wHigh=0, wLow=0; SCDateTime wStart(0.0), wEnd(0.0);

    for (int i=0; i<sc.ArraySize; ++i)
    {
        const SCDateTime bdt = sc.BaseDateTimeIn[i];
        const int secs = bdt.GetTimeInSeconds();
        if (secs < sessStartSec || secs >= sessEndSec) continue;

        // ---- daily bucket ----
        const int key = (bdt.GetYear()-2000)*10000 + bdt.GetMonth()*100 + bdt.GetDay();
        if (key != curKey)
        {
            if (curKey != -1 && !vap.empty())
            {
                SessionProfile sp = ComputeProfile(vap, sc.TickSize, vaFraction);
                if (sp.Valid){ sp.DateYMD=curKey; sp.StartDT=curStart; sp.EndDT=curEnd; sp.StartIdx=startIdx; sp.EndIdx=endIdx; sessions.push_back(sp); }
            }
            vap.clear(); curKey=key; curStart=bdt; startIdx=i;
        }
        curEnd=bdt; endIdx=i;

        // ---- weekly bucket (Monday-anchored) ----
        int dow = bdt.GetDayOfWeek();                 // 0=Sun .. 6=Sat
        int back = (dow + 6) % 7;                      // days back to Monday
        SCDateTime monday = bdt.GetDate() - SCDateTime::DAYS(back);
        int wkey = (monday.GetYear()-2000)*10000 + monday.GetMonth()*100 + monday.GetDay();
        if (wkey != curWeek)
        {
            if (curWeek != -1 && !wvap.empty())
            {
                WeekProfile wp; wp.WeekKey=curWeek; wp.StartDT=wStart; wp.EndDT=wEnd;
                wp.High=wHigh; wp.Low=wLow; wp.VPOC=VPOCfromMap(wvap, sc.TickSize); wp.Valid=true; weeks.push_back(wp);
            }
            wvap.clear(); curWeek=wkey; wStart=bdt; wHigh=sc.High[i]; wLow=sc.Low[i];
        }
        wEnd=bdt;
        if (sc.High[i] > wHigh) wHigh = sc.High[i];
        if (sc.Low[i]  < wLow ) wLow  = sc.Low[i];

        // ---- volume@price into both buckets ----
        const int n = (int)sc.VolumeAtPriceForBars->GetSizeAtBarIndex(i);
        for (int jj=0; jj<n; ++jj)
        {
            s_VolumeAtPriceV2* p=NULL; sc.VolumeAtPriceForBars->GetVAPElementAtIndex(i, jj, &p);
            if (p != NULL){ vap[p->PriceInTicks] += (double)p->Volume; wvap[p->PriceInTicks] += (double)p->Volume; }
        }
    }
    if (curKey != -1 && !vap.empty())
    {
        SessionProfile sp = ComputeProfile(vap, sc.TickSize, vaFraction);
        if (sp.Valid){ sp.DateYMD=curKey; sp.StartDT=curStart; sp.EndDT=curEnd; sp.StartIdx=startIdx; sp.EndIdx=endIdx; sessions.push_back(sp); }
    }
    if (curWeek != -1 && !wvap.empty())
    {
        WeekProfile wp; wp.WeekKey=curWeek; wp.StartDT=wStart; wp.EndDT=wEnd; wp.High=wHigh; wp.Low=wLow;
        wp.VPOC=VPOCfromMap(wvap, sc.TickSize); wp.Valid=true; weeks.push_back(wp);
    }

    sc.DeleteACSChartDrawing(sc.ChartNumber, TOOL_DELETE_ALL, 0);
    const int total = (int)sessions.size();
    if (total == 0) return;

    // Fill each session's High/Low/Close from its bar range (for ATR / gap calc)
    for (int si=0; si<total; ++si)
    {
        SessionProfile& sp = sessions[si];
        float hi=sc.High[sp.StartIdx], lo=sc.Low[sp.StartIdx];
        for (int b=sp.StartIdx; b<=sp.EndIdx; ++b){ if(sc.High[b]>hi)hi=sc.High[b]; if(sc.Low[b]<lo)lo=sc.Low[b]; }
        sp.High=hi; sp.Low=lo; sp.Close=sc.Close[sp.EndIdx];
    }

    // Function-scope daily ATR (for REV ATR-normalized tolerance)
    float atrDaily=0.0f;
    { int L=In_ATRlen.GetInt(); double ts=0; int tn=0;
      for(int k=(total-1-L>1?total-1-L:1); k<=total-1 && k>=1; ++k){
        const SessionProfile& sk=sessions[k]; const SessionProfile& pk=sessions[k-1];
        float tr=sk.High-sk.Low; float d2=sk.High-pk.Close; if(d2<0)d2=-d2; if(d2>tr)tr=d2;
        float d3=sk.Low-pk.Close; if(d3<0)d3=-d3; if(d3>tr)tr=d3; ts+=tr; tn++; }
      if(tn>0) atrDaily=(float)(ts/tn);
    }

    // Daily-anchored VWAP for REV gating. If a study ID is set, read that exact
    // line; otherwise compute an internal daily-reset VWAP (based on Last).
    std::vector<float> vwapArr(sc.ArraySize, 0.0f);
    {
        bool got=false;
        if (In_VWAPStudyID.GetInt()>0)
        {
            SCFloatArray sa; sc.GetStudyArrayUsingID(In_VWAPStudyID.GetInt(), 0, sa);
            if (sa.GetArraySize() >= sc.ArraySize){ for(int b=0;b<sc.ArraySize;++b) vwapArr[b]=sa[b]; got=true; }
        }
        if (!got)
        {
            double pv=0, vv=0; int cd=-1;
            for (int b=0;b<sc.ArraySize;++b){
                const SCDateTime t=sc.BaseDateTimeIn[b];
                int day=t.GetYear()*10000+t.GetMonth()*100+t.GetDay();
                if (day!=cd){ pv=0; vv=0; cd=day; }
                double v=sc.Volume[b]; pv+=(double)sc.Close[b]*v; vv+=v;
                vwapArr[b]= vv>0? (float)(pv/vv) : sc.Close[b];
            }
        }
    }

    const int daysToDraw = In_DaysToDraw.GetInt();
    int firstDraw = total - daysToDraw; if (firstDraw < 0) firstDraw = 0;
    const int lineWidth = In_LineWidth.GetInt();
    const bool showLabels = In_ShowLabels.GetYesNo() != 0;

    // Is the most recent session still in progress? Its value area is still
    // developing (recomputes every bar), so we must NOT draw it as a "PD" level
    // or the lines drift. Only completed sessions give frozen PD references.
    bool lastInProgress = false;
    {
        const SCDateTime lb = sc.BaseDateTimeIn[sc.ArraySize-1];
        const int lbDate = (lb.GetYear()-2000)*10000 + lb.GetMonth()*100 + lb.GetDay();
        if (lbDate == sessions[total-1].DateYMD && lb.GetTimeInSeconds() < sessEndSec)
            lastInProgress = true;
    }

    // The "current PD reference" is the most recent COMPLETED session. Its lines
    // must extend to the right edge (into the future), not stop at the live bar.
    const int curPDidx = lastInProgress ? total-2 : total-1;
    const SCDateTime farRight = sc.BaseDateTimeIn[sc.ArraySize-1] + SCDateTime::DAYS(1);

    // ---- Pass 2: project prior session's value area onto next day ----------
    for (int i=firstDraw; i<total; ++i)
    {
        if (i == total-1 && lastInProgress) continue;   // skip developing VA (drift)
        const SessionProfile& s = sessions[i];
        SCDateTime beginDT = s.EndDT;
        SCDateTime endDT = (i >= curPDidx) ? farRight                      // current ref -> right edge
                          : (i+1<total ? sessions[i+1].EndDT : s.EndDT + SCDateTime::DAYS(1));
        const int ln = 100000 + s.DateYMD*10; s_UseTool t;
        t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=ln+1; t.BeginDateTime=beginDT; t.EndDateTime=endDT;
        t.BeginValue=s.VAH; t.EndValue=s.VAH; t.Color=In_VAHColor.GetColor(); t.LineWidth=lineWidth; t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="PD VAH"; sc.UseTool(t);
        t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=ln+2; t.BeginDateTime=beginDT; t.EndDateTime=endDT;
        t.BeginValue=s.VAL; t.EndValue=s.VAL; t.Color=In_VALColor.GetColor(); t.LineWidth=lineWidth; t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="PD VAL"; sc.UseTool(t);
        t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=ln+3; t.BeginDateTime=beginDT; t.EndDateTime=endDT;
        t.BeginValue=s.POC; t.EndValue=s.POC; t.Color=In_POCColor.GetColor(); t.LineWidth=lineWidth; t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=0; if(showLabels)t.Text="PD POC"; sc.UseTool(t);
        if (In_DrawVAFill.GetYesNo())
        { t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_RECTANGLEHIGHLIGHT; t.LineNumber=ln+4; t.BeginDateTime=beginDT; t.EndDateTime=endDT;
          t.BeginValue=s.VAH; t.EndValue=s.VAL; t.Color=In_VAFillColor.GetColor(); t.SecondaryColor=In_VAFillColor.GetColor(); t.TransparencyLevel=88; t.LineWidth=1; t.AddMethod=UTAM_ADD_OR_ADJUST; sc.UseTool(t); }
    }

    // ---- Pass 2b: weekly levels (prior week projected onto current week) ----
    const int numWk = (int)weeks.size();
    bool weeklyValid = numWk >= 2 && weeks[numWk-2].Valid;
    float PWH=0, PWL=0, WVPOC=0;
    if (weeklyValid){ PWH=weeks[numWk-2].High; PWL=weeks[numWk-2].Low; WVPOC=weeks[numWk-2].VPOC; }

    if (In_DrawWeekly.GetYesNo() && numWk >= 2)
    {
        int weeksToDraw = In_WeeksToDraw.GetInt();
        int firstWk = numWk - weeksToDraw; if (firstWk < 1) firstWk = 1;
        for (int w=firstWk; w<numWk; ++w)
        {
            const WeekProfile& pw = weeks[w-1];
            SCDateTime b = weeks[w].StartDT, e = (w+1<numWk)? weeks[w+1].StartDT : weeks[w].EndDT + SCDateTime::DAYS(3);
            const int wln = 500000 + pw.WeekKey*10; s_UseTool t;
            t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=wln+1; t.BeginDateTime=b; t.EndDateTime=e;
            t.BeginValue=pw.High; t.EndValue=pw.High; t.Color=In_PWHLColor.GetColor(); t.LineWidth=lineWidth; t.LineStyle=LINESTYLE_DOT; t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="PW High"; sc.UseTool(t);
            t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=wln+2; t.BeginDateTime=b; t.EndDateTime=e;
            t.BeginValue=pw.Low; t.EndValue=pw.Low; t.Color=In_PWHLColor.GetColor(); t.LineWidth=lineWidth; t.LineStyle=LINESTYLE_DOT; t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="PW Low"; sc.UseTool(t);
            t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=wln+3; t.BeginDateTime=b; t.EndDateTime=e;
            t.BeginValue=pw.VPOC; t.EndValue=pw.VPOC; t.Color=In_WVPOCColor.GetColor(); t.LineWidth=lineWidth; t.LineStyle=LINESTYLE_DASHDOT; t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="Weekly VPOC"; sc.UseTool(t);
        }
    }

    // ---- Pass 3: IB + Fade/Follow + markers + alerts + HUD -----------------
    const bool drawMarkers=In_DrawMarkers.GetYesNo()!=0, drawIB=In_DrawIB.GetYesNo()!=0;
    const bool showTS=In_ShowTS.GetYesNo()!=0; const int tsCol=In_TSColor.GetColor(), tsFont=In_TSFontSize.GetInt(), tsOff=In_TSOffset.GetInt();
    const bool fadeAlertOn=In_FadeAlert.GetYesNo()!=0, followAlertOn=In_FollowAlert.GetYesNo()!=0, showHUD=In_ShowHUD.GetYesNo()!=0;
    const float edgePct = In_EdgeZonePct.GetFloat()/100.0f;
    int& fadeKey=sc.GetPersistentInt(2); int& followKey=sc.GetPersistentInt(3);
    int lastClosed = sc.ArraySize-1; if (lastClosed>0 && sc.GetBarHasClosedStatus(lastClosed)!=BHCS_BAR_HAS_CLOSED) lastClosed--;

    for (int j=1; j<total; ++j)
    {
        const SessionProfile& ref = sessions[j-1]; const SessionProfile& cur = sessions[j];
        if (j-1 < firstDraw) continue;
        const bool liveDay = (j == total-1);

        // Initial Balance
        bool ibValid=false; float ibHigh=0, ibLow=0; int ibLast=cur.StartIdx+ibBars-1;
        if (ibLast <= cur.EndIdx)
        {
            bool allClosed=true; ibHigh=sc.High[cur.StartIdx]; ibLow=sc.Low[cur.StartIdx];
            for (int b=cur.StartIdx; b<=ibLast; ++b){ if (sc.GetBarHasClosedStatus(b)!=BHCS_BAR_HAS_CLOSED){allClosed=false;break;} if(sc.High[b]>ibHigh)ibHigh=sc.High[b]; if(sc.Low[b]<ibLow)ibLow=sc.Low[b]; }
            ibValid=allClosed;
        }
        bool extUp=false, extDn=false;
        if (ibValid) for (int b=ibLast+1; b<=cur.EndIdx; ++b){ if(sc.High[b]>ibHigh)extUp=true; if(sc.Low[b]<ibLow)extDn=true; }
        if (drawIB && ibValid)
        {
            const int iln=400000+cur.DateYMD*10; SCDateTime ibBegin=sc.BaseDateTimeIn[cur.StartIdx];
            SCDateTime ibEnd=(j+1<total)? cur.EndDT : cur.EndDT + SCDateTime::HOURS(2); s_UseTool ib;
            ib.Clear(); ib.ChartNumber=sc.ChartNumber; ib.DrawingType=DRAWING_LINE; ib.LineNumber=iln+1; ib.BeginDateTime=ibBegin; ib.EndDateTime=ibEnd;
            ib.BeginValue=ibHigh; ib.EndValue=ibHigh; ib.Color=In_IBColor.GetColor(); ib.LineWidth=1; ib.LineStyle=LINESTYLE_DASH; ib.AddMethod=UTAM_ADD_OR_ADJUST; ib.ShowPrice=showLabels?1:0; if(showLabels)ib.Text="IB High"; sc.UseTool(ib);
            ib.Clear(); ib.ChartNumber=sc.ChartNumber; ib.DrawingType=DRAWING_LINE; ib.LineNumber=iln+2; ib.BeginDateTime=ibBegin; ib.EndDateTime=ibEnd;
            ib.BeginValue=ibLow; ib.EndValue=ibLow; ib.Color=In_IBColor.GetColor(); ib.LineWidth=1; ib.LineStyle=LINESTYLE_DASH; ib.AddMethod=UTAM_ADD_OR_ADJUST; ib.ShowPrice=showLabels?1:0; if(showLabels)ib.Text="IB Low"; sc.UseTool(ib);
        }

        // open location + outside-gate (mode dependent)
        const float openP=sc.Open[cur.StartIdx];
        const bool openedAbove=openP>ref.VAH, openedBelow=openP<ref.VAL;
        bool outAbove, outBelow;
        if (gateMode==0) { outAbove=openedAbove; outBelow=openedBelow; }                 // strict: first bar opened outside
        else             { outAbove = ibValid && (ibHigh>ref.VAH); outBelow = ibValid && (ibLow<ref.VAL); } // loose: traded outside during IB
        const bool fadeArmed = outAbove || outBelow;
        const bool fadeShort = outAbove;   // if both touched, default to short side
        const int  fadeFromBar = (gateMode==0) ? cur.StartIdx : (ibLast+1); // loose: acceptance must come after IB

        int cIn=0,cAb=0,cBe=0, fadeBar=-1, folAbove=-1, folBelow=-1;
        for (int b=cur.StartIdx; b<=cur.EndIdx; ++b)
        {
            if (sc.GetBarHasClosedStatus(b)!=BHCS_BAR_HAS_CLOSED) break;
            const float c=sc.Close[b]; const bool ab=c>ref.VAH, be=c<ref.VAL, in=!ab&&!be;
            cIn=in?cIn+1:0; cAb=ab?cAb+1:0; cBe=be?cBe+1:0;
            if (fadeBar<0 && fadeArmed && b>=fadeFromBar && cIn>=acceptN) fadeBar=b;
            if (folAbove<0 && cAb>=acceptN) folAbove=b;
            if (folBelow<0 && cBe>=acceptN) folBelow=b;
        }

        // markers
        if (drawMarkers && fadeBar>=0)
        { const bool sh=fadeShort; s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=200000+cur.DateYMD*10;
          m.BeginDateTime=sc.BaseDateTimeIn[fadeBar]; m.BeginValue=sc.Close[fadeBar]; m.Color=sh?In_VALColor.GetColor():In_VAHColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("%s\n%.2f", sh?"FADE SHORT v":"FADE LONG ^", sc.Close[fadeBar]); sc.UseTool(m);
          if (showTS) DrawSignalTime(sc, 600000+cur.DateYMD*10, fadeBar, sh?ref.VAH:ref.VAL, !sh, tsCol, tsFont, tsOff); }
        if (drawMarkers && folAbove>=0)
        { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=210000+cur.DateYMD*10; m.BeginDateTime=sc.BaseDateTimeIn[folAbove]; m.BeginValue=sc.Close[folAbove]; m.Color=In_VAHColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("FOLLOW\nLONG ^^\n%.2f", sc.Close[folAbove]); sc.UseTool(m);
          if (showTS) DrawSignalTime(sc, 610000+cur.DateYMD*10, folAbove, sc.Close[folAbove], true, tsCol, tsFont, tsOff); }
        if (drawMarkers && folBelow>=0)
        { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=220000+cur.DateYMD*10; m.BeginDateTime=sc.BaseDateTimeIn[folBelow]; m.BeginValue=sc.Close[folBelow]; m.Color=In_VALColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("FOLLOW\nSHORT vv\n%.2f", sc.Close[folBelow]); sc.UseTool(m);
          if (showTS) DrawSignalTime(sc, 620000+cur.DateYMD*10, folBelow, sc.Close[folBelow], false, tsCol, tsFont, tsOff); }

        // trade-management guide lines (entry/stop/target/trail) - live day only
        if (In_GuidesEnable.GetYesNo() && j==total-1 && atrDaily>0)
        {
            const bool tr=In_GuidesTrail.GetYesNo()!=0;
            const int cE=In_GuideEntryColor.GetColor(), cS=In_GuideStopColor.GetColor(), cT=In_GuideTgtColor.GetColor();
            const float buf=(0.08f*atrDaily>8*sc.TickSize)?0.08f*atrDaily:8*sc.TickSize;
            const float mm=(ibValid?(ibHigh-ibLow):0.0f);
            if (fadeBar>=0)
            { int dir=fadeShort?-1:1; float e=fadeShort?ref.VAH:ref.VAL; float st=fadeShort?ref.VAH+buf:ref.VAL-buf;
              DrawGuides(sc,960000,fadeBar,lastClosed,farRight,e,st,ref.POC,dir,atrDaily,tr,cE,cS,cT, fadeShort?"FADE S":"FADE L"); }
            if (folAbove>=0)
            { float e=sc.Close[folAbove]; float tg=ibValid?ibHigh+mm:e+(e-ref.VAH);
              DrawGuides(sc,960010,folAbove,lastClosed,farRight,e,ref.VAH,tg,1,atrDaily,tr,cE,cS,cT,"FOLLOW L"); }
            if (folBelow>=0)
            { float e=sc.Close[folBelow]; float tg=ibValid?ibLow-mm:e-(ref.VAL-e);
              DrawGuides(sc,960020,folBelow,lastClosed,farRight,e,ref.VAL,tg,-1,atrDaily,tr,cE,cS,cT,"FOLLOW S"); }
        }

        // alerts (live, fresh, once/day)
        if (liveDay && !sc.IsFullRecalculation && newBar && lastClosed>=0)
        {
            if (fadeAlertOn && fadeBar>=lastClosed-1 && fadeBar>=0 && fadeKey!=cur.DateYMD)
            { fadeKey=cur.DateYMD; SCString m; m.Format("FADE (80%% Rule) %s: %d periods back inside value. Target %.2f | Invalidation %.2f",
                fadeShort?"SHORT":"LONG", acceptN, fadeShort?ref.VAL:ref.VAH, fadeShort?ref.VAH:ref.VAL); sc.AddMessageToLog(m,1); sc.SetAlert(0,m);
                if(In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sc.BaseDateTimeIn[fadeBar], m.GetChars());
              if (In_NtfyEnable.GetYesNo() && strlen(In_NtfyURL.GetString())>16)
              { SCString nb; nb.Format("%s  %s", sc.Symbol.GetChars(), m.GetChars()); sc.MakeHTTPPOSTRequest(In_NtfyURL.GetString(), nb, NULL, 0); } }
            int fb=-1; bool fLong=false;
            if (folAbove>=0){ fb=folAbove; fLong=true; }
            if (folBelow>=0 && (fb<0 || folBelow<fb)){ fb=folBelow; fLong=false; }
            if (followAlertOn && fb>=lastClosed-1 && fb>=0 && followKey!=cur.DateYMD)
            { followKey=cur.DateYMD; SCString m; m.Format("FOLLOW (Breakout) %s: %d periods accepted %s value. Trade with move; invalidation back inside %.2f",
                fLong?"LONG":"SHORT", acceptN, fLong?"ABOVE":"BELOW", fLong?ref.VAH:ref.VAL); sc.AddMessageToLog(m,1); sc.SetAlert(0,m);
                if(In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sc.BaseDateTimeIn[fb], m.GetChars());
              if (In_NtfyEnable.GetYesNo() && strlen(In_NtfyURL.GetString())>16)
              { SCString nb; nb.Format("%s  %s", sc.Symbol.GetChars(), m.GetChars()); sc.MakeHTTPPOSTRequest(In_NtfyURL.GetString(), nb, NULL, 0); } }
        }

        // HUD (live day)
        if (showHUD && liveDay)
        {
            int ab=0, be=0, in=0, counted=0;
            for (int b=lastClosed; b>=cur.StartIdx && counted<acceptN; --b, ++counted)
            { const float c=sc.Close[b]; if(c>ref.VAH)ab++; else if(c<ref.VAL)be++; else in++; }
            int vcode; const char* stateStr; const char* verdict;
            if (counted>=acceptN && ab==acceptN){ vcode=4; stateStr="ACCEPTED ABOVE VAH"; verdict="=> FOLLOW LONG (tgt prior high)"; }
            else if (counted>=acceptN && be==acceptN){ vcode=5; stateStr="ACCEPTED BELOW VAL"; verdict="=> FOLLOW SHORT (tgt prior low)"; }
            else if (counted>=acceptN && in==acceptN && fadeArmed){ vcode=fadeShort?2:3; stateStr="BACK INSIDE VALUE"; verdict=fadeShort?"=> FADE SHORT -> PD VAL":"=> FADE LONG -> PD VAH"; }
            else if (in>0 && !fadeArmed){ vcode=1; stateStr="INSIDE VALUE"; verdict="=> ROTATIONAL (fade edges to POC)"; }
            else { vcode=0; stateStr="FORMING / MIXED"; verdict="=> WAIT (no acceptance yet)"; }
            const char* openStr = openedAbove?"ABOVE value":openedBelow?"BELOW value":"INSIDE value";

            // weekly classification + gate
            const float px = sc.Close[lastClosed];
            const char* wkStr="weekly n/a"; const char* gate="";
            int wloc=0; // -2 below range,-1 edge low,0 balance,1 edge high,2 above range
            if (weeklyValid && PWH>PWL)
            {
                float band=(PWH-PWL)*edgePct;
                if (px>PWH) wloc=2; else if (px<PWL) wloc=-2;
                else if (px>=PWH-band) wloc=1; else if (px<=PWL+band) wloc=-1; else wloc=0;
                wkStr = wloc==2?"OUTSIDE prior-wk range (above)": wloc==-2?"OUTSIDE prior-wk range (below)":
                        wloc==1?"AT WEEKLY EDGE (high)": wloc==-1?"AT WEEKLY EDGE (low)":"INSIDE weekly balance";
                // gate verdict
                if (vcode==2) gate = (wloc==2)?"GATE: CONFLICT - fading into weekly breakout":(wloc==0||wloc==1)?"GATE: OK - reversion inside weekly":"GATE: ok";
                else if (vcode==3) gate = (wloc==-2)?"GATE: CONFLICT - fading into weekly breakdown":(wloc==0||wloc==-1)?"GATE: OK - reversion inside weekly":"GATE: ok";
                else if (vcode==4) gate = (wloc>=1)?"GATE: CONFIRMED - aligned w/ weekly breakout":"GATE: weak - breakout vs weekly position";
                else if (vcode==5) gate = (wloc<=-1)?"GATE: CONFIRMED - aligned w/ weekly breakdown":"GATE: weak - breakdown vs weekly position";
                else if (vcode==1) gate = (wloc==0)?"GATE: clean rotation (mid weekly range)":"GATE: rotation near weekly edge - watch for break";
                else gate = "GATE: wait";
            }

            // ---- Phase 1: gap-vs-ATR, opening type, value migration ----
            float atr=0.0f;                              // 14-day daily-based ATR
            { int L=In_ATRlen.GetInt(); double tsum=0; int tn=0;
              for (int k=(j-L>1?j-L:1); k<=j-1; ++k){
                  const SessionProfile& sk=sessions[k]; const SessionProfile& pk=sessions[k-1];
                  float tr=sk.High-sk.Low;
                  float d2=sk.High-pk.Close; if(d2<0)d2=-d2; if(d2>tr)tr=d2;
                  float d3=sk.Low -pk.Close; if(d3<0)d3=-d3; if(d3>tr)tr=d3;
                  tsum+=tr; tn++;
              }
              if (tn>0) atr=(float)(tsum/tn);
            }

            const float gapPts = openP - ref.Close;      // gap classification
            float gapAbs = gapPts<0?-gapPts:gapPts;
            const float gapX = atr>0?gapAbs/atr:0.0f;
            const float largeX = In_GapLargeX.GetFloat();
            const bool openOutRange = (openP>ref.High || openP<ref.Low);
            const char* gapClass = atr<=0?"n/a":(gapX>=largeX?"LARGE":gapX>=0.5f*largeX?"MED":gapX>=0.15f?"SMALL":"FLAT");
            const bool gapLargeOut = (atr>0 && gapX>=largeX && openOutRange);
            bool fadeSuppress=false, fadeFavor=false; int gapVote=0;
            if (In_GapEnable.GetYesNo() && atr>0){
                if (gapLargeOut){ fadeSuppress=true; gapVote = gapPts>0?2:-2; }
                else if (gapX < 0.5f*largeX){ fadeFavor=true; }
            }

            const char* otype="forming"; int otVote=0;   // opening type (Dalton)
            { const int K=In_OpenTypeBars.GetInt(); const int olast=cur.StartIdx+K-1;
              if (olast<=cur.EndIdx){
                  bool ok=true; float hi=sc.High[cur.StartIdx], lo=sc.Low[cur.StartIdx];
                  for (int b=cur.StartIdx;b<=olast;++b){ if(sc.GetBarHasClosedStatus(b)!=BHCS_BAR_HAS_CLOSED){ok=false;break;} if(sc.High[b]>hi)hi=sc.High[b]; if(sc.Low[b]<lo)lo=sc.Low[b]; }
                  if (ok){
                      const float o=openP, c=sc.Close[olast], up=hi-o, dn=o-lo;
                      const float thr = atr>0?0.15f*atr:sc.TickSize*8;
                      if (up>thr && dn<=thr){ otype="DRIVE UP"; otVote=2; }
                      else if (dn>thr && up<=thr){ otype="DRIVE DOWN"; otVote=-2; }
                      else if (up>thr && dn>thr){
                          if (c>o+thr){ otype="REJ-REVERSE up"; otVote=1; }
                          else if (c<o-thr){ otype="REJ-REVERSE dn"; otVote=-1; }
                          else otype="AUCTION (low conf)";
                      } else otype="AUCTION (low conf)";
                  }
              }
            }

            const char* valMig="n/a"; int vmVote=0;       // value migration
            if (j>=2 && sessions[j-2].Valid){
                const SessionProfile& r2=sessions[j-2];
                if (ref.VAL>r2.VAH){ valMig="higher (separated)"; vmVote=1; }
                else if (ref.VAH<r2.VAL){ valMig="lower (separated)"; vmVote=-1; }
                else if (ref.VAH<=r2.VAH && ref.VAL>=r2.VAL){ valMig="inside (balance)"; vmVote=0; }
                else if (ref.POC>r2.POC){ valMig="overlap-higher"; vmVote=1; }
                else if (ref.POC<r2.POC){ valMig="overlap-lower"; vmVote=-1; }
                else valMig="unchanged";
            }

            // ---- Day-type scoring engine (5-level configuration) ----
            int score=0; const char* dayType="forming"; const char* ibPlay="forming";
            if (ibValid)
            {
                const float ibRange = ibHigh - ibLow;
                double rsum=0; int rn=0;                    // rolling avg IB range (<=20 prior days)
                for (int k=(j-20>0?j-20:0); k<j; ++k){
                    const SessionProfile& sk=sessions[k]; int kl=sk.StartIdx+ibBars-1;
                    if (kl>sk.EndIdx) continue;
                    float kh=sc.High[sk.StartIdx], klo=sc.Low[sk.StartIdx];
                    for (int b=sk.StartIdx;b<=kl;++b){ if(sc.High[b]>kh)kh=sc.High[b]; if(sc.Low[b]<klo)klo=sc.Low[b]; }
                    rsum+=(kh-klo); rn++;
                }
                float avgIB = rn>0?(float)(rsum/rn):0.0f;

                bool aboveV=ibLow>ref.VAH, belowV=ibHigh<ref.VAL;
                bool insideV=(ibHigh<ref.VAH && ibLow>ref.VAL), engulfV=(ibHigh>ref.VAH && ibLow<ref.VAL);
                bool stradVAH=(ibLow<ref.VAH && ibHigh>ref.VAH && !engulfV);
                bool stradVAL=(ibLow<ref.VAL && ibHigh>ref.VAL && !engulfV);
                if (aboveV) score+=3; else if (belowV) score-=3;
                else if (stradVAH) score+=1; else if (stradVAL) score-=1;

                if (In_ScPOC.GetYesNo()){ if(ref.POC>ibHigh) score+=1; else if(ref.POC<ibLow) score-=1; }
                if (In_ScOpen.GetYesNo()){ if(openedAbove) score+=1; else if(openedBelow) score-=1; }
                const int ibLastB=(cur.StartIdx+ibBars-1<=cur.EndIdx)?(cur.StartIdx+ibBars-1):cur.EndIdx;
                const float ibClose=sc.Close[ibLastB];   // freeze HTF vote at IB completion (structural score stops drifting)
                if (In_ScHTF.GetYesNo() && weeklyValid){ if(ibClose>WVPOC) score+=1; else if(ibClose<WVPOC) score-=1; }
                if (In_ScWidth.GetYesNo() && avgIB>0){
                    if (ibRange < 0.8f*avgIB){ if(score>0) score+=1; else if(score<0) score-=1; }
                    else if (ibRange > 1.5f*avgIB){ if(score>0) score-=1; else if(score<0) score+=1; }
                }
                if (In_GapEnable.GetYesNo())    score += gapVote;
                if (In_OpenTypeEnable.GetYesNo()) score += otVote;
                if (In_ValMigEnable.GetYesNo()) score += vmVote;

                if (insideV) dayType="NO-EDGE (inside value)";
                else if (engulfV) dayType="TWO-SIDED (engulfs value)";
                else if (score>=2) dayType="TREND-UP";
                else if (score<=-2) dayType="TREND-DOWN";
                else dayType="ROTATION";

                if (insideV||engulfV) ibPlay="FADE to IB mid (range)";
                else if (score>=2) ibPlay="BREAKOUT LONG -> ext";
                else if (score<=-2) ibPlay="BREAKDOWN SHORT -> ext";
                else ibPlay="FADE to IB mid (range)";
            }
            const char* conv = (score>=4||score<=-4)?"HIGH":(score>=2||score<=-2)?"MOD":"LOW";
            const char* rulePlay = verdict + 3;            // strip leading "=> "

            // ---- REV (Rejection/Reversal) live read for the HUD ----
            SCString revLine="REV: none", revPlayStr="none"; int revLiveDir=0;
            if (In_RevEnable.GetYesNo() && curPDidx>=0)
            {
                const int lcsec=sc.BaseDateTimeIn[lastClosed].GetTimeInSeconds();
                const bool revOK = !In_RevUSonly.GetYesNo() || (lcsec>=In_SessionStart.GetTime() && lcsec<In_SessionEnd.GetTime());
                if (revOK) {
                const bool momF=In_RevMomFilter.GetYesNo()!=0;
                float dial=RevDial(sc.BaseDateTimeIn[lastClosed].GetTimeInSeconds(),
                                   In_SessionStart.GetTime(), In_SessionEnd.GetTime(), In_UKStart.GetTime(), In_UKEnd.GetTime(),
                                   In_AsiaStart.GetTime(), In_AsiaEnd.GetTime(),
                                   In_RevDialUS.GetFloat(), In_RevDialUK.GetFloat(), In_RevDialAsia.GetFloat());
                const int Wr=(int)(In_RevWindow.GetInt()*dial+0.5f), mT=(int)(In_RevMinTouch.GetInt()*dial+0.5f),
                          mR=(int)(In_RevMinRej.GetInt()*dial+0.5f); int cfb=(int)(In_RevConfirmBars.GetInt()*dial+0.5f); if(cfb<1)cfb=1;
                const float tolr=(In_RevATRNorm.GetYesNo() && atrDaily>0)? 0.1f*atrDaily : In_RevTolTicks.GetInt()*sc.TickSize;
                const SessionProfile& A=sessions[curPDidx];
                const float Lv[3]={A.POC,A.VAH,A.VAL}; const char* Ln[3]={"PD POC","PD VAH","PD VAL"};
                int bDir=0,bSc=0,bI=-1;
                const bool gV=In_RevVWAPGate.GetYesNo()!=0, gS=In_RevSpaceGate.GetYesNo()!=0;
                const float minSpaceL = (In_RevSpaceATR.GetFloat()*atrDaily<In_RevSpacePts.GetFloat() && atrDaily>0)? In_RevSpaceATR.GetFloat()*atrDaily : In_RevSpacePts.GetFloat();
                const float wallsL[4]={A.POC,A.VAH,A.VAL,(weeklyValid?WVPOC:0.0f)};
                const float vwapL=(lastClosed<(int)vwapArr.size())?vwapArr[lastClosed]:0.0f;
                for(int i=0;i<3;++i){ int s2; int d=DetectRej(sc,lastClosed,Wr,Lv[i],tolr,mT,mR,cfb,momF,s2);
                    if(d!=0 && !RevGatePass(d,sc.Close[lastClosed],vwapL,minSpaceL,wallsL,4,gV,gS)) d=0;
                    if(d!=0&&s2>bSc){bSc=s2;bDir=d;bI=i;} }
                int wI=-1,wT=0,wRup=0,wRdn=0; const int w0=(lastClosed-Wr+1>0)?lastClosed-Wr+1:0;
                for(int i=0;i<3;++i){ float L=Lv[i]; if(L<=0)continue; int t=0,ru=0,rd=0;
                    for(int b=w0;b<=lastClosed;++b){ float hi=sc.High[b],lo=sc.Low[b],c=sc.Close[b];
                        if(lo<=L+tolr&&hi>=L-tolr)t++; if(hi>L&&c<L)ru++; if(lo<L&&c>L)rd++; }
                    if(t>wT){wT=t;wI=i;wRup=ru;wRdn=rd;} }
                if(bDir!=0){
                    revLiveDir=bDir;
                    revPlayStr.Format("%s (reject %s) -> next ref %s", bDir<0?"REV SHORT":"REV LONG", Ln[bI], bDir<0?"down":"up");
                    revLine.Format("REV: FIRED %s @%s", bDir<0?"SHORT":"LONG", Ln[bI]);
                } else if(wI>=0 && wT>0){
                    revLine.Format("REV: watching %s (%dt %du/%dd rej)", Ln[wI], wT, wRup, wRdn);
                    revPlayStr="none (watch break-back)";
                }
                }
            }

            // ---- Signal-agreement engine: confluence overrides day-type ----
            // When 2+ live signals point the same way, that agreement drives the
            // conviction (a messy day-type no longer vetoes aligned signals).
            int fadeDir=(fadeBar>=0)?(fadeShort?-1:1):0;
            int folDir=0; if(folAbove>=0) folDir=1; if(folBelow>=0 && (folAbove<0||folBelow>folAbove)) folDir=-1;
            int revDir=revLiveDir;
            int dirs[3]={fadeDir,folDir,revDir};
            int pos=0,neg=0; for(int i=0;i<3;++i){ if(dirs[i]>0)pos++; else if(dirs[i]<0)neg++; }
            int active=pos+neg, netSign=(pos>neg)?1:(neg>pos)?-1:0, aligned=(netSign>0)?pos:(netSign<0)?neg:0;
            bool conflict=(pos>0 && neg>0);
            SCString agree; const char* convFinal=conv;
            if (active==0) agree.Format("AGREE: no live signals (day-type only)");
            else if (conflict){ agree.Format("AGREE: CONFLICT (%dL/%dS) - stand aside", pos, neg); convFinal="CONFLICT"; }
            else if (aligned>=2){
                bool dtOpp=(score>=2 && netSign<0)||(score<=-2 && netSign>0);
                agree.Format("AGREE: %d aligned %s%s", aligned, netSign>0?"LONG":"SHORT", dtOpp?" (vs day-type!)":" -> CONFLUENCE");
                convFinal=dtOpp?"MOD":"HIGH";
            } else agree.Format("AGREE: 1 %s signal (needs confirm)", netSign>0?"LONG":"SHORT");

            // daily Playbook-HUD snapshot to log (once per day when score finalizes)
            if (In_LogEnable.GetYesNo() && ibValid && !sc.IsFullRecalculation && newBar)
            {
                int& dlk=sc.GetPersistentInt(8);
                if (dlk!=cur.DateYMD){
                    dlk=cur.DateYMD;
                    SCString dl; dl.Format("%04d-%02d-%02d | %s | score=%+d | conv=%s | %s | ib=%s | 80%%=%s | rev=%s | gap=%s | open=%s | val=%s",
                        (cur.DateYMD/10000)+2000, (cur.DateYMD/100)%100, cur.DateYMD%100,
                        dayType, score, convFinal, agree.GetChars(), ibPlay, rulePlay, revPlayStr.GetChars(), gapClass, otype, valMig);
                    LogDaily(In_LogFile.GetString(), dl.GetChars());
                }
            }
            // end-of-day outcome to log (once, on the last RTH bar) for score-vs-RR study
            if (In_LogEnable.GetYesNo() && !sc.IsFullRecalculation && newBar)
            {
                const int lcsec=sc.BaseDateTimeIn[lastClosed].GetTimeInSeconds();
                if (lcsec + (int)(barMin*60) >= sessEndSec)   // last RTH bar of the day
                {
                    int& eok=sc.GetPersistentInt(11);
                    if (eok!=cur.DateYMD){
                        eok=cur.DateYMD;
                        float dh=sc.High[cur.StartIdx], dl2=sc.Low[cur.StartIdx];
                        for (int b=cur.StartIdx;b<=lastClosed;++b){ if(sc.High[b]>dh)dh=sc.High[b]; if(sc.Low[b]<dl2)dl2=sc.Low[b]; }
                        const float clc=sc.Close[lastClosed];
                        const char* brk = ibValid?(clc>ibHigh?"BREAKOUT-UP":clc<ibLow?"BREAKDOWN":"INSIDE-IB"):"n/a";
                        const float ibR=ibValid?(ibHigh-ibLow):0.0f;
                        const char* ext = (ibValid && ibR>0)?((dh>=ibHigh+ibR)?"ext-UP":(dl2<=ibLow-ibR)?"ext-DN":"no-ext"):"n/a";
                        SCString el; el.Format("%04d-%02d-%02d | struct=%+d | %s | dayRange=%.0f | close=%.2f | %s | %s",
                            (cur.DateYMD/10000)+2000,(cur.DateYMD/100)%100,cur.DateYMD%100,
                            score, dayType, dh-dl2, clc, brk, ext);
                        LogEOD(In_LogFile.GetString(), el.GetChars());
                    }
                }
            }

            SCString hud, line;
            hud.Append("===== PLAYBOOK =====\n");
            line.Format("DAY: %s | STRUCT(@IB): %+d\n", dayType, score); hud.Append(line.GetChars());
            line.Format("LIVE: %s | CONV: %s\n", agree.GetChars(), convFinal); hud.Append(line.GetChars());
            line.Format("IB  PLAY: %s\n", ibPlay); hud.Append(line.GetChars());
            line.Format("80%% PLAY: %s\n", rulePlay); hud.Append(line.GetChars());
            if (In_RevEnable.GetYesNo()){ line.Format("REV PLAY: %s\n", revPlayStr.GetChars()); hud.Append(line.GetChars()); }
            if (In_GuidesEnable.GetYesNo()) hud.Append("GUIDES: yel=entry red=stop grn=tgt grn-dash=trail\n");
            hud.Append("--------------------\n");
            line.Format("Open %s | IB %.0f-%.0f%s\n", openStr, ibHigh, ibLow,
                        !ibValid?" (forming)":extUp?" extUP":extDn?" extDN":""); hud.Append(line.GetChars());
            line.Format("PD VA %.2f / %.2f / %.2f\n", ref.VAH, ref.POC, ref.VAL); hud.Append(line.GetChars());
            line.Format("State %s\n", stateStr); hud.Append(line.GetChars());
            if (weeklyValid){ line.Format("HTF %s\n", wkStr); hud.Append(line.GetChars()); hud.Append(gate); }
            else hud.Append("HTF need 2+ weeks of data");
            if (In_GapEnable.GetYesNo())
            { line.Format("\nGAP: %s %.2fxATR %s%s", gapClass, gapX, openOutRange?"out-range":"in-range",
                          fadeSuppress?" -> fade LOW, breakout":fadeFavor?" -> fade OK":""); hud.Append(line.GetChars()); }
            if (In_OpenTypeEnable.GetYesNo())
            { line.Format("\nOPEN-TYPE: %s", otype); hud.Append(line.GetChars()); }
            if (In_ValMigEnable.GetYesNo())
            { line.Format("\nVALUE: %s", valMig); hud.Append(line.GetChars()); }
            if (In_RevEnable.GetYesNo())
            { line.Format("\n%s", revLine.GetChars()); hud.Append(line.GetChars()); }

            // Fixed-on-screen HUD: stays pinned to the chart window when scrolling.
            // Signature: (sc, DisplayInFillSpace, HorizontalPosition, VerticalPosition,
            //             Subgraph, TransparentLabelBackground, TextToDisplay, DrawAboveMainPriceGraph, BoldFont)
            Sub_HUD.PrimaryColor = In_HUDColor.GetColor(); Sub_HUD.LineWidth = In_HUDFontSize.GetInt();
            sc.AddAndManageSingleTextDrawingForStudy(sc, 0, In_HUDHoriz.GetInt(), In_HUDVert.GetInt(),
                                                     Sub_HUD, In_HUDTransp.GetYesNo(), hud, 1, 1);
        }
    }

    // ---- Pass 3c: FOLLOW signals during the UK / pre-NY session ------------
    // Scans the UK-session window against the most recent prior NY value area,
    // so acceptance beyond PD VAH/VAL triggers FOLLOW during London hours too.
    if (In_UKSignals.GetYesNo())
    {
        const int ukStartSec = In_UKStart.GetTime();
        const int ukEndSec   = In_UKEnd.GetTime();
        int& ukFollowKey = sc.GetPersistentInt(4);

        // group UK-window bars by day
        std::vector<DayRange> ukDays; int k=-1; DayRange dr;
        for (int i=0; i<sc.ArraySize; ++i)
        {
            const SCDateTime bdt = sc.BaseDateTimeIn[i];
            int secs = bdt.GetTimeInSeconds();
            if (secs < ukStartSec || secs >= ukEndSec) continue;
            int d = (bdt.GetYear()-2000)*10000 + bdt.GetMonth()*100 + bdt.GetDay();
            if (d != k){ if (k != -1) ukDays.push_back(dr); k=d; dr.DateYMD=d; dr.StartIdx=i; }
            dr.EndIdx=i;
        }
        if (k != -1) ukDays.push_back(dr);

        for (size_t u=0; u<ukDays.size(); ++u)
        {
            const DayRange& d = ukDays[u];
            // reference = most recent NY session strictly before this UK day
            int refIdx=-1;
            for (int s=0; s<total; ++s){ if (sessions[s].DateYMD < d.DateYMD) refIdx=s; else break; }
            if (refIdx < 0) continue;
            const SessionProfile& ref = sessions[refIdx];

            int cAb=0, cBe=0, folAbove=-1, folBelow=-1;
            for (int b=d.StartIdx; b<=d.EndIdx; ++b)
            {
                if (sc.GetBarHasClosedStatus(b) != BHCS_BAR_HAS_CLOSED) break;
                const float c=sc.Close[b]; const bool ab=c>ref.VAH, be=c<ref.VAL;
                cAb=ab?cAb+1:0; cBe=be?cBe+1:0;
                if (folAbove<0 && cAb>=acceptN_UK) folAbove=b;
                if (folBelow<0 && cBe>=acceptN_UK) folBelow=b;
            }

            if (drawMarkers && folAbove>=0)
            { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=230000+d.DateYMD*10;
              m.BeginDateTime=sc.BaseDateTimeIn[folAbove]; m.BeginValue=sc.Close[folAbove]; m.Color=In_VAHColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("FOLLOW LONG ^\nUK\n%.2f", sc.Close[folAbove]); sc.UseTool(m);
              if (showTS) DrawSignalTime(sc, 630000+d.DateYMD*10, folAbove, sc.Close[folAbove], true, tsCol, tsFont, tsOff); }
            if (drawMarkers && folBelow>=0)
            { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=240000+d.DateYMD*10;
              m.BeginDateTime=sc.BaseDateTimeIn[folBelow]; m.BeginValue=sc.Close[folBelow]; m.Color=In_VALColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("FOLLOW SHORT v\nUK\n%.2f", sc.Close[folBelow]); sc.UseTool(m);
              if (showTS) DrawSignalTime(sc, 640000+d.DateYMD*10, folBelow, sc.Close[folBelow], false, tsCol, tsFont, tsOff); }

            const bool liveUK = (u == ukDays.size()-1);
            if (followAlertOn && liveUK && !sc.IsFullRecalculation && newBar && lastClosed>=0)
            {
                int fb=-1; bool fLong=false;
                if (folAbove>=0){ fb=folAbove; fLong=true; }
                if (folBelow>=0 && (fb<0 || folBelow<fb)){ fb=folBelow; fLong=false; }
                if (fb>=lastClosed-1 && fb>=0 && ukFollowKey!=d.DateYMD)
                {
                    ukFollowKey=d.DateYMD;
                    SCString m; m.Format("FOLLOW (UK session) %s: %d periods accepted %s prior-day value at %.2f",
                        fLong?"LONG":"SHORT", acceptN_UK, fLong?"ABOVE":"BELOW", fLong?ref.VAH:ref.VAL);
                    sc.AddMessageToLog(m,1); sc.SetAlert(0,m);
                    if(In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sc.BaseDateTimeIn[fb], m.GetChars());
                    if (In_NtfyEnable.GetYesNo() && strlen(In_NtfyURL.GetString())>16)
                    { SCString nb; nb.Format("%s  %s", sc.Symbol.GetChars(), m.GetChars()); sc.MakeHTTPPOSTRequest(In_NtfyURL.GetString(), nb, NULL, 0); }
                }
            }
        }
    }

    // ---- Pass 3d: FOLLOW signals during the ASIA session ------------------
    // Asia crosses midnight in US Eastern time, so this handles a wrap-around
    // window (start > end). It references the most recent NY value area at or
    // before the session's evening date (the NY close that just happened).
    if (In_AsiaSignals.GetYesNo())
    {
        const int aStartSec = In_AsiaStart.GetTime();
        const int aEndSec   = In_AsiaEnd.GetTime();
        const bool wrap = (aStartSec > aEndSec);
        int& asiaFollowKey = sc.GetPersistentInt(5);

        std::vector<DayRange> aDays; int k=-1; DayRange dr;
        for (int i=0; i<sc.ArraySize; ++i)
        {
            const SCDateTime bdt = sc.BaseDateTimeIn[i];
            int secs = bdt.GetTimeInSeconds();
            bool inWin = wrap ? (secs>=aStartSec || secs<aEndSec) : (secs>=aStartSec && secs<aEndSec);
            if (!inWin) continue;
            // wrap tail (after midnight) belongs to the session that started the prior evening
            SCDateTime sdt = (wrap && secs<aEndSec) ? (bdt.GetDate()-SCDateTime::DAYS(1)) : bdt.GetDate();
            int dnum = (sdt.GetYear()-2000)*10000 + sdt.GetMonth()*100 + sdt.GetDay();
            if (dnum != k){ if (k != -1) aDays.push_back(dr); k=dnum; dr.DateYMD=dnum; dr.StartIdx=i; }
            dr.EndIdx=i;
        }
        if (k != -1) aDays.push_back(dr);

        for (size_t u=0; u<aDays.size(); ++u)
        {
            const DayRange& d = aDays[u];
            // reference = most recent NY session AT OR BEFORE the evening date
            int refIdx=-1;
            for (int s=0; s<total; ++s){ if (sessions[s].DateYMD <= d.DateYMD) refIdx=s; else break; }
            if (refIdx < 0) continue;
            const SessionProfile& ref = sessions[refIdx];

            int cAb=0, cBe=0, folAbove=-1, folBelow=-1;
            for (int b=d.StartIdx; b<=d.EndIdx; ++b)
            {
                if (sc.GetBarHasClosedStatus(b) != BHCS_BAR_HAS_CLOSED) break;
                const float c=sc.Close[b]; const bool ab=c>ref.VAH, be=c<ref.VAL;
                cAb=ab?cAb+1:0; cBe=be?cBe+1:0;
                if (folAbove<0 && cAb>=acceptN_Asia) folAbove=b;
                if (folBelow<0 && cBe>=acceptN_Asia) folBelow=b;
            }

            if (drawMarkers && folAbove>=0)
            { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=250000+d.DateYMD*10;
              m.BeginDateTime=sc.BaseDateTimeIn[folAbove]; m.BeginValue=sc.Close[folAbove]; m.Color=In_VAHColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("FOLLOW LONG ^\nASIA\n%.2f", sc.Close[folAbove]); sc.UseTool(m);
              if (showTS) DrawSignalTime(sc, 650000+d.DateYMD*10, folAbove, sc.Close[folAbove], true, tsCol, tsFont, tsOff); }
            if (drawMarkers && folBelow>=0)
            { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=260000+d.DateYMD*10;
              m.BeginDateTime=sc.BaseDateTimeIn[folBelow]; m.BeginValue=sc.Close[folBelow]; m.Color=In_VALColor.GetColor(); m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("FOLLOW SHORT v\nASIA\n%.2f", sc.Close[folBelow]); sc.UseTool(m);
              if (showTS) DrawSignalTime(sc, 660000+d.DateYMD*10, folBelow, sc.Close[folBelow], false, tsCol, tsFont, tsOff); }

            const bool liveAsia = (u == aDays.size()-1);
            if (followAlertOn && liveAsia && !sc.IsFullRecalculation && newBar && lastClosed>=0)
            {
                int fb=-1; bool fLong=false;
                if (folAbove>=0){ fb=folAbove; fLong=true; }
                if (folBelow>=0 && (fb<0 || folBelow<fb)){ fb=folBelow; fLong=false; }
                if (fb>=lastClosed-1 && fb>=0 && asiaFollowKey!=d.DateYMD)
                {
                    asiaFollowKey=d.DateYMD;
                    SCString m; m.Format("FOLLOW (Asia session) %s: %d periods accepted %s prior-day value at %.2f",
                        fLong?"LONG":"SHORT", acceptN_Asia, fLong?"ABOVE":"BELOW", fLong?ref.VAH:ref.VAL);
                    sc.AddMessageToLog(m,1); sc.SetAlert(0,m);
                    if(In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sc.BaseDateTimeIn[fb], m.GetChars());
                    if (In_NtfyEnable.GetYesNo() && strlen(In_NtfyURL.GetString())>16)
                    { SCString nb; nb.Format("%s  %s", sc.Symbol.GetChars(), m.GetChars()); sc.MakeHTTPPOSTRequest(In_NtfyURL.GetString(), nb, NULL, 0); }
                }
            }
        }
    }

    // ---- Pass 3e: IVB (Initial Volume Breakout / Initial Balance Drift) ----
    // First CLOSE beyond today's opening-range high/low, in the break direction,
    // gated by volume expansion, day-type (IB width), skew strictness, and an
    // optional higher-timeframe alignment filter. Draws the 100% extension and
    // IB-midpoint targets. US/RTH only (IB is an RTH construct).
    if (In_IVBEnable.GetYesNo() && total >= 1)
    {
        const int ivbIdx = In_IVBMin.GetIndex();
        const int ivbMin = (ivbIdx==0?30: ivbIdx==1?45: 60);
        int ivbBars = (barMin > 0.0) ? (int)((ivbMin / barMin) + 0.5) : 2; if (ivbBars < 1) ivbBars = 1;
        const bool useVol = In_IVBUseVol.GetYesNo()!=0;
        const float volMult = In_IVBVolMult.GetFloat();
        const int skewMode = In_IVBSkewMode.GetIndex();            // 0 both, 1 favor longs, 2 long only
        const float shortPen = In_IVBShortPen.GetFloat();
        const bool widthFilter = In_IVBWidthFilter.GetYesNo()!=0;
        const float maxWidth = In_IVBMaxWidth.GetFloat();
        const bool htfAlign = In_IVBHTFAlign.GetYesNo()!=0;
        const bool drawTgt = In_IVBDrawTargets.GetYesNo()!=0;
        const int tgtCol = In_IVBTargetColor.GetColor();
        int& ivbKey = sc.GetPersistentInt(6);

        // precompute per-session opening-range data
        std::vector<IVBData> ivb(total);
        for (int j=0; j<total; ++j)
        {
            const SessionProfile& s = sessions[j];
            int last = s.StartIdx + ivbBars - 1;
            if (last > s.EndIdx) continue;
            bool ok=true; float hi=sc.High[s.StartIdx], lo=sc.Low[s.StartIdx]; double vsum=0; int vn=0;
            for (int b=s.StartIdx; b<=last; ++b)
            {
                if (sc.GetBarHasClosedStatus(b)!=BHCS_BAR_HAS_CLOSED){ ok=false; break; }
                if (sc.High[b]>hi) hi=sc.High[b]; if (sc.Low[b]<lo) lo=sc.Low[b];
                vsum += sc.Volume[b]; vn++;
            }
            if (!ok || vn==0) continue;
            ivb[j].High=hi; ivb[j].Low=lo; ivb[j].Range=hi-lo; ivb[j].AvgVol=(float)(vsum/vn); ivb[j].LastIdx=last; ivb[j].Valid=true;
        }

        for (int j = (firstDraw>0?firstDraw:0); j<total; ++j)
        {
            if (!ivb[j].Valid) continue;
            const SessionProfile& s = sessions[j];
            const IVBData& ib = ivb[j];

            // day-type filter: skip days whose IB is unusually wide (rotation)
            if (widthFilter)
            {
                double rsum=0; int rn=0;
                for (int k=(j-20>0?j-20:0); k<j; ++k) if (ivb[k].Valid){ rsum+=ivb[k].Range; rn++; }
                if (rn>0 && ib.Range > maxWidth*(rsum/rn)) continue;
            }

            // first qualifying breakout close beyond the opening range
            int sigBar=-1; bool sigLong=false;
            for (int b=ib.LastIdx+1; b<=s.EndIdx; ++b)
            {
                if (sc.GetBarHasClosedStatus(b)!=BHCS_BAR_HAS_CLOSED) break;
                const float c=sc.Close[b];
                bool brkUp = c>ib.High, brkDn = c<ib.Low;
                if (!brkUp && !brkDn) continue;
                bool isLong = brkUp;
                if (isLong==false && skewMode==2) continue;        // long only -> ignore shorts
                // volume gate (shorts pay a penalty in Favor-longs mode)
                if (useVol && ib.AvgVol>0)
                {
                    float need = volMult * ((!isLong && skewMode==1) ? shortPen : 1.0f);
                    if (sc.Volume[b] < need*ib.AvgVol) continue;
                }
                // HTF alignment: long above weekly VPOC, short below
                if (htfAlign && weeklyValid)
                {
                    if (isLong && !(c > WVPOC)) continue;
                    if (!isLong && !(c < WVPOC)) continue;
                }
                sigBar=b; sigLong=isLong; break;
            }
            if (sigBar<0) continue;

            const float ext = sigLong ? (ib.High + ib.Range) : (ib.Low - ib.Range);
            const float mid = (ib.High + ib.Low) * 0.5f;
            SCDateTime regBegin = sc.BaseDateTimeIn[sigBar];
            SCDateTime regEnd = (j+1<total) ? sessions[j+1].StartDT : s.EndDT + SCDateTime::HOURS(4);

            if (drawMarkers)
            { s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT; m.LineNumber=(sigLong?270000:280000)+s.DateYMD*10;
              m.BeginDateTime=sc.BaseDateTimeIn[sigBar]; m.BeginValue=sc.Close[sigBar]; m.Color=sigLong?In_VAHColor.GetColor():In_VALColor.GetColor();
              m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST; m.Text.Format("%s\n%.2f", sigLong?"IVB LONG ^":"IVB SHORT v", sc.Close[sigBar]); sc.UseTool(m);
              if (showTS) DrawSignalTime(sc, (sigLong?670000:680000)+s.DateYMD*10, sigBar, sc.Close[sigBar], sigLong, tsCol, tsFont, tsOff); }

            if (drawTgt)
            {
                s_UseTool t; t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=700000+s.DateYMD*10;
                t.BeginDateTime=regBegin; t.EndDateTime=regEnd; t.BeginValue=ext; t.EndValue=ext; t.Color=tgtCol; t.LineWidth=lineWidth; t.LineStyle=LINESTYLE_DASH;
                t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="IVB 100% ext"; sc.UseTool(t);
                t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=710000+s.DateYMD*10;
                t.BeginDateTime=regBegin; t.EndDateTime=regEnd; t.BeginValue=mid; t.EndValue=mid; t.Color=tgtCol; t.LineWidth=1; t.LineStyle=LINESTYLE_DOT;
                t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=0; if(showLabels)t.Text="IB mid"; sc.UseTool(t);
                if (In_LadderEnable.GetYesNo())
                {
                    const float r = ib.Range; const float base = sigLong?ib.High:ib.Low; const int dir = sigLong?1:-1;
                    const float l50=base+dir*0.5f*r, l150=base+dir*1.5f*r, l200=base+dir*2.0f*r;
                    t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=720000+s.DateYMD*10;
                    t.BeginDateTime=regBegin; t.EndDateTime=regEnd; t.BeginValue=l50; t.EndValue=l50; t.Color=tgtCol; t.LineWidth=1; t.LineStyle=LINESTYLE_DOT;
                    t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=0; if(showLabels)t.Text="IVB 50%"; sc.UseTool(t);
                    t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=730000+s.DateYMD*10;
                    t.BeginDateTime=regBegin; t.EndDateTime=regEnd; t.BeginValue=l150; t.EndValue=l150; t.Color=tgtCol; t.LineWidth=1; t.LineStyle=LINESTYLE_DOT;
                    t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=0; if(showLabels)t.Text="IVB 150%"; sc.UseTool(t);
                    t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE; t.LineNumber=740000+s.DateYMD*10;
                    t.BeginDateTime=regBegin; t.EndDateTime=regEnd; t.BeginValue=l200; t.EndValue=l200; t.Color=tgtCol; t.LineWidth=1; t.LineStyle=LINESTYLE_DOT;
                    t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=0; if(showLabels)t.Text="IVB 200%"; sc.UseTool(t);
                }
            }

            const bool liveDay = (j == total-1);
            if (followAlertOn && liveDay && !sc.IsFullRecalculation && newBar && sigBar>=lastClosed-1 && ivbKey!=s.DateYMD)
            {
                ivbKey=s.DateYMD;
                SCString m; m.Format("IVB %s: close beyond %dm opening range%s. Target(100%%) %.2f | stop back inside IB",
                    sigLong?"LONG":"SHORT", ivbMin, useVol?" on volume":"", ext);
                sc.AddMessageToLog(m,1); sc.SetAlert(0,m);
                if(In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sc.BaseDateTimeIn[sigBar], m.GetChars());
                if (In_NtfyEnable.GetYesNo() && strlen(In_NtfyURL.GetString())>16)
                { SCString nb; nb.Format("%s  %s", sc.Symbol.GetChars(), m.GetChars()); sc.MakeHTTPPOSTRequest(In_NtfyURL.GetString(), nb, NULL, 0); }
            }
        }
    }

    // ---- Pass 4: naked POCs (untested prior POCs act as magnets) ----------
    if (In_NakedEnable.GetYesNo())
    {
        const int look = 30; int drawn=0; const int maxN=In_NakedMax.GetInt();
        const SCDateTime nFar = sc.BaseDateTimeIn[sc.ArraySize-1] + SCDateTime::DAYS(1);
        const int nCol = In_NakedColor.GetColor();
        for (int k=total-2; k>=0 && k>=total-look && drawn<maxN; --k)
        {
            const SessionProfile& sk = sessions[k];
            if (!sk.Valid) continue;
            const float poc = sk.POC; bool touched=false;
            for (int b=sk.EndIdx+1; b<sc.ArraySize; ++b)
            { if (sc.Low[b]<=poc && sc.High[b]>=poc){ touched=true; break; } }
            if (touched) continue;
            s_UseTool t; t.Clear(); t.ChartNumber=sc.ChartNumber; t.DrawingType=DRAWING_LINE;
            t.LineNumber=800000+k; t.BeginDateTime=sk.EndDT; t.EndDateTime=nFar;
            t.BeginValue=poc; t.EndValue=poc; t.Color=nCol; t.LineWidth=1; t.LineStyle=LINESTYLE_DASH;
            t.AddMethod=UTAM_ADD_OR_ADJUST; t.ShowPrice=showLabels?1:0; if(showLabels)t.Text="nPOC"; sc.UseTool(t);
            drawn++;
        }
    }

    // ---- Pass 5: REV (Rejection/Reversal) markers + live alert -------------
    // Repeated wick-rejection at an active PD level with no acceptance beyond,
    // confirmed by a break-back through recent structure => reversal signal.
    if (In_RevEnable.GetYesNo() && total>=1)
    {
        const int baseW=In_RevWindow.GetInt(), baseMT=In_RevMinTouch.GetInt(), baseMR=In_RevMinRej.GetInt(), baseCFB=In_RevConfirmBars.GetInt();
        const bool momF=In_RevMomFilter.GetYesNo()!=0;
        const float baseTol=In_RevTolTicks.GetInt()*sc.TickSize;
        const float atrTol=(In_RevATRNorm.GetYesNo() && atrDaily>0)? 0.1f*atrDaily : baseTol;
        const int usS=In_SessionStart.GetTime(), usE=In_SessionEnd.GetTime(), ukS=In_UKStart.GetTime(),
                  ukE=In_UKEnd.GetTime(), aS=In_AsiaStart.GetTime(), aE=In_AsiaEnd.GetTime();
        const float dUS=In_RevDialUS.GetFloat(), dUK=In_RevDialUK.GetFloat(), dAsia=In_RevDialAsia.GetFloat();
        const int revCol=In_RevColor.GetColor();
        const bool gV=In_RevVWAPGate.GetYesNo()!=0, gS=In_RevSpaceGate.GetYesNo()!=0;
        const float spPts=In_RevSpacePts.GetFloat(), spATR=In_RevSpaceATR.GetFloat();
        const float minSpace=(spATR*atrDaily<spPts && atrDaily>0)? spATR*atrDaily : spPts;
        int& revBarKey=sc.GetPersistentInt(7);
        int startB = ((firstDraw>=0 && firstDraw<total)?sessions[firstDraw].StartIdx:0) + baseW*2;
        if (startB < baseW*2) startB = baseW*2;
        int actIdx=-1, lastFire=-100;
        for (int b=startB; b<=lastClosed; ++b)
        {
            while (actIdx+1<total && sessions[actIdx+1].EndIdx < b) actIdx++;
            if (actIdx<0) continue;
            if (lastInProgress && actIdx==total-1) continue;      // developing levels: skip
            const SessionProfile& A=sessions[actIdx];
            const float Lv[3]={A.POC,A.VAH,A.VAL}; const char* Ln[3]={"PD POC","PD VAH","PD VAL"};
            const int bsec=sc.BaseDateTimeIn[b].GetTimeInSeconds();
            if (In_RevUSonly.GetYesNo() && !(bsec>=usS && bsec<usE)) continue;   // 5y: REV edge is US-only
            const float dial=RevDial(bsec, usS,usE,ukS,ukE,aS,aE, dUS,dUK,dAsia);
            const int Wr=(int)(baseW*dial+0.5f), mT=(int)(baseMT*dial+0.5f), mR=(int)(baseMR*dial+0.5f);
            int cfb=(int)(baseCFB*dial+0.5f); if(cfb<1)cfb=1;
            if (b-lastFire < cfb+1) continue;                     // debounce
            int fDir=0,fI=-1,fSc=0;
            const float wallsB[4]={A.POC,A.VAH,A.VAL,(weeklyValid?WVPOC:0.0f)};
            const float vwapB=(b<(int)vwapArr.size())?vwapArr[b]:0.0f;
            for(int i=0;i<3;++i){ int s2; int d=DetectRej(sc,b,Wr,Lv[i],atrTol,mT,mR,cfb,momF,s2);
                if(d!=0 && !RevGatePass(d,sc.Close[b],vwapB,minSpace,wallsB,4,gV,gS)) d=0;
                if(d!=0&&s2>fSc){fSc=s2;fDir=d;fI=i;} }
            if (fDir==0) continue;
            lastFire=b; const bool sLong=fDir>0;
            if (drawMarkers)
            {
                s_UseTool m; m.Clear(); m.ChartNumber=sc.ChartNumber; m.DrawingType=DRAWING_TEXT;
                m.LineNumber=850000+b; m.BeginDateTime=sc.BaseDateTimeIn[b]; m.BeginValue=sc.Close[b];
                m.Color=(COLORREF)revCol; m.FontSize=11; m.FontBold=1; m.AddMethod=UTAM_ADD_OR_ADJUST;
                m.Text.Format("%s\n%.2f", sLong?"REV LONG ^":"REV SHORT v", sc.Close[b]); sc.UseTool(m);
                if (showTS) DrawSignalTime(sc, 690000+b, b, sc.Close[b], sLong, tsCol, tsFont, tsOff);
            }
            if (b==lastClosed && followAlertOn && !sc.IsFullRecalculation && newBar && revBarKey!=b)
            {
                revBarKey=b;
                SCString mm; mm.Format("REV %s: rejection at %s (%dx). Break-back confirmed @ %.2f. Target next reference %s",
                    sLong?"LONG":"SHORT", Ln[fI], fSc, sc.Close[b], sLong?"up":"down");
                sc.AddMessageToLog(mm,1); sc.SetAlert(0,mm);
                if(In_LogEnable.GetYesNo()) LogSig(In_LogFile.GetString(), sc.BaseDateTimeIn[b], mm.GetChars());
                if (In_NtfyEnable.GetYesNo() && strlen(In_NtfyURL.GetString())>16)
                { SCString nb; nb.Format("%s  %s", sc.Symbol.GetChars(), mm.GetChars()); sc.MakeHTTPPOSTRequest(In_NtfyURL.GetString(), nb, NULL, 0); }
            }
        }
    }
}
