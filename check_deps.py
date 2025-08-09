
#!/usr/bin/env python3
"""
Quick dependency checker for the Temporal Monitoring System
"""

def list_dependencies():
    """List all project dependencies with versions"""
    
    dependencies = {
        "Core Framework": [
            "flask>=3.1.1",
            "flask-login>=0.6.3", 
            "flask-sqlalchemy>=3.1.1",
            "gunicorn>=23.0.0",
            "werkzeug>=3.1.3"
        ],
        "Database": [
            "sqlalchemy>=2.0.42",
            "psycopg2-binary>=2.9.10"
        ],
        "Scientific Computing": [
            "numpy>=2.3.2",
            "scipy>=1.16.1",
            "scikit-learn>=1.7.1",
            "matplotlib>=3.10.5"
        ],
        "Data Processing": [
            "requests",
            "beautifulsoup4", 
            "python-dateutil"
        ],
        "Validation": [
            "email-validator>=2.2.0"
        ]
    }
    
    print("📦 Project Dependencies")
    print("=" * 40)
    
    for category, deps in dependencies.items():
        print(f"\n{category}:")
        for dep in deps:
            print(f"  • {dep}")
    
    print(f"\nTotal packages: {sum(len(deps) for deps in dependencies.values())}")

def check_installed():
    """Check which dependencies are currently installed"""
    import importlib
    
    package_map = {
        'flask': 'flask',
        'flask_login': 'flask-login',
        'flask_sqlalchemy': 'flask-sqlalchemy', 
        'gunicorn': 'gunicorn',
        'werkzeug': 'werkzeug',
        'sqlalchemy': 'sqlalchemy',
        'psycopg2': 'psycopg2-binary',
        'numpy': 'numpy',
        'scipy': 'scipy',
        'sklearn': 'scikit-learn',
        'matplotlib': 'matplotlib',
        'requests': 'requests',
        'bs4': 'beautifulsoup4',
        'dateutil': 'python-dateutil',
        'email_validator': 'email-validator'
    }
    
    print("\n🔍 Installation Status")
    print("=" * 40)
    
    installed = []
    missing = []
    
    for import_name, package_name in package_map.items():
        try:
            importlib.import_module(import_name)
            installed.append(package_name)
            print(f"✅ {package_name}")
        except ImportError:
            missing.append(package_name)
            print(f"❌ {package_name}")
    
    print(f"\nInstalled: {len(installed)}")
    print(f"Missing: {len(missing)}")
    
    if missing:
        print(f"\nTo install missing packages:")
        print(f"poetry add {' '.join(missing)}")

if __name__ == "__main__":
    list_dependencies()
    check_installed()
