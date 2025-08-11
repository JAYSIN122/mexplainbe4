
#!/usr/bin/env python3
"""
Mesh Network NTP Monitor for GTI System
Provides decentralized timing anomaly detection via NTP peer monitoring
"""

import time
import statistics
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

try:
    import ntplib
except ImportError:
    ntplib = None
    logger.warning("ntplib not available - mesh monitoring disabled")

class MeshMonitor:
    def __init__(self, peers: List[str], interval: int = 60, http_peers: Optional[List[str]] = None):
        """
        Initialize mesh monitor

        Args:
            peers: List of NTP server hostnames or IPs
            interval: Seconds between measurements
            http_peers: Optional list of HTTP time API URLs for fallback
        """
        self.peers = peers
        self.interval = interval
        self.http_peers = http_peers or []
        self.history = []  # list of (timestamp, phase_gap, slope) tuples
        self.baseline_window = 24 * 60 * 60  # 24 hours for baseline calculation
        
    def poll_peers(self) -> List[float]:
        """Poll all NTP peers and return list of offsets"""
        if not ntplib:
            return []
            
        client = ntplib.NTPClient()
        offsets = []
        
        # Fallback IP addresses for common NTP servers
        ip_fallbacks = {
            'pool.ntp.org': ['162.159.200.1', '162.159.200.123', '208.67.222.222'],
            'time.nist.gov': ['129.6.15.28', '129.6.15.29', '132.163.96.1'],
            'time.google.com': ['216.239.35.0', '216.239.35.4', '216.239.35.8', '216.239.35.12'],
            'ptbtime1.ptb.de': ['192.53.103.108', '192.53.103.104']
        }
        
        for peer in self.peers:
            success = False
            # First try the hostname
            try:
                response = client.request(peer, version=3, timeout=5)
                offsets.append(response.offset)
                logger.debug(f"NTP peer {peer}: offset={response.offset:.6f}s")
                success = True
            except Exception as e:
                logger.debug(f"Hostname failed for {peer}: {type(e).__name__}: {e}")

            # If hostname failed, try IP fallbacks
            if not success and peer in ip_fallbacks:
                for ip in ip_fallbacks[peer]:
                    try:
                        response = client.request(ip, version=3, timeout=5)
                        offsets.append(response.offset)
                        logger.debug(f"NTP peer {peer} (IP {ip}): offset={response.offset:.6f}s")
                        success = True
                        break
                    except Exception as e:
                        logger.debug(f"IP fallback {ip} failed for {peer}: {type(e).__name__}: {e}")

            if not success:
                logger.warning(f"Failed to poll NTP peer {peer}: all attempts failed")

        # If all NTP polls failed, try HTTP-based time APIs
        if not offsets and self.http_peers:
            logger.info("Attempting HTTP time API polling as fallback")
            # Import here to avoid circular dependency
            from app import db
            from models import MeshObservation

            for url in self.http_peers:
                result = self.poll_http_peer(url)
                if not result:
                    continue
                offset, rtt, server_time, headers = result
                offsets.append(offset)

                # Record observation
                try:
                    obs = MeshObservation(
                        peer=url,
                        protocol='http',
                        offset=offset,
                        rtt_ms=rtt * 1000.0,
                        server_time=server_time,
                        details=json.dumps({'headers': headers})
                    )
                    db.session.add(obs)
                    db.session.commit()
                except Exception as e:
                    logger.warning(f"Failed to record HTTP observation for {url}: {e}")

                logger.info(
                    f"HTTP peer {url}: offset={offset:.6f}s rtt={rtt*1000.0:.1f}ms"
                )

        return offsets

    def poll_http_peer(self, peer_url: str) -> Optional[Tuple[float, float, datetime, Dict]]:
        """Poll an HTTP time API and return offset and round-trip time."""
        try:
            start = time.time()
            response = requests.get(peer_url, timeout=5)
            rtt = time.time() - start

            server_now = None
            if 'Date' in response.headers:
                try:
                    server_now = dateparser.parse(response.headers['Date'])
                except Exception:
                    server_now = None

            if server_now is None:
                try:
                    data = response.json()
                    for key in ['datetime', 'utc_datetime', 'currentDateTime']:
                        if key in data:
                            server_now = dateparser.parse(data[key])
                            break
                except Exception:
                    server_now = None

            if server_now is None:
                logger.warning(f"HTTP peer {peer_url} did not provide parsable time")
                return None

            local_now = datetime.now(timezone.utc)
            offset = (server_now - local_now).total_seconds()
            return offset, rtt, server_now, dict(response.headers)
        except Exception as e:
            logger.warning(f"HTTP poll failed for {peer_url}: {e}")
            return None
    
    def calculate_baseline(self) -> float:
        """Calculate baseline from recent history"""
        if not self.history:
            return 0.0
            
        # Use last 24 hours of data for baseline
        cutoff_time = time.time() - self.baseline_window
        recent_gaps = [gap for ts, gap, _ in self.history if ts > cutoff_time]
        
        if not recent_gaps:
            return 0.0
            
        return statistics.mean(recent_gaps)
    
    def update(self) -> Optional[Dict]:
        """Update mesh monitoring data"""
        offsets = self.poll_peers()
        if not offsets:
            logger.warning(f"No NTP peer responses received from {len(self.peers)} configured peers")
            # In fallback mode, return a status indicating connectivity issues
            return {
                'timestamp': datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat(),
                'phase_gap': 0.0,
                'slope': 0.0,
                'median_offset': 0.0,
                'baseline': 0.0,
                'peer_count': 0,
                'eta_days': None,
                'status': 'network_unreachable',
                'message': 'All NTP peers unreachable - possible network connectivity issue'
            }
        
        logger.info(f"Successfully polled {len(offsets)} out of {len(self.peers)} NTP peers")
            
        # Calculate current phase gap
        median_offset = statistics.median(offsets)
        baseline = self.calculate_baseline()
        phase_gap = median_offset - baseline
        
        # Calculate slope (rate of change)
        slope = 0.0
        if len(self.history) >= 1:
            last_ts, last_gap, _ = self.history[-1]
            dt = time.time() - last_ts
            if dt > 0:
                slope = (phase_gap - last_gap) / dt
        
        # Store measurement
        timestamp = time.time()
        self.history.append((timestamp, phase_gap, slope))
        
        # Trim old history (keep last 7 days)
        cutoff = timestamp - (7 * 24 * 60 * 60)
        self.history = [(ts, gap, sl) for ts, gap, sl in self.history if ts > cutoff]
        
        result = {
            'timestamp': datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
            'phase_gap': float(phase_gap),
            'slope': float(slope),
            'median_offset': float(median_offset),
            'baseline': float(baseline),
            'peer_count': len(offsets),
            'eta_days': self.estimate_eta_days()
        }
        
        logger.info(f"Mesh update: phase_gap={phase_gap:.6f}s, slope={slope:.9f}s/s, eta={result['eta_days']}")
        return result
    
    def estimate_eta_days(self) -> Optional[float]:
        """Estimate days until phase gap converges to zero"""
        if not self.history:
            return None
            
        _, phase_gap, slope = self.history[-1]
        
        # Only predict if converging (negative slope)
        if slope >= 0:
            return None
            
        eta_seconds = abs(phase_gap) / abs(slope)
        return eta_seconds / 86400.0  # Convert to days
    
    def get_status(self) -> Dict:
        """Get current mesh monitor status"""
        if not self.history:
            return {
                'active': False,
                'message': 'No measurements available'
            }
            
        latest = self.history[-1]
        return {
            'active': True,
            'timestamp': datetime.fromtimestamp(latest[0], tz=timezone.utc).isoformat(),
            'phase_gap': float(latest[1]),
            'slope': float(latest[2]),
            'eta_days': self.estimate_eta_days(),
            'peer_count': len(self.peers),
            'measurement_count': len(self.history)
        }
    
    def save_history(self, path: Path):
        """Save mesh history to file"""
        data = {
            'mesh_history': [
                {
                    'timestamp': datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    'phase_gap': float(gap),
                    'slope': float(slope)
                }
                for ts, gap, slope in self.history
            ]
        }
        
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
    
    def load_history(self, path: Path):
        """Load mesh history from file"""
        if not path.exists():
            return
            
        try:
            data = json.loads(path.read_text())
            self.history = []
            
            for entry in data.get('mesh_history', []):
                ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00')).timestamp()
                gap = float(entry['phase_gap'])
                slope = float(entry['slope'])
                self.history.append((ts, gap, slope))
                
            logger.info(f"Loaded {len(self.history)} mesh history entries")
            
        except Exception as e:
            logger.error(f"Failed to load mesh history: {e}")


# Default NTP peers (public time servers with IP fallbacks)
DEFAULT_NTP_PEERS = [
    '129.6.15.28',      # NIST time server IP (primary)
    '216.239.35.0',     # Google time server IP
    '162.159.200.1',    # Cloudflare NTP IP  
    '208.67.222.222',   # OpenDNS NTP
    'time.nist.gov',    # NIST hostname
    'time.google.com'   # Google hostname
]

# Default HTTP time APIs for fallback polling
DEFAULT_HTTP_PEERS = [
    'https://worldtimeapi.org/api/timezone/Etc/UTC'
]

def create_mesh_monitor(
    peers: Optional[List[str]] = None,
    interval: int = 60,
    http_peers: Optional[List[str]] = None,
) -> MeshMonitor:
    """Create a mesh monitor with default or custom peers"""
    if peers is None:
        peers = DEFAULT_NTP_PEERS
    if http_peers is None:
        http_peers = DEFAULT_HTTP_PEERS

    return MeshMonitor(peers, interval, http_peers)
