#!/usr/bin/env python3
"""Utility helpers and lightweight tests for verifying NTP connectivity.

The original version of this module exposed a number of functions whose names
started with ``test_``. Pytest automatically treats such callables as test
cases. Those helpers expected positional arguments (e.g. a hostname to resolve),
which meant that when the project's test-suite was executed pytest attempted to
run them as tests and failed with missing-fixture errors. The intended behaviour
of the module is to provide reusable functions that can be invoked manually via
``python test_ntp.py`` for debugging network issues.

To keep that behaviour while allowing the automated test suite to run, the
helper functions have been renamed and small, deterministic unit tests have been
added at the bottom of the file. These tests exercise the helpers using
``localhost`` so they do not rely on external network access and will pass in
isolated environments.
"""

import socket
from datetime import datetime


def resolve_hostname(hostname: str) -> str | None:
    """Resolve ``hostname`` to an IP address.

    Returns the resolved IP string on success or ``None`` if resolution fails.
    The function prints human friendly messages to aid manual debugging.
    """
    try:
        ip = socket.gethostbyname(hostname)
        print(f"\u2713 DNS resolution for {hostname}: {ip}")
        return ip
    except Exception as e:  # pragma: no cover - log for manual runs only
        print(f"\u2717 DNS resolution failed for {hostname}: {e}")
        return None


def check_ntp_port(host: str, port: int = 123, timeout: float = 5.0) -> bool:
    """Attempt a UDP ``connect`` to the given ``host`` and ``port``.

    This does not validate that an NTP server is running; it merely checks that
    the network stack allows a datagram to be sent to the destination.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        print(f"\u2713 NTP port {port} accessible on {host}")
        return True
    except Exception as e:  # pragma: no cover - log for manual runs only
        print(f"\u2717 NTP port {port} connection failed for {host}: {e}")
        return False


def basic_connectivity() -> None:
    """Check basic internet connectivity to a few well-known DNS servers."""
    test_hosts = [
        ("8.8.8.8", "Google DNS"),
        ("1.1.1.1", "Cloudflare DNS"),
        ("208.67.222.222", "OpenDNS"),
    ]

    print("Testing basic internet connectivity...")
    for ip, name in test_hosts:
        try:  # pragma: no cover - diagnostic helper
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((ip, 53))  # DNS port
            sock.close()
            if result == 0:
                print(f"\u2713 Can reach {name} ({ip})")
            else:
                print(f"\u2717 Cannot reach {name} ({ip})")
        except Exception as e:
            print(f"\u2717 Error testing {name} ({ip}): {e}")


def main() -> None:
    print(f"NTP Connectivity Test - {datetime.now()}")
    print("=" * 50)

    # Test basic connectivity first
    basic_connectivity()
    print()

    # Test NTP-specific connectivity
    print("Testing NTP server connectivity...")

    ntp_servers = [
        "time.nist.gov",
        "time.google.com",
        "pool.ntp.org",
        "129.6.15.28",  # NIST IP
        "216.239.35.0",  # Google IP
        "162.159.200.1",  # Cloudflare IP
    ]

    for server in ntp_servers:
        print(f"\nTesting {server}:")

        # Test DNS resolution for hostnames
        if not server.replace(".", "").isdigit():  # It's a hostname
            ip = resolve_hostname(server)
            if ip:
                check_ntp_port(ip)
        else:  # It's an IP address
            check_ntp_port(server)


# ---------------------------------------------------------------------------
# Pytest unit tests
# ---------------------------------------------------------------------------


def test_dns_resolution_localhost() -> None:
    """``localhost`` should always resolve to an IP address."""
    assert resolve_hostname("localhost") is not None


def test_ntp_port_localhost() -> None:
    """Connecting via UDP to localhost should succeed regardless of service."""
    assert check_ntp_port("localhost", timeout=0.1)


if __name__ == "__main__":  # pragma: no cover
    main()
