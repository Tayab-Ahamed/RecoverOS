# Evaluation artifacts

`runs/` holds benchmark results written by `python -m scripts.run_benchmark`.

Every artifact records the seed, the dataset run id, and the data provenance,
so any number quoted from it can be reproduced by re-running with the same
seed, or challenged.

All data in this directory is **SYNTHETIC EVALUATION DATA**. Recovery outcomes
come from a seeded simulation whose conversion priors were chosen by the
authors. The numbers demonstrate that the control system behaves correctly at
batch scale. They are not a prediction of real-world recovery rates.
