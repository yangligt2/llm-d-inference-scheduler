# OSDI LaTeX sources

Generated from `../draft2.md` (2026-08-26). Content is a 1:1 conversion; no
text was added or removed. The draft's front-matter provenance and
terminology-map paragraphs are preserved as comments at the top of
`paper.tex`.

## Layout

- `paper.tex` - main file: preamble, title, abstract, `\input`s.
- `sections/*.tex` - one file per section, numbered as in the draft.
- `macros.tex` - math shorthands and the `\evid{}` marker macro.
- `references.bib` - converted from the draft's References section.
- `usenix2019_v3.sty` - USENIX two-column style (OSDI format). Compare
  against the current template linked from the OSDI call for papers
  before submission; conferences occasionally revise it.

## Build

Requires a TeX distribution (none is installed on this machine; on macOS,
MacTeX or BasicTeX). Then:

    make            # latexmk -pdf paper.tex

LaTeX Workshop's default latexmk recipe also works once a distribution is
installed. Figures are read directly from `../../out/` and `../../out/paper/`
via `\graphicspath`; regenerate them with the `fig_*.py` generators.

## Submission checklist

- Evidence markers `[R<n>]`/`[C<nn>]` render via `\evid{}`. For
  camera-ready, change the macro body in `macros.tex` to `{}`.
- Author block is anonymized (`Paper #XXX`); OSDI submissions are
  double-blind. The `llmdasync` citation names the project; consider
  anonymizing it for submission.
- Draft numeric-reference style (`Section 5.5`, `rule (9)`, `Figure 1b`)
  is converted to `\ref`/`\eqref`; equation numbers (1)-(10) match the
  draft because the equations appear in the same order.
- The Section 5.2 outcome table, Section 6.4 size series, Section 8.2
  calibration table, and Appendix A claim register are proper `tabular`/
  `tabularx` environments; the claim register is split into two `table*`
  floats (C01-C18, C19-C35) to fit pages.
