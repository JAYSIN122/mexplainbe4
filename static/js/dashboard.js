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
    
    // Load initial mesh status
    updateMeshStatus();
    
    console.log('Dashboard initialization complete');
}

function updateMeshStatus() {
    fetch('/api/mesh_status')
        .then(response => response.json())
        .then(data => {
            const meshStatusDiv = document.getElementById('mesh-status');
            if (!meshStatusDiv) return;
            
            if (!data.active) {
                meshStatusDiv.innerHTML = `
                    <div class="text-center text-muted">
                        <i class="fas fa-times-circle me-2"></i>
                        ${data.message || 'Mesh monitoring disabled'}
                    </div>`;
                return;
            }
            
            const etaDisplay = data.eta_days !== null ? 
                `${data.eta_days.toFixed(2)} days` : 'Not converging';
            
            const statusClass = data.eta_days !== null && data.eta_days < 30 ? 'text-warning' : 'text-success';
            
            meshStatusDiv.innerHTML = `
                <div class="row g-3">
                    <div class="col-6">
                        <div class="text-center">
                            <div class="scientific-value ${statusClass}">${data.phase_gap.toFixed(6)}s</div>
                            <small class="text-muted">Phase Gap</small>
                        </div>
                    </div>
                    <div class="col-6">
                        <div class="text-center">
                            <div class="scientific-value">${data.slope.toExponential(2)}</div>
                            <small class="text-muted">Slope (s/s)</small>
                        </div>
                    </div>
                    <div class="col-6">
                        <div class="text-center">
                            <div class="scientific-value ${statusClass}">${etaDisplay}</div>
                            <small class="text-muted">ETA to Zero</small>
                        </div>
                    </div>
                    <div class="col-6">
                        <div class="text-center">
                            <div class="scientific-value text-info">${data.peer_count}</div>
                            <small class="text-muted">Active Peers</small>
                        </div>
                    </div>
                </div>
                <div class="text-center mt-2">
                    <small class="text-muted">
                        Last updated: ${new Date(data.timestamp).toLocaleTimeString()}
                    </small>
                </div>`;
        })
        .catch(error => {
            console.error('Error updating mesh status:', error);
            const meshStatusDiv = document.getElementById('mesh-status');
            if (meshStatusDiv) {
                meshStatusDiv.innerHTML = `
                    <div class="text-center text-danger">
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        Error loading mesh status
                    </div>`;
            }
        });
}

function updateMeshMonitor() {
    fetch('/api/mesh_update', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                console.log('Mesh monitor updated:', data.data);
                updateMeshStatus(); // Refresh display
                showAlert('Mesh monitor updated successfully', 'success');
            } else {
                console.error('Mesh update failed:', data.message);
                showAlert('Mesh update failed: ' + data.message, 'warning');
            }
        })
        .catch(error => {
            console.error('Error updating mesh monitor:', error);
            showAlert('Error updating mesh monitor', 'danger');
        });
}

function showAlert(message, type = 'info') {
    // Simple alert function - can be enhanced with Bootstrap alerts
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    alertDiv.style.top = '20px';
    alertDiv.style.right = '20px';
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(alertDiv);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.remove();
        }
    }, 5000);
}

function updateCurrentTime() {
    const timeElement = document.getElementById('current-time');
    if (timeElement) {
        const now = new Date();
        timeElement.textContent = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
    }
}

// Add debouncing to prevent update loops
let updateInProgress = false;

function updateSystemStatus() {
    if (updateInProgress) {
        return;
    }
    updateInProgress = true;
    
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
        })
        .finally(() => {
            updateInProgress = false;
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