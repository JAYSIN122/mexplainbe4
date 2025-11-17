"""
ETA Scheduler
Background scheduler that periodically calculates convergence ETA
"""

import threading
import time
import logging
from datetime import datetime
from app import app, db
from eta_calculator import ETACalculator
from gti_pipeline import GTIPipeline
from data_ingestion import DataIngestion
from models import GTICalculation

logger = logging.getLogger(__name__)


class ETAScheduler:
    """Background scheduler for ETA calculations"""
    
    def __init__(self, interval_seconds=300):
        """
        Initialize the scheduler
        
        Args:
            interval_seconds: How often to calculate ETA (default: 5 minutes)
        """
        self.interval_seconds = interval_seconds
        self.calculator = ETACalculator()
        self.pipeline = GTIPipeline()
        self.data_ingestion = DataIngestion()
        self.running = False
        self.thread = None
        
    def start(self):
        """Start the background scheduler"""
        if self.running:
            logger.warning("ETA scheduler already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"ETA scheduler started (interval: {self.interval_seconds}s)")
    
    def stop(self):
        """Stop the background scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("ETA scheduler stopped")
    
    def _run(self):
        """Main scheduler loop"""
        while self.running:
            try:
                self._calculate_eta()
            except Exception as e:
                logger.error(f"Error in ETA scheduler: {e}", exc_info=True)
            
            # Sleep in small chunks so we can stop quickly
            for _ in range(self.interval_seconds):
                if not self.running:
                    break
                time.sleep(1)
    
    def _calculate_eta(self):
        """Calculate and save ETA estimate"""
        with app.app_context():
            try:
                logger.info("Running scheduled ETA calculation...")
                
                # Get latest GTI calculation
                latest_gti = GTICalculation.query\
                    .order_by(GTICalculation.timestamp.desc())\
                    .first()
                
                if not latest_gti:
                    logger.info("No GTI calculations available yet")
                    return
                
                # Check if GTI is recent (within last hour)
                time_diff = (datetime.utcnow() - latest_gti.timestamp).total_seconds()
                if time_diff > 3600:
                    logger.info(f"Latest GTI is {time_diff/60:.1f} minutes old - running new analysis")
                    # Trigger new GTI analysis
                    self._run_gti_analysis()
                    
                    # Get the newly created GTI
                    latest_gti = GTICalculation.query\
                        .order_by(GTICalculation.timestamp.desc())\
                        .first()
                
                if not latest_gti:
                    logger.warning("No GTI calculation available after analysis")
                    return
                
                # Convert GTI to result dict
                gti_result = {
                    'timestamp': latest_gti.timestamp.isoformat(),
                    'gti_value': latest_gti.gti_value,
                    'phase_gap_degrees': latest_gti.phase_gap or 0,
                    'coherence_median': latest_gti.coherence_median or 0,
                    'variance_explained': latest_gti.variance_explained or 0,
                    'bayes_factor': latest_gti.bayes_factor or 1.0,
                    'alert_level': latest_gti.alert_level or 'UNKNOWN'
                }
                
                # Calculate and save ETA
                eta_estimate = self.calculator.save_eta_estimate(gti_result)
                
                if eta_estimate:
                    logger.info(f"ETA calculated: {eta_estimate.eta_days:.2f} days ({eta_estimate.convergence_status})")
                    
                    # Check for convergence events
                    event = self.calculator.check_for_convergence_event(gti_result)
                    if event:
                        logger.info(f"Convergence event detected: {event.verification_status}")
                else:
                    logger.info("No ETA estimate generated")
                
            except Exception as e:
                logger.error(f"Error calculating ETA: {e}", exc_info=True)
    
    def _run_gti_analysis(self):
        """Run GTI analysis on current data"""
        try:
            # Ingest latest data
            stream_data = self.data_ingestion.ingest_all_streams()
            
            if not stream_data:
                logger.warning("No stream data available for GTI analysis")
                return
            
            # Run GTI pipeline
            results = self.pipeline.process_streams(stream_data)
            
            if not results:
                logger.warning("GTI pipeline returned no results")
                return
            
            # Save GTI calculation
            gti_calc = GTICalculation()
            gti_calc.timestamp = datetime.utcnow()
            gti_calc.gti_value = results['gti_value']
            gti_calc.phase_gap = results['phase_gap_degrees']
            gti_calc.coherence_median = results['coherence_median']
            gti_calc.variance_explained = results['variance_explained']
            gti_calc.bayes_factor = results['bayes_factor']
            gti_calc.time_to_overlap = results['time_to_overlap']
            gti_calc.alert_level = results['alert_level']
            
            db.session.add(gti_calc)
            db.session.commit()
            
            logger.info(f"GTI analysis completed: {gti_calc.gti_value:.6f}")
            
        except Exception as e:
            logger.error(f"Error running GTI analysis: {e}", exc_info=True)
            db.session.rollback()


# Global scheduler instance
_scheduler = None


def get_scheduler(interval_seconds=300):
    """Get or create the global ETA scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = ETAScheduler(interval_seconds)
    return _scheduler


def start_scheduler(interval_seconds=300):
    """Start the global ETA scheduler"""
    scheduler = get_scheduler(interval_seconds)
    scheduler.start()
    return scheduler


def stop_scheduler():
    """Stop the global ETA scheduler"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
