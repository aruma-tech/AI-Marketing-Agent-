"""google_services.py - Google login, Google Sheet and Google Form setup."""
import json
import config

_client = {"gc": None}

# The Google Form questions (title, type, required). One list = one source.
FORM_FIELDS = [
    ("Business Name", "short", True),
    ("Owner Name", "short", True),
    ("Email", "short", True),
    ("Business Type", "short", False),
    ("Website URL", "short", True),
    ("Business Description", "paragraph", True),
    ("Main Products / Services", "paragraph", True),
    ("Target Audience", "short", False),
    ("Contact Information", "short", False),
    ("Preferred Language", "choice", True),
    ("Social Media Page Links", "paragraph", False),
]


SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_gspread_client():
    """Log in to Google and return a gspread client.

    On a server (Railway, or anywhere outside Colab) this uses the service
    account JSON stored in the GOOGLE_SERVICE_ACCOUNT_JSON secret - no
    browser popup needed. Inside Colab, if that secret is not set, it falls
    back to Colab's own one-click Google login, same as before.
    """
    if _client["gc"] is None:
        import gspread
        if config.GOOGLE_SERVICE_ACCOUNT_JSON:
            info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(info, scopes=SHEET_SCOPES)
            _client["gc"] = gspread.authorize(creds)
        else:
            from google.colab import auth
            auth.authenticate_user()          # Colab asks for permission once
            from google.auth import default
            creds, _ = default()
            _client["gc"] = gspread.authorize(creds)
    return _client["gc"]


def open_or_create_spreadsheet():
    """Open the project Google Sheet by name. Create it if it does not exist."""
    import gspread
    gc = get_gspread_client()
    try:
        return gc.open(config.SHEET_TITLE)
    except gspread.SpreadsheetNotFound:
        return gc.create(config.SHEET_TITLE)


def form_apps_script(sheet_id):
    """Return a Google Apps Script that creates the signup Form and links it
    to the Sheet. Colab's default Google login cannot create Forms, so the
    owner runs this script once (about 1 minute)."""
    lines = [
        "function createSignupForm() {",
        "  var form = FormApp.create('%s');" % config.FORM_TITLE,
        "  form.setDescription('Tell us about your business. Public information only - no passwords.');",
    ]
    for title, kind, required in FORM_FIELDS:
        req = "true" if required else "false"
        if kind == "short":
            lines.append("  form.addTextItem().setTitle('%s').setRequired(%s);" % (title, req))
        elif kind == "paragraph":
            lines.append("  form.addParagraphTextItem().setTitle('%s').setRequired(%s);" % (title, req))
        else:
            lines.append("  form.addMultipleChoiceItem().setTitle('%s').setChoiceValues(%s).setRequired(%s);"
                         % (title, json.dumps(config.LANGUAGES), req))
    lines += [
        "  // Responses go into the project Google Sheet (new tab: Form Responses)",
        "  form.setDestination(FormApp.DestinationType.SPREADSHEET, '%s');" % sheet_id,
        "  Logger.log('Send this link to business owners: ' + form.getPublishedUrl());",
        "}",
    ]
    return "\n".join(lines)


def form_setup_steps(sheet_id):
    """Simple steps (plain text) to create the Form with the script above."""
    return (
        "GOOGLE FORM SETUP (one time, about 1 minute)\n"
        "1. Open https://script.google.com and click 'New project'.\n"
        "2. Delete the sample code and paste the script printed below.\n"
        "3. Click Run (function: createSignupForm) and allow the permissions.\n"
        "4. Open 'Execution log' - it shows the Form link. Share that link.\n"
        "5. Come back here and run this cell again. The Sheet now has a\n"
        "   'Form Responses' tab and the Form is connected.\n\n"
        + form_apps_script(sheet_id)
    )
