"""
Bayesian analysis module for model selection and parameter estimation
"""

import numpy as np
import logging
from scipy import stats
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

class BayesianAnalyzer:
    def __init__(self, config=None):
        """Initialize Bayesian analyzer"""
        self.config = config or self._default_config()
    
    def _default_config(self):
        """Default configuration for Bayesian analysis"""
        return {
            'prior_strength': 1.0,
            'mcmc_samples': 1000,
            'burnin': 100,
            'evidence_threshold': 10.0  # log Bayes factor threshold
        }
    
    def model_selection(self, data, models=None):
        """
        Perform Bayesian model selection between different hypotheses
        
        H0: Pure noise model
        H1: Signal + noise model
        """
        try:
            if models is None:
                models = ['noise', 'signal_plus_noise']
            
            # Calculate evidence for each model
            evidences = {}
            
            for model in models:
                if model == 'noise':
                    evidence = self._calculate_noise_evidence(data)
                elif model == 'signal_plus_noise':
                    evidence = self._calculate_signal_noise_evidence(data)
                else:
                    logger.warning(f"Unknown model: {model}")
                    evidence = -np.inf
                
                evidences[model] = evidence
            
            # Calculate Bayes factors
            bayes_factors = {}
            reference_model = 'noise'
            
            for model, evidence in evidences.items():
                if model != reference_model:
                    bf = evidence - evidences[reference_model]
                    bayes_factors[f"{model}_vs_{reference_model}"] = bf
            
            # Determine winning model
            best_model = max(evidences, key=evidences.get)
            
            return {
                'evidences': evidences,
                'bayes_factors': bayes_factors,
                'best_model': best_model,
                'model_probabilities': self._calculate_model_probabilities(evidences)
            }
            
        except Exception as e:
            logger.error(f"Error in Bayesian model selection: {str(e)}")
            return self._default_model_selection_result()
    
    def _calculate_noise_evidence(self, data):
        """Calculate evidence for pure noise model"""
        try:
            n = len(data)
            
            # Assume Gaussian noise with unknown variance
            # Use conjugate prior: Inverse-Gamma for variance
            
            # Sample variance
            sample_var = np.var(data, ddof=1)
            
            # Prior parameters (weakly informative)
            alpha_prior = 1.0
            beta_prior = 1.0
            
            # Posterior parameters
            alpha_post = alpha_prior + n / 2
            beta_post = beta_prior + np.sum(data**2) / 2
            
            # Log marginal likelihood (evidence)
            log_evidence = (
                alpha_prior * np.log(beta_prior) - 
                alpha_post * np.log(beta_post) +
                np.log(stats.gamma(alpha_post)) - 
                np.log(stats.gamma(alpha_prior)) -
                n / 2 * np.log(2 * np.pi)
            )
            
            return log_evidence
            
        except Exception as e:
            logger.error(f"Error calculating noise evidence: {str(e)}")
            return -np.inf
    
    def _calculate_signal_noise_evidence(self, data):
        """Calculate evidence for signal plus noise model"""
        try:
            n = len(data)
            
            # Model: y = A*sin(2*pi*f*t + phi) + noise
            # Use numerical integration/approximation
            
            # Grid search over frequency
            freqs = np.linspace(0.01, 0.5, 50)  # Normalized frequencies
            max_log_likelihood = -np.inf
            
            for freq in freqs:
                # For each frequency, optimize amplitude and phase
                t = np.arange(n)
                
                def neg_log_likelihood(params):
                    A, phi, sigma = params
                    if sigma <= 0:
                        return np.inf
                    
                    signal = A * np.sin(2 * np.pi * freq * t + phi)
                    residuals = data - signal
                    
                    # Gaussian likelihood
                    ll = -0.5 * n * np.log(2 * np.pi * sigma**2) - \
                         0.5 * np.sum(residuals**2) / sigma**2
                    
                    return -ll
                
                # Initial guess
                A_init = np.std(data)
                phi_init = 0.0
                sigma_init = np.std(data) * 0.5
                
                try:
                    result = minimize(
                        neg_log_likelihood, 
                        [A_init, phi_init, sigma_init],
                        bounds=[(0, 10*A_init), (-np.pi, np.pi), (1e-6, 10*sigma_init)]
                    )
                    
                    if result.success:
                        max_log_likelihood = max(max_log_likelihood, -result.fun)
                        
                except:
                    continue
            
            # Apply Occam's penalty for additional parameters
            # Simplified BIC-like penalty
            num_params = 3  # A, phi, sigma for each frequency
            bic_penalty = num_params * np.log(n) / 2
            
            log_evidence = max_log_likelihood - bic_penalty
            
            return log_evidence
            
        except Exception as e:
            logger.error(f"Error calculating signal+noise evidence: {str(e)}")
            return -np.inf
    
    def _calculate_model_probabilities(self, evidences):
        """Calculate model probabilities from evidences"""
        try:
            # Convert log evidences to probabilities
            max_evidence = max(evidences.values())
            exp_evidences = {
                model: np.exp(evidence - max_evidence) 
                for model, evidence in evidences.items()
            }
            
            total = sum(exp_evidences.values())
            
            probabilities = {
                model: exp_evidence / total 
                for model, exp_evidence in exp_evidences.items()
            }
            
            return probabilities
            
        except Exception as e:
            logger.error(f"Error calculating model probabilities: {str(e)}")
            return {model: 1.0/len(evidences) for model in evidences}
    
    def estimate_parameters(self, data, model_type='signal_plus_noise'):
        """Estimate parameters for the selected model"""
        try:
            if model_type == 'noise':
                return self._estimate_noise_parameters(data)
            elif model_type == 'signal_plus_noise':
                return self._estimate_signal_parameters(data)
            else:
                logger.warning(f"Unknown model type: {model_type}")
                return {}
                
        except Exception as e:
            logger.error(f"Error in parameter estimation: {str(e)}")
            return {}
    
    def _estimate_noise_parameters(self, data):
        """Estimate noise parameters"""
        return {
            'mean': np.mean(data),
            'variance': np.var(data, ddof=1),
            'std': np.std(data, ddof=1)
        }
    
    def _estimate_signal_parameters(self, data):
        """Estimate signal parameters using maximum likelihood"""
        try:
            n = len(data)
            t = np.arange(n)
            
            # Grid search for frequency
            freqs = np.linspace(0.01, 0.5, 100)
            best_params = None
            best_likelihood = -np.inf
            
            for freq in freqs:
                def neg_log_likelihood(params):
                    A, phi, sigma = params
                    if sigma <= 0:
                        return np.inf
                    
                    signal = A * np.sin(2 * np.pi * freq * t + phi)
                    residuals = data - signal
                    
                    ll = -0.5 * n * np.log(2 * np.pi * sigma**2) - \
                         0.5 * np.sum(residuals**2) / sigma**2
                    
                    return -ll
                
                A_init = np.std(data)
                phi_init = 0.0
                sigma_init = np.std(data) * 0.5
                
                try:
                    result = minimize(
                        neg_log_likelihood,
                        [A_init, phi_init, sigma_init],
                        bounds=[(0, 10*A_init), (-np.pi, np.pi), (1e-6, 10*sigma_init)]
                    )
                    
                    if result.success and -result.fun > best_likelihood:
                        best_likelihood = -result.fun
                        best_params = {
                            'amplitude': result.x[0],
                            'phase': result.x[1],
                            'noise_std': result.x[2],
                            'frequency': freq,
                            'log_likelihood': best_likelihood
                        }
                        
                except:
                    continue
            
            return best_params or {}
            
        except Exception as e:
            logger.error(f"Error estimating signal parameters: {str(e)}")
            return {}
    
    def _default_model_selection_result(self):
        """Return default result when analysis fails"""
        return {
            'evidences': {'noise': 0.0, 'signal_plus_noise': 0.0},
            'bayes_factors': {'signal_plus_noise_vs_noise': 0.0},
            'best_model': 'noise',
            'model_probabilities': {'noise': 0.5, 'signal_plus_noise': 0.5}
        }
    
    def calculate_credible_intervals(self, samples, confidence=0.95):
        """Calculate credible intervals from posterior samples"""
        try:
            alpha = 1 - confidence
            lower = np.percentile(samples, 100 * alpha / 2)
            upper = np.percentile(samples, 100 * (1 - alpha / 2))
            
            return {
                'lower': lower,
                'upper': upper,
                'median': np.median(samples),
                'mean': np.mean(samples)
            }
            
        except Exception as e:
            logger.error(f"Error calculating credible intervals: {str(e)}")
            return {'lower': 0, 'upper': 0, 'median': 0, 'mean': 0}
