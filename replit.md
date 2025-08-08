# Overview

This is a Flask-based temporal anomaly detection system that implements a Gravitational Time Interferometry (GTI) pipeline for analyzing timing data streams from multiple sources. The system monitors various timing standards (TAI, GNSS, VLBI, PTA) to detect potential temporal anomalies and calculate GTI metrics that could indicate timeline convergence events. It features a comprehensive web dashboard for real-time monitoring, advanced signal processing capabilities using multitaper analysis and Bayesian methods, and synthetic data generation for testing and demonstration purposes.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Web Framework**: Flask-based web application with Bootstrap dark theme
- **Template Engine**: Jinja2 templates organized in `templates/` directory
- **Static Assets**: CSS and JavaScript files in `static/` with Chart.js for visualizations
- **User Interface**: Dashboard, analysis, and configuration pages with real-time updates

## Backend Architecture
- **Core Framework**: Flask application with SQLAlchemy ORM using DeclarativeBase
- **Database Layer**: SQLite as default with PostgreSQL support through DATABASE_URL environment variable
- **Session Management**: Flask sessions with configurable secret key
- **Proxy Support**: ProxyFix middleware for deployment behind reverse proxies

## Data Processing Pipeline
- **GTI Pipeline**: 8-step process including multitaper spectral analysis, coherence calculation, and phase gap detection
- **Signal Processing**: Advanced algorithms using scipy for filtering, Hilbert transforms, and PCA analysis
- **Bayesian Analysis**: Model selection and parameter estimation for anomaly detection
- **Data Ingestion**: Multi-source timing data streams with synthetic data generation capability

## Database Schema
- **DataStream**: Stores timing data from different sources (TAI, GNSS, VLBI, PTA) with timestamps and metadata
- **GTICalculation**: Results of GTI analysis including phase gaps, coherence values, and alert levels
- **ProcessingConfiguration**: Configurable analysis parameters stored as JSON
- **AnalysisResult**: Additional analysis outputs and intermediate results

## Processing Components
- **Multitaper Analysis**: Configurable time-bandwidth products and taper counts for spectral estimation
- **Coherence Detection**: Pairwise coherence analysis across timing streams
- **Phase Gap Tracking**: Hilbert transform-based phase difference monitoring
- **Alert System**: Multi-level alerting (LOW, MEDIUM, HIGH, CRITICAL) based on GTI thresholds

# External Dependencies

## Core Libraries
- **Flask**: Web application framework with SQLAlchemy integration
- **Scientific Computing**: NumPy, SciPy for mathematical operations and signal processing
- **Machine Learning**: scikit-learn for PCA and canonical correlation analysis
- **Visualization**: Matplotlib for plot generation (non-interactive backend)

## Frontend Dependencies
- **Bootstrap**: Dark theme CSS framework via CDN
- **Chart.js**: Real-time data visualization library
- **Font Awesome**: Icon library for UI components

## Database Support
- **SQLite**: Default embedded database for development
- **PostgreSQL**: Production database support through DATABASE_URL configuration
- **Connection Pooling**: Configured with pool recycling and pre-ping health checks

## Environment Configuration
- **SESSION_SECRET**: Flask session encryption key
- **DATABASE_URL**: Database connection string with fallback to SQLite
- **Logging**: Configurable logging levels for debugging and monitoring

## Data Sources (Future Integration)
- **BIPM Circular-T**: International Atomic Time (TAI) data source
- **IGS Products**: Global Navigation Satellite System (GNSS) clock data
- **VLBI Networks**: Very Long Baseline Interferometry timing data
- **Pulsar Timing Arrays**: High-precision astronomical timing references