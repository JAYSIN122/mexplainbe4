"""
Flask routes for the temporal monitoring system
"""

from flask import render_template, jsonify, request, flash, redirect, url_for
from app import app, db
from models import DataStream, GTICalculation, ProcessingConfiguration, AnalysisResult
from gti_pipeline import GTIPipeline
from data_ingestion import DataIngestion
from signal_processing import SignalProcessor
from bayesian_analysis import BayesianAnalyzer
import json
import logging
import subprocess
import traceback
import hashlib
import socket
import time
import os
from datetime import datetime, timedelta
import numpy as np
import requests
from pathlib import Path
from datetime import timezone

logger = logging.getLogger(__name__)

def _load_phase_history():
    p = Path("artifacts/phase_gap_history.json")
    if not p.exists():
        return [], []
    try:
        obj = json.loads(p.read_text())
        H = obj.get("history", [])
        out = []
        for h in H:
            ts = h.get("as_of_utc")
            val = h.get("phase_deg")
            if ts is None or val is None:
                continue
            try:
                t = datetime.fromisoformat(ts.replace("Z","+00:00"))
            except Exception:
                continue
            out.append((t, float(val)))
        out.sort(key=lambda x: x[0])
        t_list = [t for t, _ in out]
        deg_list = [deg for _, deg in out]
        return t_list, deg_list
    except Exception:
        return [], []

def _get_latest_gti():
    try:
        return GTICalculation.query.order_by(GTICalculation.timestamp.desc()).first()
    except Exception:
        return None

def _unwrap_deg_to_rad(deg_series):
    rad = np.deg2rad(np.array(deg_series, dtype=float))
    return np.unwrap(rad)

def _robust_fit_eta(t_list, phase_rad, min_days=150, max_days=300):
    if len(t_list) < 20:
        return None
    t_end = t_list[-1]
    t_start = t_end - timedelta(days=max_days)
    idx = [i for i, t in enumerate(t_list) if t >= t_start]
    if len(idx) < 20:
        idx = list(range(max(0, len(t_list)-200), len(t_list)))
    t_sel = [t_list[i] for i in idx]
    y = phase_rad[idx]
    t0 = t_sel[0]
    x = np.array([(t - t0).total_seconds() / 86400.0 for t in t_sel], dtype=float)
    for _ in range(2):
        coeffs = np.polyfit(x, y, 1)
        m, b = coeffs[0], coeffs[1]
        yhat = m*x + b
        resid = y - yhat
        q1, q3 = np.percentile(resid, [5, 95])
        keep = (resid >= q1) & (resid <= q3)
        x, y = x[keep], y[keep]
        if len(x) < 10:
            break
    coeffs = np.polyfit(x, y, 1)
    m, b = coeffs[0], coeffs[1]
    phi_now = float(y[-1])
    if m >= 0:
        return None
    eta_days = abs(phi_now) / (-m)
    return {"eta_days": float(eta_days)}

# Global exception storage
_last_exception_text = None

# Allowed hosts for /api/ping
ALLOWED_HOSTS = [
    'webtai.bipm.org',
    'datacenter.iers.org',
    'hpiers.obspm.fr',
    'tai.bipm.org'
]


