/**
 * Charts JavaScript for Temporal Monitoring System
 * Handles all Chart.js visualizations and real-time updates
 */

// Chart instances
let charts = {
    gti: null,
    phase: null,
    coherence: null,
    streams: {}
};

// Chart configuration
const chartConfig = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            labels: {
                color: 'var(--bs-body-color)',
                usePointStyle: true
            }
        }
    },
    scales: {
        x: {
            type: 'time',
            time: {
                displayFormats: {
                    hour: 'HH:mm',
                    day: 'MM/DD'
                }
            },
            grid: {
                color: 'rgba(255, 255, 255, 0.1)'
            },
            ticks: {
                color: 'var(--bs-body-color)'
            }
        },
        y: {
            grid: {
                color: 'rgba(255, 255, 255, 0.1)'
            },
            ticks: {
                color: 'var(--bs-body-color)'
            }
        }
    }
};

function initializeCharts() {
    console.log('Initializing charts...');
    
    // Initialize GTI timeline chart
    initializeGTIChart();
    
    // Initialize phase gap chart
    initializePhaseChart();
    
    // Initialize coherence chart
    initializeCoherenceChart();
    
    console.log('Charts initialized successfully');
}

function initializeGTIChart() {
    const ctx = document.getElementById('gti-chart');
    if (!ctx) return;
    
    charts.gti = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'GTI Value',
                data: [],
                borderColor: 'rgba(54, 162, 235, 1)',
                backgroundColor: 'rgba(54, 162, 235, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 3,
                pointHoverRadius: 6
            }, {
                label: 'Critical Threshold',
                data: [],
                borderColor: 'rgba(255, 99, 132, 0.8)',
                backgroundColor: 'rgba(255, 99, 132, 0.1)',
                borderWidth: 1,
                borderDash: [5, 5],
                fill: false,
                pointRadius: 0
            }]
        },
        options: {
            ...chartConfig,
            scales: {
                ...chartConfig.scales,
                y: {
                    ...chartConfig.scales.y,
                    title: {
                        display: true,
                        text: 'GTI Value',
                        color: 'var(--bs-body-color)'
                    },
                    beginAtZero: true
                }
            },
            plugins: {
                ...chartConfig.plugins,
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.parsed.y;
                            return `${context.dataset.label}: ${value.toExponential(3)}`;
                        }
                    }
                }
            }
        }
    });
}

function initializePhaseChart() {
    const ctx = document.getElementById('phase-chart');
    if (!ctx) return;
    
    charts.phase = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Phase Gap (degrees)',
                data: [],
                borderColor: 'rgba(255, 206, 86, 1)',
                backgroundColor: 'rgba(255, 206, 86, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 2
            }, {
                label: 'Overlap Target',
                data: [],
                borderColor: 'rgba(75, 192, 192, 0.8)',
                borderWidth: 1,
                borderDash: [10, 5],
                fill: false,
                pointRadius: 0
            }]
        },
        options: {
            ...chartConfig,
            scales: {
                ...chartConfig.scales,
                y: {
                    ...chartConfig.scales.y,
                    title: {
                        display: true,
                        text: 'Phase Gap (degrees)',
                        color: 'var(--bs-body-color)'
                    },
                    min: 0,
                    max: 360
                }
            }
        }
    });
}

function initializeCoherenceChart() {
    const ctx = document.getElementById('coherence-chart');
    if (!ctx) return;
    
    charts.coherence = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Median Coherence',
                data: [],
                borderColor: 'rgba(153, 102, 255, 1)',
                backgroundColor: 'rgba(153, 102, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 2
            }, {
                label: 'Coherence Threshold',
                data: [],
                borderColor: 'rgba(255, 159, 64, 0.8)',
                borderWidth: 1,
                borderDash: [5, 5],
                fill: false,
                pointRadius: 0
            }]
        },
        options: {
            ...chartConfig,
            scales: {
                ...chartConfig.scales,
                y: {
                    ...chartConfig.scales.y,
                    title: {
                        display: true,
                        text: 'Coherence',
                        color: 'var(--bs-body-color)'
                    },
                    min: 0,
                    max: 1
                }
            }
        }
    });
}

function updateAllCharts() {
    console.log('Updating all charts...');
    
    // Update GTI timeline
    updateGTIChart();
    
    // Update phase and coherence charts
    updatePhaseChart();
    updateCoherenceChart();
}

function updateGTIChart() {
    if (!charts.gti) return;
    
    fetch('/api/gti_history?hours=24')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.data.timestamps.length > 0) {
                const timestamps = data.data.timestamps.map(ts => new Date(ts));
                const gtiValues = data.data.gti_values;
                
                // Update GTI data
                charts.gti.data.datasets[0].data = timestamps.map((time, i) => ({
                    x: time,
                    y: gtiValues[i]
                }));
                
                // Add critical threshold line
                const criticalThreshold = 0.2; // From configuration
                charts.gti.data.datasets[1].data = timestamps.map(time => ({
                    x: time,
                    y: criticalThreshold
                }));
                
                charts.gti.update('none');
                
                // Update alert level coloring
                updateChartAlertColoring(charts.gti, data.data.alert_levels);
            }
        })
        .catch(error => {
            console.error('Error updating GTI chart:', error);
        });
}

function updatePhaseChart() {
    if (!charts.phase) return;
    
    fetch('/api/gti_history?hours=24')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.data.timestamps.length > 0) {
                const timestamps = data.data.timestamps.map(ts => new Date(ts));
                const phaseGaps = data.data.phase_gaps;
                
                // Update phase gap data
                charts.phase.data.datasets[0].data = timestamps.map((time, i) => ({
                    x: time,
                    y: Math.abs(phaseGaps[i] || 180) // Use absolute value, default to 180
                }));
                
                // Add zero-degree target line
                charts.phase.data.datasets[1].data = timestamps.map(time => ({
                    x: time,
                    y: 0
                }));
                
                charts.phase.update('none');
            }
        })
        .catch(error => {
            console.error('Error updating phase chart:', error);
        });
}

function updateCoherenceChart() {
    if (!charts.coherence) return;
    
    fetch('/api/gti_history?hours=24')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.data.timestamps.length > 0) {
                const timestamps = data.data.timestamps.map(ts => new Date(ts));
                const coherenceValues = data.data.coherence_values;
                
                // Update coherence data
                charts.coherence.data.datasets[0].data = timestamps.map((time, i) => ({
                    x: time,
                    y: coherenceValues[i] || 0
                }));
                
                // Add coherence threshold line
                const coherenceThreshold = 0.1; // From configuration
                charts.coherence.data.datasets[1].data = timestamps.map(time => ({
                    x: time,
                    y: coherenceThreshold
                }));
                
                charts.coherence.update('none');
            }
        })
        .catch(error => {
            console.error('Error updating coherence chart:', error);
        });
}

function updateChartAlertColoring(chart, alertLevels) {
    if (!alertLevels || alertLevels.length === 0) return;
    
    // Change point colors based on alert levels
    const colors = alertLevels.map(level => {
        switch (level) {
            case 'CRITICAL': return 'rgba(220, 53, 69, 0.8)';
            case 'HIGH': return 'rgba(255, 193, 7, 0.8)';
            case 'MEDIUM': return 'rgba(13, 202, 240, 0.8)';
            default: return 'rgba(25, 135, 84, 0.8)';
        }
    });
    
    // Update point background colors
    if (chart.data.datasets[0]) {
        chart.data.datasets[0].pointBackgroundColor = colors;
        chart.data.datasets[0].pointBorderColor = colors;
    }
}