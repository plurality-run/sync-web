LATEXMK ?= latexmk

.PHONY: all clean

all: whitepaper.pdf

whitepaper.pdf: main.tex references.bib sections/*.tex figures/*.pdf tables/*.tex algorithms/*.tex
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -jobname=whitepaper main.tex

clean:
	$(LATEXMK) -C -jobname=whitepaper main.tex