def make_serializable(obj):
    """Recursively convert NumPy arrays and scalars to native Python types."""
    if isinstance(obj, np.ndarray):
        return [make_serializable(x) for x in obj.tolist()]

    if isinstance(obj, np.generic):
        return obj.item()

    if isinstance(obj, dict):
        return {key: make_serializable(value) for key, value in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [make_serializable(item) for item in obj]

    return obj

# Initialize processors
pipeline = GTIPipeline()
data_ingestion = DataIngestion()
signal_processor = SignalProcessor()
bayesian_analyzer = BayesianAnalyzer()

# Initialize mesh monitor if enabled
mesh_monitor = None
if app.config.get("USE_MESH_MONITOR"):
    try:
        from mesh_monitor import create_mesh_monitor
        mesh_monitor = create_mesh_monitor(
            peers=app.config.get("MESH_PEERS"),
            interval=app.config.get("MESH_INTERVAL", 60)
        )
        # Load existing history
        from pathlib import Path
        mesh_history_path = Path("artifacts/mesh_history.json")
        mesh_monitor.load_history(mesh_history_path)
        logger.info("Mesh monitor initialized")
    except Exception as e:
        logger.error(f"Failed to initialize mesh monitor: {e}")
        mesh_monitor = None

@app.route('/')
def dashboard():
    """Main dashboard view"""
    try:
        from models import ETAEstimate
        
        # Get latest GTI calculation
        latest_gti = _get_latest_gti()

        # Get recent GTI history for trending
        recent_gtis = GTICalculation.query.order_by(GTICalculation.timestamp.desc()).limit(100).all()
        
        # Get latest ETA estimate
        latest_eta = ETAEstimate.query.order_by(ETAEstimate.as_of_utc.desc()).first()

        # Get data stream status
        stream_status = {}
        for stream_type in ['TAI', 'GNSS', 'VLBI', 'PTA']:
            latest_data = DataStream.query.filter_by(stream_type=stream_type)\
                .order_by(DataStream.timestamp.desc()).first()

            if latest_data:
                time_diff = datetime.utcnow() - latest_data.timestamp
                stream_status[stream_type] = {
                    'status': 'active' if time_diff.total_seconds() < 3600 else 'stale',
                    'last_update': latest_data.timestamp.isoformat(),
                    'latest_value': latest_data.value
                }
            else:
                stream_status[stream_type] = {
                    'status': 'offline',
                    'last_update': None,
                    'latest_value': None
                }

        return render_template('dashboard.html', 
                             latest_gti=latest_gti,
                             recent_gtis=recent_gtis,
                             stream_status=stream_status,
                             latest_eta=latest_eta)

    except Exception as e:
        logger.error(f"Error rendering dashboard: {str(e)}")
        flash(f"Error loading dashboard: {str(e)}", 'error')
        return render_template('dashboard.html', 
                             latest_gti=None,
                             recent_gtis=[],
                             stream_status={},
                             latest_eta=None)

@app.route('/configuration')
def configuration():
    """Configuration management view"""
    try:
        # Get all configuration parameters
        configs = ProcessingConfiguration.query.all()
        config_dict = {config.parameter_name: config for config in configs}

        return render_template('configuration.html', configurations=config_dict)

    except Exception as e:
        logger.error(f"Error rendering configuration: {str(e)}")
        flash(f"Error loading configuration: {str(e)}", 'error')
        return render_template('configuration.html', configurations={})

@app.route('/api/mesh_status')
def mesh_status():
    """Get mesh network monitoring status"""
    try:
        import os
        from app import mesh_monitor
        
        # Check if using HTTP mesh
        if os.getenv("MESH_USE_HTTP", "true").lower() == "true":
            # Get recent HTTP mesh observations from database
            from models import MeshObservation
            from datetime import datetime, timedelta
            
            recent_cutoff = datetime.utcnow() - timedelta(minutes=10)
            recent_obs = MeshObservation.query.filter(
                MeshObservation.created_at > recent_cutoff,
                MeshObservation.protocol == 'http-date'
            ).order_by(MeshObservation.created_at.desc()).limit(50).all()
            
            if not recent_obs:
                return jsonify({
                    'active': False,
                    'message': 'No recent HTTP mesh observations'
                })
            
            # Calculate current stats
            offsets = [obs.offset for obs in recent_obs]
            if offsets:
                import statistics
                median_offset = statistics.median(offsets)
                phase_gap = median_offset  # Simplified for now
                
                # Estimate slope from recent data
                if len(recent_obs) >= 2:
                    latest = recent_obs[0]
                    older = recent_obs[-1]
                    dt = (latest.created_at - older.created_at).total_seconds()
                    slope = (latest.offset - older.offset) / dt if dt > 0 else 0.0
                else:
                    slope = 0.0
                
                return jsonify({
                    'active': True,
                    'timestamp': recent_obs[0].created_at.isoformat() + 'Z',
                    'phase_gap': phase_gap,
                    'slope': slope,
                    'median_offset': median_offset,
                    'peer_count': len(set(obs.peer for obs in recent_obs)),
                    'eta_days': abs(phase_gap / slope) / 86400.0 if slope < 0 else None,
                    'protocol': 'http-date'
                })
            else:
                return jsonify({
                    'active': False,
                    'message': 'No HTTP mesh data available'
                })
        
        # Fall back to NTP mesh monitor
        if not mesh_monitor:
            return jsonify({
                'active': False,
                'message': 'Mesh monitoring not enabled'
            })

        # Update mesh data
        update_result = mesh_monitor.update()
        if update_result:
            # Save updated history
            from pathlib import Path
            mesh_history_path = Path("artifacts/mesh_history.json")
            mesh_monitor.save_history(mesh_history_path)

        status = mesh_monitor.get_status()
        return jsonify(status)

    except Exception as e:
        logger.error(f"Error in mesh status: {str(e)}")
        return jsonify({
            'active': False,
            'error': str(e)
        }), 500

@app.route('/api/mesh_update', methods=['POST'])
def mesh_update():
    """Manually trigger mesh monitor update"""
    try:
        from app import mesh_monitor

        if not mesh_monitor:
            return jsonify({
                'success': False,
                'message': 'Mesh monitoring not enabled'
            })

        result = mesh_monitor.update()
        if result:
            # Save history
            from pathlib import Path
            mesh_history_path = Path("artifacts/mesh_history.json")
            mesh_monitor.save_history(mesh_history_path)

            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No peer responses received'
            })

    except Exception as e:
        logger.error(f"Error in mesh update: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/analysis')
def analysis():
    """Analysis page with detailed GTI breakdown"""
    try:
        # Get recent analysis results
        coherence_results = AnalysisResult.query.filter_by(analysis_type='coherence')\
            .order_by(AnalysisResult.timestamp.desc()).limit(10).all()

        phase_results = AnalysisResult.query.filter_by(analysis_type='phase_analysis')\
            .order_by(AnalysisResult.timestamp.desc()).limit(10).all()

        bayesian_results = AnalysisResult.query.filter_by(analysis_type='bayesian')\
            .order_by(AnalysisResult.timestamp.desc()).limit(10).all()

        return render_template('analysis.html',
                             coherence_results=coherence_results,
                             phase_results=phase_results,
                             bayesian_results=bayesian_results)

    except Exception as e:
        logger.error(f"Error rendering analysis: {str(e)}")
        return f"Analysis page error: {str(e)}", 500


@app.route('/proof')
def proof():
    """Proof page showing evidence of convergence predictions"""
    try:
        from models import ETAEstimate, ConvergenceEvent
        
        # Get latest ETA estimate
        latest_eta = ETAEstimate.query.order_by(ETAEstimate.as_of_utc.desc()).first()
        
        # Get recent ETA history (last 30 estimates)
        eta_history = ETAEstimate.query.order_by(ETAEstimate.as_of_utc.desc()).limit(30).all()
        
        # Get convergence events
        convergence_events = ConvergenceEvent.query.order_by(ConvergenceEvent.event_utc.desc()).limit(10).all()
        
        # Get latest GTI calculation for data sources
        latest_gti = _get_latest_gti()
        
        # Get stream status
        stream_status = {}
        for stream_type in ['TAI', 'GNSS', 'VLBI', 'PTA']:
            latest_data = DataStream.query.filter_by(stream_type=stream_type)\
                .order_by(DataStream.timestamp.desc()).first()
            
            if latest_data:
                time_diff = datetime.utcnow() - latest_data.timestamp
                stream_status[stream_type] = {
                    'status': 'active' if time_diff.total_seconds() < 3600 else 'stale',
                    'last_update': latest_data.timestamp,
                    'latest_value': latest_data.value
                }
            else:
                stream_status[stream_type] = {
                    'status': 'offline',
                    'last_update': None,
                    'latest_value': None
                }
        
        return render_template('proof.html',
                             latest_eta=latest_eta,
                             eta_history=eta_history,
                             convergence_events=convergence_events,
                             latest_gti=latest_gti,
                             stream_status=stream_status)
    
    except Exception as e:
        logger.error(f"Error rendering proof page: {str(e)}")
        return f"Proof page error: {str(e)}", 500

@app.route('/api/ingest_data', methods=['POST'])
def api_ingest_data():
    """API endpoint to trigger data ingestion"""
    try:
        # Ingest data from all sources
        stream_data = data_ingestion.ingest_all_streams()

        if not stream_data:
            return jsonify({
                'success': False,
                'message': 'No data was ingested from any source'
            }), 400

        # Store ingested data in database only if we have data
        total_points = 0
        for stream_type, data in stream_data.items():
            if data:  # Only process streams with actual data
                for timestamp, value in data[-10:]:  # Store only last 10 points to avoid overflow
                    # Convert timestamp to datetime
                    dt = datetime.fromtimestamp(timestamp)

                    # Create new data point
                    data_point = DataStream()
                    data_point.stream_type = stream_type
                    data_point.timestamp = dt
                    data_point.value = value

                    db.session.add(data_point)
                    total_points += 1

        if total_points > 0:
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'Successfully ingested data from {len([k for k, v in stream_data.items() if v])} streams',
                'streams': [k for k, v in stream_data.items() if v],
                'data_points': {k: len(v) for k, v in stream_data.items() if v}
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No real data available to ingest - all data sources returned empty'
            }), 204

    except Exception as e:
        logger.error(f"Error in data ingestion API: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Data ingestion failed: {str(e)}'
        }), 500

