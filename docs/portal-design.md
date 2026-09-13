# Loki portal visual system

The customer application and accounts review portals share a forest, parchment,
and brass palette. Serif editorial headings give the brand a distinct voice;
system sans-serif text keeps forms and account data readable without downloads.

- Forest `#123c35`: navigation, primary actions and current steps.
- Parchment `#f5f3ed`: page background; paper `#fffefa`: cards.
- Brass `#e4b45b`: restrained header accent and progress indicators.
- Ink `#203b34` and muted `#5e6d65`: primary and supporting text.
- Pale green `#eaf0e8`: selected states and decision panels.
- Spacing: 8px base, 20–32px card padding, 44px minimum button height.
- Motion: short color/focus transitions, with reduced-motion support.

The UI/UX Pro Max search matched Minimalism & Swiss Style for enterprise tools.
Its landing-page pattern and generic palettes did not match this workflow, so
the layout uses the skill's general form/dashboard guidance and retains Loki's
existing green identity. These are intentional project-specific decisions.

The capture portal uses an editorial introduction and numbered journey beside
the active form. On smaller screens the journey yields to the compact progress
bar. The review portal uses an application queue and a detail panel, with account
decisions grouped in a pale-green inset. Columns stack on narrower viewports.

Edit `account-capture.html` and `accounts-dashboard.html` as the source files.
Run `python build_preview.py` after capture changes to regenerate both previews.
Inline styles preserve standalone preview compatibility. Keep the shared token
block consistent between the two source portals.

Validation: preview generation and JavaScript syntax checks pass. A connected
browser was unavailable during implementation, so rendered viewport checks and
end-to-end interaction testing remain outstanding.
