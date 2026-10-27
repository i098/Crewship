---
name: apple-hig
description: Apple Human Interface Guidelines digest for native-feeling UI. Use when designing, building or reviewing iOS, iPadOS, macOS, watchOS, tvOS or visionOS screens, SwiftUI/UIKit/AppKit code, or mobile app UI.
---

# Apple HIG

Short rules from the [Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines). Use system components first. Open the linked page before you decide on an exact value: Apple changes the guidelines each release, and this file is a digest, not a copy.

## Layout

- Respect safe areas, margins and the keyboard. Never place controls under system bars or the home indicator.
- Use system layout (stacks, size classes, adaptive grids), not fixed frames. Test compact, regular, landscape and split-screen.
- Group related items, give the primary content the most space, and align to a grid.
- Hit targets: 44x44 pt on iOS, 28x28 pt on macOS, 60 pt on visionOS.

[Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

## Typography

- Use the system font (SF) and text styles, so Dynamic Type works.
- Build hierarchy with a few styles and weights. Do not use one size for every text.
- Let text wrap. Do not truncate key labels.

[Typography](https://developer.apple.com/design/human-interface-guidelines/typography)

## Color and materials

- Use semantic and system colors; they adapt to Light, Dark and increased contrast.
- Never use color as the only signal. Pair it with a label, icon or shape.
- Keep accent color for interactive items and key state.
- Use system materials for depth. Keep text over them readable.

[Color](https://developer.apple.com/design/human-interface-guidelines/color) · [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode) · [Materials](https://developer.apple.com/design/human-interface-guidelines/materials)

## Iconography

- Prefer SF Symbols. Match symbol weight and scale to the adjacent text.
- Add a label when an icon is ambiguous.
- An app icon is one simple, recognizable shape, with no text and no screenshots.

[SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols) · [App icons](https://developer.apple.com/design/human-interface-guidelines/app-icons)

## Navigation

- Pick one model per app: tab bar (flat top-level areas), navigation stack (drill-down), sidebar (large screens, Mac).
- Tab bars hold 3 to 5 top-level destinations on iPhone. They never perform actions.
- Keep a visible back path. Support the back-swipe gesture.
- Use a sheet for a short, focused task. Give it a clear way to finish or cancel.

[Navigation and search](https://developer.apple.com/design/human-interface-guidelines/navigation-and-search) · [Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars) · [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars) · [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars) · [Modality](https://developer.apple.com/design/human-interface-guidelines/modality) · [Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)

## Controls

- Use system buttons, menus, toggles and text fields. Keep their standard states and behavior.
- Give each screen one clear primary action. Style destructive actions as destructive.
- Use an alert only for important, rare information. Make the button titles verbs.
- Prefer undo to a confirmation dialog for reversible actions.

[Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons) · [Menus](https://developer.apple.com/design/human-interface-guidelines/menus) · [Toggles](https://developer.apple.com/design/human-interface-guidelines/toggles) · [Text fields](https://developer.apple.com/design/human-interface-guidelines/text-fields) · [Lists and tables](https://developer.apple.com/design/human-interface-guidelines/lists-and-tables) · [Alerts](https://developer.apple.com/design/human-interface-guidelines/alerts)

## Gestures

- Use the standard gestures with their standard meaning: tap, swipe, drag, pinch, long press.
- Never make a custom gesture the only way to do something. Give every gesture a visible alternative.
- Do not override system edge gestures.

[Gestures](https://developer.apple.com/design/human-interface-guidelines/gestures)

## Accessibility

- Support Dynamic Type, VoiceOver labels, Reduce Motion and increased contrast from the start.
- Contrast: at least 4.5:1 for body text.
- Every control has an accessible name and a logical focus order.
- Use motion to explain change, never only to decorate.

[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) · [Motion](https://developer.apple.com/design/human-interface-guidelines/motion) · [Inclusion](https://developer.apple.com/design/human-interface-guidelines/inclusion) · [Right to left](https://developer.apple.com/design/human-interface-guidelines/right-to-left)

## Platform differences

| Platform | Input | Design bias |
|---|---|---|
| iOS | Touch, one hand | Focused tasks, thumb reach, tab bar and stack |
| iPadOS | Touch, keyboard, pointer | Adaptive layout, sidebar, multitasking, drag and drop |
| macOS | Pointer, keyboard | Menu bar commands, shortcuts, resizable windows, dense layout |
| watchOS | Touch, Digital Crown | Glanceable, short text, large targets |
| tvOS | Remote, focus | Focus states, large type, read at distance |
| visionOS | Eyes, hands | Depth, comfort, windows with room around content |

Never copy one platform's layout to another. Keep names, icons and meanings the same across them.

[iOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-ios) · [iPadOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-ipados) · [macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos) · [watchOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-watchos) · [tvOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-tvos) · [visionOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-visionos)
