
"""
Configuration loader with YAML support and environment variable substitution
"""

import os
import re
import logging

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    yaml = None

logger = logging.getLogger(__name__)

class ConfigLoader:
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self._config = None
        self.load_config()
    
    def load_config(self):
        """Load configuration from YAML file with env var substitution"""
        try:
            if not HAS_YAML:
                logger.warning("PyYAML not available, using defaults with authentic data files enabled")
                self._config = self._default_config_with_data_files()
                return
                
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    content = f.read()
                
                # Substitute environment variables
                content = self._substitute_env_vars(content)
                
                self._config = yaml.safe_load(content) if yaml else {}
                logger.info(f"Loaded configuration from {self.config_path}")
            else:
                logger.warning(f"Config file {self.config_path} not found, using defaults")
                self._config = self._default_config_with_data_files()
        except Exception as e:
            logger.error(f"Error loading config: {e}, using defaults")
            self._config = self._default_config_with_data_files()
    
    def _substitute_env_vars(self, content):
        """Substitute ${VAR_NAME} patterns with environment variables"""
        def replace_env_var(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))  # Return original if env var not found
        
        return re.sub(r'\$\{([^}]+)\}', replace_env_var, content)
    
    def _default_config_with_data_files(self):
        """Default configuration that enables streams with authentic data files"""
        return {
            'ingestion': {
                'gnss': {'enabled': os.path.exists('data/gnss/clock_data.csv')},
                'vlbi': {'enabled': os.path.exists('data/vlbi/delays.csv')},
                'pta': {'enabled': os.path.exists('data/pta/residuals.csv')},
                'tai': {'enabled': os.path.exists('data/bipm/utcrlab.all')}
            },
            'mesh_monitor': {
                'use_http': True,
                'interval_seconds': 60,
                'peers': [
                    "https://google.com",
                    "https://cloudflare.com",
                    "https://github.com",
                    "https://microsoft.com",
                    "https://apple.com",
                    "https://akamai.com"
                ]
            }
        }
    
    def _default_config(self):
        """Default configuration if file not found"""
        return self._default_config_with_data_files()
    
    def get(self, key_path, default=None):
        """Get config value by dot-notation path (e.g., 'ingestion.gnss.enabled')"""
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def is_ingestion_enabled(self, source_type):
        """Check if ingestion is enabled for a specific source"""
        # Check environment variable first (takes precedence)
        env_var = f"INGEST_{source_type.upper()}"
        if os.getenv(env_var) == "1":
            return True
        
        # Fall back to config file
        return self.get(f'ingestion.{source_type.lower()}.enabled', False)

# Global config instance
config = ConfigLoader()
