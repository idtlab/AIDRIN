# AIDRIN – AI Data Readiness Inspector

**AIDRIN** (AI Data Readiness Inspector) is a lightweight, open-source tool designed to evaluate the readiness of datasets for AI and machine learning workflows. It provides an intuitive web interface to assess dataset quality, completeness, and structure through quantitative metrics.

For installation, usage, and contribution guidelines, please refer to the [AIDRIN documentation](https://aidrin.readthedocs.io/en/latest/).

## Security Configuration

Set the Flask secret key with the `AIDRIN_SECRET_KEY` environment variable before running AIDRIN.

Example:

```powershell
$env:AIDRIN_SECRET_KEY = "your-strong-random-secret"
```

The app uses a fallback value (`change-me-in-production`) only for local development convenience. Do not use this fallback in staging or production environments.
