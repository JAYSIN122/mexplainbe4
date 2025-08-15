"""
Data ingestion module for various timing data sources
"""

import numpy as np
import logging
from datetime import datetime, timedelta
import os
import requests
from pathlib import Path

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
            self.data_sources['GNSS'] = self._ingest_gnss_data
        else:
            logger.info("GNSS stream disabled via configuration")
            self.disabled_sources.append('GNSS')

        # Check VLBI enablement via config
        if self._is_source_enabled('VLBI'):
            self.data_sources['VLBI'] = self._ingest_vlbi_data
        else:
            logger.info("VLBI stream disabled via configuration")
            self.disabled_sources.append('VLBI')

        # Check PTA enablement via config
        if self._is_source_enabled('PTA'):
            self.data_sources['PTA'] = self._ingest_pta_data
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
        errors = {}

        for disabled in getattr(self, 'disabled_sources', []):
            logger.info(f"{disabled} stream disabled; skipping ingestion")

        for stream_type, ingest_func in self.data_sources.items():
            try:
                data = ingest_func()
                stream_data[stream_type] = data
                logger.info(
                    f"Successfully ingested {len(data)} points from {stream_type}"
                )
            except Exception as e:
                errors[stream_type] = str(e)
                logger.error(f"Error ingesting {stream_type} data: {str(e)}")

        if errors:
            missing = ", ".join(errors.keys())
            raise RuntimeError(f"Failed to ingest required streams: {missing}")

        return stream_data

    def _ingest_tai_data(self):
        """Ingest TAI/UTC offset data from REAL BIPM files ONLY"""
        bipm_file = "data/bipm/utcrlab.all"
        if os.path.exists(bipm_file) and os.path.getsize(bipm_file) > 0:
            data = self._parse_bipm_data(bipm_file)
            if not data:
                raise ValueError("Parsed BIPM data was empty")
            return data
        else:
            msg = "No real BIPM data file found or file is empty"
            logger.error(msg)
            raise FileNotFoundError(msg)

    def _ingest_gnss_data(self):
        """Ingest GNSS clock data from authentic datasets"""
        gnss_file = "data/gnss/clock_data.csv"
        if os.path.exists(gnss_file):
            data = self._load_csv_data(gnss_file)
            if not data:
                raise ValueError(f"Failed to load GNSS data from {gnss_file}")
            return data
        else:
            msg = "No GNSS authentic dataset found"
            logger.error(msg)
            raise FileNotFoundError(msg)

    def _ingest_vlbi_data(self):
        """Ingest VLBI delay residuals from authentic datasets"""
        vlbi_file = "data/vlbi/delays.csv"
        if os.path.exists(vlbi_file):
            data = self._load_csv_data(vlbi_file)
            if not data:
                raise ValueError(f"Failed to load VLBI data from {vlbi_file}")
            return data
        else:
            msg = "No VLBI authentic dataset found"
            logger.error(msg)
            raise FileNotFoundError(msg)

    def _ingest_pta_data(self):
        """Ingest Pulsar Timing Array TOA residuals from authentic datasets"""
        pta_file = "data/pta/residuals.csv"
        if os.path.exists(pta_file):
            data = self._load_csv_data(pta_file)
            if not data:
                raise ValueError(f"Failed to load PTA data from {pta_file}")
            return data
        else:
            msg = "No PTA authentic dataset found"
            logger.error(msg)
            raise FileNotFoundError(msg)

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
            # Skip empty line and header row (first 2 rows)
            data = np.loadtxt(filepath, delimiter=',', skiprows=2)
            # Convert to list of (timestamp, value) tuples with Python native types
            return [(float(row[0]), float(row[1])) for row in data]
        except Exception as e:
            logger.error(f"Error loading CSV data from {filepath}: {str(e)}")
            return []

    def _fetch_igs_clock_data(self):
        """Fetch real IGS GPS clock data from CDDIS archive"""
        try:
            # IGS Final Clock Products (sp3 format)
            base_url = "https://cddis.nasa.gov/archive/gnss/products"

            # Get current GPS week
            gps_epoch = datetime(1980, 1, 6)
            now = datetime.utcnow()
            days_since_epoch = (now - gps_epoch).days
            gps_week = days_since_epoch // 7

            # Fetch recent final products (typically 2 weeks behind)
            url = f"{base_url}/{gps_week-2:04d}/igs{gps_week-2:04d}7.clk.Z"

            logger.info(f"Fetching IGS clock data from: {url}")
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                # Parse IGS clock format and save to CSV
                return self._parse_igs_clock_file(response.content)
            else:
                logger.warning(f"Failed to fetch IGS data: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error fetching IGS data: {str(e)}")
            return False

    def _fetch_ivs_vlbi_data(self):
        """Fetch real VLBI data from IVS Data Centers"""
        try:
            # IVS database for EOP and delays
            base_url = "https://ivscc.gsfc.nasa.gov/products-data/data.html"

            # Fetch recent session results
            url = f"{base_url}/eops/eop.txt"

            logger.info(f"Fetching IVS VLBI data from: {url}")
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                return self._parse_ivs_eop_file(response.text)
            else:
                logger.warning(f"Failed to fetch IVS data: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error fetching IVS data: {str(e)}")
            return False

    def _fetch_pta_data(self):
        """Fetch real PTA timing residuals from NANOGrav/EPTA/PPTA"""
        try:
            # NANOGrav public data releases
            base_url = "https://data.nanograv.org"

            # Fetch recent timing residuals
            url = f"{base_url}/releases/15yr/timing_residuals.txt"

            logger.info(f"Fetching NANOGrav PTA data from: {url}")
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                return self._parse_nanograv_residuals(response.text)
            else:
                logger.warning(f"Failed to fetch NANOGrav data: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error fetching PTA data: {str(e)}")
            return False

    def _parse_igs_clock_file(self, content):
        """Parse IGS clock file format"""
        try:
            # Create output directory
            Path("data/gnss").mkdir(parents=True, exist_ok=True)

            # Simple parsing - extract satellite clock offsets
            lines = content.decode('utf-8').splitlines()
            data_points = []

            for line in lines:
                if line.startswith('AS '):  # Clock record
                    parts = line.split()
                    if len(parts) >= 6:
                        # Extract MJD and clock offset
                        mjd = float(parts[2])
                        offset_ns = float(parts[5]) * 1e9  # Convert to nanoseconds
                        timestamp = (mjd - 40587.0) * 86400.0
                        data_points.append([timestamp, offset_ns])

            # Save to CSV
            if data_points:
                np.savetxt("data/gnss/clock_data.csv", data_points, delimiter=',')
                logger.info(f"Saved {len(data_points)} GNSS data points")
                return True
            return False

        except Exception as e:
            logger.error(f"Error parsing IGS clock data: {str(e)}")
            return False

    def _parse_ivs_eop_file(self, content):
        """Parse IVS EOP file for VLBI delays"""
        try:
            # Create output directory
            Path("data/vlbi").mkdir(parents=True, exist_ok=True)

            lines = content.splitlines()
            data_points = []

            for line in lines:
                if not line.strip() or line.startswith('#'):
                    continue

                parts = line.split()
                if len(parts) >= 8:
                    # Extract MJD and UT1-UTC (proxy for timing delays)
                    mjd = float(parts[0])
                    ut1_utc_ms = float(parts[6]) * 1000  # Convert to milliseconds
                    timestamp = (mjd - 40587.0) * 86400.0
                    data_points.append([timestamp, ut1_utc_ms])

            # Save to CSV
            if data_points:
                np.savetxt("data/vlbi/delays.csv", data_points, delimiter=',')
                logger.info(f"Saved {len(data_points)} VLBI data points")
                return True
            return False

        except Exception as e:
            logger.error(f"Error parsing IVS data: {str(e)}")
            return False

    def _parse_nanograv_residuals(self, content):
        """Parse NANOGrav timing residuals"""
        try:
            # Create output directory
            Path("data/pta").mkdir(parents=True, exist_ok=True)

            lines = content.splitlines()
            data_points = []

            for line in lines:
                if not line.strip() or line.startswith('#'):
                    continue

                parts = line.split()
                if len(parts) >= 4:
                    # Extract MJD and residual
                    mjd = float(parts[0])
                    residual_us = float(parts[3]) * 1e6  # Convert to microseconds
                    timestamp = (mjd - 40587.0) * 86400.0
                    data_points.append([timestamp, residual_us])

            # Save to CSV
            if data_points:
                np.savetxt("data/pta/residuals.csv", data_points, delimiter=',')
                logger.info(f"Saved {len(data_points)} PTA data points")
                return True
            return False

        except Exception as e:
            logger.error(f"Error parsing PTA data: {str(e)}")
            return False

