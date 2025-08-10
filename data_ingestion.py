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
        """Ingest TAI/UTC offset data from BIPM files"""
        # Read from real BIPM data files
        bipm_file = "data/bipm/utcrlab.all"
        if os.path.exists(bipm_file):
            return self._parse_bipm_data(bipm_file)
        else:
            logger.warning("No BIPM data file found")
            return []

    def _ingest_gnss_data(self):
        """Ingest GNSS clock data from IGS products"""
        # Look for IGS clock files or processed GNSS data
        gnss_file = "data/gnss/clock_data.csv"
        if os.path.exists(gnss_file):
            return self._load_synthetic_data('gnss')
        else:
            logger.warning("No GNSS data file found")
            return []

    def _ingest_vlbi_data(self):
        """Ingest VLBI delay residuals"""
        # Look for VLBI data files
        vlbi_file = "data/vlbi/delays.csv"
        if os.path.exists(vlbi_file):
            return self._load_synthetic_data('vlbi')
        else:
            logger.warning("No VLBI data file found")
            return []

    def _ingest_pta_data(self):
        """Ingest Pulsar Timing Array TOA residuals"""
        # Look for PTA data files
        pta_file = "data/pta/residuals.csv"
        if os.path.exists(pta_file):
            return self._load_synthetic_data('pta')
        else:
            logger.warning("No PTA data file found")
            return []

    def _parse_bipm_data(self, filepath):
        """Parse BIPM UTC(lab) data"""
        try:
            data_points = []
            with open(filepath, 'r') as f:
                for line in f:
                    # Parse BIPM format - adjust based on actual format
                    if line.strip() and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                # Assuming first column is MJD, second is offset
                                mjd = float(parts[0])
                                offset = float(parts[1])
                                # Convert MJD to Unix timestamp
                                timestamp = (mjd - 40587.0) * 86400.0
                                data_points.append((timestamp, offset))
                            except ValueError:
                                continue
            logger.info(f"Loaded {len(data_points)} BIPM data points")
            return data_points
        except Exception as e:
            logger.error(f"Error parsing BIPM data: {str(e)}")
            return []

    def _load_synthetic_data(self, stream_type):
        """Load data from CSV files only - no synthetic generation"""
        try:
            data_file = f"data/stream_{stream_type}.csv"
            if os.path.exists(data_file):
                data = np.loadtxt(data_file, delimiter=',')
                # Convert to list of (timestamp, value) tuples
                return [(row[0], row[1]) for row in data]
            else:
                logger.warning(f"No data file found for {stream_type} at {data_file}")
                return []
        except Exception as e:
            logger.error(f"Error loading data for {stream_type}: {str(e)}")
            return []