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

logger = logging.getLogger(__name__)

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
    """Recursively convert NumPy types to Python native types."""
    try:
        if obj is None:
            return None
        if isinstance(obj, np.ndarray):
            return make_serializable(obj.tolist())
        if isinstance(obj, (np.generic, np.integer, np.floating, np.complexfloating)):
            return obj.item()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, dict):
            return {str(key): make_serializable(value) for key, value in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [make_serializable(item) for item in obj]
        if isinstance(obj, set):
            return list(make_serializable(list(obj)))
        if hasattr(obj, '__dict__') and not isinstance(obj, (type, int, float, str, bool)):
            # Handle custom objects by converting their __dict__
            return make_serializable(obj.__dict__)
        if isinstance(obj, (int, float, str, bool)):
            # Check for special float values
            if isinstance(obj, float) and (np.isinf(obj) or np.isnan(obj)):
                return None
            return obj
        # For any other type, try to convert to string as last resort
        return str(obj)
    except Exception as e:
        logger.warning(f"Could not serialize object of type {type(obj)}: {e}")
        return None

# Initialize processors
pipeline = GTIPipeline()
data_ingestion = DataIngestion()
signal_processor = SignalProcessor()
bayesian_analyzer = BayesianAnalyzer()

@app.route('/')
def dashboard():
    """Main dashboard view"""
    try:
        # Get latest GTI calculation
        latest_gti = GTICalculation.query.order_by(GTICalculation.timestamp.desc()).first()
        
        # Get recent GTI history for trending
        recent_gtis = GTICalculation.query.order_by(GTICalculation.timestamp.desc()).limit(100).all()
        
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
                             stream_status=stream_status)
        
    except Exception as e:
        logger.error(f"Error rendering dashboard: {str(e)}")
        flash(f"Error loading dashboard: {str(e)}", 'error')
        return render_template('dashboard.html', 
                             latest_gti=None,
                             recent_gtis=[],
                             stream_status={})

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

@app.route('/analysis')
def analysis():
    """Detailed analysis view"""
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
        flash(f"Error loading analysis: {str(e)}", 'error')
        return render_template('analysis.html',
                             coherence_results=[],
                             phase_results=[],
                             bayesian_results=[])

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
        
        # Store ingested data in database
        for stream_type, data in stream_data.items():
            for timestamp, value in data[-10:]:  # Store only last 10 points to avoid overflow
                # Convert timestamp to datetime
                dt = datetime.fromtimestamp(timestamp)
                
                # Create new data point
                data_point = DataStream()
                data_point.stream_type = stream_type
                data_point.timestamp = dt
                data_point.value = value
                
                db.session.add(data_point)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully ingested data from {len(stream_data)} streams',
            'streams': list(stream_data.keys()),
            'data_points': {k: len(v) for k, v in stream_data.items()}
        })
        
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
        
        if not stream_data:
            return jsonify({
                'success': False,
                'message': 'No recent data available for analysis'
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
        
        # Serialize results with additional safety
        try:
            serialized_results = make_serializable(results)
            # Test that it can actually be JSON serialized
            import json
            json.dumps(serialized_results)
        except Exception as serialize_error:
            logger.warning(f"Results serialization failed: {serialize_error}, using summary instead")
            # Return a safe summary if full results can't be serialized
            serialized_results = {
                'gti_value': float(results.get('gti_value', 0)),
                'phase_gap_degrees': float(results.get('phase_gap_degrees', 0)),
                'coherence_median': float(results.get('coherence_median', 0)),
                'variance_explained': float(results.get('variance_explained', 0)),
                'alert_level': str(results.get('alert_level', 'UNKNOWN')),
                'timestamp': str(results.get('timestamp', datetime.utcnow().isoformat()))
            }
        
        return jsonify({
            'success': True,
            'results': serialized_results
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
        latest_gti = GTICalculation.query.order_by(GTICalculation.timestamp.desc()).first()
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
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        
        if hostname not in ALLOWED_HOSTS:
            return jsonify({
                'success': False,
                'message': f'Host {hostname} not in allowlist'
            }), 400
        
        # Resolve IP
        try:
            resolved_ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            resolved_ip = None
        
        # Try HEAD first, fallback to GET
        start_time = time.time()
        try:
            response = requests.head(url, timeout=10)
            if response.status_code == 405:  # Method not allowed
                response = requests.get(url, timeout=10, stream=True)
        except:
            response = requests.get(url, timeout=10, stream=True)
        
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
            'url': url
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
        
        # Security: ensure path is under data/
        if not path.startswith('data/'):
            return jsonify({
                'success': False,
                'message': 'Access denied: path must be under data/'
            }), 403
        
        # Security: prevent directory traversal
        if '..' in path or path.startswith('/'):
            return jsonify({
                'success': False,
                'message': 'Access denied: invalid path'
            }), 403
        
        if not os.path.exists(path):
            return jsonify({
                'success': False,
                'message': 'File not found'
            }), 404
        
        # Serve file content
        with open(path, 'rb') as f:
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
