
"""
ETL fetch_all.py - Downloads timing data with complete provenance tracking
"""

import os
import hashlib
import json
import time
import socket
from datetime import datetime
import requests
from urllib.parse import urlparse

# Ensure data/_meta directory exists
os.makedirs('data/_meta', exist_ok=True)

def resolve_ip(hostname):
    """Resolve hostname to IP address"""
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None

def download_with_provenance(url, out_path):
    """
    Download file with complete provenance tracking
    Records: sha256, status_code, elapsed_ms, headers, resolved_ip, url, out_path, ts_utc
    """
    start_time = time.time()
    ts_utc = datetime.utcnow().isoformat() + 'Z'
    
    # Parse URL and resolve IP
    parsed_url = urlparse(url)
    resolved_ip = resolve_ip(parsed_url.hostname)
    
    try:
        # Make request with timeout
        response = requests.get(url, timeout=30)
        elapsed_ms = (time.time() - start_time) * 1000

        # Create output directory if needed
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        # Download, handle JSON if needed, and hash content
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' in content_type or url.endswith('.json'):
            data = response.json()
            text = json.dumps(data, ensure_ascii=False, indent=2)
            content_bytes = text.encode('utf-8')
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(text)
        else:
            content_bytes = response.content
            with open(out_path, 'wb') as f:
                f.write(content_bytes)

        sha256_hash = hashlib.sha256(content_bytes)
        
        # Extract relevant headers
        headers = {
            'Date': response.headers.get('Date'),
            'ETag': response.headers.get('ETag'),
            'Last-Modified': response.headers.get('Last-Modified'),
            'Content-Length': response.headers.get('Content-Length'),
            'Content-Type': response.headers.get('Content-Type')
        }
        
        # Create provenance record
        provenance_record = {
            'ts_utc': ts_utc,
            'url': url,
            'out_path': out_path,
            'sha256': sha256_hash.hexdigest(),
            'status_code': response.status_code,
            'elapsed_ms': elapsed_ms,
            'resolved_ip': resolved_ip,
            'headers': headers
        }
        
        # Append to provenance log
        with open('data/_meta/provenance.jsonl', 'a') as f:
            f.write(json.dumps(provenance_record) + '\n')
        
        return provenance_record
        
    except Exception as e:
        # Log failed attempts too
        elapsed_ms = (time.time() - start_time) * 1000
        error_record = {
            'ts_utc': ts_utc,
            'url': url,
            'out_path': out_path,
            'sha256': None,
            'status_code': None,
            'elapsed_ms': elapsed_ms,
            'resolved_ip': resolved_ip,
            'headers': None,
            'error': str(e)
        }
        
        with open('data/_meta/provenance.jsonl', 'a') as f:
            f.write(json.dumps(error_record) + '\n')
        
        raise

def fetch_all():
    """Fetch all timing data sources with provenance"""
    sources = [
        {
            'url': 'https://webtai.bipm.org/ftp/pub/tai/other-products/utcrlab/utcrlab.all',
            'out_path': 'data/bipm/utcrlab.all'
        },
        {
            'url': 'https://datacenter.iers.org/products/eop/rapid/standard/json/finals2000A.data.json',
            'out_path': 'data/iers/finals2000A.data.json'
        }
    ]
    
    results = []
    for source in sources:
        try:
            result = download_with_provenance(source['url'], source['out_path'])
            results.append(result)
            print(f"✅ Downloaded {source['url']} → {source['out_path']}")
        except Exception as e:
            print(f"❌ Failed {source['url']}: {e}")
            results.append({'url': source['url'], 'error': str(e)})
    
    return results

if __name__ == '__main__':
    results = fetch_all()
    print(f"Fetched {len(results)} sources")
