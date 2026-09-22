PNG copies of the diagrams in [TOUR.md](../TOUR.md), for slides. Each `.png` is drawn from the `.tex` beside it.

To rebuild one: `pdflatex <name>.tex && pdftoppm -png -r 200 -singlefile <name>.pdf <name>`, then delete the `.aux`, `.log` and `.pdf`.
