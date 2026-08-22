#!/usr/bin/env sh
set -eu

profile_dir=${AGENT_BROWSER_PROFILE:-/var/lib/mova-fpl/browser-profile}

# Container recreation changes the hostname recorded in Chromium's singleton
# symlinks. Processes do not survive the recreation, so only these ephemeral
# locks are stale; authenticated profile data must remain untouched.
rm -f \
  "$profile_dir/SingletonCookie" \
  "$profile_dir/SingletonLock" \
  "$profile_dir/SingletonSocket"

exec "$@"
