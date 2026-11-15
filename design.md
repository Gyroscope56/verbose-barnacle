---
name: Editorial & Refined
colors:
  surface: '#faf9fa'
  surface-dim: '#dbdadb'
  surface-bright: '#faf9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3f4'
  surface-container: '#efedee'
  surface-container-high: '#e9e8e9'
  surface-container-highest: '#e3e2e3'
  on-surface: '#1b1c1d'
  on-surface-variant: '#434653'
  inverse-surface: '#303031'
  inverse-on-surface: '#f2f0f1'
  outline: '#737784'
  outline-variant: '#c3c6d5'
  surface-tint: '#2259bf'
  primary: '#094cb2'
  on-primary: '#ffffff'
  primary-container: '#3366cc'
  on-primary-container: '#e7ebff'
  inverse-primary: '#b1c5ff'
  secondary: '#5a5f63'
  on-secondary: '#ffffff'
  secondary-container: '#dfe3e8'
  on-secondary-container: '#606569'
  tertiary: '#6d5e00'
  on-tertiary: '#ffffff'
  tertiary-container: '#bfab49'
  on-tertiary-container: '#4a3f00'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d9e2ff'
  primary-fixed-dim: '#b1c5ff'
  on-primary-fixed: '#001946'
  on-primary-fixed-variant: '#00419d'
  secondary-fixed: '#dfe3e8'
  secondary-fixed-dim: '#c2c7cc'
  on-secondary-fixed: '#171c20'
  on-secondary-fixed-variant: '#42474b'
  tertiary-fixed: '#f9e37a'
  tertiary-fixed-dim: '#dcc661'
  on-tertiary-fixed: '#211b00'
  on-tertiary-fixed-variant: '#524600'
  background: '#faf9fa'
  on-background: '#1b1c1d'
  surface-variant: '#e3e2e3'
typography:
  headline-lg:
    fontFamily: Noto Serif
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-sm:
    fontFamily: Public Sans
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  margin: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

# Design System - Editorial & Refined

## Brand & Style
This design system embraces an editorial, refined aesthetic. It combines traditional literary elements with modern digital utility, evoking a sense of trust, intellectual depth, and sophisticated clarity. The interface uses a balance of high-contrast readability, generous whitespace, and restrained ornamentation.

## Colors
The color palette is built for clarity and editorial sophistication. 
- **Primary (`#3366cc`)**: A reliable, authoritative blue used for key interactive elements, primary actions, and brand touchpoints.
- **Secondary (`#54595d`)**: A cool slate gray that provides balanced support for secondary text and structural UI borders.
- **Tertiary (`#fee77e`)**: A warm, soft yellow accent used sparingly for highlights and important callouts.
- **Neutral (`#202122`)**: A deep, rich charcoal used for high-contrast text and primary structural surfaces in a light mode context.

## Typography
Typography bridges editorial storytelling with crisp user interfaces. 
- **Headlines**: Set in *Noto Serif*, bringing a classic, authoritative voice to major headings.
- **Body**: Set in *Inter*, ensuring exceptional legibility across dense blocks of text and varying screen resolutions.
- **Labels**: Set in *Public Sans*, offering clean, functional support for UI controls, navigation, and metadata.

## Layout & Spacing
The layout model relies on a structured, fluid grid system that adapts gracefully across form factors. Generous margins and consistent gutters establish a comfortable reading rhythm, avoiding visual clutter and emphasizing content hierarchy. Spacing tokens scale predictably to support dense data displays as well as airy editorial spreads.

## Elevation & Depth
Elevation is handled with subtle tonal layering and soft, low-opacity ambient shadows. Rather than relying on heavy drop shadows, surfaces are distinguished through clean structural boundaries and slight shifts in background luminance, maintaining a flat yet perceptually layered hierarchy.

## Shapes
The shape language is restrained and professional, utilizing soft, subtle rounding (`roundedness: 1`). Interactive elements and containers feature gentle radii that soften the interface without sacrificing its editorial rigor.

## Components
Components follow the editorial and refined ethos of the design system:
- **Buttons**: Clear primary actions utilize the primary blue with subtle rounded corners. Secondary and ghost variants maintain clean typography and structured padding.
- **Input Fields**: Crisp borders with neutral charcoal text and soft focus states reflecting the primary color.
- **Cards**: Clean container surfaces structured with subtle outlines and soft internal padding.
- **Chips & Checkboxes**: Minimalist controls utilizing clean label fonts and accessible touch targets.
