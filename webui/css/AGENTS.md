# WebUI CSS DOX

## Purpose

- Own shared stylesheet modules for the WebUI.
- Keep shared visual primitives stable across components and pages.

## Ownership

- Each CSS file owns a named surface or primitive family such as buttons, messages, modals, notifications, scheduler, settings, surfaces, tables, or toast.
- Component-specific styles should usually stay inside the component HTML unless they are intentionally shared.
- `modals.css` owns the shared stacked modal shell, backdrop, scroll area, footer slot, modal button classes, floating/no-backdrop modal behavior, and shared modal section primitives.
- `surfaces.css` owns surface modal switchers, action rails, draggable header affordances, focus-button state, and right-canvas surface primitives.
- `index.css` defines global theme variables such as `--color-*`, `--spacing-*`, `--font-size-*`, and `--transition-speed`.
- `theme.css` owns the visual theme (loaded last among core sheets; replaces the unlinked `glassmorphism.css`): palette tokens (`--s0..--s3` surfaces, `--t0..--t2` text, `--line`, `--accent`), the material tokens (`--mat-alpha`, `--mat-filter`, `--mat-edge`, `--mat-rim`, `--mat-lens`) selected by `<html data-material="solid|glass|enhanced">`, and their mapping onto the app-wide `--color-*` variables.

## Local Contracts

- Use existing CSS variables and naming patterns before introducing new global tokens.
- Avoid broad selectors that unexpectedly restyle plugin UI or unrelated components.
- Keep layout rules responsive and verify text does not overflow fixed controls.
- Shared modal buttons use `btn btn-ok` for positive actions and `btn btn-cancel` for dismissive or negative actions.
- Shared compact text actions use `.text-button`; component-local styles may adjust layout or sizing but must not be the only definition of the primitive.
- Modal footer action order is positive action first, dismissive or negative action second.
- Modal footers use `.modal-footer` plus `data-modal-footer`; do not redefine `.btn`, `.modal-footer`, `.modal-inner`, or `.modal-scroll` inside components.
- Shared modal sizing keeps `.modal-inner` centered with `width: 90%`, `max-width: 960px`, and `max-height: 90vh`.
- Tall modal bodies must scroll inside `.modal-scroll`; pinned footer content must stay outside that scroll area.
- `.modal-floating` must keep the full-screen shell pointer-transparent while `.modal-inner` remains pointer-active.
- Use `.modal-no-backdrop` only for backdrop suppression without click-through floating behavior.
- Shared modal layers must stay above the mobile right-canvas rail while confirmation dialogs remain above normal modals.
- Do not add decorative one-note palette changes that conflict with existing WebUI design.
- Theme rules are scoped under `body.a0-theme` so they win on specificity; add `!important` only to override an `!important` or inline style in the base, with a comment saying which.
- Glass surfaces read the `--mat-*` tokens instead of hard-coding blur/opacity, so Solid/Glass/Enhanced and `prefers-reduced-transparency` work everywhere without duplicate rules.
- `backdrop-filter` only on a few floating surfaces (composer, menus, modals, toasts, top pill, sidebar header). The sidebar body and chat bubbles (`.process-group`, user `.message-text`, `.message-warning`, `.message-error`) blur only under `body.has-wallpaper`; never blur other per-item elements.
- The sidebar (`#left-panel`) floats inset by `--sidebar-gap` with the composer's rim/radius/glow (blur only over a wallpaper); the fixed `.sidebar-header-panel` is shifted by the same gap with `margin-left` (never a transform, which would capture its fixed-position dropdown).
- The docked right canvas (`.right-canvas.is-open`, desktop only) floats like the sidebar (gap, rim, radius, accent glow) with accent tab/rail states, but never gets a `backdrop-filter`: canvas surfaces use `position: fixed` (Desktop viewer expanded mode) and a filter would trap them.
- Button accent tiers (theme): filled accent for main actions (`.btn-ok`, `.btn-primary`, `.btn.primary`, `.btn-upload`, `.button.confirm`, `.button.primary`); soft accent tint for secondary actions (`.btn-field`, plugin-list `.plugin-actions .button`); other `.button` variants stay neutral with an accent hover; cancel/secondary/mass buttons stay neutral. Do not hard-code button blues in components.
- Chat bubbles (`.process-group`, user `.message-text`, `.message-warning`/`.message-error`) use the sidebar surface `color-mix(--s2 var(--mat-alpha))` - solid in Solid, translucent in Glass/Enhanced - and no accent glow (contrast over bright wallpapers).
- Toggles (`.slider`, `.toggler`) use the theme's neo style (MIT, adapted from uiverse.io chicogale/tall-starfish-3) on the existing markup: change surfaces only, never the per-component knob size/offset; no looping animations.
- Approval decision buttons (`.permissions-decision-btn`, `.safety-policy-decision-btn`) are styled in the theme: first approve is the filled accent action, other approves soft accent, Deny neutral with a `--bad` hover.
- An overlay nested inside a backdrop-filtered surface cannot blur the page behind it (the parent is its backdrop root), so overlays inside the composer get a near-solid fill instead of glass.
- Use the accent (`--accent`, `--accent-ui`, `--accent-soft`) for interaction and selection only; success/warning/error use the semantic `--ok`/`--warn`/`--bad` tokens.

## Work Guidance

- Keep shared CSS small and scoped to clear class families.
- Coordinate class renames with all component and plugin references.
- Prefer improving an existing primitive over creating a near-duplicate style family.
- Use component-local styles for unique layouts and shared CSS for repeated primitives such as modal sections, toolbars, buttons, tables, notifications, and surfaces.
- Preserve modal sizing and scrolling expectations: centered `.modal-inner`, constrained viewport height, body scroll inside `.modal-scroll`, and footer outside the scroll area.

## Verification

- Manually inspect affected WebUI screens at desktop and mobile widths for shared CSS changes.
- Run visual or frontend tests if the touched style has coverage.
- For modal CSS, test a tall modal, a footer modal, a stacked modal, and a floating modal.

## Child DOX Index

No child DOX files.
