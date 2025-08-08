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
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
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

function refreshCharts() {
    if (typeof updateAllCharts === 'function') {
        updateAllCharts();
    }
    
    // Update last refresh indicator
    const lastRefreshElement = document.getElementById('last-refresh');
    if (lastRefreshElement) {
        const now = new Date();
        lastRefreshElement.textContent = now.toLocaleTimeString();
        dashboardState.lastRefreshTime = now;
    }
    
    showNotification('Charts refreshed', 'info', 2000);
}

function showNotification(message, type = 'info', duration = 5000) {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = `
        top: 20px;
        right: 20px;
        z-index: 1050;
        min-width: 300px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    `;
    
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Add to document
    document.body.appendChild(notification);
    
    // Auto-remove after duration
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, duration);
}

function formatScientificValue(value, precision = 3) {
    if (value === null || value === undefined) return '--';
    
    if (Math.abs(value) < 0.001 || Math.abs(value) > 1000) {
        return value.toExponential(precision);
    } else {
        return value.toFixed(precision);
    }
}

function formatTimestamp(timestamp) {
    if (!timestamp) return '--';
    
    const date = new Date(timestamp);
    return date.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

function exportData(format = 'json') {
    // Get current GTI history
    fetch('/api/gti_history?hours=24')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                let exportData;
                let filename;
                let mimeType;
                
                switch (format) {
                    case 'csv':
                        exportData = convertToCSV(data.data);
                        filename = `gti_data_${new Date().toISOString().slice(0, 10)}.csv`;
                        mimeType = 'text/csv';
                        break;
                    case 'json':
                    default:
                        exportData = JSON.stringify(data.data, null, 2);
                        filename = `gti_data_${new Date().toISOString().slice(0, 10)}.json`;
                        mimeType = 'application/json';
                }
                
                // Create download link
                const blob = new Blob([exportData], { type: mimeType });
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = filename;
                link.click();
                
                window.URL.revokeObjectURL(url);
                showNotification(`Data exported as ${filename}`, 'success');
            } else {
                showNotification('Export failed: ' + data.message, 'danger');
            }
        })
        .catch(error => {
            console.error('Export error:', error);
            showNotification('Export error: ' + error.message, 'danger');
        });
}

function convertToCSV(data) {
    if (!data.timestamps || data.timestamps.length === 0) {
        return 'No data available';
    }
    
    const headers = ['timestamp', 'gti_value', 'phase_gap', 'coherence', 'alert_level'];
    const rows = [headers.join(',')];
    
    for (let i = 0; i < data.timestamps.length; i++) {
        const row = [
            data.timestamps[i] || '',
            data.gti_values[i] || '',
            data.phase_gaps[i] || '',
            data.coherence_values[i] || '',
            data.alert_levels[i] || ''
        ];
        rows.push(row.join(','));
    }
    
    return rows.join('\n');
}

// Expose global functions
window.ingestData = ingestData;
window.runAnalysis = runAnalysis;
window.refreshCharts = refreshCharts;
window.exportData = exportData;
window.showNotification = showNotification;
window.formatScientificValue = formatScientificValue;
window.formatTimestamp = formatTimestamp;
