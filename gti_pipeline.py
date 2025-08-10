"""
Core GTI Pipeline Implementation
Based on the 8-step process described in the technical specification
"""

import numpy as np
import logging
from scipy import signal
from scipy.signal import hilbert
from sklearn.decomposition import PCA
from sklearn.cross_decomposition import CCA
from scipy.signal.windows import dpss
from datetime import datetime, timedelta
import json
from analysis.phase_persist import append_phase_gap

logger = logging.getLogger(__name__)

class GTIPipeline:
    def __init__(self, config=None):
        """Initialize GTI Pipeline with configuration parameters"""
        self.config = config or self._default_config()

    def _default_config(self):
        """Default configuration parameters"""
        return {
            'multitaper_bandwidth': 4,
            'multitaper_samples': 7,
            'coherence_threshold': 0.1,
            'bayes_factor_threshold': 10.0,
            'phase_smoothing_window': 50,
            'gti_alert_thresholds': {
                'low': 0.01,
                'medium': 0.05,
                'high': 0.1,
                'critical': 0.2
            }
        }

    def process_streams(self, stream_data):
        """
        Main processing pipeline for multiple timing data streams

        Args:
            stream_data: dict with keys as stream types (TAI, GNSS, VLBI, PTA)
                        and values as arrays of (timestamp, value) pairs

        Returns:
            dict: Complete analysis results including GTI calculation or None if no data
        """
        try:
            # Check if we have any real data
            if not stream_data or all(len(data) == 0 for data in stream_data.values()):
                logger.info("No data streams available - GTI pipeline cannot run")
                return None

            logger.info("Starting GTI pipeline processing")

            # Step 1-2: Prepare residuals and reference
            residuals = self._prepare_residuals(stream_data)
            reference = self._generate_sun_clock_reference(residuals)

            # Step 3: Whiten and sanitize
            whitened_residuals = self._whiten_residuals(residuals)

            # Step 4: Cross-spectral analysis
            coherence_results = self._compute_cross_spectral_coherence(whitened_residuals)

            # Step 5: Extract common component
            common_component = self._extract_common_component(whitened_residuals, coherence_results)

            # Step 6: Phase analysis
            phase_results = self._analyze_phase_gap(common_component, reference)

            # Step 7: Bayesian model selection
            bayes_results = self._bayesian_model_selection(whitened_residuals)

            # Step 8: Calculate GTI
            gti_result = self._calculate_gti(coherence_results, common_component, phase_results)

            # Compile complete results - ensure all values are JSON serializable
            results = {
                'timestamp': datetime.utcnow().isoformat(),
                'gti_value': float(gti_result['gti']),
                'phase_gap_degrees': float(phase_results['phase_gap_degrees']),
                'coherence_median': float(coherence_results['median_coherence']),
                'variance_explained': float(common_component['variance_explained']),
                'bayes_factor': float(bayes_results['bayes_factor']),
                'time_to_overlap': float(phase_results['time_to_overlap']),
                'alert_level': self._determine_alert_level(gti_result['gti']),
                'detailed_results': self._make_json_safe({
                    'coherence': coherence_results,
                    'phase_analysis': phase_results,
                    'bayesian': bayes_results,
                    'component_analysis': common_component
                })
            }

            logger.info(f"GTI pipeline completed. GTI value: {gti_result['gti']:.6f}")
            return results

        except Exception as e:
            logger.error(f"Error in GTI pipeline processing: {str(e)}")
            raise

    def _make_json_safe(self, obj):
        """Recursively convert NumPy types to Python native types"""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.integer, np.floating, np.complexfloating)):
            return obj.item()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, dict):
            return {str(key): self._make_json_safe(value) for key, value in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_safe(item) for item in obj]
        elif isinstance(obj, set):
            return [self._make_json_safe(item) for item in list(obj)]
        elif hasattr(obj, '__dict__') and not isinstance(obj, (type, int, float, str, bool)):
            return self._make_json_safe(obj.__dict__)
        elif isinstance(obj, float) and (np.isinf(obj) or np.isnan(obj)):
            return None
        else:
            return obj

    def _prepare_residuals(self, stream_data):
        """Prepare residuals from raw stream data"""
        residuals = {}

        for stream_type, data in stream_data.items():
            if len(data) < 10:  # Minimum data points required
                logger.warning(f"Insufficient data for stream {stream_type}")
                continue

            timestamps = np.array([d[0] for d in data])
            values = np.array([d[1] for d in data])

            # Remove linear trend (basic detrending)
            detrended = signal.detrend(values, type='linear')

            # Calculate residuals by removing expected Sun-clock prediction
            expected = self._calculate_expected_values(timestamps, stream_type)
            residual_values = detrended - expected

            residuals[stream_type] = {
                'timestamps': timestamps,
                'values': residual_values,
                'raw_values': values
            }

        return residuals

    def _calculate_expected_values(self, timestamps, stream_type):
        """Calculate expected values based on Sun-clock model"""
        # Return zeros - let the real data speak for itself
        # In production this would include proper theoretical models
        return np.zeros(len(timestamps))

    def _generate_sun_clock_reference(self, residuals):
        """Generate Sun-clock reference signal from real data"""
        if not residuals:
            return {'timestamps': np.array([]), 'signal': np.array([]), 'frequency': 0.0}
            
        # Use the first available stream as time base
        first_stream = next(iter(residuals.values()))
        timestamps = first_stream['timestamps']

        # Use median of all streams as reference (simple approach)
        all_values = []
        for stream_data in residuals.values():
            if len(stream_data['values']) == len(timestamps):
                all_values.append(stream_data['values'])
        
        if all_values:
            reference_signal = np.median(all_values, axis=0)
        else:
            reference_signal = np.zeros(len(timestamps))

        reference = {
            'timestamps': timestamps,
            'signal': reference_signal,
            'frequency': 1.0 / (24 * 3600)  # Daily frequency as baseline
        }

        return reference

    def _whiten_residuals(self, residuals):
        """Whiten and sanitize residual streams"""
        whitened = {}

        for stream_type, data in residuals.items():
            values = data['values']

            # Remove outliers using robust statistics
            median_val = np.median(values)
            mad = np.median(np.abs(values - median_val))
            threshold = 3 * mad

            # Clip extreme outliers
            clipped = np.clip(values, median_val - threshold, median_val + threshold)

            # Z-score normalization
            whitened_values = (clipped - np.mean(clipped)) / np.std(clipped)

            whitened[stream_type] = {
                'timestamps': data['timestamps'],
                'values': whitened_values,
                'original_values': values
            }

        return whitened

    def _compute_cross_spectral_coherence(self, residuals):
        """Compute cross-spectral coherence using multitaper method"""
        stream_names = list(residuals.keys())
        n_streams = len(stream_names)

        if n_streams < 2:
            logger.warning("Need at least 2 streams for coherence analysis")
            return {'median_coherence': 0.0, 'pairwise_coherence': {}}

        coherence_values = []
        pairwise_coherence = {}

        for i in range(n_streams):
            for j in range(i + 1, n_streams):
                stream1 = stream_names[i]
                stream2 = stream_names[j]

                data1 = residuals[stream1]['values']
                data2 = residuals[stream2]['values']

                # Ensure same length
                min_len = min(len(data1), len(data2))
                data1 = data1[:min_len]
                data2 = data2[:min_len]

                # Compute coherence using Welch's method
                freqs, coherence = signal.coherence(data1, data2, nperseg=min(256, min_len//4))

                # Find peak coherence
                peak_coherence = np.max(coherence)
                peak_freq_idx = np.argmax(coherence)
                peak_frequency = freqs[peak_freq_idx]

                coherence_values.append(peak_coherence)
                pairwise_coherence[f"{stream1}_{stream2}"] = {
                    'coherence': peak_coherence,
                    'frequency': peak_frequency,
                    'full_coherence': coherence.tolist(),
                    'frequencies': freqs.tolist()
                }

        median_coherence = np.median(coherence_values) if coherence_values else 0.0

        return {
            'median_coherence': median_coherence,
            'pairwise_coherence': pairwise_coherence,
            'coherence_values': coherence_values
        }

    def _extract_common_component(self, residuals, coherence_results):
        """Extract common component using PCA"""
        if not residuals:
            return {'variance_explained': 0.0, 'component': np.array([])}

        # Stack all residual streams
        stream_names = list(residuals.keys())
        min_length = min(len(residuals[name]['values']) for name in stream_names)

        data_matrix = np.column_stack([
            residuals[name]['values'][:min_length] for name in stream_names
        ])

        # Apply PCA
        pca = PCA()
        components = pca.fit_transform(data_matrix)

        # First component is the common signal
        first_component = components[:, 0]
        variance_explained = pca.explained_variance_ratio_[0]

        return {
            'component': first_component,
            'variance_explained': variance_explained,
            'all_components': components,
            'explained_variance_ratio': pca.explained_variance_ratio_.tolist()
        }

    def _analyze_phase_gap(self, common_component, reference):
        """Analyze phase gap using Hilbert transform"""
        if len(common_component['component']) == 0:
            return {
                'phase_gap_degrees': 180.0,
                'time_to_overlap': np.inf,
                'phase_gap_trend': 0.0
            }

        # Get analytic signals using Hilbert transform
        component_analytic = hilbert(common_component['component'])
        reference_analytic = hilbert(reference['signal'][:len(common_component['component'])])

        # Extract instantaneous phases
        component_phase = np.angle(component_analytic)
        reference_phase = np.angle(reference_analytic)

        # Calculate phase difference and unwrap
        phase_diff = np.unwrap(component_phase - reference_phase)

        # Convert to degrees
        phase_diff_degrees = np.degrees(phase_diff)

        # Calculate trend (phase rate)
        if len(phase_diff) > 1:
            phase_trend = np.polyfit(range(len(phase_diff)), phase_diff, 1)[0]
        else:
            phase_trend = 0.0

        # Estimate time to overlap
        current_phase = phase_diff_degrees[-1] % 360
        if current_phase > 180:
            current_phase -= 360

        if phase_trend < 0 and abs(current_phase) > 1e-6:
            # Phase is closing toward zero
            time_to_overlap = abs(current_phase / np.degrees(phase_trend))
        else:
            time_to_overlap = np.inf

        return {
            'phase_gap_degrees': abs(current_phase),
            'phase_diff_series': phase_diff_degrees.tolist(),
            'time_to_overlap': time_to_overlap,
            'phase_gap_trend': phase_trend,
            'raw_phase_diff': phase_diff.tolist()
        }

    def _bayesian_model_selection(self, residuals):
        """Simplified Bayesian model selection"""
        # In a full implementation, this would use pymc or ultranest
        # For now, we'll use a simplified approach based on variance explained

        if not residuals:
            return {'bayes_factor': 1.0, 'model_probability': 0.5}

        # Calculate total variance in residuals
        all_values = np.concatenate([data['values'] for data in residuals.values()])
        total_variance = np.var(all_values)

        # Calculate noise variance (simplified)
        noise_variance = total_variance * 0.8  # Assume 80% is noise
        signal_variance = total_variance - noise_variance

        # Simplified Bayes factor calculation
        # In practice, this would involve proper model comparison
        if signal_variance > 0:
            bayes_factor = signal_variance / noise_variance
        else:
            bayes_factor = 1.0

        model_probability = bayes_factor / (1 + bayes_factor)

        return {
            'bayes_factor': bayes_factor,
            'model_probability': model_probability,
            'log_bayes_factor': np.log(bayes_factor)
        }

    def _calculate_gti(self, coherence_results, common_component, phase_results):
        """Calculate the Grounded Timeline Index (GTI)"""
        # GTI = median_coherence × variance_explained × exp(-|phase_gap|)

        median_coherence = coherence_results['median_coherence']
        variance_explained = common_component['variance_explained']
        phase_gap_rad = np.radians(phase_results['phase_gap_degrees'])

        # GTI calculation as specified
        gti = median_coherence * variance_explained * np.exp(-abs(phase_gap_rad))

        return {
            'gti': gti,
            'components': {
                'median_coherence': median_coherence,
                'variance_explained': variance_explained,
                'phase_factor': np.exp(-abs(phase_gap_rad))
            }
        }

    def _determine_alert_level(self, gti_value):
        """Determine alert level based on GTI value"""
        thresholds = self.config['gti_alert_thresholds']

        if gti_value >= thresholds['critical']:
            return 'CRITICAL'
        elif gti_value >= thresholds['high']:
            return 'HIGH'
        elif gti_value >= thresholds['medium']:
            return 'MEDIUM'
        elif gti_value >= thresholds['low']:
            return 'LOW'
        else:
            return 'NORMAL'