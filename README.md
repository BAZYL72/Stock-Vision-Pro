# StockVision Pro

**StockVision Pro** is an AI-powered stock prediction system that analyzes historical market data and provides next-day price predictions with technical analysis for multiple stock tickers.

---

##  Features

-  **Multi-stock prediction** — Supports `AAPL`, `AMZN`, `GOOGL`, `META`, `MSFT`, `TSLA`
-  **LSTM-based deep learning models** — Individual models trained per ticker
-  **Automatic technical indicators** — Calculates MA20, MA50, MA100, RSI
-  **Real-time market data** — Fetches live data via Yahoo Finance API
-  **Next-day price prediction** — AI-powered forecasting
-  **BUY / SELL / HOLD recommendations** — Automated trading signals
-  **Interactive charts** — Visualizes actual vs predicted prices
-  **REST API + Web dashboard** — Full-stack Flask application

---

##  Project Structure
StockVision_Pro/
│
├── app.py                 # Main Flask backend
├── api/                   # Vercel serverless entry
│   └── index.py
├── models/                # Trained LSTM models (.keras)
├── scalers/               # Feature scalers (.pkl)
├── templates/             # HTML frontend
│   └── index.html
├── requirements.txt
├── vercel.json
└── .gitignore

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python |
| Web Framework | Flask |
| Deep Learning | TensorFlow / Keras |
| Data Processing | NumPy & Pandas |
| Feature Scaling | Scikit-learn |
| Market Data | Yahoo Finance (`yfinance`) |
| Deployment | Render |

---

##  Running Locally

**1. Install dependencies:**

```bash
pip install -r requirements.txt
```

**2. Start the server:**

```bash
python app.py
```

**3. Open in browser:**
http://localhost:5000

---

##  Output

Each prediction response includes:

| Field | Description |
|---|---|
| Current Price | Latest market price |
| Predicted Price | Next-day AI forecast |
| Price Change | Absolute & percentage change |
| Recommendation | BUY / SELL / HOLD signal |
| Technical Indicators | MA20, MA50, MA100, RSI |
| Chart Data | Historical + predicted prices |

---

##  Deployment

StockVision Pro is deployed on **Render** with continuous deployment from GitHub.
The Flask API runs as a web service, and both frontend and backend are managed from a single repository.

---

##  Notes

- Models and scalers are loaded dynamically per ticker
- Files are cached in memory for faster performance
- Model files are stored in `/models`
- Scalers are stored in `/scalers`

---

##  License

This project is for **educational and research purposes only**.
It does not provide financial or investment advice.

---

##  Authors

**Arsalan Tahir · Usayd Arsalan · Bazyl Sheikh**

---

> **Disclaimer:** This tool is for educational purposes only. Always do your own research before making investment decisions.
