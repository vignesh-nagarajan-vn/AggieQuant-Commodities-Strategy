# AggieQuant: Commodities Strategy

A research project by the **Commodities Strategy** team at [AggieQuant](https://aggiequant.com/), Texas A&M University for the 2026-2027 academic year.

- **Objective:** Pick one liquid commodity, or a small related universe, and test a single hypothesis on it. Candidate hypotheses include trend, seasonality, or a relative-value relationship.
- **Team:** Vignesh Nagarajan, Lucky Karthikeyan, Myles Brandon, Bryce Millington, Javier Marquez

## Deliverable

A reproducible notebook that includes:

- A baseline to compare the strategy against
- Held-out (out-of-sample) results
- Transaction-cost assumptions
- Drawdown analysis
- A short explanation of the economics behind the hypothesis
- If futures are used, an explanation of roll methodology and contract selection

## Running the prototype

```bash
pip install -r requirements.txt
pytest
jupyter nbconvert --to notebook --execute --inplace notebooks/trend_prototype.ipynb
```

- `src/trend.py` holds the signal, backtest and metric functions.
- `tests/test_trend.py` checks them on synthetic prices (including a look-ahead test).
- `notebooks/trend_prototype.ipynb` runs the 12-month trend rule from `ideas/commodity-etfs.md`: build on 2008-2017, lock the rules, one held-out run on 2018-now.
- Prices download from Yahoo Finance on first run and are cached in `data/` (not committed).
