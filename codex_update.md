# Update for JSON serialization in `routes.py`

This update addresses the `Object of type ndarray is not JSON serializable` error seen when hitting the `/api/run_analysis` endpoint. The solution is twofold:

- [x] **Added a helper function `make_serializable`**

  A new function is defined in `routes.py` to recursively convert any NumPy arrays or NumPy scalar types into Python lists or native Python numbers. The helper also handles nested structures (lists and dictionaries) so that the entire result can be serialized by Flask's `jsonify`.

- [x] **Updated the `/api/run_analysis` route**

  In the `api_run_analysis` endpoint, the return statement has been modified to wrap the `results` dictionary with `make_serializable` before passing it to `jsonify`. This change ensures that all data returned in the API response are JSON‑serializable and prevents serialization errors.

### Example Usage

After these changes, a successful call to `/api/run_analysis` will return JSON like:

```json
{
  "success": true,
  "results": {
    "timestamp": "2025-08-08T12:00:00Z",
    "gti_value": 0.08,
    "phase_gap_degrees": 12.5,
    "coherence_median": 0.04,
    "variance_explained": 0.98,
    "bayes_factor": 12.3,
    "time_to_overlap": 43.7,
    "alert_level": "medium",
    "detailed_results": {
      ...
    }
  }
}
```

These modifications make the API robust against NumPy data types in the results.
