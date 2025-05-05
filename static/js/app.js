// --- Start of File: static/js/app.js ---

document.addEventListener('DOMContentLoaded', function() {

    console.log("app.js loaded.");

    // --- Helper: Get CSRF Token ---
    function getCsrfToken() {
        const input = document.getElementById('csrf-token-input');
        if (input) {
            return input.value;
        }
        console.warn('CSRF token input field #csrf-token-input not found.');
        return null;
    }

    // --- Helper: Show Feedback ---
    function showFeedback(elementId, message, isError = false, duration = 5000) {
        const feedbackEl = document.getElementById(elementId);
        // Also allow selecting by data attribute for batch status
        const feedbackElByData = feedbackEl || document.querySelector(`.batch-cut-status[data-clip-type="${elementId}"]`);

        if (!feedbackElByData) {
             console.warn(`Feedback element not found for ID/Selector: ${elementId}`);
             return;
         }

        feedbackElByData.textContent = message;
        feedbackElByData.className = `mt-3 small ${isError ? 'text-danger fw-bold' : 'text-success'}`;
        if (feedbackElByData.classList.contains('batch-cut-status')) {
             feedbackElByData.classList.add('ms-3'); // Keep margin for batch status
         }

        // Clear feedback after duration
        setTimeout(() => {
            if (feedbackElByData.textContent === message) { // Only clear if message hasn't changed
                feedbackElByData.textContent = '';
                feedbackElByData.className = 'mt-3 small';
                 if (feedbackElByData.classList.contains('batch-cut-status')) {
                     feedbackElByData.classList.add('ms-3', 'text-body-secondary');
                     feedbackElByData.setAttribute('data-clip-type', elementId); // Re-add data attribute if needed
                 }
            }
        }, duration);
    }


    // --- Index Page: Form Submission Spinner --- (No changes needed)
    const addVideosForm = document.getElementById('addVideosForm');
    const addVideosButton = document.getElementById('addVideosButton');
    const loadingSpinnerSubmit = document.getElementById('loadingSpinnerSubmit');
    if (addVideosForm && addVideosButton && loadingSpinnerSubmit) {
        addVideosForm.addEventListener('submit', function(event) {
            // ... (rest of the logic is fine) ...
            addVideosButton.disabled = true;
            loadingSpinnerSubmit.style.display = 'inline-block';
            addVideosButton.innerHTML = '<i class="bi bi-hourglass-split"></i> Adding...';
        });
    }

    // --- Index Page: Delete Button & Checkbox Logic --- (No changes needed)
    const selectAllCheckbox = document.getElementById('selectAll');
    const videoCheckboxes = document.querySelectorAll('.video-checkbox');
    const deleteButton = document.getElementById('deleteSelectedButton');
    const deleteForm = document.getElementById('deleteVideosForm');
    // ... (Toggle logic, submit handler remain the same) ...
    function toggleDeleteButtonState() { /* ... */ }
    if (selectAllCheckbox) { /* ... */ }
    videoCheckboxes.forEach(checkbox => { /* ... */ });
    if (deleteForm) { /* ... */ }
    toggleDeleteButtonState();


    // --- Video Details Page: Manual Clip Form AJAX Submission ---
    // MODIFIED: Changed feedback target and messages to reflect task queueing
    const manualClipForms = document.querySelectorAll('.manual-clip-form');
    manualClipForms.forEach(form => {
        // ... (Duration calculation logic remains the same) ...
        const startTimeInput = form.querySelector('.clip-start-time');
        const endTimeInput = form.querySelector('.clip-end-time');
        const durationDisplay = form.querySelector('.clip-calculated-duration .value');
        function updateDuration() { /* ... */ }
        if (startTimeInput) startTimeInput.addEventListener('input', updateDuration);
        if (endTimeInput) endTimeInput.addEventListener('input', updateDuration);
        updateDuration();

        form.addEventListener('submit', function(event) {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            // Use the generic action status message area for feedback now
            const feedbackElementId = 'action-status-message'; // Target global feedback area
            const currentStartTime = startTimeInput ? startTimeInput.value : null;
            const currentEndTime = endTimeInput ? endTimeInput.value : null;

            // --- Validation (remains the same) ---
            const start = parseFloat(currentStartTime);
            const end = parseFloat(currentEndTime);
            if (isNaN(start) || isNaN(end) || start < 0 || end <= start) {
                 showFeedback(feedbackElementId, 'Error: Invalid start/end time for manual clip.', true);
                 return;
            }

            const formData = new FormData(form); // Includes start/end times and hidden CSRF from form

            const csrfToken = getCsrfToken(); // Also available via hidden input in form data
            const headers = {
                'Accept': 'application/json',
                // 'X-CSRFToken' will be added via formData if using Flask-WTF hidden tag
            };
            // Add CSRF header explicitly if needed (e.g., if not relying on form data)
            if (!formData.has('csrf_token') && csrfToken) {
                 console.log("Adding X-CSRFToken header explicitly");
                 headers['X-CSRFToken'] = csrfToken;
            } else if (!formData.has('csrf_token') && !csrfToken) {
                 console.warn("CSRF Token not found for manual clip creation. Request might fail.");
                 showFeedback(feedbackElementId, 'Error: CSRF token missing.', true);
                 return;
            }

            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Queueing...';
            showFeedback(feedbackElementId, 'Queueing manual clip task...', false, 10000); // Longer duration

            fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: headers // Pass headers if needed explicitly
             })
            .then(response => {
                // More robust error checking from response
                if (!response.ok) {
                    return response.json().then(errData => {
                        // Try to get specific error, fallback to status text
                        throw new Error(errData.error || `Request failed: ${response.status} ${response.statusText}`);
                    }).catch((parseError) => {
                        // If parsing JSON fails, use status text
                        console.error("Error parsing error response:", parseError);
                        throw new Error(`Request failed: ${response.status} ${response.statusText}`);
                    });
                }
                return response.json();
             })
            .then(data => {
                 if (data.success) {
                    const successMsg = `Success: ${data.message || 'Task queued.'} (Task ID: ${data.task_id || 'N/A'})`;
                    showFeedback(feedbackElementId, successMsg, false, 7000);
                    button.innerHTML = '<i class="bi bi-check-lg"></i> Queued';
                    // No immediate UI update for clip list, as task runs in background
                 } else {
                    // Throw error to be caught by .catch block
                    throw new Error(data.error || 'Unknown server error.');
                 }
             })
            .catch(error => {
                console.error('Manual clip task queue error:', error);
                showFeedback(feedbackElementId, `Error: ${error.message || 'Failed to queue task.'}`, true);
                button.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Error';
            })
            .finally(() => {
                // Re-enable button after a delay, regardless of success/failure
                 setTimeout(() => {
                     button.disabled = false;
                     // Reset button text based on final status if needed, or just reset generally
                     button.innerHTML = '<i class="bi bi-send"></i> Queue Manual Clip Task';
                 }, 1000);
            });
        });
    }); // End manualClipForms.forEach

    // --- Video Details Page: Regeneration Action Button Logic ---
    // MODIFIED: Only "reprocess_full" action remains relevant. Added CSRF header.
    const actionButtons = document.querySelectorAll('.action-button');
    const actionStatusMessage = document.getElementById('action-status-message'); // Used by manual clip form too now

    async function handleActionButtonClick(event) {
        const button = event.target.closest('button');
        if (!button || !actionStatusMessage) return;

        const action = button.dataset.action;
        const videoId = button.dataset.videoId;

        let url = '';
        const fetchOptions = {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
                // CSRF token will be added below
            }
        };

        // --- Build URL based on action ---
        if (action === 'reprocess_full') {
             url = `/reprocess_full/${videoId}`;
        } else {
            console.error("Unknown action:", action, button);
            showFeedback('action-status-message', 'Error: Unknown button action.', true);
            return;
        }

        // --- Add CSRF Token ---
        const csrfToken = getCsrfToken();
        if (csrfToken) {
            fetchOptions.headers['X-CSRFToken'] = csrfToken;
        } else {
            console.warn(`CSRF Token not found for action button '${action}'. Request might fail.`);
            showFeedback('action-status-message', 'Error: CSRF token missing. Action aborted.', true);
            return;
        }

        // --- UI Feedback: Loading ---
        button.disabled = true;
        const originalHtml = button.innerHTML;
        button.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Queueing...`;
        showFeedback('action-status-message', `Sending request for '${action}'...`, false, 10000);

        // --- AJAX Call ---
        try {
            const response = await fetch(url, fetchOptions);
            const data = await response.json();

            if (!response.ok) {
                 // Throw error using detailed message from JSON response if possible
                 throw new Error(data.error || `Request failed: ${response.status} ${response.statusText}`);
            }

            if (data.success) {
                const successMsg = `Success: ${data.message || 'Task queued.'} (Task ID: ${data.task_id || 'N/A'})`;
                showFeedback('action-status-message', successMsg, false, 7000);
            } else {
                // Throw error if server explicitly reports failure
                throw new Error(data.error || 'Unknown error reported by server.');
            }

        } catch (error) {
            console.error(`Action '${action}' failed:`, error);
            showFeedback('action-status-message', `Error: ${error.message || 'Failed to queue task.'}`, true);
        } finally {
            // Re-enable button after a short delay
            setTimeout(() => {
                button.disabled = false;
                button.innerHTML = originalHtml;
            }, 1000);
        }
    }

    // Add listener only if actionButtons exist
    if (actionButtons.length > 0) {
        actionButtons.forEach(button => {
            button.addEventListener('click', handleActionButtonClick);
        });
    }

    // --- Video Details Page: Single Video Delete Confirmation --- (No changes needed)
    const deleteSingleVideoButton = document.getElementById('deleteSingleVideoButton');
    if (deleteSingleVideoButton) {
         deleteSingleVideoButton.addEventListener('click', function(event) {
             if (!confirm('Are you sure you want to delete this video job and its local files?\n\nThis action cannot be undone.')) {
                 event.preventDefault();
             } else {
                 // Disable button immediately on confirm
                 deleteSingleVideoButton.disabled = true;
                 deleteSingleVideoButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Deleting...';
                 // Allow form submission to proceed
             }
         });
    }

    // --- REMOVED: Video Details Page: Q&A Exchange Delete Button Logic ---


    // --- Index Page: Auto-Refresh Logic (Polling) --- (No changes needed, uses derived status)
    const indexPageTable = document.querySelector('#deleteVideosForm table');
    const statusUpdateFeedbackEl = document.getElementById('statusUpdateFeedback');
    if (indexPageTable && indexPageTable.querySelector('tbody tr[data-video-id]')) {
        const REFRESH_INTERVAL_MS = 15000;
        let pollErrorCount = 0;
        const MAX_POLL_ERRORS = 5;
        let pollingIntervalId = null;
        function updateVideoStatuses() { /* ... (logic remains the same) ... */ }
        pollingIntervalId = setInterval(updateVideoStatuses, REFRESH_INTERVAL_MS);
        console.log(`Auto-refresh polling started (Interval: ${REFRESH_INTERVAL_MS / 1000}s).`);
    } else {
        console.log("Not on index page or no video rows found, auto-refresh polling not started.");
    }

    // --- MODIFIED: Manual Batch Cutting JS ---
    const batchCutFormsContainer = document.getElementById('batch-cut-forms');
    const batchCutVideoIdInput = document.getElementById('batch-cut-video-id'); // Still one hidden input

    if (batchCutFormsContainer && batchCutVideoIdInput) {
        // Use event delegation on the container
        batchCutFormsContainer.addEventListener('click', async function(event) {
            // Check if the clicked element is one of our batch cut buttons
            const button = event.target.closest('.batch-cut-btn');
            if (!button) return; // Ignore clicks that aren't on the buttons

            const clipType = button.dataset.clipType;
            const textareaId = button.dataset.textareaId;
            const timestampsInput = document.getElementById(textareaId);
            const batchCutStatusSpan = batchCutFormsContainer.querySelector(`.batch-cut-status[data-clip-type="${clipType}"]`);
            const videoId = batchCutVideoIdInput.value;

            if (!timestampsInput || !batchCutStatusSpan) {
                console.error(`Missing elements for batch cut type: ${clipType}`);
                return;
            }

            const rawTimestamps = timestampsInput.value.trim();
            if (!rawTimestamps) {
                 batchCutStatusSpan.textContent = 'Error: Please enter timestamps.';
                 batchCutStatusSpan.className = 'batch-cut-status ms-3 text-danger fw-bold small';
                 batchCutStatusSpan.setAttribute('data-clip-type', clipType);
                return;
            }

            // --- Timestamp Parsing (remains the same) ---
            const timestampStrings = rawTimestamps.split(/[\n,;]+/)
                                              .map(ts => ts.trim())
                                              .filter(ts => ts.length > 0);
            if (timestampStrings.length === 0) {
                batchCutStatusSpan.textContent = 'Error: No valid timestamps found.';
                batchCutStatusSpan.className = 'batch-cut-status ms-3 text-danger fw-bold small';
                batchCutStatusSpan.setAttribute('data-clip-type', clipType);
                return;
            }

            // --- Prepare Request ---
            const url = `/video/${videoId}/batch_cut`;
            const csrfToken = getCsrfToken();
            const headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            };
            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken; // Add CSRF token header
            } else {
                console.warn(`CSRF Token not found for batch cutting video ${videoId}. Request might fail.`);
                batchCutStatusSpan.textContent = 'Error: CSRF token missing.';
                batchCutStatusSpan.className = 'batch-cut-status ms-3 text-danger fw-bold small';
                batchCutStatusSpan.setAttribute('data-clip-type', clipType);
                return;
            }

            // --- Include clip_type in the body ---
            const body = JSON.stringify({
                timestamps: timestampStrings,
                clip_type: clipType // Send the type determined by the button clicked
            });

            // --- UI Feedback: Loading ---
            button.disabled = true;
            const originalButtonHtml = button.innerHTML;
            button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Queueing...';
            batchCutStatusSpan.textContent = 'Queueing batch cut task...';
            batchCutStatusSpan.className = 'batch-cut-status ms-3 text-muted small';
            batchCutStatusSpan.setAttribute('data-clip-type', clipType);


            // --- AJAX Call ---
            try {
                const response = await fetch(url, { method: 'POST', headers: headers, body: body });
                const data = await response.json();

                if (!response.ok) {
                    // Throw error using detailed message from JSON response if possible
                    throw new Error(data.error || `Request failed: ${response.status} ${response.statusText}`);
                }

                if (data.success) {
                    batchCutStatusSpan.textContent = `Success: ${data.message} (Task ID: ${data.task_id || 'N/A'})`;
                    batchCutStatusSpan.className = 'batch-cut-status ms-3 text-success fw-bold small';
                } else {
                    // Throw error if server explicitly reports failure
                    throw new Error(data.error || 'Server reported failure.');
                }

            } catch (error) {
                console.error(`Failed to queue batch cut for video ${videoId} (Type: ${clipType}):`, error);
                batchCutStatusSpan.textContent = `Error: ${error.message}`;
                batchCutStatusSpan.className = 'batch-cut-status ms-3 text-danger fw-bold small';
            } finally {
                // Re-enable button after a short delay
                 batchCutStatusSpan.setAttribute('data-clip-type', clipType); // Ensure data attribute persists
                setTimeout(() => {
                    button.disabled = false;
                    button.innerHTML = originalButtonHtml;
                }, 1000);
            }
        });
    } // End batch cut logic

}); // End DOMContentLoaded

// --- END OF FILE: static/js/app.js ---