@app.route('/api/run_analysis', methods=['POST'])
def api_run_analysis():
    """API endpoint to run GTI analysis"""
    try:
        # Get recent data from database
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        stream_data = {}
        for stream_type in ['TAI', 'GNSS', 'VLBI', 'PTA']:
            data_points = DataStream.query.filter_by(stream_type=stream_type)\
                .filter(DataStream.timestamp >= cutoff_time)\
                .order_by(DataStream.timestamp).all()

            if data_points:
                stream_data[stream_type] = [
                    (dp.timestamp.timestamp(), dp.value) for dp in data_points
                ]

        # If no recent data, try using all available archival data
        if not stream_data:
            logger.info("No recent data found, attempting to use archival data")
            for stream_type in ['TAI', 'GNSS', 'VLBI', 'PTA']:
                data_points = DataStream.query.filter_by(stream_type=stream_type)\
                    .order_by(DataStream.timestamp.desc()).limit(100).all()

                if data_points:
                    stream_data[stream_type] = [
                        (dp.timestamp.timestamp(), dp.value) for dp in data_points
                    ]

        if not stream_data:
            return jsonify({
                'success': False,
                'message': 'No data available for analysis'
            }), 400

        # Run GTI pipeline
        results = pipeline.process_streams(stream_data)

        # Store GTI calculation result
        gti_calc = GTICalculation()
        gti_calc.timestamp = datetime.fromisoformat(results['timestamp'].replace('Z', '+00:00'))
        gti_calc.gti_value = results['gti_value']
        gti_calc.phase_gap = results['phase_gap_degrees']
        gti_calc.coherence_median = results['coherence_median']
        gti_calc.variance_explained = results['variance_explained']
        gti_calc.bayes_factor = results['bayes_factor']
        gti_calc.time_to_overlap = results['time_to_overlap']
        gti_calc.alert_level = results['alert_level']

        db.session.add(gti_calc)

        # Store detailed analysis results
        for analysis_type, data in results['detailed_results'].items():
            analysis_result = AnalysisResult()
            analysis_result.timestamp = datetime.utcnow()
            analysis_result.analysis_type = analysis_type
            analysis_result.set_result_data(data)
            db.session.add(analysis_result)

        db.session.commit()

        return jsonify({
            'success': True,
            'results': make_serializable(results)
        })

    except Exception as e:
        logger.error(f"Error in analysis API: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Analysis failed: {str(e)}'
        }), 500

