"""
Data ingestion module for various timing data sources
"""

import numpy as np
import logging
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)

class DataIngestion:
    def __init__(self):
        """Initialize data ingestion system"""
        self.data_sources = {
            'TAI': self._ingest_tai_data,
            'GNSS': self._ingest_gnss_data,
            'VLBI': self._ingest_vlbi_data,
            'PTA': self._ingest_pta_data
        }
    
    def ingest_all_streams(self):
        """Ingest data from all available sources"""
        stream_data = {}
        
        for stream_type, ingest_func in self.data_sources.items():
            try:
                data = ingest_func()
                if data:
                    stream_data[stream_type] = data
                    logger.info(f"Successfully ingested {len(data)} points from {stream_type}")
                else:
                    logger.warning(f"No data available for {stream_type}")
            except Exception as e:
                logger.error(f"Error ingesting {stream_type} data: {str(e)}")
        
        return stream_data
    
    def _ingest_tai_data(self):
        """Ingest TAI/UTC offset data from BIPM Circular-T"""
        # In production, this would connect to BIPM data sources
        # For now, we'll check if synthetic data exists
        return self._load_synthetic_data('tai')
    
    def _ingest_gnss_data(self):
        """Ingest GNSS clock data from IGS products"""
        # In production, this would connect to IGS data streams
        return self._load_synthetic_data('gnss')
    
    def _ingest_vlbi_data(self):
        """Ingest VLBI delay residuals"""
        # In production, this would connect to VLBI networks
        return self._load_synthetic_data('vlbi')
    
    def _ingest_pta_data(self):
        """Ingest Pulsar Timing Array TOA residuals"""
        # In production, this would connect to PTA data sources
        return self._load_synthetic_data('pta')
    
    def _load_synthetic_data(self, stream_type):
        """Load synthetic data if available"""
        try:
            data_file = f"data/stream_{stream_type}.csv"
            if os.path.exists(data_file):
                data = np.loadtxt(data_file, delimiter=',')
                # Convert to list of (timestamp, value) tuples
                return [(row[0], row[1]) for row in data]
            else:
                # Generate minimal synthetic data for demonstration
                return self._generate_minimal_synthetic(stream_type)
        except Exception as e:
            logger.error(f"Error loading data for {stream_type}: {str(e)}")
            return []
    
    def _generate_minimal_synthetic(self, stream_type):
        """Generate minimal synthetic data for testing"""
        logger.info(f"Generating minimal synthetic data for {stream_type}")
        
        # Create 100 data points over the last 24 hours
        n_points = 100
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        
        timestamps = []
        values = []
        
        for i in range(n_points):
            # Linear interpolation of time
            t = start_time + (end_time - start_time) * i / (n_points - 1)
            timestamp = t.timestamp()
            
            # Generate synthetic value with some physics-inspired characteristics
            base_freq = 1.0 / (3600 * 24)  # Daily cycle
            noise_level = 1e-12
            
            # Different streams have different characteristics
            if stream_type == 'tai':
                # TAI data - very stable with small variations
                value = noise_level * 0.1 * np.sin(2 * np.pi * base_freq * timestamp)
            elif stream_type == 'gnss':
                # GNSS - more variation due to atmospheric effects
                value = noise_level * np.sin(2 * np.pi * base_freq * timestamp) + \
                       noise_level * 0.5 * np.random.normal()
            elif stream_type == 'vlbi':
                # VLBI - similar to GNSS but different phase
                value = noise_level * np.sin(2 * np.pi * base_freq * timestamp + np.pi/4) + \
                       noise_level * 0.3 * np.random.normal()
            elif stream_type == 'pta':
                # PTA - lower frequency variations
                value = noise_level * 0.5 * np.sin(2 * np.pi * base_freq * 0.1 * timestamp) + \
                       noise_level * 0.2 * np.random.normal()
            else:
                value = noise_level * np.random.normal()
            
            timestamps.append(timestamp)
            values.append(value)
        
        return list(zip(timestamps, values))
