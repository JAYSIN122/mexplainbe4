
#!/usr/bin/env python3
"""
Simple NTP connectivity test for debugging mesh monitor issues
"""

import socket
import time
from datetime import datetime

def test_dns_resolution(hostname):
    """Test if we can resolve a hostname"""
    try:
        ip = socket.gethostbyname(hostname)
        print(f"✓ DNS resolution for {hostname}: {ip}")
        return ip
    except Exception as e:
        print(f"✗ DNS resolution failed for {hostname}: {e}")
        return None

def test_ntp_port(host, port=123, timeout=5):
    """Test if we can connect to NTP port"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        print(f"✓ NTP port {port} accessible on {host}")
        return True
    except Exception as e:
        print(f"✗ NTP port {port} connection failed for {host}: {e}")
        return False

def test_basic_connectivity():
    """Test basic internet connectivity"""
    test_hosts = [
        ('8.8.8.8', 'Google DNS'),
        ('1.1.1.1', 'Cloudflare DNS'), 
        ('208.67.222.222', 'OpenDNS')
    ]
    
    print("Testing basic internet connectivity...")
    for ip, name in test_hosts:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((ip, 53))  # DNS port
            sock.close()
            if result == 0:
                print(f"✓ Can reach {name} ({ip})")
            else:
                print(f"✗ Cannot reach {name} ({ip})")
        except Exception as e:
            print(f"✗ Error testing {name} ({ip}): {e}")

def main():
    print(f"NTP Connectivity Test - {datetime.now()}")
    print("=" * 50)
    
    # Test basic connectivity first
    test_basic_connectivity()
    print()
    
    # Test NTP-specific connectivity
    print("Testing NTP server connectivity...")
    
    ntp_servers = [
        'time.nist.gov',
        'time.google.com', 
        'pool.ntp.org',
        '129.6.15.28',      # NIST IP
        '216.239.35.0',     # Google IP
        '162.159.200.1'     # Cloudflare IP
    ]
    
    for server in ntp_servers:
        print(f"\nTesting {server}:")
        
        # Test DNS resolution for hostnames
        if not server.replace('.', '').isdigit():  # It's a hostname
            ip = test_dns_resolution(server)
            if ip:
                test_ntp_port(ip)
        else:  # It's an IP address
            test_ntp_port(server)

if __name__ == "__main__":
    main()
