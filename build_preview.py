"""Regenerate the demo-preview files from the real capture form.

Run after editing account-capture.html:  python build_preview.py

Produces two artifacts, both driven off the single source of truth so they never drift:
  - account-capture-preview.html : standalone file (open via file://) — full HTML document.
  - loki-form-preview.html       : body-only version for publishing as a claude.ai Artifact.

Both run in DEMO mode: validation is off (Continue always advances) and Sign & submit goes
straight to a confirmation, since there is no server behind a preview.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "account-capture.html"

# --- preview transforms (each is an exact-match replace against the source) --- #
EYEBROW_FROM = '<div class="eyebrow">Loki Ventures Limited</div>'
EYEBROW_TO = '<div class="eyebrow">Loki Ventures · Demo preview (validation off)</div>'

NEXT_FROM = ('function next(){ const err=steps[step].validate(); if(err){ toast(err,true); return; } '
             'if(step<steps.length-1){ step++; render(); } }')
NEXT_TO = ('function next(){ if(!PREVIEW){ const err=steps[step].validate(); if(err){ toast(err,true); return; } } '
           'if(step<steps.length-1){ step++; render(); } }')

SUBMIT_FROM = ('async function submit(){\n'
               '  const err=steps[step].validate(); if(err){ toast(err,true); return; }\n'
               '  const btn=document.getElementById("submitBtn");')
SUBMIT_TO = ('const PREVIEW = true; // demo preview: no server behind it\n'
             'async function submit(){\n'
             '  if(PREVIEW){ toast("Preview mode — nothing was actually sent."); '
             'showDone({submission_id:"PREVIEW-0001", preview:true}); return; }\n'
             '  const err=steps[step].validate(); if(err){ toast(err,true); return; }\n'
             '  const btn=document.getElementById("submitBtn");')

DONE_FROM = '''  card.innerHTML=`<div class="done">
    <div class="tick">✓</div>
    <h3 style="margin:0 0 8px">Application submitted</h3>
    <p style="color:var(--muted);max-width:520px;margin:0 auto 6px">Thank you. Your account application has been sent to the Loki Ventures accounts team for review.</p>
    <p style="color:var(--muted);max-width:520px;margin:0 auto">Reference: <b>${esc(ref)}</b>${data.emailed===false?'<br><small>(saved — the team will be notified shortly)</small>':''}</p>
    <div style="margin-top:22px"><button class="btn" onclick="location.reload()">Start a new application</button></div>
  </div>`;'''
DONE_TO = '''  const note = data.preview
    ? 'This is a <b>preview</b> — no data was sent. In the live app this confirms submission and notifies the accounts team.'
    : 'Thank you. Your account application has been sent to the Loki Ventures accounts team for review.';
  card.innerHTML=`<div class="done">
    <div class="tick">✓</div>
    <h3 style="margin:0 0 8px">${data.preview?"Preview complete":"Application submitted"}</h3>
    <p style="color:var(--muted);max-width:520px;margin:0 auto 6px">${note}</p>
    <p style="color:var(--muted);max-width:520px;margin:0 auto">Reference: <b>${esc(ref)}</b></p>
    <div style="margin-top:22px"><button class="btn" onclick="location.reload()">Start again</button></div>
  </div>`;'''

# head wrapper stripped for the Artifact body-only version
HEAD_FROM = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#123c35">
  <title>Account Opening Form — Loki Ventures</title>
  <style>'''
HEAD_TO = '<style>'


def apply(text: str, pairs: list[tuple[str, str]]) -> str:
    for a, b in pairs:
        if a not in text:
            raise SystemExit(f"build_preview: expected snippet not found:\n{a[:80]}…")
        text = text.replace(a, b, 1)
    return text


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    preview = apply(src, [(EYEBROW_FROM, EYEBROW_TO), (NEXT_FROM, NEXT_TO),
                          (SUBMIT_FROM, SUBMIT_TO), (DONE_FROM, DONE_TO)])

    (ROOT / "account-capture-preview.html").write_text(preview, encoding="utf-8")

    body = apply(preview, [(HEAD_FROM, HEAD_TO),
                           ("  </style>\n</head>\n<body>", "  </style>"),
                           ("</script>\n</body>\n</html>", "</script>")])
    (ROOT / "loki-form-preview.html").write_text(body, encoding="utf-8")

    print("Wrote account-capture-preview.html and loki-form-preview.html")


if __name__ == "__main__":
    main()
