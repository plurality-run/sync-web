# Synchronic Web whitepaper

LaTeX sources for the Synchronic Web whitepaper.

## Build

```sh
cd docs/whitepaper
make
```

The build requires `latexmk`, pdfLaTeX, and BibTeX. It generates `whitepaper.pdf`; generated build artifacts are ignored by the local `.gitignore`.

## Structure

- `main.tex` — report setup and section order
- `sections/` — independently editable section sources
- `figures/` — editable draw.io diagrams and their PDF exports used in the build
- `style/` — report class and required cover assets
- `tables/` — table sources
- `algorithms/` — algorithm sources
- `references.bib` — bibliography
