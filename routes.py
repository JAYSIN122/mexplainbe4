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
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)

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
        
        return jsonify({
            'success': True,
            'results': results
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

@app.errorhandler(404)
def not_found_error(error):
    return render_template('dashboard.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('dashboard.html'), 500
