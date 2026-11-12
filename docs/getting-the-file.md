# Getting the registry's file

**In short:** the registry (HRSA's OPAIS) offers a daily file from its public reports page. You can save it by hand, or let `opais pull` press the button for you. Either way the raw file names people, so it stays private.

## The raw file is not for sharing

The file lists an authorizing official and a primary contact for each entity. Do not share it, commit it or upload it anywhere. Keep the zip somewhere private, or delete it once the snapshot is made. `opais snapshot` drops those fields, so a snapshot is safe to keep and publish.

## By hand

Open HRSA's public 340B reports page in a browser and press the button called `Covered Entity Daily Export (JSON)`. Unzip what it sends and give the file to `opais snapshot`.

There is no direct address for the file. The page is an interactive app that hands the file to the browser when the button is pressed.

## With `opais pull`

`opais pull --out DIR` does the same thing a person does: it opens that one page in a plain headless browser, presses that one button, and saves the zip into `DIR`. It then prints one line of JSON with the file's name, size, fingerprint (SHA-256), the time and the day of the export.

It is built to be a polite visitor:

- one page, one button, one attempt;
- no retries;
- it does not hide that it is automated;
- if the page has changed, it stops with a plain message. It does not guess.

### Setting it up

`pull` is an optional extra, so the rest of the tool stays free of dependencies.

```bash
uv sync --extra pull
```

On a server, install a browser for it:

```bash
uv run playwright install chromium
```

If a browser is already installed, give its path with `--browser`. `--timeout` is how many seconds to wait for the download to start (default 600).

### Exit codes

Each way the fetch can fail has its own code, so a scheduled job can tell them apart.

| Code | Meaning |
|---|---|
| 0 | Done |
| 2 | Another error |
| 4 | The `pull` extra is not installed |
| 5 | The page did not answer with HTTP 200 |
| 6 | The page does not have exactly one such button |
| 7 | No download started in time |
| 8 | What came back is not a zip |
| 9 | The zip does not hold exactly one `OPA_CE_DAILY_PUBLIC.JSON` |
| 10 | The zip is under 5 MB (the real file is far larger) |
| 11 | The file inside does not start like JSON |
| 12 | The browser failed to run |

The checks from 8 to 11 mean a broken or surprising download is refused before anything reads it.
