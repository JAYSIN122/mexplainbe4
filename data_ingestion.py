"""
Data ingestion module for various timing data sources
"""

import numpy as np
import logging
from datetime import datetime, timedelta
import os

try:
    from config_loader import config
except ImportError:
    # Fallback if config_loader not available
    config = None

logger = logging.getLogger(__name__)

class DataIngestion:
    def __init__(self):
        """Initialize data ingestion system"""
        self.data_sources = {
            'TAI': self._ingest_tai_data,
        }

        self.disabled_sources = []

        # Check GNSS enablement via config
        if self._is_source_enabled('GNSS'):
            gnss_file = "data/gnss/clock_data.csv"
            if os.getenv("GNSS_API_KEY") or os.path.exists(gnss_file):
                self.data_sources['GNSS'] = self._ingest_gnss_data
            else:
                logger.warning("GNSS ingest enabled but missing GNSS_API_KEY or data file")
                self.disabled_sources.append('GNSS')
        else:
            logger.info("GNSS stream disabled via configuration")
            self.disabled_sources.append('GNSS')

        # Check VLBI enablement via config
        if self._is_source_enabled('VLBI'):
            vlbi_file = "data/vlbi/delays.csv"
            if os.getenv("VLBI_API_KEY") or os.path.exists(vlbi_file):
                self.data_sources['VLBI'] = self._ingest_vlbi_data
            else:
                logger.warning("VLBI ingest enabled but missing VLBI_API_KEY or data file")
                self.disabled_sources.append('VLBI')
        else:
            logger.info("VLBI stream disabled via configuration")
            self.disabled_sources.append('VLBI')

        # Check PTA enablement via config
        if self._is_source_enabled('PTA'):
            pta_file = "data/pta/residuals.csv"
            if os.getenv("PTA_API_KEY") or os.path.exists(pta_file):
                self.data_sources['PTA'] = self._ingest_pta_data
            else:
                logger.warning("PTA ingest enabled but missing PTA_API_KEY or data file")
                self.disabled_sources.append('PTA')
        else:
            logger.info("PTA stream disabled via configuration")
            self.disabled_sources.append('PTA')

    def _is_source_enabled(self, source_type):
        """Check if a data source is enabled via config or environment variables"""
        # Environment variable takes precedence
        env_var = f"INGEST_{source_type.upper()}"
        if os.getenv(env_var) == "1":
            return True
        
        # Fall back to config file if available
        if config and hasattr(config, 'is_ingestion_enabled'):
            return config.is_ingestion_enabled(source_type)
        
        # Default to disabled if no config available
        return False

    def ingest_all_streams(self):
        """Ingest data from all available sources"""
        stream_data = {}

        for disabled in getattr(self, 'disabled_sources', []):
            logger.info(f"{disabled} stream disabled; skipping ingestion")

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
        """Ingest TAI/UTC offset data from REAL BIPM files ONLY"""
        bipm_file = "data/bipm/utcrlab.all"
        if os.path.exists(bipm_file):
            return self._parse_bipm_data(bipm_file)
        else:
            logger.info("No BIPM data file found - no data returned")
            return []

    def _ingest_gnss_data(self):
        """Ingest GNSS clock data from IGS products"""
        # Look for real IGS clock files only
        gnss_file = "data/gnss/clock_data.csv"
        if os.path.exists(gnss_file):
            return self._load_csv_data(gnss_file)
        else:
            logger.info("No GNSS data file found - no data returned")
            return []

    def _ingest_vlbi_data(self):
        """Ingest VLBI delay residuals"""
        # Look for real VLBI data files only
        vlbi_file = "data/vlbi/delays.csv"
        if os.path.exists(vlbi_file):
            return self._load_csv_data(vlbi_file)
        else:
            logger.info("No VLBI data file found - no data returned")
            return []

    def _ingest_pta_data(self):
        """Ingest Pulsar Timing Array TOA residuals"""
        # Look for real PTA data files only
        pta_file = "data/pta/residuals.csv"
        if os.path.exists(pta_file):
            return self._load_csv_data(pta_file)
        else:
            logger.info("No PTA data file found - no data returned")
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

    def _load_csv_data(self, filepath):
        """Load data from CSV files"""
        try:
            data = np.loadtxt(filepath, delimiter=',')
            # Convert to list of (timestamp, value) tuples
            return [(row[0], row[1]) for row in data]
        except Exception as e:
            logger.error(f"Error loading CSV data from {filepath}: {str(e)}")
            return []
