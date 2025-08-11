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
