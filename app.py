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

with app.app_context():
    # Import models to ensure tables are created
    import models  # noqa: F401
    # Import routes to register them
    import routes  # noqa: F401

    db.create_all()

    # Load mesh monitor configuration from database
    try:
        from models import ProcessingConfiguration
        use_mesh_config = ProcessingConfiguration.query.filter_by(parameter_name='use_mesh_monitor').first()
        if use_mesh_config:
            app.config['USE_MESH_MONITOR'] = use_mesh_config.get_value()

        mesh_peers_config = ProcessingConfiguration.query.filter_by(parameter_name='mesh_peers').first()
        if mesh_peers_config:
            app.config['MESH_PEERS'] = mesh_peers_config.get_value()

        mesh_interval_config = ProcessingConfiguration.query.filter_by(parameter_name='mesh_interval').first()
        if mesh_interval_config:
            app.config['MESH_INTERVAL'] = mesh_interval_config.get_value()

    except Exception as e:
        logger.warning(f"Failed to load mesh monitor configuration: {e}")

    logger.info("Database initialized")