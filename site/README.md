# Autopsy Memory Marketing Site

Marketing website for Autopsy Memory, built with the Sites vinext starter and
designed for Cloudflare Worker-compatible deployment through Sites.

## Prerequisites

- Node.js `>=22.13.0`

## Quick Start

```bash
npm install
npm run dev
npm run build
```

The local site is static/content-led and does not require D1, R2, or runtime
environment variables.

## Site Shape

- `app/page.tsx`: Autopsy marketing page copy and section structure
- `app/globals.css`: responsive visual system and layout
- `public/autopsy-memory-console.png`: generated hero product visual
- `public/screenshot.jpeg`: canonical Sites preview at 1200x750
- `.openai/hosting.json`: Sites project metadata and unused storage bindings

## Hosting

`npm run build` writes Cloudflare Worker-compatible output to `dist/` and copies
`.openai/hosting.json` into `dist/_appgen_meta/appgarden.json` for Sites
binding discovery.

## Useful Commands

- `npm run dev`: start local development
- `npm run build`: verify the vinext build output
- `npm run lint`: run ESLint

## Learn More

- [Autopsy Memory](../README.md)
- [vinext Documentation](https://github.com/cloudflare/vinext)