@app.route('/api/gti_history')
def api_gti_history():
    """API endpoint to get GTI history"""
    try:
        # Get query parameters
        hours = request.args.get('hours', 24, type=int)
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        # Query GTI calculations
        gti_calcs = GTICalculation.query.filter(GTICalculation.timestamp >= cutoff_time)\
            .order_by(GTICalculation.timestamp).all()

        # Format data for charting
        history_data = {
            'timestamps': [calc.timestamp.isoformat() for calc in gti_calcs],
            'gti_values': [calc.gti_value for calc in gti_calcs],
            'phase_gaps': [calc.phase_gap for calc in gti_calcs],
            'coherence_values': [calc.coherence_median for calc in gti_calcs],
            'alert_levels': [calc.alert_level for calc in gti_calcs]
        }

        return jsonify({
            'success': True,
            'data': history_data
        })

    except Exception as e:
        logger.error(f"Error in GTI history API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to get GTI history: {str(e)}'
        }), 500


@app.route('/api/phase_gap_history')
def api_phase_gap_history():
    """
    API endpoint to get phase gap history in radians format for external systems.
    
    Returns data in the format:
    - as_of_utc: ISO timestamp
    - phase_gap_rad: phase gap in radians (converted from degrees)
    - slope_rad_per_day: rate of change in radians per day
    - notes: source/method information
    
    Query params:
    - days: number of days of history (default 30)
    - limit: max number of records (default 500)
    """
    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 500, type=int)
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        gti_calcs = GTICalculation.query.filter(
            GTICalculation.timestamp >= cutoff_time,
            GTICalculation.phase_gap.isnot(None)
        ).order_by(GTICalculation.timestamp.asc()).limit(limit + 1).all()

        if len(gti_calcs) < 2:
            return jsonify({
                'success': True,
                'records': [],
                'message': 'Insufficient data for slope calculation'
            })

        records = []
        for i in range(1, len(gti_calcs)):
            curr = gti_calcs[i]
            prev = gti_calcs[i - 1]

            curr_phase_deg = curr.phase_gap if curr.phase_gap is not None else 0
            prev_phase_deg = prev.phase_gap if prev.phase_gap is not None else 0
            curr_phase_rad = np.deg2rad(curr_phase_deg)
            prev_phase_rad = np.deg2rad(prev_phase_deg)

            time_diff_seconds = (curr.timestamp - prev.timestamp).total_seconds()
            time_diff_days = time_diff_seconds / 86400.0

            if time_diff_days > 0:
                slope_rad_per_day = (curr_phase_rad - prev_phase_rad) / time_diff_days
            else:
                slope_rad_per_day = 0.0

            as_of_utc = curr.timestamp.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')

            records.append({
                'as_of_utc': as_of_utc,
                'phase_gap_rad': float(curr_phase_rad),
                'slope_rad_per_day': float(slope_rad_per_day),
                'notes': f'GTI:{curr.gti_value:.4f}' if curr.gti_value else 'from_gti_calc'
            })

        return jsonify({
            'success': True,
            'records': records,
            'total_records': len(records),
            'unit_info': {
                'phase_gap_rad': 'radians [0, pi]',
                'slope_rad_per_day': 'radians per day (negative = converging)'
            }
        })

    except Exception as e:
        logger.error(f"Error in phase gap history API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to get phase gap history: {str(e)}'
        }), 500


