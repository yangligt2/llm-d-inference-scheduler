PAPER = paper

all: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex macros.tex references.bib sections/*.tex
	latexmk -pdf -interaction=nonstopmode $(PAPER).tex

clean:
	latexmk -C $(PAPER).tex
	rm -f $(PAPER).bbl

.PHONY: all clean
