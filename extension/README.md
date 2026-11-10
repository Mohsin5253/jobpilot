# JobPilot Autofill (Chrome extension)

Fills a company's Greenhouse, Lever or Ashby application form with your JobPilot details. For a job JobPilot
matched, it also adds that job's **tailored resume** and **cover note**. It highlights every field it filled.
It **never clicks Submit**. When you submit, it tells JobPilot, and the job moves to *Applied* on your tracker with
the resume version you used.

What it doesn't do:
- It doesn't touch LinkedIn.
- It doesn't read your browsing history.
- It doesn't run on any other site.
- It leaves sensitive questions blank (salary, visa, gender, ID numbers and similar).

## Install (developer mode)

1. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick this `extension/` folder.
2. JobPilot → **Settings → Chrome extension** → **Create token**. Copy it; it's shown once.
3. Click the extension → **Settings**:
   - API address: `http://localhost:8000` locally, or your API's public URL.
   - Paste the token, then **Save**. Chrome asks once for permission to reach that address.
4. Open an application page (for example `https://boards.greenhouse.io/<company>/jobs/<id>`) → **Fill this application**.
   Review everything, then submit yourself.

Revoke a token any time in Settings; the extension stops working immediately.

## Develop

```bash
node --test test/fields.test.js   # field-mapping rules
```

`src/fields.js` decides which value goes in which field, and it's shared by the content script and the tests.
API calls run in `background.js`, so the job site never sees your token.
To publish to the Chrome Web Store, zip this folder and follow Google's developer program steps; the privacy
disclosure is simple because it only reads the application form on the four ATS domains.