@app.route('/api/stream_data/<stream_type>')
def api_stream_data(stream_type):
    """API endpoint to get data for a specific stream"""
    try:
        # Get query parameters
        hours = request.args.get('hours', 24, type=int)
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        # Query stream data
        data_points = DataStream.query.filter_by(stream_type=stream_type.upper())\
            .filter(DataStream.timestamp >= cutoff_time)\
            .order_by(DataStream.timestamp).all()

        # Format data
        stream_data = {
            'timestamps': [dp.timestamp.isoformat() for dp in data_points],
            'values': [dp.value for dp in data_points],
            'residuals': [dp.residual for dp in data_points if dp.residual is not None]
        }

        return jsonify({
            'success': True,
            'stream_type': stream_type.upper(),
            'data': stream_data
        })

    except Exception as e:
        logger.error(f"Error in stream data API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to get stream data: {str(e)}'
        }), 500

@app.route('/api/update_configuration', methods=['POST'])
def api_update_configuration():
    """API endpoint to update configuration parameters"""
    try:
        data = request.get_json()

        if not data or 'parameter_name' not in data or 'parameter_value' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing required fields: parameter_name and parameter_value'
            }), 400

        # Find or create configuration
        config = ProcessingConfiguration.query.filter_by(
            parameter_name=data['parameter_name']
        ).first()

        if not config:
            config = ProcessingConfiguration()
            config.parameter_name = data['parameter_name']

        config.set_value(data['parameter_value'])
        config.description = data.get('description', '')
        config.updated_at = datetime.utcnow()

        db.session.add(config)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Configuration {data["parameter_name"]} updated successfully'
        })

    except Exception as e:
        logger.error(f"Error updating configuration: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Failed to update configuration: {str(e)}'
        }), 500

