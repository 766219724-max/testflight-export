# TestFlight Export

Export your full TestFlight beta program — testers, builds, crash & screenshot feedback — via the official App Store Connect API, in one command.

**The problem it solves:** App Store Connect has no bulk export for beta testers. The web UI shows you a paginated list you cannot download. If you're a product manager or indie developer who wants to analyze beta activation, invitation conversion, or feedback volume, you're stuck clicking through screens. This script pulls everything into CSV/JSON plus a funnel summary.

## What you get

| File | Content |
|------|---------|
| `testers.csv` | All beta testers: name, email, state (`INVITED` / `ACCEPTED` / `INSTALLED`), invite type, beta groups |
| `builds.csv` | Build versions with upload date, expiration date, processing state |
| `crashes.json` | Crash feedback submissions (raw API JSON) |
| `screenshots.json` | Screenshot feedback submissions (raw API JSON) |
| `summary.txt` | Funnel & stats: install conversion rate, state distribution, invite type breakdown |

## Quick start

```bash
pip install -r requirements.txt

python asc_fetch.py \
    --key AuthKey_XXXXXX.p8 \
    --key-id XXXXXXXXXX \
    --issuer-id 11111111-2222-3333-4444-555555555555 \
    --app-id 1234567890
```

### Getting API credentials (one time)

1. Go to [App Store Connect → Users and Access → Integrations](https://appstoreconnect.apple.com/access/integrations/api)
2. Click **Generate API Key** with the **App Manager** role
3. Download the `.p8` key file and note the **Key ID** and **Issuer ID**
4. Pass all three to the script. Credentials are used in-memory only and never stored or sent anywhere except `api.appstoreconnect.apple.com`.

Your **App ID** is the numeric ID visible in App Store Connect → App Information, or in the URL of your app's page.

## Example output (`summary.txt`)

```
Total testers          : 117

By state:
  INSTALLED: 61
  ACCEPTED: 22
  INVITED: 19

Identifiable tester funnel:
  invited, not accepted : 19
  accepted, not installed: 22
  installed             : 61
  install conversion    : 63.5%
```

## Notes

- Handles API pagination and 429 rate-limit retries automatically.
- Testers invited via public link are recorded as `(anonymous/public link)` — Apple doesn't expose their identity, which is itself a useful metric for public-link campaigns.
- Apple's TestFlight data is retained for 180 days; run this regularly if you want history.

## License

MIT
