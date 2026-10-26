# Research context and implementation choices

[Fleurquin, Ramasco and Eguiluz, Systemic delay propagation in the US airport network (2013)](https://arxiv.org/abs/1301.1136) motivates studying connections and systemic disruption rather than isolated airport averages. Its results highlight passenger and crew connectivity, which are absent from the public flight reports used here. CASCADE therefore reports retrospective aircraft-continuity associations and schedule-weighted predictive features, without inventing passenger or crew links.

The SQL warehouse uses [DuckDB](https://duckdb.org/docs/) and the [dbt DuckDB adapter](https://github.com/duckdb/dbt-duckdb). Substantial analytical queries remain visible in `dbt/models/` and `sql/`; model code consumes their outputs as arrays.

[PyTorch Geometric](https://github.com/pyg-team/pytorch_geometric) is a foundation for larger graph-learning experiments. At four hubs, CASCADE tests weighted neighborhood features and a compact temporal residual correction first. The final test reports whether network features add predictive value. There is no assumption that a deep architecture improves this selected dataset.

[OR-Tools](https://github.com/google/or-tools) supports larger constrained allocation problems. With four airports, a cap of two integer units per airport, and a budget of at most four, this release can enumerate all 81 unconstrained combinations and filter to exact feasible allocations. The simple exhaustive optimizer is reproducible and has no approximation gap for its stated objective. That objective remains a hypothetical aggregate model, not a complete airline resource plan.