@app.route('/api/forecast')
def api_forecast():
    """API endpoint to get GTI forecast/prediction"""
    try:
        # Get recent GTI calculations for trend analysis
        recent_gtis = GTICalculation.query.order_by(GTICalculation.timestamp.desc()).limit(50).all()

        if len(recent_gtis) < 5:
            return jsonify({
                'success': False,
                'message': 'Insufficient data for forecasting'
            }), 400

        # Simple trend analysis - calculate rate of change
        values = [g.gti_value for g in reversed(recent_gtis)]
        timestamps = [g.timestamp.timestamp() for g in reversed(recent_gtis)]

        # Linear trend calculation
        if len(values) >= 2:
            time_diff = timestamps[-1] - timestamps[0]
            value_diff = values[-1] - values[0]
            trend_rate = value_diff / time_diff if time_diff > 0 else 0

            # Project 1 hour ahead
            forecast_time = timestamps[-1] + 3600  # 1 hour
            forecast_value = values[-1] + (trend_rate * 3600)

            forecast_data = {
                'current_value': values[-1],
                'forecast_value': forecast_value,
                'forecast_time': datetime.fromtimestamp(forecast_time).isoformat(),
                'trend_rate': trend_rate,
                'confidence': 'Low' if len(values) < 10 else 'Medium'
            }
        else:
            forecast_data = {
                'current_value': values[-1] if values else 0,
                'forecast_value': None,
                'forecast_time': None,
                'trend_rate': 0,
                'confidence': 'None'
            }

        return jsonify({
            'success': True,
            'forecast': forecast_data
        })

    except Exception as e:
        logger.error(f"Error in forecast API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Forecast failed: {str(e)}'
        }), 500

@app.route('/api/system_status')
def api_system_status():
    """API endpoint to get overall system status"""
    try:
        # Check data freshness
        stream_status = {}
        for stream_type in ['TAI', 'GNSS', 'VLBI', 'PTA']:
            latest = DataStream.query.filter_by(stream_type=stream_type)\
                .order_by(DataStream.timestamp.desc()).first()

            if latest:
                age_minutes = (datetime.utcnow() - latest.timestamp).total_seconds() / 60
                stream_status[stream_type] = {
                    'status': 'healthy' if age_minutes < 60 else 'stale',
                    'last_update_minutes_ago': age_minutes,
                    'data_points_24h': DataStream.query.filter_by(stream_type=stream_type)\
                        .filter(DataStream.timestamp >= datetime.utcnow() - timedelta(hours=24))\
                        .count()
                }
            else:
                stream_status[stream_type] = {
                    'status': 'no_data',
                    'last_update_minutes_ago': None,
                    'data_points_24h': 0
                }

        # Check latest GTI calculation
        latest_gti = _get_latest_gti()
        gti_status = {
            'has_recent_calculation': latest_gti is not None,
            'last_calculation_minutes_ago': (datetime.utcnow() - latest_gti.timestamp).total_seconds() / 60 if latest_gti else None,
            'current_alert_level': latest_gti.alert_level if latest_gti else 'UNKNOWN'
        }

        # Overall system health
        healthy_streams = sum(1 for status in stream_status.values() if status['status'] == 'healthy')
        overall_status = 'healthy' if healthy_streams >= 2 else 'degraded' if healthy_streams >= 1 else 'critical'

        return jsonify({
            'success': True,
            'system_status': {
                'overall': overall_status,
                'streams': stream_status,
                'gti': gti_status,
                'timestamp': datetime.utcnow().isoformat()
            }
        })

    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to get system status: {str(e)}'
        }), 500

@app.route('/proof')
def proof_page():
    """Serve the proof page"""
    return render_template('proof.html')

@app.route('/api/provenance')
def api_provenance():
    """Return last N lines from provenance.jsonl"""
    try:
        n = request.args.get('n', 50, type=int)
        provenance_file = 'data/_meta/provenance.jsonl'

        if not os.path.exists(provenance_file):
            return jsonify({
                'success': True,
                'records': [],
                'message': 'No provenance data yet'
            })

        # Read last N lines
        with open(provenance_file, 'r') as f:
            lines = f.readlines()

        # Get last N lines and parse JSON
        last_lines = lines[-n:] if len(lines) > n else lines
        records = []
        for line in last_lines:
            try:
                records.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

        return jsonify({
            'success': True,
            'records': records,
            'total_records': len(lines)
        })

    except Exception as e:
        logger.error(f"Error in provenance API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to get provenance: {str(e)}'
        }), 500

