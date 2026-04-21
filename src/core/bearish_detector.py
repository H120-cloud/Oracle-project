"""Bearish Transition Detector — V6. Detects bearish transitions for exit warnings."""
import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass
import numpy as np
from src.models.schemas import OHLCVBar, BearishState, ExitWarningLevel, BearishTransitionData, VolumeProfileData

logger = logging.getLogger(__name__)

@dataclass
class SwingPoint:
    idx: int
    price: float
    is_high: bool

class BearishDetector:
    def __init__(self, swing_lb: int = 5, vwap_thr: float = 0.5, ema_thr: float = 1.0):
        self.swing_lb = swing_lb
        self.vwap_thr = vwap_thr
        self.ema_thr = ema_thr

    def detect(self, ticker: str, bars: List[OHLCVBar], vp: Optional[VolumeProfileData] = None) -> Optional[BearishTransitionData]:
        if len(bars) < 30:
            return None
        try:
            h = np.array([b.high for b in bars])
            l = np.array([b.low for b in bars])
            c = np.array([b.close for b in bars])
            v = np.array([b.volume for b in bars])
            price = float(c[-1])
            
            ema9 = self._ema(c, 9)
            ema20 = self._ema(c, 20)
            vwap = self._vwap(bars[-20:])
            
            swing_h, swing_l = self._swings(h, l, c)
            struct = self._structure(swing_h, swing_l, price)
            breakout = self._breakout(h, l, c, v)
            support = self._support(price, l, vp, vwap, ema9, ema20)
            mom = self._momentum(c, v)

            # V7: Early topping detection (pre-reversal signals)
            early_top = self._detect_early_topping(h, l, c, v, swing_h)

            # Adjust probability with early topping signals
            prob = self._prob(struct, breakout, support, mom, early_top)
            state = self._state(prob, struct)
            warning = self._warning(state, prob, struct, support, early_top)
            ks, inv = self._levels(price, l, vp, ema20, swing_l)
            reasons = self._reasons(struct, breakout, support, mom, early_top)

            # V7: Calculate early warning confidence
            early_confidence = 0.0
            if early_top.get("early_warning"):
                early_confidence = (
                    (10 if early_top.get("resistance_rejections", 0) >= 2 else 0) +
                    (20 if early_top.get("decreasing_volume_on_rises") else 0) +
                    (15 if early_top.get("increasing_upper_wicks") else 0) +
                    (15 if early_top.get("momentum_slowed") else 0)
                )
                early_confidence = min(100, early_confidence)

            return BearishTransitionData(
                ticker=ticker, bearish_state=state, bearish_probability=round(prob, 1),
                exit_warning=warning, key_support_level=round(ks, 2) if ks else None,
                invalidation_level=round(inv, 2) if inv else None, top_reasons=reasons[:3],
                lower_highs_detected=struct.get("lower_highs", False),
                failed_breakout_detected=breakout.get("failed", False),
                structure_break_detected=struct.get("struct_break", False),
                support_lost=support.get("support_lost", False),
                resistance_rejection=breakout.get("reject", False),
                vwap_lost=support.get("vwap_lost", False), ema9_lost=support.get("ema9_lost", False),
                ema20_lost=support.get("ema20_lost", False),
                rising_selling_pressure=mom.get("selling_pressure", False),
                negative_order_flow=mom.get("neg_flow", False),
                distribution_behavior=breakout.get("distribution", False),
                # V7 early topping fields
                early_bearish_warning=early_top.get("early_warning", False),
                early_bearish_confidence=round(early_confidence, 1),
                multiple_resistance_rejections=early_top.get("resistance_rejections", 0),
                decreasing_volume_on_rises=early_top.get("decreasing_volume_on_rises", False),
                increasing_upper_wicks=early_top.get("increasing_upper_wicks", False),
                momentum_slowed_near_highs=early_top.get("momentum_slowed", False))
        except Exception as e:
            logger.error("Bearish detect failed %s: %s", ticker, e)
            return None

    def _swings(self, h, l, c):
        sh, sl = [], []
        for i in range(self.swing_lb, len(h) - self.swing_lb):
            if h[i] == max(h[i-self.swing_lb:i+self.swing_lb+1]):
                sh.append(SwingPoint(i, float(h[i]), True))
            if l[i] == min(l[i-self.swing_lb:i+self.swing_lb+1]):
                sl.append(SwingPoint(i, float(l[i]), False))
        return sh, sl

    def _structure(self, sh, sl, price):
        r = {"lower_highs": False, "lower_lows": False, "struct_break": False, "higher_highs": False, "higher_lows": False}
        if len(sh) < 2 or len(sl) < 2: return r
        hp = [p.price for p in sh[-3:]]
        lp = [p.price for p in sl[-3:]]
        if len(hp) >= 2 and hp[-1] < hp[-2]: r["lower_highs"] = True
        elif len(hp) >= 2 and hp[-1] > hp[-2]: r["higher_highs"] = True
        if len(lp) >= 2 and lp[-1] < lp[-2]: r["lower_lows"] = True
        elif len(lp) >= 2 and lp[-1] > lp[-2]: r["higher_lows"] = True
        if r["higher_lows"] and len(sl) >= 2 and price < sl[-2].price * 0.995:
            r["struct_break"] = True
        return r

    def _breakout(self, h, l, c, v):
        r = {"failed": False, "reject": False, "distribution": False, "rev_pct": 0.0}
        if len(h) < 10: return r
        local_h = float(max(h[-10:-3])) if len(h) > 3 else float(h[0])
        for i in range(-5, 0):
            if h[i] > local_h * 1.005 and c[i] < local_h:
                r["failed"] = True
                r["rev_pct"] = round(((h[i] - c[i]) / h[i]) * 100, 2)
                r["reject"] = True
                if v[i] > np.mean(v[-10:-5]) * 1.3: r["distribution"] = True
                break
        return r

    def _support(self, price, lows, vp, vwap, ema9, ema20):
        r = {"vwap_lost": False, "ema9_lost": False, "ema20_lost": False, "poc_lost": False, "val_lost": False, "support_lost": False}
        if ((price - vwap) / vwap) * 100 < -self.vwap_thr: r["vwap_lost"] = r["support_lost"] = True
        if ((price - ema9) / ema9) * 100 < -self.ema_thr: r["ema9_lost"] = r["support_lost"] = True
        if ((price - ema20) / ema20) * 100 < -self.ema_thr: r["ema20_lost"] = r["support_lost"] = True
        if vp:
            if price < vp.poc_price * 0.995: r["poc_lost"] = r["support_lost"] = True
            if price < vp.value_area_low: r["val_lost"] = r["support_lost"] = True
        return r

    def _momentum(self, c, v):
        r = {"selling_pressure": False, "neg_flow": False, "divergence": False, "buy_ratio": 0.5}
        if len(c) < 20: return r
        ch = np.diff(c)
        up = v[1:][ch > 0].sum() if np.any(ch > 0) else 0
        down = v[1:][ch < 0].sum() if np.any(ch < 0) else 0
        total = up + down
        if total > 0:
            r["buy_ratio"] = round(up / total, 2)
            if r["buy_ratio"] < 0.4: r["neg_flow"] = True
        rd = v[-5:][ch[-5:] < 0].sum() if len(ch) >= 5 else 0
        pd = v[-10:-5][ch[-10:-5] < 0].sum() if len(ch) >= 10 else rd
        if pd > 0 and rd > pd * 1.3: r["selling_pressure"] = True
        rm = (c[-1] - c[-5]) / c[-5] if len(c) >= 5 else 0
        pm = (c[-10] - c[-15]) / c[-15] if len(c) >= 15 else rm
        if rm < 0 and pm > 0: r["divergence"] = True
        return r

    def _prob(self, s, b, sup, m, early_top=None):
        p = 0
        if s.get("lower_highs"): p += 15
        if s.get("lower_lows"): p += 20
        if s.get("struct_break"): p += 25
        if b.get("failed"): p += 15
        if b.get("reject"): p += 10
        if b.get("distribution"): p += 10
        if sup.get("vwap_lost"): p += 8
        if sup.get("ema9_lost"): p += 8
        if sup.get("ema20_lost"): p += 15
        if sup.get("val_lost"): p += 15
        if m.get("selling_pressure"): p += 10
        if m.get("neg_flow"): p += 10
        # V7: Early topping signals increase bearish probability
        if early_top:
            if early_top.get("early_warning"): p += 15
            if early_top.get("resistance_rejections", 0) >= 2: p += 10
            if early_top.get("decreasing_volume_on_rises"): p += 8
            if early_top.get("increasing_upper_wicks"): p += 8
            if early_top.get("momentum_slowed"): p += 5
        return min(100, p)

    def _state(self, prob, s):
        if prob >= 75: return BearishState.CONFIRMED_BEARISH
        if prob >= 55: return BearishState.BEARISH_TRANSITION
        if prob >= 35: return BearishState.WEAKENING
        if prob >= 15: return BearishState.NEUTRAL
        return BearishState.BULLISH

    def _warning(self, state, prob, s, sup, early_top=None):
        if state == BearishState.CONFIRMED_BEARISH: return ExitWarningLevel.EXIT_SIGNAL
        if state == BearishState.BEARISH_TRANSITION:
            if s.get("struct_break") or sup.get("ema20_lost"): return ExitWarningLevel.STRONG_WARNING
            return ExitWarningLevel.EARLY_WARNING
        if state == BearishState.WEAKENING and sup.get("vwap_lost") and s.get("lower_highs"):
            return ExitWarningLevel.EARLY_WARNING
        # V7: Early topping can trigger warning even in neutral state
        if early_top and early_top.get("early_warning") and early_top.get("resistance_rejections", 0) >= 2:
            return ExitWarningLevel.EARLY_WARNING
        return ExitWarningLevel.NONE

    def _levels(self, price, lows, vp, ema20, swing_l):
        ks = None
        if vp and vp.value_area_low: ks = vp.value_area_low
        if swing_l:
            rl = swing_l[-1].price
            if ks is None or rl < ks: ks = rl
        if ks is None: ks = ema20 * 0.99
        inv = ks * 0.98 if ks else None
        return ks, inv

    def _reasons(self, s, b, sup, m, early_top=None):
        r = []
        if s.get("struct_break"): r.append("Structure break: price below higher low")
        elif s.get("lower_highs"): r.append("Lower highs pattern forming")
        elif s.get("lower_lows"): r.append("Lower lows: downtrend confirmed")
        if b.get("failed"): r.append(f"Failed breakout: reversed {b.get('rev_pct', 0):.1f}%")
        elif b.get("reject"): r.append("Resistance rejection with long wicks")
        if b.get("distribution"): r.append("Distribution: high volume on decline")
        if sup.get("ema20_lost"): r.append("Lost EMA-20 support")
        elif sup.get("ema9_lost"): r.append("Lost EMA-9 support")
        if sup.get("val_lost"): r.append("Below volume profile value area")
        elif sup.get("poc_lost"): r.append("Below point of control")
        if sup.get("vwap_lost"): r.append("Lost VWAP support")
        if m.get("selling_pressure"): r.append("Rising selling pressure on declines")
        if m.get("neg_flow"): r.append("Negative order flow: more selling volume")
        # V7: Early topping reasons
        if early_top:
            if early_top.get("resistance_rejections", 0) >= 2:
                r.append(f"Multiple resistance rejections ({early_top.get('resistance_rejections')})")
            if early_top.get("decreasing_volume_on_rises"):
                r.append("Decreasing volume on upward moves")
            if early_top.get("increasing_upper_wicks"):
                r.append("Increasing upper wicks near highs")
            if early_top.get("momentum_slowed"):
                r.append("Momentum slowing near resistance")
        return r

    def _detect_early_topping(self, h, l, c, v, swing_h):
        """
        V7: Detect early topping signals before full bearish reversal.
        Returns dict with early warning indicators.
        """
        r = {
            "early_warning": False,
            "resistance_rejections": 0,
            "decreasing_volume_on_rises": False,
            "increasing_upper_wicks": False,
            "momentum_slowed": False
        }
        if len(c) < 15 or not swing_h:
            return r

        # Find recent resistance level (last swing high)
        recent_resistance = swing_h[-1].price if swing_h else float(max(h[-15:]))

        # 1. Count resistance rejections (price approached but failed to break)
        rejections = 0
        for i in range(-10, 0):
            if h[i] > recent_resistance * 0.995 and c[i] < recent_resistance:
                rejections += 1
        r["resistance_rejections"] = rejections

        # 2. Check for decreasing volume on upward moves
        up_moves = [i for i in range(-10, 0) if c[i] > c[i-1]] if len(c) >= 11 else []
        if len(up_moves) >= 3:
            recent_up_vol = float(np.mean([v[i] for i in up_moves[-2:]]))
            prior_up_vol = float(np.mean([v[i] for i in up_moves[:-2]])) if len(up_moves) > 2 else recent_up_vol
            if prior_up_vol > 0 and recent_up_vol < prior_up_vol * 0.8:
                r["decreasing_volume_on_rises"] = True

        # 3. Check for increasing upper wicks near highs
        upper_wicks = []
        for i in range(-10, 0):
            candle_range = h[i] - l[i]
            if candle_range > 0:
                upper_wick = (h[i] - max(c[i], c[i-1 if i > -len(c) else i])) / candle_range
                upper_wicks.append(upper_wick)
        if len(upper_wicks) >= 5:
            recent_wicks = float(np.mean(upper_wicks[-3:]))
            prior_wicks = float(np.mean(upper_wicks[:-3])) if len(upper_wicks) > 3 else recent_wicks
            if recent_wicks > prior_wicks * 1.3 and recent_wicks > 0.3:
                r["increasing_upper_wicks"] = True

        # 4. Check if momentum slowed near highs
        if len(c) >= 10:
            recent_momentum = (c[-1] - c[-5]) / c[-5] if c[-5] != 0 else 0
            prior_momentum = (c[-6] - c[-10]) / c[-10] if c[-10] != 0 else 0
            # Slowing momentum = recent move smaller than prior move
            if recent_momentum < prior_momentum * 0.5 and recent_momentum > -0.01:
                r["momentum_slowed"] = True

        # Determine if early warning should be triggered
        warning_score = (
            (10 if rejections >= 2 else 0) +
            (20 if r["decreasing_volume_on_rises"] else 0) +
            (15 if r["increasing_upper_wicks"] else 0) +
            (15 if r["momentum_slowed"] else 0)
        )
        r["early_warning"] = warning_score >= 30

        return r

    def _ema(self, data, period):
        if len(data) < period: return float(np.mean(data))
        mult = 2 / (period + 1)
        ema = float(data[0])
        for val in data[1:]:
            ema = (float(val) - ema) * mult + ema
        return ema

    def _vwap(self, bars):
        if not bars: return 0.0
        recent = bars[-20:] if len(bars) >= 20 else bars
        tpv = sum(((b.high + b.low + b.close) / 3) * b.volume for b in recent)
        vol = sum(b.volume for b in recent)
        return tpv / vol if vol > 0 else 0.0
