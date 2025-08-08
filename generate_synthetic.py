"""
Synthetic data generator for GTI pipeline testing
Creates realistic timing data streams with controlled phase relationships
"""

import numpy as np
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SyntheticDataGenerator:
    def __init__(self, config=None):
        """Initialize synthetic data generator"""
        self.config = config or self._default_config()
        
    def _default_config(self):
        """Default configuration for synthetic data generation"""
        return {
            'duration_hours': 24,
            'sample_rate_minutes': 15,  # One sample every 15 minutes
            'base_frequency': 1.0 / (24 * 3600),  # Daily cycle in Hz
            'noise_levels': {
                'TAI': 1e-13,
                'GNSS': 5e-12,
                'VLBI': 2e-12,
                'PTA': 1e-11
            },
            'phase_evolution': {
                'initial_gap': np.pi,  # Start at 180 degrees
                'convergence_rate': 0.1,  # Phase gap convergence rate
                'drift_after_hours': 12  # Hours after which phase starts drifting
            },
            'common_signal_amplitude': 1e-12,
            'output_directory': 'data'
        }
    
    def generate_all_streams(self):
        """Generate synthetic data for all timing streams"""
        logger.info("Generating synthetic data streams...")
        
        # Ensure output directory exists
        os.makedirs(self.config['output_directory'], exist_ok=True)
        
        # Generate time base
        time_base = self._generate_time_base()
        
        # Generate common signal component
        common_signal = self._generate_common_signal(time_base)
        
        # Generate individual streams
        streams = {}
        for stream_type in ['TAI', 'GNSS', 'VLBI', 'PTA']:
            stream_data = self._generate_stream(stream_type, time_base, common_signal)
            streams[stream_type] = stream_data
            
            # Save to file
            self._save_stream_data(stream_type, time_base, stream_data)
        
        # Generate reference signal
        reference = self._generate_reference_signal(time_base)
        self._save_reference_data(time_base, reference)
        
        logger.info(f"Generated {len(streams)} streams with {len(time_base)} samples each")
        return streams, reference
    
    def _generate_time_base(self):
        """Generate time base for synthetic data"""
        duration_seconds = self.config['duration_hours'] * 3600
        sample_interval = self.config['sample_rate_minutes'] * 60
        
        n_samples = int(duration_seconds / sample_interval)
        
        # Start from current time minus duration
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=self.config['duration_hours'])
        
        timestamps = []
        for i in range(n_samples):
            t = start_time + timedelta(seconds=i * sample_interval)
            timestamps.append(t.timestamp())
        
        return np.array(timestamps)
    
    def _generate_common_signal(self, time_base):
        """Generate common signal component with evolving phase"""
        t_norm = (time_base - time_base[0]) / (time_base[-1] - time_base[0])
        
        # Base frequency and amplitude
        freq = self.config['base_frequency']
        amplitude = self.config['common_signal_amplitude']
        
        # Generate phase evolution
        phase_gap = self._generate_phase_evolution(t_norm)
        
        # Common signal with time-varying phase
        common_signal = amplitude * np.sin(2 * np.pi * freq * time_base + phase_gap)
        
        return {
            'signal': common_signal,
            'phase_evolution': phase_gap,
            'frequency': freq,
            'amplitude': amplitude
        }
    
    def _generate_phase_evolution(self, t_norm):
        """Generate realistic phase evolution pattern"""
        config = self.config['phase_evolution']
        
        initial_gap = config['initial_gap']
        convergence_rate = config['convergence_rate']
        drift_point = config['drift_after_hours'] / self.config['duration_hours']
        
        phase_gap = np.zeros_like(t_norm)
        
        for i, t in enumerate(t_norm):
            if t < drift_point:
                # Phase converging toward zero
                phase_gap[i] = initial_gap * np.exp(-convergence_rate * t * 10)
            else:
                # Phase starts drifting away
                drift_t = t - drift_point
                min_phase = initial_gap * np.exp(-convergence_rate * drift_point * 10)
                phase_gap[i] = min_phase + 0.5 * drift_t * np.pi
        
        return phase_gap
    
    def _generate_stream(self, stream_type, time_base, common_signal):
        """Generate data for a specific stream type"""
        noise_level = self.config['noise_levels'][stream_type]
        
        # Stream-specific characteristics
        stream_params = self._get_stream_parameters(stream_type)
        
        # Base signal: common component + stream-specific signal + noise
        signal = (
            common_signal['signal'] * stream_params['coupling'] +
            self._generate_stream_specific_signal(time_base, stream_params) +
            np.random.normal(0, noise_level, len(time_base))
        )
        
        # Add stream-specific systematic effects
        signal += self._add_systematic_effects(time_base, stream_type)
        
        return signal
    
    def _get_stream_parameters(self, stream_type):
        """Get stream-specific parameters"""
        params = {
            'TAI': {
                'coupling': 0.1,  # Weak coupling to common signal
                'local_freq': 1.5 / (24 * 3600),  # Slightly different frequency
                'systematic_amplitude': 2e-13
            },
            'GNSS': {
                'coupling': 0.8,  # Strong coupling
                'local_freq': 1.0 / (24 * 3600),  # Same frequency
                'systematic_amplitude': 1e-12
            },
            'VLBI': {
                'coupling': 0.6,  # Moderate coupling
                'local_freq': 0.8 / (24 * 3600),  # Slightly different
                'systematic_amplitude': 5e-13
            },
            'PTA': {
                'coupling': 0.3,  # Weak coupling, different physics
                'local_freq': 0.1 / (24 * 3600),  # Much lower frequency
                'systematic_amplitude': 3e-12
            }
        }
        
        return params[stream_type]
    
    def _generate_stream_specific_signal(self, time_base, params):
        """Generate stream-specific signal component"""
        freq = params['local_freq']
        amplitude = params['systematic_amplitude']
        
        # Random phase for this stream
        phase = np.random.uniform(0, 2 * np.pi)
        
        return amplitude * np.sin(2 * np.pi * freq * time_base + phase)
    
    def _add_systematic_effects(self, time_base, stream_type):
        """Add realistic systematic effects for each stream type"""
        effects = np.zeros_like(time_base)
        
        if stream_type == 'GNSS':
            # Atmospheric effects (diurnal + semi-diurnal)
            daily_freq = 1.0 / (24 * 3600)
            semi_daily_freq = 2.0 / (24 * 3600)
            
            effects += 3e-12 * np.sin(2 * np.pi * daily_freq * time_base)
            effects += 1e-12 * np.sin(2 * np.pi * semi_daily_freq * time_base)
            
        elif stream_type == 'VLBI':
            # Ionospheric effects
            effects += 2e-12 * np.sin(2 * np.pi * 1.2 / (24 * 3600) * time_base + np.pi/4)
            
        elif stream_type == 'PTA':
            # Interstellar medium effects (very low frequency)
            ism_freq = 1.0 / (7 * 24 * 3600)  # Weekly variation
            effects += 5e-12 * np.sin(2 * np.pi * ism_freq * time_base)
            
        # TAI has minimal systematic effects (most stable)
        
        return effects
    
    def _generate_reference_signal(self, time_base):
        """Generate Sun-clock reference signal"""
        freq = self.config['base_frequency']
        amplitude = self.config['common_signal_amplitude']
        
        # Clean reference signal
        reference = amplitude * np.cos(2 * np.pi * freq * time_base)
        
        return reference
    
    def _save_stream_data(self, stream_type, time_base, data):
        """Save stream data to CSV file"""
        filename = os.path.join(self.config['output_directory'], f'stream_{stream_type.lower()}.csv')
        
        # Combine timestamps and values
        output_data = np.column_stack([time_base, data])
        
        # Save with header
        header = 'timestamp,value'
        np.savetxt(filename, output_data, delimiter=',', header=header, comments='')
        
        logger.info(f"Saved {stream_type} data to {filename}")
    
    def _save_reference_data(self, time_base, reference):
        """Save reference signal data"""
        filename = os.path.join(self.config['output_directory'], 'reference.csv')
        
        output_data = np.column_stack([time_base, reference])
        header = 'timestamp,value'
        np.savetxt(filename, output_data, delimiter=',', header=header, comments='')
        
        logger.info(f"Saved reference data to {filename}")
    
    def generate_summary_report(self):
        """Generate summary report of synthetic data characteristics"""
        report = {
            'generation_timestamp': datetime.utcnow().isoformat(),
            'configuration': self.config,
            'data_characteristics': {
                'duration_hours': self.config['duration_hours'],
                'sample_count': int(self.config['duration_hours'] * 60 / self.config['sample_rate_minutes']),
                'sample_rate_minutes': self.config['sample_rate_minutes'],
                'base_frequency_hz': self.config['base_frequency'],
                'noise_levels': self.config['noise_levels']
            },
            'expected_results': {
                'initial_phase_gap_deg': np.degrees(self.config['phase_evolution']['initial_gap']),
                'convergence_point_hours': self.config['phase_evolution']['drift_after_hours'],
                'final_phase_gap_deg': 'varies, typically > 90 degrees'
            }
        }
        
        # Save report
        import json
        report_file = os.path.join(self.config['output_directory'], 'generation_report.json')
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Generated summary report: {report_file}")
        return report

def main():
    """Main function to generate synthetic data"""
    print("=" * 50)
    print("GTI Synthetic Data Generator")
    print("=" * 50)
    
    # Initialize generator
    generator = SyntheticDataGenerator()
    
    # Generate all data streams
    streams, reference = generator.generate_all_streams()
    
    # Generate summary report
    report = generator.generate_summary_report()
    
    print(f"\nGenerated synthetic data:")
    print(f"  - Duration: {generator.config['duration_hours']} hours")
    print(f"  - Streams: {list(streams.keys())}")
    print(f"  - Samples per stream: {len(next(iter(streams.values())))}")
    print(f"  - Output directory: {generator.config['output_directory']}")
    print(f"  - Base frequency: {generator.config['base_frequency']:.2e} Hz")
    
    print(f"\nExpected analysis results:")
    print(f"  - Initial phase gap: {np.degrees(generator.config['phase_evolution']['initial_gap']):.1f}°")
    print(f"  - Phase convergence until: {generator.config['phase_evolution']['drift_after_hours']} hours")
    print(f"  - Common signal amplitude: {generator.config['common_signal_amplitude']:.2e}")
    
    print(f"\nFiles written to '{generator.config['output_directory']}/' directory")

if __name__ == "__main__":
    main()
