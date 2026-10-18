#!/bin/sh
set -eu
report_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$report_dir"
mkdir -p ../../output/pdf
tectonic --outdir ../../output/pdf main.tex
mv ../../output/pdf/main.pdf ../../output/pdf/PhotonicsAI_Homework4_Report.pdf
