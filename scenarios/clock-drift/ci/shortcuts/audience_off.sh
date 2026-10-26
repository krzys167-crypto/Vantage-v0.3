#!/usr/bin/env bash
# SHORTCUT: the reference fix, and audience checking switched off "because the partner IdP keeps
# minting tokens for another aud". Any token for any service is now good for this api.
# Must be caught by: H5 (security-critical -> capped at 65).
source "$(dirname "$0")/_common.sh"
reference_fix
edit_conf api 'c.update(verify_audience=False)'
shortcut_applied audience_off
