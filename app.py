import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Set up logging for debugging and file output
import os
os.makedirs('logs', exist_ok=True)

# Configure logging to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(name)s:%(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "temporal-anomaly-detection-key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///temporal_monitoring.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Mesh monitor configuration
app.config["USE_MESH_MONITOR"] = os.environ.get("USE_MESH_MONITOR", "false").lower() == "true"
app.config["MESH_PEERS"] = os.environ.get("MESH_PEERS", "").split(",") if os.environ.get("MESH_PEERS") else None
app.config["MESH_INTERVAL"] = int(os.environ.get("MESH_INTERVAL", "60"))

# Initialize the app with the extension
db.init_app(app)

# Global mesh monitor instance
mesh_monitor = None

with app.app_context():
    # Import models to ensure tables are created
    import models  # noqa: F401
    # Import routes to register them
    import routes  # noqa: F401

    db.create_all()

    # Initialize default mesh monitor configuration if not exists
    try:
        from models import ProcessingConfiguration
        
        # Check and create default mesh monitor settings
        use_mesh_config = ProcessingConfiguration.query.filter_by(parameter_name='use_mesh_monitor').first()
        if not use_mesh_config:
            use_mesh_config = ProcessingConfiguration(
                parameter_name='use_mesh_monitor',
                parameter_value='true',
                description='Enable mesh network monitoring'
            )
            db.session.add(use_mesh_config)
        
        mesh_peers_config = ProcessingConfiguration.query.filter_by(parameter_name='mesh_peers').first()
        if not mesh_peers_config:
            default_peers = ["pool.ntp.org", "time.nist.gov", "time.google.com", "ptbtime1.ptb.de"]
            mesh_peers_config = ProcessingConfiguration(
                parameter_name='mesh_peers',
                parameter_value=str(default_peers),
                description='List of NTP peers for mesh monitoring'
            )
            db.session.add(mesh_peers_config)
        
        mesh_interval_config = ProcessingConfiguration.query.filter_by(parameter_name='mesh_interval').first()
        if not mesh_interval_config:
            mesh_interval_config = ProcessingConfiguration(
                parameter_name='mesh_interval',
                parameter_value='60',
                description='Mesh polling interval in seconds'
            )
            db.session.add(mesh_interval_config)
        
        db.session.commit()
        
        # Load configuration values
        app.config['USE_MESH_MONITOR'] = use_mesh_config.get_value()
        app.config['MESH_PEERS'] = mesh_peers_config.get_value()
        app.config['MESH_INTERVAL'] = mesh_interval_config.get_value()

        # Initialize mesh monitor if enabled
        if app.config.get('USE_MESH_MONITOR'):
            from mesh_monitor import create_mesh_monitor
            from pathlib import Path
            
            peers = app.config.get('MESH_PEERS', [])
            if isinstance(peers, str):
                # Handle string representation of list
                import ast
                try:
                    peers = ast.literal_eval(peers)
                except:
                    peers = peers.split(',')
            
            interval = int(app.config.get('MESH_INTERVAL', 60))
            mesh_monitor = create_mesh_monitor(peers, interval)
            
            # Load existing history if available
            mesh_history_path = Path("artifacts/mesh_history.json")
            mesh_monitor.load_history(mesh_history_path)
            
            logger.info(f"Mesh monitor initialized with {len(peers)} peers, interval: {interval}s")
        else:
            logger.info("Mesh monitor disabled in configuration")

    except Exception as e:
        logger.error(f"Failed to initialize mesh monitor: {e}")

    logger.info("Database initialized")