@app.route('/api/ping')
def api_ping():
    """Ping allowed hosts and return connection info"""
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({
                'success': False,
                'message': 'URL parameter required'
            }), 400

        # Parse hostname and check against allowlist
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        
        # Validate scheme (only allow http/https)
        if parsed.scheme not in ['http', 'https']:
            return jsonify({
                'success': False,
                'message': 'Only http and https schemes are allowed'
            }), 400
        
        hostname = parsed.hostname
        
        # Validate hostname exists and is in allowlist
        if not hostname or hostname not in ALLOWED_HOSTS:
            return jsonify({
                'success': False,
                'message': f'Host {hostname} not in allowlist'
            }), 400

        # Reconstruct URL from validated components to prevent URL manipulation
        safe_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path or '/',
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))

        # Resolve IP
        try:
            resolved_ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            resolved_ip = None

        # Try HEAD first, fallback to GET
        start_time = time.time()
        try:
            response = requests.head(safe_url, timeout=10)
            if response.status_code == 405:  # Method not allowed
                response = requests.get(safe_url, timeout=10, stream=True)
        except:
            response = requests.get(safe_url, timeout=10, stream=True)

        elapsed_ms = (time.time() - start_time) * 1000

        # Extract relevant headers
        headers = {
            'Date': response.headers.get('Date'),
            'Server': response.headers.get('Server'),
            'Content-Type': response.headers.get('Content-Type'),
            'Content-Length': response.headers.get('Content-Length'),
            'Last-Modified': response.headers.get('Last-Modified')
        }

        return jsonify({
            'success': True,
            'status_code': response.status_code,
            'elapsed_ms': elapsed_ms,
            'resolved_ip': resolved_ip,
            'headers': headers,
            'url': safe_url
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ping failed: {str(e)}',
            'elapsed_ms': (time.time() - start_time) * 1000 if 'start_time' in locals() else None
        }), 500

