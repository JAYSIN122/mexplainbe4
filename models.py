from app import db
from datetime import datetime
import json

class DataStream(db.Model):
    """Model for storing different types of timing data streams"""
    id = db.Column(db.Integer, primary_key=True)
    stream_type = db.Column(db.String(50), nullable=False)  # TAI, GNSS, VLBI, PTA
    timestamp = db.Column(db.DateTime, nullable=False)
    value = db.Column(db.Float, nullable=False)
    residual = db.Column(db.Float)
    stream_metadata = db.Column(db.Text)  # JSON string for additional parameters
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DataStream {self.stream_type}: {self.value} at {self.timestamp}>'

class GTICalculation(db.Model):
    """Model for storing GTI calculation results"""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    gti_value = db.Column(db.Float, nullable=False)
    phase_gap = db.Column(db.Float)  # Phase gap in degrees
    coherence_median = db.Column(db.Float)
    variance_explained = db.Column(db.Float)
    bayes_factor = db.Column(db.Float)
    time_to_overlap = db.Column(db.Float)  # Time units to potential overlap
    alert_level = db.Column(db.String(20))  # LOW, MEDIUM, HIGH, CRITICAL
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<GTI {self.gti_value:.6f} at {self.timestamp}>'

class ProcessingConfiguration(db.Model):
    """Model for storing analysis configuration parameters"""
    id = db.Column(db.Integer, primary_key=True)
    parameter_name = db.Column(db.String(100), nullable=False, unique=True)
    parameter_value = db.Column(db.Text, nullable=False)  # JSON string for complex values
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_value(self):
        """Parse the JSON value"""
        try:
            return json.loads(self.parameter_value)
        except:
            return self.parameter_value

    def set_value(self, value):
        """Set value as JSON string"""
        if isinstance(value, (dict, list)):
            self.parameter_value = json.dumps(value)
        else:
            self.parameter_value = str(value)

class AnalysisResult(db.Model):
    """Model for storing detailed analysis results"""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    analysis_type = db.Column(db.String(50), nullable=False)  # coherence, pca, phase_analysis
    result_data = db.Column(db.Text, nullable=False)  # JSON string with results
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_result_data(self):
        """Parse the JSON result data"""
        try:
            return json.loads(self.result_data)
        except:
            return {}

    def set_result_data(self, data):
        """Set result data as JSON string"""
        self.result_data = json.dumps(data)


class MeshObservation(db.Model):
    """Observation from NTP or HTTP peer polling"""
    id = db.Column(db.Integer, primary_key=True)
    peer = db.Column(db.String(255), nullable=False)
    protocol = db.Column(db.String(10), nullable=False)
    offset = db.Column(db.Float)
    rtt_ms = db.Column(db.Float)
    server_time = db.Column(db.DateTime)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<MeshObservation {self.protocol} {self.peer} offset={self.offset}>"


class ETAEstimate(db.Model):
    """Model for storing ETA (Estimated Time to Arrival) convergence forecasts"""
    id = db.Column(db.Integer, primary_key=True)
    as_of_utc = db.Column(db.DateTime, nullable=False)  # When this estimate was made
    phase_gap_rad = db.Column(db.Float)  # Current phase gap in radians
    phase_gap_degrees = db.Column(db.Float)  # Current phase gap in degrees
    slope_rad_per_day = db.Column(db.Float)  # Rate of change (negative = converging)
    slope_rad_per_sec = db.Column(db.Float)  # Rate of change in rad/sec
    eta_days = db.Column(db.Float)  # Days until convergence
    eta_date = db.Column(db.DateTime)  # Predicted convergence date
    confidence_band_iqr = db.Column(db.Float)  # IQR stability band in days
    kendall_tau = db.Column(db.Float)  # Monotonicity test statistic
    kendall_pvalue = db.Column(db.Float)  # Statistical significance
    convergence_status = db.Column(db.String(20))  # CONVERGING, DIVERGING, STABLE, UNKNOWN
    notes = db.Column(db.Text)  # Additional metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ETAEstimate {self.eta_days:.2f} days as of {self.as_of_utc}>'

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'as_of_utc': self.as_of_utc.isoformat() if self.as_of_utc else None,
            'phase_gap_rad': self.phase_gap_rad,
            'phase_gap_degrees': self.phase_gap_degrees,
            'slope_rad_per_day': self.slope_rad_per_day,
            'slope_rad_per_sec': self.slope_rad_per_sec,
            'eta_days': self.eta_days,
            'eta_date': self.eta_date.isoformat() if self.eta_date else None,
            'confidence_band_iqr': self.confidence_band_iqr,
            'kendall_tau': self.kendall_tau,
            'kendall_pvalue': self.kendall_pvalue,
            'convergence_status': self.convergence_status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ConvergenceEvent(db.Model):
    """Model for recording actual convergence events when phase gap reaches zero"""
    id = db.Column(db.Integer, primary_key=True)
    event_utc = db.Column(db.DateTime, nullable=False)  # When convergence occurred
    phase_gap_at_event = db.Column(db.Float)  # Phase gap at the event (should be near 0)
    predicted_utc = db.Column(db.DateTime)  # When it was predicted to occur
    prediction_error_hours = db.Column(db.Float)  # Difference between predicted and actual
    gti_value = db.Column(db.Float)  # GTI value at convergence
    coherence = db.Column(db.Float)  # Coherence at convergence
    evidence_data = db.Column(db.Text)  # JSON with supporting measurements
    verification_status = db.Column(db.String(20))  # CONFIRMED, PROBABLE, FALSE_POSITIVE
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ConvergenceEvent at {self.event_utc}>'

    def get_evidence(self):
        """Parse the JSON evidence data"""
        try:
            return json.loads(self.evidence_data) if self.evidence_data else {}
        except:
            return {}

    def set_evidence(self, data):
        """Set evidence data as JSON string"""
        self.evidence_data = json.dumps(data)
