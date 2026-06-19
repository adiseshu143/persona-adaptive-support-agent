# Browser Cache and Cookies Troubleshooting

## When to try this
Clearing cache and cookies resolves most issues where:
- The interface appears stuck on a loading spinner
- Recent changes (profile updates, new uploads) aren't showing
- You're logged out unexpectedly or stuck in a login loop
- Buttons appear unresponsive after a recent product update

## Steps by browser

### Chrome
1. Open Settings > Privacy and security > Clear browsing data
2. Select "Cached images and files" and "Cookies and other site data"
3. Set time range to "All time"
4. Click "Clear data" and restart the browser

### Firefox
1. Open Settings > Privacy & Security
2. Under Cookies and Site Data, click "Clear Data"
3. Check both boxes and confirm
4. Restart the browser

### Safari
1. Safari > Settings > Privacy > Manage Website Data
2. Search for our domain and click "Remove"
3. Quit and reopen Safari

### Edge
1. Settings > Privacy, search, and services > Clear browsing data
2. Choose "Cached images and files" and "Cookies and other site data"
3. Clear now, then restart

## If clearing cache doesn't help
1. Try an incognito/private window — if the issue disappears, it confirms
   a cache/extension conflict rather than a server-side problem.
2. Disable browser extensions one at a time, particularly ad blockers and
   privacy extensions, which can interfere with our session cookies.
3. Confirm your system clock is accurate — session tokens are time-sensitive
   and a clock more than 5 minutes off can cause repeated login failures.

## Mobile app users
The "clear cache" steps above apply to browser-based access only. For the
mobile app, go to device Settings > Apps > [App Name] > Storage > Clear
Cache (Android) or reinstall the app (iOS, which does not expose a
cache-clear option).

## Persistent failures
If the interface still fails to load crucial profile data after cache
clearing across two different browsers/devices, this points to a
server-side data sync issue rather than a client-side cache problem, and
should be escalated with the exact error code shown (if any) and a
screenshot.
