# Swing Trading Agent

## Project Structure
- `swing_agent.py` - Main scanner agent
- `config.json` - Watchlist and indicator settings

## Quick Commands
```bash
python swing_agent.py                    # Scan full watchlist
python swing_agent.py AAPL TSLA NVDA     # Scan specific stocks
python swing_agent.py --detail AAPL      # Deep analysis on one stock
python swing_agent.py --top 5            # Show top 5 only
python swing_agent.py --export results.csv  # Save to CSV
```

## Strategy
- Lookback: 60 days (2 months), Hourly candles
- Hold period: 2-4 weeks
- Signals: EMA 8/21 crossover, RSI 14, MACD, Volume spikes, Support/Resistance
- Risk: 2% per trade, auto position sizing

## Dependencies
- yfinance, pandas, numpy
