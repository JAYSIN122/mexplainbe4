"""
Advanced signal processing utilities for timing analysis
"""

import numpy as np
from scipy import signal
from scipy.signal import hilbert, savgol_filter
from scipy.signal.windows import dpss
import logging

logger = logging.getLogger(__name__)

class SignalProcessor:
    def __init__(self, config=None):
        """Initialize signal processor with configuration"""
        self.config = config or self._default_config()
    
    def _default_config(self):
        """Default signal processing configuration"""
        return {
            'multitaper_bandwidth': 4.0,
            'multitaper_samples': 7,
            'filter_order': 5,
            'smoothing_window': 51,
            'polynomial_order': 3
        }
    
    def multitaper_psd(self, data, fs=1.0):
        """Compute power spectral density using multitaper method"""
        try:
            # Parameters for multitaper
            N = len(data)
            NW = self.config['multitaper_bandwidth']
            K = self.config['multitaper_samples']
            
            # Generate DPSS tapers
            tapers, eigenvalues = dpss(N, NW, K, return_ratios=True)
            
            # Compute periodograms for each taper
            psds = []
            for taper in tapers:
                windowed = data * taper
                fft_windowed = np.fft.fft(windowed)
                psd = np.abs(fft_windowed)**2
                psds.append(psd)
            
            # Average across tapers
            psd_avg = np.mean(psds, axis=0)
            
            # Frequency vector
            freqs = np.fft.fftfreq(N, 1/fs)
            
            # Return positive frequencies only
            n_pos = N // 2 + 1
            return freqs[:n_pos], psd_avg[:n_pos]
            
        except Exception as e:
            logger.error(f"Error in multitaper PSD computation: {str(e)}")
            # Fallback to Welch's method
            return signal.welch(data, fs=fs)
    
    def cross_spectrum_coherence(self, x, y, fs=1.0):
        """Compute cross-spectrum and coherence between two signals"""
        try:
            # Compute cross-power spectral density
            freqs, Pxy = signal.csd(x, y, fs=fs)
            
            # Compute auto-power spectral densities
            _, Pxx = signal.welch(x, fs=fs)
            _, Pyy = signal.welch(y, fs=fs)
            
            # Ensure same frequency resolution
            min_len = min(len(Pxx), len(Pyy), len(Pxy))
            Pxx = Pxx[:min_len]
            Pyy = Pyy[:min_len]
            Pxy = Pxy[:min_len]
            freqs = freqs[:min_len]
            
            # Compute coherence
            coherence = np.abs(Pxy)**2 / (Pxx * Pyy)
            
            # Compute phase
            phase = np.angle(Pxy)
            
            return {
                'frequencies': freqs,
                'coherence': coherence,
                'phase': phase,
                'cross_psd': Pxy,
                'psd_x': Pxx,
                'psd_y': Pyy
            }
            
        except Exception as e:
            logger.error(f"Error in cross-spectrum computation: {str(e)}")
            return None
    
    def extract_instantaneous_phase(self, signal_data):
        """Extract instantaneous phase using Hilbert transform"""
        try:
            # Apply Hilbert transform to get analytic signal
            analytic_signal = hilbert(signal_data)
            
            # Extract amplitude and phase
            amplitude = np.abs(analytic_signal)
            phase = np.angle(analytic_signal)
            
            # Unwrap phase to avoid discontinuities
            unwrapped_phase = np.unwrap(phase)
            
            # Calculate instantaneous frequency
            instant_freq = np.diff(unwrapped_phase) / (2 * np.pi)
            
            return {
                'amplitude': amplitude,
                'phase': phase,
                'unwrapped_phase': unwrapped_phase,
                'instantaneous_frequency': instant_freq
            }
            
        except Exception as e:
            logger.error(f"Error in phase extraction: {str(e)}")
            return None
    
    def smooth_signal(self, data, method='savgol'):
        """Smooth signal using various methods"""
        try:
            if method == 'savgol':
                # Savitzky-Golay filter
                window_length = min(self.config['smoothing_window'], len(data) // 2)
                if window_length % 2 == 0:
                    window_length -= 1  # Must be odd
                if window_length < 3:
                    return data  # Cannot smooth very short signals
                
                poly_order = min(self.config['polynomial_order'], window_length - 1)
                smoothed = savgol_filter(data, window_length, poly_order)
                
            elif method == 'moving_average':
                # Simple moving average
                window = self.config['smoothing_window']
                smoothed = np.convolve(data, np.ones(window)/window, mode='same')
                
            else:
                logger.warning(f"Unknown smoothing method: {method}")
                return data
            
            return smoothed
            
        except Exception as e:
            logger.error(f"Error in signal smoothing: {str(e)}")
            return data
    
    def bandpass_filter(self, data, low_freq, high_freq, fs=1.0):
        """Apply bandpass filter to signal"""
        try:
            # Design Butterworth bandpass filter
            nyquist = fs / 2
            low = low_freq / nyquist
            high = high_freq / nyquist
            
            # Ensure frequencies are valid
            if low <= 0 or high >= 1 or low >= high:
                logger.error("Invalid filter frequencies")
                return data
            
            b, a = signal.butter(self.config['filter_order'], [low, high], btype='band')
            
            # Apply filter
            filtered_data = signal.filtfilt(b, a, data)
            
            return filtered_data
            
        except Exception as e:
            logger.error(f"Error in bandpass filtering: {str(e)}")
            return data
    
    def detect_outliers(self, data, method='mad', threshold=3.0):
        """Detect outliers in signal data"""
        try:
            if method == 'mad':
                # Median Absolute Deviation
                median_val = np.median(data)
                mad = np.median(np.abs(data - median_val))
                
                # Modified z-score
                modified_z_scores = 0.6745 * (data - median_val) / mad
                outliers = np.abs(modified_z_scores) > threshold
                
            elif method == 'zscore':
                # Standard z-score
                z_scores = (data - np.mean(data)) / np.std(data)
                outliers = np.abs(z_scores) > threshold
                
            else:
                logger.warning(f"Unknown outlier detection method: {method}")
                return np.zeros(len(data), dtype=bool)
            
            return outliers
            
        except Exception as e:
            logger.error(f"Error in outlier detection: {str(e)}")
            return np.zeros(len(data), dtype=bool)
    
    def estimate_noise_level(self, data):
        """Estimate noise level in signal"""
        try:
            # Use robust statistics to estimate noise
            diff = np.diff(data)
            
            # Median absolute deviation of differences
            mad_diff = np.median(np.abs(diff - np.median(diff)))
            
            # Estimate noise standard deviation
            noise_std = mad_diff / 0.6745
            
            return {
                'noise_std': noise_std,
                'snr_estimate': np.std(data) / noise_std if noise_std > 0 else np.inf
            }
            
        except Exception as e:
            logger.error(f"Error in noise estimation: {str(e)}")
            return {'noise_std': 0.0, 'snr_estimate': np.inf}
