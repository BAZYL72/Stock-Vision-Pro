import sys
import os
from flask import Flask, render_template, request, jsonify
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, datetime, timedelta
from tensorflow import keras
import joblib
import time
import sqlite3
import json

# Absolute paths (Render-safe)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
SCALERS_DIR = os.path.join(BASE_DIR, "scalers")
DB_PATH = os.path.join(BASE_DIR, "stock_data.db")

app = Flask(__name__)

# Dictionary to cache loaded models and scalers
loaded_models = {}

# Mapping of ticker symbols to file names
TICKER_FILE_MAP = {
    'AAPL': 'AAPL',
    'AMZN': 'AMZN',
    'GOOGL': 'GOOGL',
    'META': 'META',
    'MSFT': 'MSFT',
    'TSLA': 'TESLA',
}

AVAILABLE_TICKERS = list(TICKER_FILE_MAP.keys())

# ==================== DATABASE FUNCTIONS ====================

def init_database():
    """Initialize SQLite database with tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for storing stock price data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            data_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, date)
        )
    """)
    
    # Table for tracking last update
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS update_log (
            ticker TEXT PRIMARY KEY,
            last_updated TIMESTAMP,
            record_count INTEGER
        )
    """)
    
    # Table for storing ticker info (company name, market cap, etc.)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticker_info (
            ticker TEXT PRIMARY KEY,
            company_name TEXT,
            market_cap TEXT,
            pe_ratio TEXT,
            fifty_two_week_high TEXT,
            fifty_two_week_low TEXT,
            last_updated TIMESTAMP
        )
    """)
    
    # Create index for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticker_date 
        ON stock_data(ticker, date DESC)
    """)
    
    conn.commit()
    conn.close()

def needs_update(ticker, hours=24):
    """Check if ticker needs updating (older than X hours)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT last_updated FROM update_log WHERE ticker = ?
    """, (ticker,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result is None:
        return True
    
    last_updated = datetime.fromisoformat(result[0])
    hours_passed = (datetime.now() - last_updated).total_seconds() / 3600
    
    return hours_passed >= hours

def save_stock_data_to_db(ticker, data):
    """Save downloaded stock data to database"""
    if data.empty:
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Reset index to get date as column
    df = data.reset_index()
    
    # Handle MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if col[0] != '' else col[1] for col in df.columns]
    
    # Save each row
    for _, row in df.iterrows():
        # Convert row to dictionary
        row_dict = {}
        
        # Get date string
        if 'Date' in row:
            date_value = row['Date']
            date_str = date_value.strftime('%Y-%m-%d') if hasattr(date_value, 'strftime') else str(date_value)
        else:
            date_str = str(row.name) if hasattr(row, 'name') else str(row.index)
        
        # Convert all values to native Python types (JSON serializable)
        for key, value in row.items():
            if pd.isna(value):
                row_dict[key] = None
            elif hasattr(value, 'strftime'):  # Timestamp/datetime
                row_dict[key] = value.strftime('%Y-%m-%d')
            elif hasattr(value, 'item'):  # numpy types
                row_dict[key] = value.item()
            else:
                row_dict[key] = float(value) if isinstance(value, (int, float)) else str(value)
        
        data_json = json.dumps(row_dict)
        close_price = float(row.get('Close', 0)) if 'Close' in row else 0.0
        
        cursor.execute("""
            INSERT OR REPLACE INTO stock_data (ticker, date, close, data_json)
            VALUES (?, ?, ?, ?)
        """, (ticker, date_str, close_price, data_json))
    
    # Update log
    cursor.execute("""
        INSERT OR REPLACE INTO update_log (ticker, last_updated, record_count)
        VALUES (?, ?, ?)
    """, (ticker, datetime.now().isoformat(), len(df)))
    
    conn.commit()
    conn.close()

def load_stock_data_from_db(ticker, start_date="2014-01-01"):
    """Load stock data from database"""
    conn = sqlite3.connect(DB_PATH)
    
    query = """
        SELECT date, data_json FROM stock_data
        WHERE ticker = ? AND date >= ?
        ORDER BY date
    """
    
    cursor = conn.cursor()
    cursor.execute(query, (ticker, start_date))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return None
    
    # Reconstruct DataFrame from stored JSON
    data_list = []
    for date_str, json_str in rows:
        row_data = json.loads(json_str)
        row_data['Date'] = pd.to_datetime(date_str)
        data_list.append(row_data)
    
    df = pd.DataFrame(data_list)
    df.set_index('Date', inplace=True)
    
    return df

def get_stock_data_smart(ticker, start_date="2014-01-01"):
    """
    Smart function: Load from DB if fresh, otherwise download from Yahoo Finance
    """
    ticker = ticker.upper()
    
    # Check if we need to update
    if not needs_update(ticker, hours=24):
        data = load_stock_data_from_db(ticker, start_date)
        if data is not None and not data.empty:
            return data, None
    
    # Need to download fresh data
    try:
        time.sleep(2)  # Rate limiting
        end_date = date.today().strftime("%Y-%m-%d")
        data = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True, progress=False)
        
        if data.empty:
            return None, "No data found for this ticker symbol"
        
        # Save to database
        save_stock_data_to_db(ticker, data)
        
        return data, None
        
    except Exception as e:
        # Try to return cached data even if old
        data = load_stock_data_from_db(ticker, start_date)
        if data is not None and not data.empty:
            return data, None
        return None, str(e)

def save_ticker_info(ticker, info):
    """Save ticker information to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Safely convert values, handling None
    def safe_str(value):
        if value is None or value == '' or (isinstance(value, float) and pd.isna(value)):
            return 'N/A'
        return str(value)
    
    cursor.execute("""
        INSERT OR REPLACE INTO ticker_info 
        (ticker, company_name, market_cap, pe_ratio, fifty_two_week_high, fifty_two_week_low, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker,
        safe_str(info.get('longName', ticker)),
        safe_str(info.get('marketCap')),
        safe_str(info.get('trailingPE')),
        safe_str(info.get('fiftyTwoWeekHigh')),
        safe_str(info.get('fiftyTwoWeekLow')),
        datetime.now().isoformat()
    ))
    
    conn.commit()
    conn.close()

def get_ticker_info(ticker):
    """Get ticker information from database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT company_name, market_cap, pe_ratio, fifty_two_week_high, fifty_two_week_low, last_updated
            FROM ticker_info WHERE ticker = ?
        """, (ticker,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result is None:
            return None
        
        # Check if info is older than 7 days
        last_updated = datetime.fromisoformat(result[5])
        days_old = (datetime.now() - last_updated).days
        
        if days_old > 7:
            return None  # Info too old, need to refresh
        
        # Convert string values back to appropriate types
        def safe_convert(value):
            if value == 'N/A' or value == 'None':
                return 'N/A'
            try:
                return int(value) if value.replace('.', '').isdigit() else value
            except:
                return value
        
        return {
            'longName': result[0],
            'marketCap': safe_convert(result[1]),
            'trailingPE': safe_convert(result[2]),
            'fiftyTwoWeekHigh': safe_convert(result[3]),
            'fiftyTwoWeekLow': safe_convert(result[4])
        }
    except Exception as e:
        return None

# ==================== ORIGINAL FUNCTIONS (MODIFIED) ====================

def get_model_paths(ticker):
    """Get model and scaler file paths for a given ticker"""
    ticker = ticker.upper()
    file_name = TICKER_FILE_MAP.get(ticker, ticker)
    model_path = os.path.join(MODELS_DIR, f"stock_model{file_name}.keras")
    scaler_path = os.path.join(SCALERS_DIR, f"scaler{file_name}.pkl")
    return model_path, scaler_path

def load_model_for_ticker(ticker):
    """Load model and scaler for a specific ticker"""
    ticker = ticker.upper()
    
    if ticker in loaded_models:
        return loaded_models[ticker]['model'], loaded_models[ticker]['scaler'], None
    
    model_path, scaler_path = get_model_paths(ticker)
    
    if not os.path.exists(model_path):
        return None, None, f"Model for {ticker} not found at {model_path}"
    
    if not os.path.exists(scaler_path):
        return None, None, f"Scaler for {ticker} not found at {scaler_path}"
    
    try:
        model = keras.models.load_model(model_path)
        scaler = joblib.load(scaler_path)
        loaded_models[ticker] = {'model': model, 'scaler': scaler}
        return model, scaler, None
    except Exception as e:
        return None, None, f"Error loading model for {ticker}: {str(e)}"

def get_available_models():
    """Get list of tickers that have trained models available"""
    available = []
    for ticker in AVAILABLE_TICKERS:
        model_path, scaler_path = get_model_paths(ticker)
        if os.path.exists(model_path) and os.path.exists(scaler_path):
            available.append(ticker)
    return available

def compute_rsi(series, period=14):
    """Compute Relative Strength Index"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def prepare_data(ticker):
    """Download and prepare stock data for prediction - NOW USING DATABASE"""
    try:
        # Use smart data loading (database + cache)
        data, error = get_stock_data_smart(ticker, start_date="2014-01-01")
        
        if error:
            return None, None, error
        
        if data is None or data.empty:
            return None, None, "No data found for this ticker symbol"
        
        df = data.copy()
        
        # Handle MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if col[0] != '' else col[1] for col in df.columns]
        
        # Feature engineering
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA50'] = df['Close'].rolling(window=50).mean()
        df['MA100'] = df['Close'].rolling(window=100).mean()
        df['RSI'] = compute_rsi(df['Close'], 14)
        
        # Drop NaN values
        df = df.dropna()
        df = df.drop(columns=['High', 'Low', 'Open', 'Volume'], errors='ignore')
        
        if len(df) < 100:
            return None, None, "Not enough historical data for prediction"
        
        return df, data, None
        
    except Exception as e:
        return None, None, str(e)

def predict_stock(ticker):
    """Make predictions for the given stock ticker"""
    ticker = ticker.upper()
    
    model, scaler, load_error = load_model_for_ticker(ticker)
    if load_error:
        return None, load_error
    
    df, raw_data, error = prepare_data(ticker)
    if error:
        return None, error
    
    try:
        train_size = int(len(df) * 0.80)
        train = df[:train_size]
        test = df[train_size:]
        
        past_100_days = train[-100:]
        final_df = pd.concat([past_100_days, test], ignore_index=True)
        
        input_data = scaler.transform(final_df)
        
        x_test = []
        y_test_actual = []
        
        for i in range(100, input_data.shape[0]):
            x_test.append(input_data[i-100:i])
            y_test_actual.append(input_data[i, 0])
        
        x_test = np.array(x_test)
        y_test_actual = np.array(y_test_actual)
        
        y_pred_scaled = model.predict(x_test, verbose=0)
        
        dummy_pred = np.zeros((len(y_pred_scaled), 5))
        dummy_pred[:, 0] = y_pred_scaled[:, 0]
        y_pred_actual = scaler.inverse_transform(dummy_pred)[:, 0]
        
        dummy_actual = np.zeros((len(y_test_actual), 5))
        dummy_actual[:, 0] = y_test_actual
        y_actual = scaler.inverse_transform(dummy_actual)[:, 0]
        
        last_100_days = df[-100:]
        last_input = scaler.transform(last_100_days)
        x_input = np.array([last_input])
        next_pred_scaled = model.predict(x_input, verbose=0)
        
        dummy_next = np.zeros((1, 5))
        dummy_next[0, 0] = next_pred_scaled[0, 0]
        predicted_price = scaler.inverse_transform(dummy_next)[0, 0]
        
        current_price = float(df['Close'].iloc[-1])
        price_change = predicted_price - current_price
        percent_change = (price_change / current_price) * 100
        
        chart_data = raw_data['Close'].tail(60).reset_index()
        chart_data.columns = ['Date', 'Close']
        chart_data['Date'] = chart_data['Date'].dt.strftime('%Y-%m-%d')
        
        # Get stock info - try cache first, then fetch if needed
        info = get_ticker_info(ticker)
        
        if info is None:
            # Not in cache or too old, fetch fresh
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # Validate info is not empty
                if info and info.get('marketCap') and info.get('trailingPE'):
                    # Only cache it if we actually got the good stuff!
                    save_ticker_info(ticker, info)
                else:
                    info = {}
            except Exception as e:
                info = {}
        
        # Ensure info dict exists even if all fetches failed
        if not info:
            info = {}
        
        # Format info values - convert to float if possible, otherwise keep as string
        def format_info_value(value):
            if value == 'N/A' or value is None:
                return None  # Return None instead of 'N/A' for JSON
            try:
                # Try to convert to number
                return float(value)
            except (ValueError, TypeError):
                return value
        
        result = {
            'ticker': ticker.upper(),
            'company_name': info.get('longName', ticker.upper()),
            'current_price': round(current_price, 2),
            'predicted_price': round(predicted_price, 2),
            'price_change': round(price_change, 2),
            'percent_change': round(percent_change, 2),
            'recommendation': 'BUY' if percent_change > 1 else ('SELL' if percent_change < -1 else 'HOLD'),
            'market_cap': format_info_value(info.get('marketCap', 'N/A')),
            'pe_ratio': format_info_value(info.get('trailingPE', 'N/A')),
            'fifty_two_week_high': format_info_value(info.get('fiftyTwoWeekHigh', 'N/A')),
            'fifty_two_week_low': format_info_value(info.get('fiftyTwoWeekLow', 'N/A')),
            'ma20': round(float(df['MA20'].iloc[-1]), 2),
            'ma50': round(float(df['MA50'].iloc[-1]), 2),
            'ma100': round(float(df['MA100'].iloc[-1]), 2),
            'rsi': round(float(df['RSI'].iloc[-1]), 2),
            'chart_dates': chart_data['Date'].tolist(),
            'chart_prices': [round(float(p), 2) for p in chart_data['Close'].tolist()],
            'actual_prices': [round(float(p), 2) for p in y_actual.tolist()],
            'predicted_prices': [round(float(p), 2) for p in y_pred_actual.tolist()],
            'comparison_labels': list(range(1, len(y_actual) + 1))
        }
        
        return result, None
        
    except Exception as e:
        return None, str(e)

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/available_models', methods=['GET'])
def available_models():
    available = get_available_models()
    return jsonify({'available_tickers': available})

@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json()
    ticker = data.get('ticker', '').strip().upper()
    
    if not ticker:
        return jsonify({'error': 'Please enter a stock ticker symbol'}), 400
    
    result, error = predict_stock(ticker)
    if error:
        return jsonify({'error': error}), 400
    
    return jsonify(result)

@app.route('/force_update/<ticker>', methods=['POST'])
def force_update(ticker):
    """Force update data from Yahoo Finance"""
    ticker = ticker.upper()
    try:
        # Delete old data
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM update_log WHERE ticker = ?", (ticker,))
        conn.commit()
        conn.close()
        
        # Download fresh
        data, error = get_stock_data_smart(ticker)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({
            'status': 'updated',
            'ticker': ticker,
            'records': len(data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/cache_status', methods=['GET'])
def cache_status():
    """Check cache status for all tickers"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, last_updated, record_count FROM update_log")
    rows = cursor.fetchall()
    conn.close()
    
    status = []
    for ticker, last_updated, count in rows:
        last_updated_dt = datetime.fromisoformat(last_updated)
        hours_ago = (datetime.now() - last_updated_dt).total_seconds() / 3600
        status.append({
            'ticker': ticker,
            'last_updated': last_updated,
            'hours_ago': round(hours_ago, 1),
            'records': count,
            'needs_update': hours_ago >= 24
        })
    
    return jsonify({'cache_status': status})

@app.route('/health')
def health():
    available = get_available_models()
    return jsonify({
        'status': 'healthy',
        'available_models': available,
        'loaded_models': list(loaded_models.keys()),
        'database': 'connected' if os.path.exists(DB_PATH) else 'not_found'
    })

# Initialize database when app starts
with app.app_context():
    init_database()

if __name__ == '__main__':
    app.run(debug=True, port=5000)