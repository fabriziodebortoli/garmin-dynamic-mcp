# Garmin Personal API: verified behavior

What we learned by calling the real API with a personal key (probe run on 2026-11-10, with
`scripts/live_probe.py`). It contains no personal data. Garmin's own specification is the source of the
endpoint list; this page records what the specification does not say.

## Authentication

- The user creates a key at <https://connect.garmin.com/app/settings/personalApiToken>.
- `POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`
  with header `Authorization: ApiKey <key>` returns the access token **as the bare response body** (a JWT, not JSON).
  `GET` on that URL answers 404.
- The token lasts 24 hours (less when the key expires sooner: `exp - iat` in the JWT tells). There is no refresh token.
- Data calls use `Authorization: Bearer <token>`.
- An invalid, expired or revoked key makes the exchange answer **HTTP 401**.

## Endpoints

Calling each enabled endpoint once with plausible parameters:

| Result | Endpoints |
|---|---|
| Verified (22) | every endpoint of the catalog except the three below |
| Not verified, sensitive, disabled by default (3) | `/nutrition-service/food/logs/{date}`, `/periodichealth-service/menstrualcycle/summary/{calendarDate}`, `/periodichealth-service/menstrualcycle/dayview/{calendarDate}` |

The `verified` flag in `catalog.json` records this per endpoint. New endpoints that appear after a catalog update start as
unverified.

## Response shapes

- Activity search returns a **JSON list** of activities, most recent first. Each activity has hundreds of fields,
  including owner data with profile image URLs and per-split detail, which is why the server returns a reduced default view.
- `/usersummary-service/v2/dailysummaries` returns `{"data": [...]}`; most other range endpoints return a list or an
  object with a list inside (for example `hrvSummaries`, `dailyWeightSummaries`).
- Days without data come back as records whose values are all `null`; the server adds a note when that happens.

## Pagination

- `GET /activitylist-service/activities/search/activities?start=&limit=`: `limit=200` works; `limit=250` and above answers
  HTTP 500. The server pages by 200 and combines the pages.
- `startDate` / `endDate` filters (YYYY-MM-DD) work on activity search.
- The reachable history is limited only by what the account stores; the probe reached back several years.

## Date range limits

Garmin documents these in the endpoint descriptions ("up to a maximum of N days"), and the probe confirmed them. The
catalog builder reads them from the specification, and the server splits longer requests.

| Endpoint | Maximum range |
|---|---|
| `/usersummary-service/stats/steps/daily/{startDate}/{endDate}` | 28 days |
| `/usersummary-service/stats/stress/daily/{startDate}/{endDate}` | 28 days |
| `/sleep-service/sleep/dailySleepSummariesByDate` | 31 days |
| `/usersummary-service/stats/hydration/daily/{startDate}/{endDate}` | 31 days |
| `/wellness-service/wellness/bodyBattery/reports/daily` | 31 days |
| `/weight-service/weight/all/{startDate}/{endDate}` | 180 days (366 fails; measured, not documented) |
| `/usersummary-service/v2/dailysummaries` | 1 year |
| other range endpoints | at least 366 days worked |

Longer requests answer HTTP 500 (not a helpful error), so the server never sends them.

## Notes

- `/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}` returns *wellness activities* (for example
  guided sessions), not workouts; it is an empty list when there are none in the range.
- Garmin does not publish rate limits. The server sends requests sequentially and reports HTTP 429 clearly.
- The specification has no `operationId`s, so the path is the identifier of an endpoint.