@app.route('/api/last_trace')
def api_last_trace():
    """Return last captured Python traceback"""
    global _last_exception_text
    return jsonify({
        'success': True,
        'last_exception': _last_exception_text,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/logs')
def api_logs():
    """Return last K lines of application logs"""
    try:
        k = request.args.get('k', 200, type=int)
        log_file = 'logs/app.log'

        if not os.path.exists(log_file):
            return jsonify({
                'success': True,
                'logs': [],
                'message': 'No log file found'
            })

        # Read last K lines
        with open(log_file, 'r') as f:
            lines = f.readlines()

        last_lines = lines[-k:] if len(lines) > k else lines

        return jsonify({
            'success': True,
            'logs': [line.strip() for line in last_lines],
            'total_lines': len(lines)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Failed to get logs: {str(e)}'
        }), 500

@app.route('/api/raw')
def api_raw():
    """Serve files from data/ directory with path checking"""
    try:
        path = request.args.get('path')
        if not path:
            return jsonify({
                'success': False,
                'message': 'Path parameter required'
            }), 400

        # Security: resolve canonical path and ensure it's under data/
        base_dir = os.path.abspath('data')
        requested_path = os.path.abspath(path)
        
        # Check if the resolved path is actually within the base directory
        if not requested_path.startswith(base_dir + os.sep) and requested_path != base_dir:
            return jsonify({
                'success': False,
                'message': 'Access denied: path must be under data/'
            }), 403

        if not os.path.exists(requested_path):
            return jsonify({
                'success': False,
                'message': 'File not found'
            }), 404

        # Serve file content
        with open(requested_path, 'rb') as f:
            content = f.read()

        # Try to determine if it's text
        try:
            text_content = content.decode('utf-8')
            return jsonify({
                'success': True,
                'content': text_content,
                'size': len(content),
                'path': path
            })
        except UnicodeDecodeError:
            # Binary file - return base64
            import base64
            return jsonify({
                'success': True,
                'content': base64.b64encode(content).decode('ascii'),
                'encoding': 'base64',
                'size': len(content),
                'path': path
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Failed to serve file: {str(e)}'
        }), 500

@app.route('/api/pull', methods=['GET', 'POST'])
def api_pull():
    """Trigger ETL data pull via subprocess"""
    try:
        # Run the ETL script
        result = subprocess.run(
            ['python', 'etl/fetch_all.py'],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            # Parse any JSON output or just return success
            return jsonify({
                'ok': True,
                'result': {
                    'pulled': ['BIPM', 'IERS'],
                    'stdout': result.stdout,
                    'exit_code': result.returncode
                }
            })
        else:
            return jsonify({
                'ok': False,
                'error': result.stderr,
                'stdout': result.stdout,
                'exit_code': result.returncode
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            'ok': False,
            'error': 'ETL process timed out'
        }), 500
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500

@app.route('/api/forecast_history')
def api_forecast_history():
    """Get historical forecast data"""
    try:
        # Get recent GTI calculations for historical analysis
        recent_gtis = GTICalculation.query.order_by(GTICalculation.timestamp.desc()).limit(100).all()

        if len(recent_gtis) < 10:
            return jsonify({
                'success': False,
                'message': 'Insufficient historical data'
            }), 400

        # Format historical data
        history = []
        for gti in reversed(recent_gtis):
            history.append({
                'timestamp': gti.timestamp.isoformat(),
                'gti_value': gti.gti_value,
                'phase_gap': gti.phase_gap,
                'coherence': gti.coherence_median,
                'alert_level': gti.alert_level
            })

        return jsonify({
            'success': True,
            'history': history,
            'summary': {
                'total_points': len(history),
                'avg_gti': sum(h['gti_value'] for h in history) / len(history),
                'latest_gti': history[-1]['gti_value'] if history else 0
            }
        })

    except Exception as e:
        logger.error(f"Error in forecast history API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Forecast history failed: {str(e)}'
        }), 500


@app.route('/api/eta_history')
def api_eta_history():
    """Get ETA prediction history and convergence events"""
    try:
        from models import ETAEstimate, ConvergenceEvent
        
        # Get recent ETA estimates
        eta_estimates = ETAEstimate.query.order_by(ETAEstimate.as_of_utc.desc()).limit(100).all()
        
        # Get convergence events
        convergence_events = ConvergenceEvent.query.order_by(ConvergenceEvent.event_utc.desc()).limit(20).all()
        
        # Format data
        eta_history = [eta.to_dict() for eta in eta_estimates]
        
        events = []
        for event in convergence_events:
            events.append({
                'event_utc': event.event_utc.isoformat() if event.event_utc else None,
                'phase_gap_at_event': event.phase_gap_at_event,
                'predicted_utc': event.predicted_utc.isoformat() if event.predicted_utc else None,
                'prediction_error_hours': event.prediction_error_hours,
                'gti_value': event.gti_value,
                'coherence': event.coherence,
                'verification_status': event.verification_status,
                'evidence': event.get_evidence()
            })
        
        return jsonify({
            'success': True,
            'eta_history': eta_history,
            'convergence_events': events,
            'latest_eta': eta_history[0] if eta_history else None,
            'total_estimates': len(eta_history),
            'total_events': len(events)
        })
        
    except Exception as e:
        logger.error(f"Error in ETA history API: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'ETA history failed: {str(e)}'
        }), 500


@app.route("/api/eta", methods=["GET"])
def api_eta():
    t_list, deg_list = _load_phase_history()
    if not t_list:
        return jsonify({"ok": False, "error": "No phase history available"}), 200
    phase_rad = _unwrap_deg_to_rad(deg_list)
    res = _robust_fit_eta(t_list, phase_rad)
    asof = datetime.now(timezone.utc)
    if not res:
        return jsonify({
            "ok": True,
            "as_of_utc": asof.isoformat().replace("+00:00","Z"),
            "message": "No convergence or insufficient data"
        }), 200
    eta_days = res["eta_days"]
    eta_date = (asof + timedelta(days=eta_days)).date().isoformat()
    return jsonify({
        "ok": True,
        "as_of_utc": asof.isoformat().replace("+00:00","Z"),
        "eta_days": eta_days,
        "eta_date_utc": eta_date
    }), 200

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler to capture tracebacks"""
    global _last_exception_text
    _last_exception_text = traceback.format_exc()
    logger.error(f"Unhandled exception: {_last_exception_text}")

    if hasattr(e, 'code') and e.code == 404:
        return render_template('dashboard.html', 
                             latest_gti=None,
                             recent_gtis=[],
                             stream_status={}), 404

    db.session.rollback()
    return jsonify({
        'success': False,
        'message': 'Internal server error',
        'error': str(e)
    }), 500

@app.errorhandler(404)
def not_found_error(error):
    return render_template('dashboard.html', 
                         latest_gti=None,
                         recent_gtis=[],
                         stream_status={}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('dashboard.html',
                         latest_gti=None,
                         recent_gtis=[],
                         stream_status={}), 500