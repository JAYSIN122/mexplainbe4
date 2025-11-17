"""
ETA Calculator
Calculates time-to-convergence for Gravitational Time Interferometry
Based on phase gap analysis with stability validation
"""

import numpy as np
import logging
from datetime import datetime, timezone, timedelta
from scipy.stats import kendalltau
from app import db
from models import ETAEstimate, GTICalculation, ConvergenceEvent

logger = logging.getLogger(__name__)


class ETACalculator:
    """Calculates ETA to convergence with confidence analysis"""
    
    def __init__(self):
        self.min_history_points = 10
        self.lookback_days = 365  # Use last year for stability analysis
        
    def compute_instantaneous_eta(self, phase_gap_rad, slope_rad_per_day):
        """
        Compute ETA from current phase gap and slope
        
        Args:
            phase_gap_rad: Current phase gap in radians
            slope_rad_per_day: Rate of change in radians per day (negative = converging)
            
        Returns:
            tuple: (eta_days, convergence_status, notes)
        """
        notes = []
        
        # Check if converging
        if slope_rad_per_day >= 0:
            return None, "DIVERGING", "Phase gap not closing (slope >= 0)"
        
        # Calculate ETA
        eta_days = abs(phase_gap_rad) / (-slope_rad_per_day)
        
        # Sanity check
        if eta_days > 36500:  # > 100 years
            notes.append("ETA exceeds 100 years - likely not converging")
            return eta_days, "STABLE", "; ".join(notes)
        
        if eta_days < 1:
            notes.append("Convergence imminent (<1 day)")
            return eta_days, "CONVERGING", "; ".join(notes)
        
        return eta_days, "CONVERGING", "; ".join(notes)
    
    def compute_robust_eta_from_history(self, lookback_days=None):
        """
        Compute robust ETA using historical GTI calculations
        Uses IQR stability bands and Kendall tau for monotonicity
        
        Args:
            lookback_days: How many days of history to analyze
            
        Returns:
            dict: Stability analysis results
        """
        if lookback_days is None:
            lookback_days = self.lookback_days
            
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        # Get historical GTI calculations
        history = GTICalculation.query\
            .filter(GTICalculation.timestamp >= cutoff_date)\
            .order_by(GTICalculation.timestamp.asc())\
            .all()
        
        if len(history) < self.min_history_points:
            logger.warning(f"Insufficient history: {len(history)} points (need {self.min_history_points})")
            return None
        
        # Extract phase gaps and calculate ETAs
        eta_values = []
        slopes = []
        
        for i in range(1, len(history)):
            curr = history[i]
            prev = history[i-1]
            
            # Calculate slope (rate of change in phase gap)
            time_diff_days = (curr.timestamp - prev.timestamp).total_seconds() / 86400.0
            if time_diff_days > 0:
                # Convert phase gap from degrees to radians
                curr_phase_rad = np.deg2rad(curr.phase_gap) if curr.phase_gap else 0
                prev_phase_rad = np.deg2rad(prev.phase_gap) if prev.phase_gap else 0
                slope_rad_per_day = (curr_phase_rad - prev_phase_rad) / time_diff_days
                
                # Calculate ETA if converging
                if slope_rad_per_day < 0 and curr_phase_rad > 0:
                    eta_days = abs(curr_phase_rad) / (-slope_rad_per_day)
                    if 0 < eta_days < 36500:  # Sanity check
                        eta_values.append(eta_days)
                        slopes.append(slope_rad_per_day)
        
        if len(eta_values) < self.min_history_points:
            logger.warning(f"Insufficient valid ETA values: {len(eta_values)}")
            return None
        
        # Calculate stability metrics
        eta_array = np.array(eta_values)
        q1, q3 = np.percentile(eta_array, [25, 75])
        iqr = float(q3 - q1)
        median_eta = float(np.median(eta_array))
        
        # Kendall tau for monotonicity (are we consistently converging?)
        tau, p_value = kendalltau(range(len(slopes)), slopes) if len(slopes) >= 8 else (None, None)
        
        # Latest values
        latest_eta = float(eta_values[-1]) if eta_values else None
        latest_slope = float(slopes[-1]) if slopes else None
        
        return {
            'eta_days_latest': latest_eta,
            'eta_days_median': median_eta,
            'band_iqr_days': iqr,
            'slope_rad_per_day_latest': latest_slope,
            'kendall_tau': float(tau) if tau is not None else None,
            'kendall_pvalue': float(p_value) if p_value is not None else None,
            'n_points': len(eta_values),
            'stability_assessment': self._assess_stability(iqr, tau)
        }
    
    def _assess_stability(self, iqr, tau):
        """
        Assess whether the convergence prediction is stable
        
        Args:
            iqr: Interquartile range in days
            tau: Kendall tau statistic
            
        Returns:
            str: Assessment message
        """
        if iqr is None:
            return "Insufficient data for stability assessment"
        
        if iqr > 90:
            return "UNSTABLE - Prediction varies widely (>90 days IQR)"
        elif iqr > 45:
            return "MODERATE - Some variability in prediction"
        else:
            decision = "STABLE - Consistent prediction band"
            if tau is not None and tau < -0.3:
                decision += " with accelerating convergence"
            elif tau is not None and tau > 0.3:
                decision += " but slope increasing (diverging trend)"
            return decision
    
    def save_eta_estimate(self, gti_result):
        """
        Save ETA estimate to database based on GTI calculation
        
        Args:
            gti_result: GTI pipeline results dict
            
        Returns:
            ETAEstimate object or None
        """
        try:
            # Extract phase gap and calculate slope from recent history
            phase_gap_deg = gti_result.get('phase_gap_degrees', 0)
            phase_gap_rad = np.deg2rad(phase_gap_deg)
            
            # Get slope from recent calculations
            recent_gtis = GTICalculation.query\
                .order_by(GTICalculation.timestamp.desc())\
                .limit(10).all()
            
            if len(recent_gtis) < 2:
                logger.info("Not enough history to calculate slope")
                return None
            
            # Calculate average slope from recent data
            slopes = []
            for i in range(1, len(recent_gtis)):
                curr = recent_gtis[i-1]  # More recent
                prev = recent_gtis[i]    # Older
                
                time_diff = (curr.timestamp - prev.timestamp).total_seconds() / 86400.0
                if time_diff > 0:
                    curr_rad = np.deg2rad(curr.phase_gap) if curr.phase_gap else 0
                    prev_rad = np.deg2rad(prev.phase_gap) if prev.phase_gap else 0
                    slope = (curr_rad - prev_rad) / time_diff
                    slopes.append(slope)
            
            if not slopes:
                logger.info("Cannot calculate slope")
                return None
            
            slope_rad_per_day = float(np.median(slopes))
            slope_rad_per_sec = slope_rad_per_day / 86400.0
            
            # Compute instantaneous ETA
            eta_days, status, notes = self.compute_instantaneous_eta(
                phase_gap_rad, slope_rad_per_day
            )
            
            # Get stability metrics
            stability = self.compute_robust_eta_from_history()
            
            # Create estimate
            estimate = ETAEstimate()
            estimate.as_of_utc = datetime.utcnow()
            estimate.phase_gap_rad = float(phase_gap_rad)
            estimate.phase_gap_degrees = float(phase_gap_deg)
            estimate.slope_rad_per_day = slope_rad_per_day
            estimate.slope_rad_per_sec = slope_rad_per_sec
            estimate.convergence_status = status
            estimate.notes = notes
            
            if eta_days is not None:
                estimate.eta_days = float(eta_days)
                estimate.eta_date = datetime.utcnow() + timedelta(days=eta_days)
            
            if stability:
                estimate.confidence_band_iqr = stability.get('band_iqr_days')
                estimate.kendall_tau = stability.get('kendall_tau')
                estimate.kendall_pvalue = stability.get('kendall_pvalue')
                if estimate.notes:
                    estimate.notes += f"; {stability.get('stability_assessment', '')}"
                else:
                    estimate.notes = stability.get('stability_assessment', '')
            
            db.session.add(estimate)
            db.session.commit()
            
            logger.info(f"Saved ETA estimate: {eta_days:.2f} days ({status})")
            return estimate
            
        except Exception as e:
            logger.error(f"Error saving ETA estimate: {e}")
            db.session.rollback()
            return None
    
    def check_for_convergence_event(self, gti_result, threshold_degrees=0.05):
        """
        Check if a convergence event has occurred (phase gap near zero)
        
        Args:
            gti_result: GTI pipeline results
            threshold_degrees: Phase gap threshold for convergence detection
            
        Returns:
            ConvergenceEvent object if detected, None otherwise
        """
        phase_gap_deg = gti_result.get('phase_gap_degrees', 0)
        
        if abs(phase_gap_deg) > threshold_degrees:
            return None  # Not converged
        
        # Check if we haven't already recorded this event recently
        recent_event = ConvergenceEvent.query\
            .filter(ConvergenceEvent.event_utc >= datetime.utcnow() - timedelta(hours=6))\
            .first()
        
        if recent_event:
            logger.info("Convergence event already recorded recently")
            return None
        
        # Get latest ETA prediction
        latest_eta = ETAEstimate.query\
            .filter(ETAEstimate.convergence_status == 'CONVERGING')\
            .order_by(ETAEstimate.as_of_utc.desc())\
            .first()
        
        # Create convergence event
        event = ConvergenceEvent()
        event.event_utc = datetime.utcnow()
        event.phase_gap_at_event = float(phase_gap_deg)
        event.gti_value = float(gti_result.get('gti_value', 0))
        event.coherence = float(gti_result.get('coherence_median', 0))
        
        if latest_eta and latest_eta.eta_date:
            event.predicted_utc = latest_eta.eta_date
            time_diff = (event.event_utc - latest_eta.eta_date).total_seconds() / 3600.0
            event.prediction_error_hours = float(time_diff)
        
        # Store evidence
        evidence = {
            'phase_gap_degrees': float(phase_gap_deg),
            'variance_explained': float(gti_result.get('variance_explained', 0)),
            'bayes_factor': float(gti_result.get('bayes_factor', 0)),
            'alert_level': gti_result.get('alert_level', 'UNKNOWN')
        }
        event.set_evidence(evidence)
        
        # Verify if this is a real convergence
        if abs(phase_gap_deg) < 0.01 and gti_result.get('coherence_median', 0) > 0.7:
            event.verification_status = 'CONFIRMED'
        elif abs(phase_gap_deg) < threshold_degrees:
            event.verification_status = 'PROBABLE'
        else:
            event.verification_status = 'FALSE_POSITIVE'
        
        db.session.add(event)
        db.session.commit()
        
        logger.info(f"Convergence event recorded: {event.verification_status}")
        return event
