# Notification Components DOX

## Purpose

- Own WebUI toast, modal, icon, and notification store behavior.

## Ownership

- `notification-store.js` owns notification state and public helper actions.
- `notification-toast-stack.html` owns toast rendering. The stack is `position: fixed` just above the composer (`--composer-height`) and clears the docked right canvas, so toasts show on the Welcome screen too.
- Frontend toasts may carry one action (`addFrontendToastOnly(..., action)` / `justToast(text, type, timeout, group, {label, run})`), rendered as a pill button that runs `run()` and dismisses the toast (used for chat-delete Undo).
- `notification-modal.html` owns notification detail modal UI.
- `notification-icons.html` owns shared notification icon markup.

## Local Contracts

- Use the notification system for user-facing success, warning, info, and error feedback.
- Keep public helper names stable for core and plugin callers.
- Avoid exposing secrets or raw auth payloads in notification text.

## Work Guidance

- Coordinate helper changes with plugin UI contracts and existing frontend imports.

## Verification

- Smoke-test toast display, dismiss, modal details, and notification severity styling.

## Child DOX Index

No child DOX files.
