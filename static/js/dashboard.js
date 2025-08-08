/**
 * Dashboard JavaScript for Temporal Monitoring System
 * Handles real-time updates, system status, and user interactions
 */

// Global state management
let dashboardState = {
    autoRefreshEnabled: true,
    refreshInterval: 30000,
    lastRefreshTime: null,
    systemStatus: null
};

// Initialize dashboard functionality
document.addEventListener('DOMContentLoaded', function() {
    initializeDashboard();
    updateCurrentTime();
    
    // Update time every second
    setInterval(updateCurrentTime, 1000);
    
    // Check system status every 30 seconds
    setInterval(updateSystemStatus, 30000);
    
    // Initial system status check
    updateSystemStatus();
});

function initializeDashboard() {
    console.log('Initializing Temporal Monitoring Dashboard...');
    
    // Set up auto-refresh toggle
    const autoRefreshToggle = document.getElementById('auto-refresh');
    if (autoRefreshToggle) {
        autoRefreshToggle.addEventListener('change', function() {
            dashboardState.autoRefreshEnabled = this.checked;
            console.log('Auto-refresh', this.checked ? 'enabled' : 'disabled');
        });
    }
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    if (typeof bootstrap !== 'undefined') {
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
    
    console.log('Dashboard initialization complete');
}

function updateCurrentTime() {
    const timeElement = document.getElementById('current-time');
    if (timeElement) {
        const now = new Date();
        timeElement.textContent = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
    }
}

function updateSystemStatus() {
    fetch('/api/system_status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                dashboardState.systemStatus = data.system_status;
                updateStatusIndicator(data.system_status);
            } else {
                console.error('Failed to get system status:', data.message);
                updateStatusIndicator({ overall: 'error' });
            }
        })
        .catch(error => {
            console.error('System status check failed:', error);
            updateStatusIndicator({ overall: 'error' });
        });
}

function updateStatusIndicator(status) {
    const indicator = document.getElementById('system-status-indicator');
    const statusText = document.getElementById('status-text');
    
    if (!indicator || !statusText) return;
    
    const icon = indicator.querySelector('i');
    
    // Update status display based on overall system health
    switch (status.overall) {
        case 'healthy':
            icon.className = 'fas fa-circle text-success me-1';
            statusText.textContent = 'System Healthy';
            break;
        case 'degraded':
            icon.className = 'fas fa-circle text-warning me-1';
            statusText.textContent = 'System Degraded';
            break;
        case 'critical':
            icon.className = 'fas fa-circle text-danger me-1';
            statusText.textContent = 'System Critical';
            break;
        default:
            icon.className = 'fas fa-circle text-secondary me-1';
            statusText.textContent = 'Status Unknown';
    }
    
    // Update tooltip with detailed information
    if (status.streams) {
        const streamDetails = Object.entries(status.streams)
            .map(([stream, info]) => `${stream}: ${info.status}`)
            .join('\n');
        
        indicator.setAttribute('data-bs-title', 
            `System Status: ${status.overall}\n\nStreams:\n${streamDetails}`);
    }
}

function ingestData() {
    const button = event.target;
    const originalText = button.innerHTML;
    
    // Show loading state
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Ingesting...';
    button.disabled = true;
    
    fetch('/api/ingest_data', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Data ingestion completed successfully', 'success');
            console.log('Ingested data:', data);
            
            // Refresh charts after data ingestion
            if (typeof refreshCharts === 'function') {
                setTimeout(refreshCharts, 1000);
            }
        } else {
            showNotification(`Data ingestion failed: ${data.message}`, 'danger');
        }
    })
    .catch(error => {
        console.error('Data ingestion error:', error);
        showNotification(`Data ingestion error: ${error.message}`, 'danger');
    })
    .finally(() => {
        // Restore button
        button.innerHTML = originalText;
        button.disabled = false;
    });
}

function runAnalysis() {
    const button = event.target;
    const originalText = button.innerHTML;
    
    // Show loading state
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Analyzing...';
    button.disabled = true;
    
    fetch('/api/run_analysis', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Analysis completed successfully', 'success');
            console.log('Analysis results:', data.results);
            
            // Update dashboard with new results
            updateDashboardMetrics(data.results);
            
            // Refresh charts
            if (typeof refreshCharts === 'function') {
                setTimeout(refreshCharts, 1000);
            }
        } else {
            showNotification(`Analysis failed: ${data.message}`, 'danger');
        }
    })
    .catch(error => {
        console.error('Analysis error:', error);
        showNotification(`Analysis error: ${error.message}`, 'danger');
    })
    .finally(() => {
        // Restore button
        button.innerHTML = originalText;
        button.disabled = false;
    });
}

function updateDashboardMetrics(results) {
    // Update GTI value display
    const gtiElements = document.querySelectorAll('[data-metric="gti"]');
    gtiElements.forEach(element => {
        if (results.gti_value !== undefined) {
            element.textContent = results.gti_value.toFixed(6);
            
            // Update alert level styling
            const alertLevel = results.alert_level || 'NORMAL';
            element.className = element.className.replace(/text-(success|info|warning|danger)/, '');
            
            switch (alertLevel) {
                case 'CRITICAL':
                    element.classList.add('text-danger');
                    break;
                case 'HIGH':
                    element.classList.add('text-warning');
                    break;
                case 'MEDIUM':
                    element.classList.add('text-info');
                    break;
                default:
                    element.classList.add('text-success');
            }
        }
    });
    
    // Update phase gap display
    const phaseElements = document.querySelectorAll('[data-metric="phase"]');
    phaseElements.forEach(element => {
        if (results.phase_gap_degrees !== undefined) {
            element.textContent = results.phase_gap_degrees.toFixed(2) + '°';
        }
    });
    
    // Update coherence display
    const coherenceElements = document.querySelectorAll('[data-metric="coherence"]');
    coherenceElements.forEach(element => {
        if (results.coherence_median !== undefined) {
            element.textContent = results.coherence_median.toFixed(4);
        }
    });
    
    // Update variance explained display
    const varianceElements = document.querySelectorAll('[data-metric="variance"]');
    varianceElements.forEach(element => {
        if (results.variance_explained !== undefined) {
            element.textContent = (results.variance_explained * 100).toFixed(1) + '%';
        }
    });
}

function showNotification(message, type = 'info', duration = 5000) {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 1050; max-width: 400px;';
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Auto-remove after specified duration
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, duration);
}

function refreshCharts() {
    console.log('Refreshing charts...');
    if (typeof updateAllCharts === 'function') {
        updateAllCharts();
    }
    
    // Update last refresh time
    const lastRefreshElement = document.getElementById('last-refresh');
    if (lastRefreshElement) {
        const now = new Date();
        lastRefreshElement.textContent = now.toLocaleTimeString();
        dashboardState.lastRefreshTime = now;
    }
}