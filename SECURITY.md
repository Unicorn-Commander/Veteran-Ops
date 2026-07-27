# Security policy

## Scope

This repository is an educational, self-hostable application. Treat every uploaded record, token, password, and model-provider credential as sensitive.

## Never disclose publicly

- API keys, JWT secrets, database credentials, SSH keys, or private certificates
- Real veteran records, decision letters, medical documents, or personally identifying information
- Private deployment hosts, network dumps, backups, or production environment files

The public export is intended to be secrets-clean, but review your local configuration before deployment. Run `gitleaks` and `trufflehog` before publication.

## Reporting a vulnerability

Please do not open a public issue for an exploitable security problem. Use GitHub’s private vulnerability reporting for this repository when enabled, or contact the maintainers privately through the organization’s security channel. Include reproduction steps, affected versions, impact, and a safe remediation suggestion.

Do not test against the hosted dogfood service without explicit authorization.

## Safety boundary

Veteran-Ops must not fabricate evidence, impersonate a veteran or provider, submit a claim, expose one user’s records to another, or promise a VA outcome. Report violations of these boundaries as security or safety issues even when they are not classic vulnerabilities.
