# Overview
This project is a Flask-based temporal anomaly detection system, primarily focused on Gravitational Time Interferometry (GTI). It processes timing data from various sources (BIPM, TAI, GNSS, VLBI, PTA) to identify and analyze temporal anomalies and forecast potential timeline convergence events, aiming to provide insights into global timing synchronization. The system features a web dashboard for monitoring, advanced signal processing, and the capability to generate synthetic data. A proposed extension involves integrating a decentralized NTP-based mesh network to independently detect global timing anomalies, offering a cross-validation mechanism for the GTI pipeline's findings.

# User Preferences
Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Web Framework**: Flask with Bootstrap dark theme.
- **Template Engine**: Jinja2 templates.
- **Static Assets**: CSS and JavaScript with Chart.js for visualizations.
- **User Interface**: Dashboard, analysis, and configuration pages.

## Backend Architecture
- **Core Framework**: Flask application with SQLAlchemy ORM.
- **Database Layer**: SQLite (default) and PostgreSQL support.
- **Session Management**: Flask sessions.
- **Proxy Support**: ProxyFix middleware.

## Data Processing Pipeline
- **GTI Pipeline**: 8-step process for multitaper spectral analysis, coherence, and phase gap detection.
- **Signal Processing**: Utilizes `scipy` for filtering, Hilbert transforms, and PCA.
- **Bayesian Analysis**: For model selection and parameter estimation.
- **Data Ingestion**: Supports multi-source timing data and synthetic data generation.

## Database Schema
- **Core Registries**: `source_registry`, `ingest_run`.
- **Streams & Observations**: `timeseries_stream`, `observation`.
- **Phase Gap History**: `phase_gap_history`.
- **Forecast**: `forecast_history`.
- **ETA Outputs**: `eta_estimate`.
- **Mesh NTP**: `mesh_node`, `ntp_probe`, `mesh_consensus`.
- **Config & Audit**: `app_config`, `audit_log`.

## Processing Components
- **Multitaper Analysis**: Configurable time-bandwidth products and taper counts.
- **Coherence Detection**: Pairwise coherence analysis across timing streams.
- **Phase Gap Tracking**: Hilbert transform-based phase difference monitoring.
- **Alert System**: Multi-level alerting based on GTI thresholds.

## Mesh Network Module (Proposed)
- **Functionality**: Periodically pings NTP peers, records round-trip delay and offset, computes local "mesh-phase gap" and slope.
- **ETA Calculation**: Uses `eta = |phase_gap| / |slope|`.
- **API Endpoint**: `/api/mesh_status` for mesh data.
- **Integration**: Configurable via `USE_MESH_MONITOR` flag; UI toggle for "Mesh only," "GTI only," or "Combined" display.

# External Dependencies

## Core Libraries
- **Flask**: Web framework.
- **Scientific Computing**: NumPy, SciPy.
- **Machine Learning**: scikit-learn.
- **Visualization**: Matplotlib (non-interactive backend).
- **NTP Client**: ntplib (for mesh module).

## Frontend Dependencies
- **Bootstrap**: CSS framework.
- **Chart.js**: Data visualization.
- **Font Awesome**: Icon library.

## Database Support
- **SQLite**: Default embedded database.
- **PostgreSQL**: Production database.
- **Connection Pooling**: Configured with pool recycling and pre-ping.

## Environment Configuration
- **SESSION_SECRET**: Flask session encryption key.
- **DATABASE_URL**: Database connection string.
- **Logging**: Configurable levels.

## Data Sources
- **BIPM Circular-T**: International Atomic Time (TAI) data.
- **IGS Products**: GNSS clock data.
- **VLBI Networks**: Interferometry timing data.
- **Pulsar Timing Arrays**: Astronomical timing references.